"""Fixed refusal messages, one per cause (docs/agent.md, "Refusal messages").

What it is:   The fixed messages the user sees when we can't answer, one per cause.
Why we need:  Each cause has its own message because the user's next step differs: an AI
              outage must not look like "no data".
Used by:      app/tools/base.py, app/tools/find.py ("airport_not_found"),
              app/agent/loop.py and app/agent/prompt.py.
              tests: test_step08_tool_base.py, test_step09_resolver.py, test_step14_agent_loop.py.
              app/presenters.py (refusal_dict picks a message by its key; used by app/api.py).
Uses:         nothing (plain text only).
Main parts:   REFUSALS - cause key -> message, one per row of the table in docs/agent.md.
              Refusal - a refusal sent to the user: its cause (a REFUSALS key) and message.
Design:       docs/agent.md "Refusal messages"; docs/implementation-plan.md P23.
"""

from typing import NamedTuple

REFUSALS = {
    "no_data": "We don't have data to answer this question. Please try asking something else.",
    "airport_not_found": "I couldn't find that airport. Please check the name or use its 3-letter code.",
    "chat_not_found": "I couldn't find this chat. Please start a new chat.",
    "out_of_scope": "I can only answer questions about US airports. Please ask about US airports.",
    "ai_unavailable": "The AI service is not available right now. The airport data is fine; please try again later.",
    "too_many_steps": "This question needed too many steps to answer. Please ask a narrower question.",
    "question_too_long": "Your question is too long (over 1,000 characters). Please shorten it.",
    "busy": "I'm still answering your last question. Please wait for that answer first.",
    "internal_error": "Something went wrong on our side. Please try again later.",
}


class Refusal(NamedTuple):
    """A refusal sent to the user: its cause (a REFUSALS key) and its message."""

    cause: str
    message: str
