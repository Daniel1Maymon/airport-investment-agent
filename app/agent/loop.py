"""The agent loop: one chat turn, from the user's question to the final answer.

What it is:   `run_turn`: loads the chat, asks the AI, runs the tools it asks for (at most
              5 rounds), saves every step as it happens, and returns the answer.
Why we need:  The AI picks tools and writes the text; Python runs the tools, keeps the
              history, enforces the round limit and picks the refusal messages.
Used by:      app/agent/cli.py.
              tests: test_step14_agent_loop.py.
              Planned: Step 15 question script, Step 16 backend API.
Uses:         app/store.py (ChatStore), app/tools (TOOLS, run_tool, tool_specs_for_ai),
              app/refusals.py (REFUSALS, Refusal), app/agent/prompt.py (SYSTEM_PROMPT),
              app/agent/provider.py (AIProvider, AIUnavailable).
Main parts:   run_turn(store, con, provider, chat_id, message) -> TurnResult.
              TurnResult - chat_id, answer, tool_events, refusal.
              HISTORY_CHAR_LIMIT - most characters of history sent to the AI (P60).
              MAX_TOKENS - token limit sent on every AI call; leaves room for hidden
                "thinking" (P61).
              CUT_OFF_NOTE - note added after an answer cut off at that limit (P68).
              MAX_ROUNDS - at most 5 tool rounds per turn (P57).
Design:       docs/agent.md "One turn, step by step", "Conversation memory", "Stop rule";
              docs/decisions.md 1.2, 7.9, 7.12; docs/implementation-plan.md P9, P55-P64, P68.
"""

import json
from dataclasses import dataclass

import app.tools  # noqa: F401  (fills the tool registry TOOLS)
from app.agent.prompt import SYSTEM_PROMPT
from app.agent.provider import AIUnavailable
from app.refusals import REFUSALS, Refusal
from app.tools.base import run_tool, tool_specs_for_ai

HISTORY_CHAR_LIMIT = 60_000  # about 15K tokens (P60)
MAX_TOKENS = 4_000  # room for an about-800-word answer plus hidden "thinking" tokens (P61)
MAX_ROUNDS = 5  # P57
CUT_OFF_NOTE = (  # P68
    "(This answer was cut off because it reached the length limit. Ask a narrower question to get the rest.)"
)


@dataclass
class TurnResult:
    """What one turn gives back (P64). `answer` is "" when `refusal` is set."""

    chat_id: str
    answer: str
    tool_events: list
    refusal: Refusal | None


def _to_message(step):
    """One saved step in OpenRouter's chat format (P55)."""
    if step.role == "user":
        return {"role": "user", "content": step.content}
    if step.role == "tool":
        return {"role": "tool", "tool_call_id": step.tool_call_id, "content": step.content}
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
    turns = []
    for m in messages:
        if m["role"] == "user" or not turns:
            turns.append([])
        turns[-1].append(m)
    while len(turns) > 1 and len(json.dumps([m for t in turns for m in t])) > HISTORY_CHAR_LIMIT:
        turns.pop(0)
    return [m for t in turns for m in t]


def _messages(store, chat_id):
    history = [_to_message(s) for s in store.load_steps(chat_id)]
    return [{"role": "system", "content": SYSTEM_PROMPT}] + _trimmed(history)


def _end_early(store, chat_id, events, cause):
    """Save the refusal as the final assistant text, so the history stays valid (P59)."""
    store.add_step(chat_id, "assistant", REFUSALS[cause])
    return TurnResult(chat_id, "", events, Refusal(cause, REFUSALS[cause]))


def run_turn(store, con, provider, chat_id, message):
    """Run one chat turn and return its TurnResult. Every step is saved as it happens."""
    if chat_id is not None and not store.exists(chat_id):
        return TurnResult(chat_id, "", [], Refusal("chat_not_found", REFUSALS["chat_not_found"]))
    if chat_id is None:
        chat_id = store.new_chat()
    store.add_step(chat_id, "user", message)

    tools = tool_specs_for_ai()
    events = []
    rounds = 0
    while True:
        try:
            reply = provider.send(_messages(store, chat_id), tools, MAX_TOKENS)
        except AIUnavailable:  # QuotaReached too
            return _end_early(store, chat_id, events, "ai_unavailable")

        if not reply.tool_calls:
            text = reply.text or ""
            if reply.cut_off:  # P68: tell the user the answer is incomplete
                text = f"{text}\n\n{CUT_OFF_NOTE}"
            store.add_step(
                chat_id, "assistant", text, model=reply.model, input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens, cost_usd=reply.cost_usd,
            )  # fmt: skip
            if text.strip() == REFUSALS["out_of_scope"]:
                return TurnResult(chat_id, "", events, Refusal("out_of_scope", REFUSALS["out_of_scope"]))
            return TurnResult(chat_id, text, events, None)

        if rounds == MAX_ROUNDS:  # the request after round 5 is not saved and not run
            return _end_early(store, chat_id, events, "too_many_steps")
        rounds += 1

        store.add_step(
            chat_id, "assistant", reply.text, tool_calls=reply.tool_calls, model=reply.model,
            input_tokens=reply.input_tokens, output_tokens=reply.output_tokens, cost_usd=reply.cost_usd,
        )  # fmt: skip
        for call in reply.tool_calls:
            content = json.dumps(run_tool(con, call["name"], call["args"]))
            store.add_step(chat_id, "tool", content, tool_call_id=call["id"])
            # The event holds what was saved, so it equals the result rebuilt from the steps.
            events.append({"id": call["id"], "name": call["name"], "args": call["args"], "result": json.loads(content)})
