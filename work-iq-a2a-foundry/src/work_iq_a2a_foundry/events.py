"""Pure helpers for interpreting the Foundry response stream.

Foundry agents stream over the OpenAI Responses API, so most of the stream is already
modelled by typed classes in the ``openai`` package and this module dispatches on those
types rather than re-parsing raw dictionaries.

Two things are *not* covered by any SDK today, and are the only places this module falls
back to untyped access:

* the A2A tool-call output item, which is a Foundry preview extension, and
* the OAuth sign-in payload Foundry emits when a connection has no delegated token yet.

These functions perform no network or Azure I/O, so they can be unit tested offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseTextDeltaEvent,
)

CONSENT_PREFIX = "OAuth consent required. Please visit: "

#: Stream item types that indicate a call out to the remote A2A endpoint.
A2A_CALL_ITEM_TYPES = frozenset({"a2a_preview_call", "remote_function_call"})

#: Keys whose string values are treated as a sign-in/consent URL.
CONSENT_URL_KEYS = frozenset(
    {"consent_link", "consent_url", "signin_link", "sign_in_url", "authorization_url"}
)


@dataclass
class AgentRunResult:
    """Outcome of a single agent run.

    Attributes:
        answer_text: Concatenated assistant text, if the run produced any.
        consent_url: Sign-in/consent URL, if Foundry asked the user to sign in.
        called_remote_agent: Whether the agent actually invoked the A2A tool.
        error: Human-readable failure description, if the run failed.
        event_count: Number of stream events observed.
        tool_names: Names of remote tools the agent invoked.
    """

    answer_text: str = ""
    consent_url: str | None = None
    called_remote_agent: bool = False
    error: str | None = None
    event_count: int = 0
    tool_names: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """True when the run produced text and reported no error."""
        return bool(self.answer_text.strip()) and self.error is None

    @property
    def needs_consent(self) -> bool:
        """True when the run stopped because the user must sign in or consent."""
        return self.consent_url is not None and not self.answer_text.strip()


def event_to_dict(event: Any) -> dict[str, Any]:
    """Convert an SDK stream event into a plain, JSON-safe dictionary.

    Falls back to ``{"repr": ...}`` when the event exposes no serialization method.
    """
    for method_name in ("model_dump", "to_dict", "dict"):
        method = getattr(event, method_name, None)
        if not callable(method):
            continue
        try:
            raw = method(mode="json", warnings=False) if method_name == "model_dump" else method()
        except TypeError:
            try:
                raw = method()
            except Exception:  # noqa: BLE001 - serialization is best effort
                continue
        except Exception:  # noqa: BLE001 - serialization is best effort
            continue
        return _json_safe(raw)
    return {"repr": repr(event)}


def strip_consent_prefix(value: str) -> str:
    """Remove the human-readable prefix Foundry prepends to consent URLs."""
    if value.startswith(CONSENT_PREFIX):
        return value[len(CONSENT_PREFIX) :].strip()
    return value.strip()


def find_consent_url(payload: Any) -> str | None:
    """Recursively search a payload for an OAuth consent or sign-in URL.

    Foundry surfaces the URL under different key names depending on the event, so this
    looks for well-known key names as well as any string carrying the consent prefix.
    """
    if isinstance(payload, str):
        return strip_consent_prefix(payload) if payload.startswith(CONSENT_PREFIX) else None

    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, str) and value.startswith("http") and str(key).lower() in CONSENT_URL_KEYS:
                return strip_consent_prefix(value)
            nested = find_consent_url(value)
            if nested:
                return nested
        return None

    if isinstance(payload, (list, tuple)):
        for item in payload:
            nested = find_consent_url(item)
            if nested:
                return nested
    return None


def classify_event(event: Any, payload: dict[str, Any] | None = None) -> str:
    """Map a stream event onto a small, stable vocabulary.

    Dispatches on the typed OpenAI Responses events where they exist, and only falls
    back to the serialized payload for the Foundry preview items the SDK does not model.

    Returns one of ``text_delta``, ``a2a_call``, ``consent_required``, ``completed``,
    ``failed``, or ``other``.
    """
    if isinstance(event, ResponseTextDeltaEvent):
        return "text_delta"
    if isinstance(event, (ResponseFailedEvent, ResponseErrorEvent, ResponseIncompleteEvent)):
        return "failed"
    if isinstance(event, ResponseCompletedEvent):
        return "completed"
    if isinstance(event, (ResponseOutputItemAddedEvent, ResponseOutputItemDoneEvent)):
        item_type = str(getattr(getattr(event, "item", None), "type", "") or "")
        if item_type in A2A_CALL_ITEM_TYPES:
            return "a2a_call"

    # Foundry preview events. The SDK may deliver these as unmodelled objects, so the
    # event type string and serialized payload are the only reliable signals.
    event_type = str(getattr(event, "type", "") or "")
    if event_type == "response.output_text.delta":
        return "text_delta"
    if event_type in {"response.failed", "response.error", "error"}:
        return "failed"
    if event_type == "response.completed":
        return "completed"
    if "oauth" in event_type or "consent" in event_type:
        return "consent_required"
    if event_type in {"response.output_item.added", "response.output_item.done"} and payload:
        item = payload.get("item")
        if isinstance(item, dict) and item.get("type") in A2A_CALL_ITEM_TYPES:
            return "a2a_call"
    return "other"


def text_delta(event: Any) -> str:
    """Return the incremental assistant text carried by a text-delta event."""
    return str(getattr(event, "delta", "") or "")


def error_message(event: Any, payload: dict[str, Any] | None = None) -> str:
    """Extract a human-readable error from a failure event.

    ``ResponseFailedEvent`` carries a typed ``response.error`` and ``ResponseErrorEvent``
    carries a typed ``message``; the payload is only consulted for preview events.
    """
    if isinstance(event, ResponseFailedEvent):
        error = getattr(getattr(event, "response", None), "error", None)
        message = getattr(error, "message", None)
        if isinstance(message, str) and message:
            return message
    if isinstance(event, ResponseErrorEvent):
        message = getattr(event, "message", None)
        if isinstance(message, str) and message:
            return message
    if isinstance(event, ResponseIncompleteEvent):
        details = getattr(getattr(event, "response", None), "incomplete_details", None)
        reason = getattr(details, "reason", None)
        if isinstance(reason, str) and reason:
            return f"The response ended early: {reason}"
    return _error_message_from_payload(payload or {})


def remote_tool_name(event: Any, payload: dict[str, Any] | None = None) -> str | None:
    """Return the remote tool or connection name from an A2A call event, if present."""
    item = getattr(event, "item", None)
    for key in ("name", "label", "connection_name"):
        value = getattr(item, key, None)
        if isinstance(value, str) and value:
            return value
    raw_item = (payload or {}).get("item")
    if isinstance(raw_item, dict):
        for key in ("name", "label", "connection_name"):
            value = raw_item.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def describe_failure(message: str) -> str:
    """Turn a known raw error into actionable guidance for the reader."""
    guidance = {
        "only text modality is supported": (
            "Work IQ authenticated the request but rejected the A2A message shape because "
            "it accepts text parts only. Upgrade 'azure-ai-projects' to the latest release, "
            "which sends text-only A2A parts."
        ),
        "consent_required": (
            "Work IQ requires the signed-in user to consent. Open the sign-in URL printed "
            "above, complete consent as that same user, then run the sample again."
        ),
        "tenant provided in token does not match": (
            "Your Azure sign-in is for a different tenant than the Foundry project. Set "
            "AZURE_TENANT_ID to the project's tenant and run 'az login --tenant <id>' again."
        ),
        "does not have authorization to perform action": (
            "The signed-in user is missing a role on the Foundry resource. Assign the "
            "'Azure AI User' role on the Foundry account, then retry."
        ),
        "connection": (
            "Check that WORK_IQ_CONNECTION_NAME matches a RemoteA2A connection in the "
            "Foundry project. 'azd provision' creates it for you."
        ),
        "403": (
            "Work IQ returned 403. The most likely causes are that the tenant has no "
            "usage-based billing plan for Work IQ, that the signed-in user is not assigned "
            "to that plan, or that admin consent for WorkIQAgent.Ask was never granted. See "
            "https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/enable-work-iq"
        ),
    }
    lowered = message.lower()
    for needle, advice in guidance.items():
        if needle in lowered:
            return f"{message}\n\nWhat to do: {advice}"
    return message


def append_event_log(log_path: Path | None, index: int, event_type: str, payload: dict[str, Any]) -> None:
    """Append one event to a JSON Lines log, creating parent directories as needed."""
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"event_index": index, "type": event_type, "payload": payload}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True))
        handle.write("\n")


def _error_message_from_payload(payload: dict[str, Any]) -> str:
    for key in ("error", "message", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            nested = value.get("message") or value.get("detail")
            if isinstance(nested, str) and nested:
                return nested
    response = payload.get("response")
    if isinstance(response, dict):
        return _error_message_from_payload(response)
    return "The response stream reported a failure without a message."


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)
