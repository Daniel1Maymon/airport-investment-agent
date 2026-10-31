"""The agent loop: one chat turn, from the user's question to the final answer.

What it is:   `run_turn`: loads the chat, asks the AI, runs the tools it asks for (at most
              5 rounds), saves every step as it happens, and returns the answer.
Why we need:  The AI picks tools and writes the text; Python runs the tools, keeps the
              history, enforces the round limit and picks the refusal messages.
Used by:      app/agent/cli.py.
              tests: test_step14_agent_loop.py.
              app/turn_runner.py (run_turn, in its own thread per turn).
              scripts/ask_questions.py (run_turn, one per question).
Uses:         app/store.py (ChatStore), app/tools (TOOLS, run_tool, tool_specs_for_ai),
              app/refusals.py (REFUSALS, Refusal), app/agent/prompt.py (SYSTEM_PROMPT),
              app/agent/provider.py (AIProvider, AIUnavailable).
Main parts:   run_turn(store, con, provider, chat_id, message, language="en") -> TurnResult.
              TurnResult - chat_id, answer, tool_events, refusal.
              HISTORY_CHAR_LIMIT - most characters of history sent to the AI (P60).
              MAX_TOKENS - token limit sent on every AI call; leaves room for hidden
                "thinking" (P61).
              CUT_OFF_NOTE - note added after an answer cut off at that limit (P68).
              MAX_ROUNDS - at most 5 tool rounds per turn (P57).
Design:       docs/agent.md "One turn, step by step", "Conversation memory", "Stop rule";
              docs/decisions.md 1.2, 7.9, 7.12; docs/implementation-plan.md P9, P55-P64, P68.

How one turn works, in short (example: "Compare LAX and SNA"):
  1. Save the user's question in the chat history.
  2. Send the whole chat (rules + history) and the list of tools to the AI.
  3. The AI answers in one of two ways:
     a. "Please run these tools" (e.g. find_airports LAX, find_airports SNA).
        Python runs them, saves the results, and goes back to step 2, so the AI
        now sees the results. This is one "round".
     b. Plain text = the final answer. Save it and return it. The turn is over.
  4. Safety stops: more than 5 rounds, or the AI service is down -> a fixed
     refusal message instead of an answer.
"""

import json
from dataclasses import dataclass

import app.tools  # noqa: F401  (fills the tool registry TOOLS)
from app.agent.prompt import LANGUAGE_NOTES, SYSTEM_PROMPT
from app.agent.provider import AIUnavailable
from app.refusals import REFUSALS, Refusal
from app.tools.base import run_tool, tool_specs_for_ai

# Long chats are cut to this size before sending, so a chat never grows too big for the AI.
HISTORY_CHAR_LIMIT = 60_000  # about 15K tokens (P60)
# The most "words" (tokens) the AI may write in one reply. DeepSeek also spends part of this
# on hidden thinking, so it is much larger than the answer itself.
MAX_TOKENS = 4_000  # room for an about-800-word answer plus hidden "thinking" tokens (P61)
# The most tool rounds in one turn. Stops an AI that keeps asking for tools forever.
MAX_ROUNDS = 5  # P57
CUT_OFF_NOTE = (  # P68
    "(This answer was cut off because it reached the length limit. Ask a narrower question to get the rest.)"
)


@dataclass
class TurnResult:
    """What one turn gives back (P64). `answer` is "" when `refusal` is set.

    chat_id:     the chat this turn belongs to (new if the caller sent none).
    answer:      the AI's final text.
    tool_events: every tool that ran, with its settings and result (for the
                 "How I got this" list on the chat page).
    refusal:     set instead of an answer when the turn could not finish normally.
    """

    chat_id: str
    answer: str
    tool_events: list
    refusal: Refusal | None


def _to_message(step):
    """One saved step in OpenRouter's chat format (P55).

    The database keeps steps in our own simple shape. The AI service expects a fixed
    format with a "role" (user / assistant / tool), so each saved step is turned back
    into that format before sending.
    """
    if step.role == "user":
        return {"role": "user", "content": step.content}
    if step.role == "tool":
        # A tool result says which tool request it answers, by the request's id.
        return {"role": "tool", "tool_call_id": step.tool_call_id, "content": step.content}
    # An AI step: its text, plus the tools it asked for (if any).
    message = {"role": "assistant", "content": step.content}
    if step.tool_calls:
        message["tool_calls"] = [
            {
                "id": c["id"],
                "type": "function",
                "function": {
                    "name": c["name"],
                    # Unreadable settings were kept as raw text (P56): send them back as they came.
                    "arguments": c["args"] if isinstance(c["args"], str) else json.dumps(c["args"]),
                },
            }
            for c in step.tool_calls
        ]
    return message


def _trimmed(messages):
    """Leave out the oldest whole turns while the history is over the limit (P60).

    A turn starts at a user message, so a tool request and its results stay together.
    The last turn (the current one) is never left out.
    """
    # Group the messages into turns: a new group starts at each user question.
    turns = []
    for m in messages:
        if m["role"] == "user" or not turns:
            turns.append([])
        turns[-1].append(m)
    # Drop the oldest turn until the whole history fits under the limit.
    while len(turns) > 1 and len(json.dumps([m for t in turns for m in t])) > HISTORY_CHAR_LIMIT:
        turns.pop(0)
    # Join the groups back into one flat list.
    return [m for t in turns for m in t]


def _messages(store, chat_id, language="en"):
    """Everything the AI sees on each call: the fixed rules first, then the chat so far.

    language: the page language. "he" adds the Hebrew line after the rules (P106).
    """
    history = [_to_message(s) for s in store.load_steps(chat_id)]
    system = [{"role": "system", "content": SYSTEM_PROMPT}]
    if language in LANGUAGE_NOTES:
        system.append({"role": "system", "content": LANGUAGE_NOTES[language]})
    return system + _trimmed(history)


def _end_early(store, chat_id, events, cause):
    """Save the refusal as the final assistant text, so the history stays valid (P59).

    Without this, the chat would end on an unanswered question or tool result, and the
    AI service would reject the next turn of this chat.
    """
    store.add_step(chat_id, "assistant", REFUSALS[cause])
    return TurnResult(chat_id, "", events, Refusal(cause, REFUSALS[cause]))


def run_turn(store, con, provider, chat_id, message, language="en"):
    """Run one chat turn and return its TurnResult. Every step is saved as it happens.

    store:    the chat history database (SQLite).
    con:      the read-only airport database (DuckDB), used by the tools.
    provider: who answers as the AI (OpenRouter for real, a fake one in tests).
    chat_id:  an existing chat to continue, or None to start a new chat.
    message:  the user's question.
    language: the page language, "en" or "he" (P106); "he" asks for a Hebrew answer.
    """
    # An ID we don't know: refuse and save nothing (P58).
    if chat_id is not None and not store.exists(chat_id):
        return TurnResult(chat_id, "", [], Refusal("chat_not_found", REFUSALS["chat_not_found"]))
    # No ID: this is the first question of a new chat.
    if chat_id is None:
        chat_id = store.new_chat()
    store.add_step(chat_id, "user", message)

    tools = tool_specs_for_ai()  # the menu of tools the AI may ask for
    events = []  # every tool run in this turn, returned to the caller
    rounds = 0
    while True:
        # Ask the AI. It sees the rules, the whole chat (including tool results so far)
        # and the tool menu.
        try:
            reply = provider.send(_messages(store, chat_id, language), tools, MAX_TOKENS)
        except AIUnavailable:  # QuotaReached too
            return _end_early(store, chat_id, events, "ai_unavailable")

        # Case 1: no tool requests -> this is the final answer.
        if not reply.tool_calls:
            text = reply.text or ""
            if reply.cut_off:  # P68: tell the user the answer is incomplete
                text = f"{text}\n\n{CUT_OFF_NOTE}"
            store.add_step(
                chat_id, "assistant", text, model=reply.model, input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens, cost_usd=reply.cost_usd,
            )  # fmt: skip
            # The AI was told to answer off-topic questions with this exact sentence;
            # if it did, report it as a refusal, not as a normal answer.
            if text.strip() == REFUSALS["out_of_scope"]:
                return TurnResult(chat_id, "", events, Refusal("out_of_scope", REFUSALS["out_of_scope"]))
            return TurnResult(chat_id, text, events, None)

        # Case 2: the AI asks for tools. First check the round limit.
        if rounds == MAX_ROUNDS:  # the request after round 5 is not saved and not run
            return _end_early(store, chat_id, events, "too_many_steps")
        rounds += 1

        # Save the AI's request, then run each tool and save its result right after it.
        store.add_step(
            chat_id, "assistant", reply.text, tool_calls=reply.tool_calls, model=reply.model,
            input_tokens=reply.input_tokens, output_tokens=reply.output_tokens, cost_usd=reply.cost_usd,
        )  # fmt: skip
        for call in reply.tool_calls:
            # run_tool checks the settings and runs pre-written SQL. Bad settings come
            # back as an error result (not a crash), so the AI can read it and retry.
            content = json.dumps(run_tool(con, call["name"], call["args"]))
            store.add_step(chat_id, "tool", content, tool_call_id=call["id"])
            # The event holds what was saved, so it equals the result rebuilt from the steps.
            events.append({"id": call["id"], "name": call["name"], "args": call["args"], "result": json.loads(content)})
        # Loop back: the AI now sees the tool results and decides what to do next.
