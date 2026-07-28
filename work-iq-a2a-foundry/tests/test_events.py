"""Tests for the response-stream helpers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseTextDeltaEvent,
)

from work_iq_a2a_foundry.events import (
    CONSENT_PREFIX,
    AgentRunResult,
    append_event_log,
    classify_event,
    describe_failure,
    error_message,
    event_to_dict,
    find_consent_url,
    remote_tool_name,
    strip_consent_prefix,
    text_delta,
)

CONSENT_URL = "https://login.example.com/consent?state=abc"


class _Dumpable:
    def model_dump(self, mode: str = "python", warnings: bool = True) -> dict[str, object]:
        return {"type": "response.completed", "nested": {"value": 1}}


class _Opaque:
    def __repr__(self) -> str:
        return "<opaque event>"


def test_event_to_dict_prefers_model_dump() -> None:
    assert event_to_dict(_Dumpable())["type"] == "response.completed"


def test_event_to_dict_falls_back_to_repr() -> None:
    assert event_to_dict(_Opaque()) == {"repr": "<opaque event>"}


def test_event_to_dict_is_json_serializable() -> None:
    payload = event_to_dict(_Dumpable())

    json.dumps(payload)  # must not raise


def test_strip_consent_prefix() -> None:
    assert strip_consent_prefix(f"{CONSENT_PREFIX}{CONSENT_URL}") == CONSENT_URL
    assert strip_consent_prefix(CONSENT_URL) == CONSENT_URL


@pytest.mark.parametrize(
    "payload",
    [
        {"consent_link": CONSENT_URL},
        {"item": {"sign_in_url": CONSENT_URL}},
        {"a": [{"b": {"consent_url": CONSENT_URL}}]},
        {"message": f"{CONSENT_PREFIX}{CONSENT_URL}"},
    ],
)
def test_find_consent_url_locates_nested_urls(payload: dict) -> None:
    assert find_consent_url(payload) == CONSENT_URL


def test_find_consent_url_ignores_unrelated_urls() -> None:
    assert find_consent_url({"docs_url": "https://example.com/docs"}) is None
    assert find_consent_url({"count": 3, "items": []}) is None


class _RawEvent:
    """Stands in for a preview stream event the SDK does not model as a typed class."""

    def __init__(self, event_type: str, item: dict | None = None) -> None:
        self.type = event_type
        if item is not None:
            self.item = item


@pytest.mark.parametrize(
    ("event", "payload", "expected"),
    [
        (ResponseTextDeltaEvent.model_construct(delta="hi"), {}, "text_delta"),
        (ResponseCompletedEvent.model_construct(), {}, "completed"),
        (ResponseFailedEvent.model_construct(), {}, "failed"),
        (ResponseErrorEvent.model_construct(message="boom"), {}, "failed"),
        (
            ResponseOutputItemAddedEvent.model_construct(item=SimpleNamespace(type="a2a_preview_call")),
            {},
            "a2a_call",
        ),
        (
            ResponseOutputItemDoneEvent.model_construct(item=SimpleNamespace(type="message")),
            {},
            "other",
        ),
    ],
)
def test_classify_event_uses_typed_sdk_events(event: object, payload: dict, expected: str) -> None:
    assert classify_event(event, payload) == expected


@pytest.mark.parametrize(
    ("event_type", "payload", "expected"),
    [
        ("response.output_text.delta", {}, "text_delta"),
        ("response.completed", {}, "completed"),
        ("response.failed", {}, "failed"),
        ("response.oauth_consent_requested", {}, "consent_required"),
        ("response.output_item.added", {"item": {"type": "a2a_preview_call"}}, "a2a_call"),
        ("response.output_item.done", {"item": {"type": "remote_function_call"}}, "a2a_call"),
        ("response.output_item.added", {"item": {"type": "message"}}, "other"),
        ("keepalive", {}, "other"),
    ],
)
def test_classify_event_falls_back_for_preview_events(event_type: str, payload: dict, expected: str) -> None:
    assert classify_event(_RawEvent(event_type), payload) == expected


def test_text_delta_reads_the_typed_field() -> None:
    assert text_delta(ResponseTextDeltaEvent.model_construct(delta="chunk")) == "chunk"
    assert text_delta(_RawEvent("keepalive")) == ""


def test_error_message_prefers_typed_fields() -> None:
    typed = ResponseErrorEvent.model_construct(message="typed failure")
    assert error_message(typed, {"error": "ignored"}) == "typed failure"

    failed = ResponseFailedEvent.model_construct(
        response=SimpleNamespace(error=SimpleNamespace(message="response failed"))
    )
    assert error_message(failed, {}) == "response failed"

    assert error_message(_RawEvent("error"), {"error": {"message": "raw"}}) == "raw"
    assert "without a message" in error_message(_RawEvent("error"), {})


def test_remote_tool_name() -> None:
    typed = ResponseOutputItemAddedEvent.model_construct(
        item=SimpleNamespace(type="a2a_preview_call", name="work-iq-a2a")
    )
    assert remote_tool_name(typed, {}) == "work-iq-a2a"

    assert remote_tool_name(_RawEvent("x"), {"item": {"name": "work-iq-a2a"}}) == "work-iq-a2a"
    assert remote_tool_name(_RawEvent("x"), {"item": {"label": "work-iq"}}) == "work-iq"
    assert remote_tool_name(_RawEvent("x"), {"item": {}}) is None
    assert remote_tool_name(_RawEvent("x"), {}) is None


def test_describe_failure_adds_guidance_for_known_errors() -> None:
    described = describe_failure("Unsupported A2A modality. Only text modality is supported.")

    assert "What to do:" in described
    assert "azure-ai-projects" in described


def test_describe_failure_passes_through_unknown_errors() -> None:
    assert describe_failure("something odd") == "something odd"


def test_append_event_log_writes_json_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "events.jsonl"

    append_event_log(log_path, 0, "response.created", {"a": 1})
    append_event_log(log_path, 1, "response.completed", {"b": 2})

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line)["event_index"] for line in lines] == [0, 1]


def test_append_event_log_accepts_none() -> None:
    append_event_log(None, 0, "response.created", {})  # must not raise


def test_run_result_success_semantics() -> None:
    result = AgentRunResult(answer_text="an answer", called_remote_agent=True)

    assert result.succeeded is True
    assert result.needs_consent is False


def test_run_result_consent_semantics() -> None:
    result = AgentRunResult(consent_url=CONSENT_URL)

    assert result.succeeded is False
    assert result.needs_consent is True


def test_run_result_error_beats_text() -> None:
    result = AgentRunResult(answer_text="partial", error="boom")

    assert result.succeeded is False
