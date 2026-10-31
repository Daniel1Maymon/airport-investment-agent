"""Fixed refusal messages, one per cause (docs/agent.md, "Refusal messages").

Each cause has its own message because the user's next step differs: an AI
outage must not look like "no data". Steps 14 and 16 pick a message by its key.
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
