"""Test doubles: FakeProvider plays back scripted AI replies, so no test calls a real AI (P66)."""

import copy

import pytest

from app.agent.provider import AIProvider, AIReply


class FakeProvider(AIProvider):
    """An AI provider that plays back a script instead of calling a real AI.

    Each script item is an `AIReply` (returned) or an exception (raised), in order.
    Running out of script fails the test. `calls` holds a deep copy of
    `(messages, tools, max_tokens)` of every call, in order.

    Example: FakeProvider([reply_asking_for_a_tool, final_text_reply]) makes the loop
    run one tool round and then finish, and the test can check what the loop sent.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def send(self, messages, tools, max_tokens):
        # Recorded first, so a call that raises is counted too.
        self.calls.append(copy.deepcopy((messages, tools, max_tokens)))
        if not self.script:
            pytest.fail(f"FakeProvider ran out of scripted replies (call {len(self.calls)}).")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, AIReply):
            pytest.fail(f"FakeProvider script item is neither an AIReply nor an exception: {item!r}")
        return item
