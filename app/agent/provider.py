"""The AI provider layer: send messages and tools to the AI, get its reply back.

What it is:   One small interface (`AIProvider.send`) and its one real version,
              `OpenRouterProvider`, which calls OpenRouter over HTTP.
Why we need:  The agent loop must not care which AI service answers. Tests pass a fake
              provider instead, so no test calls a real AI. Two errors tell apart "the AI
              is down" and "our quota or spend cap is used up".
Used by:      app/agent/loop.py, app/agent/cli.py, app/api.py (OpenRouterProvider).
              tests: fakes.py, test_step14_agent_loop.py.
Uses:         httpx (HTTP calls to OpenRouter). No other project file.
Main parts:   AIReply - one AI reply: text, tool_calls, model, input_tokens,
                output_tokens, cost_usd, cut_off (stopped at the token limit).
              AIProvider - the interface: send(messages, tools, max_tokens) -> AIReply.
              OpenRouterProvider(api_key, model, client=None) - the real provider.
              AIUnavailable - the AI service could not answer.
              QuotaReached - a kind of AIUnavailable: quota or spend cap reached (402/429).
Design:       docs/agent.md "AI provider layer"; docs/decisions.md 1.2;
              docs/implementation-plan.md P8, P55, P56, P65, P68.
"""

import json
from dataclasses import dataclass

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = 45  # under the API's 60-second limit for a whole turn


class AIUnavailable(Exception):
    """The AI service could not answer (outage, timeout, network, unreadable reply)."""


class QuotaReached(AIUnavailable):
    """The AI service refused because a quota or spend cap is used up."""


@dataclass(frozen=True)
class AIReply:
    """One AI reply. `tool_calls` is [{"id", "name", "args"}] or None (P44, P55).

    `cut_off` is True when the reply stopped at the token limit (P68).
    """

    text: str | None
    tool_calls: list | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    cut_off: bool = False


class AIProvider:
    """Send messages and tools to an AI, get one reply.

    This is only the shape every provider must have. The loop talks to this shape, so
    the real OpenRouter provider and the fake test provider can be swapped freely.
    """

    def send(self, messages, tools, max_tokens):
        raise NotImplementedError


def _args(text):
    """The tool settings as a dict; text that is not JSON is kept as it is (P56).

    The AI sends tool settings as text, e.g. '{"airports": ["SFO"]}'. If the AI writes
    broken text, we keep it as it is; the tool check then returns an error the AI can read.
    """
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


class OpenRouterProvider(AIProvider):
    """The real provider: one POST to OpenRouter's chat completions address per call."""

    def __init__(self, api_key, model, client=None):
        if not api_key or not model:
            raise ValueError("OpenRouter needs an API key and a model name.")
        self.api_key = api_key
        self.model = model
        # Tests can pass their own HTTP client; normally we make a real one.
        self.client = client if client is not None else httpx.Client(timeout=TIMEOUT_SECONDS)

    def send(self, messages, tools, max_tokens):
        # What we send: which model, the chat so far, the tool menu, and the length limit.
        body = {"model": self.model, "messages": messages, "tools": tools, "max_tokens": max_tokens}
        try:
            response = self.client.post(
                OPENROUTER_URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=body
            )
        except httpx.HTTPError as exc:
            # No reply at all: network down, or no answer within 45 seconds.
            raise AIUnavailable(f"OpenRouter call failed: {type(exc).__name__}") from exc
        # 402 = out of credit, 429 = too many requests. Both mean "try later", not a bug.
        if response.status_code in (402, 429):
            raise QuotaReached(f"OpenRouter quota reached (HTTP {response.status_code})")
        if response.status_code >= 400:
            raise AIUnavailable(f"OpenRouter error (HTTP {response.status_code})")
        # Read the reply. Any unexpected shape becomes AIUnavailable, never a crash.
        try:
            data = response.json()
            choice = data["choices"][0]  # we ask for one reply, so there is one choice
            message = choice["message"]
            # The tools the AI asks for, in our simple shape {id, name, args}.
            # The id links each tool result back to its request.
            calls = [
                {"id": c["id"], "name": c["function"]["name"], "args": _args(c["function"]["arguments"])}
                for c in message.get("tool_calls") or []
            ]
            # Token counts and price of this one call, as OpenRouter reports them.
            usage = data.get("usage") or {}
            return AIReply(
                text=message.get("content"),
                tool_calls=calls or None,
                model=data.get("model"),
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                cost_usd=usage.get("cost"),
                cut_off=choice.get("finish_reason") == "length",  # stopped at max_tokens (P68)
            )
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise AIUnavailable("OpenRouter reply could not be read") from exc
