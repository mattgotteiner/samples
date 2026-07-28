"""Tests for settings resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from work_iq_a2a_foundry.config import (
    DEFAULT_AGENT_NAME,
    DEFAULT_PROMPT,
    WORK_IQ_A2A_ENDPOINT,
    WORK_IQ_SCOPE,
    ConfigurationError,
    Settings,
)


def test_from_env_reads_required_values(base_env: dict[str, str]) -> None:
    settings = Settings.from_env(base_env)

    assert settings.project_endpoint.endswith("/api/projects/demo")
    assert settings.connection_name == "work-iq-a2a"
    assert settings.model_deployment == "gpt-4.1-mini"
    assert settings.agent_name == DEFAULT_AGENT_NAME
    assert settings.prompt == DEFAULT_PROMPT


REQUIRED_KEYS = sorted(
    ["AZURE_AI_PROJECT_ENDPOINT", "WORK_IQ_CONNECTION_NAME", "AZURE_AI_MODEL_DEPLOYMENT_NAME"]
)


@pytest.mark.parametrize("missing", REQUIRED_KEYS)
def test_missing_required_value_is_reported_by_name(base_env: dict[str, str], missing: str) -> None:
    base_env.pop(missing)

    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env(base_env)

    assert missing in str(excinfo.value)
    assert "azd up" in str(excinfo.value)


def test_endpoint_must_be_https(base_env: dict[str, str]) -> None:
    base_env["AZURE_AI_PROJECT_ENDPOINT"] = "ftp://example.invalid"

    with pytest.raises(ConfigurationError, match="https"):
        Settings.from_env(base_env)


def test_trailing_slash_is_removed_from_endpoint(base_env: dict[str, str]) -> None:
    base_env["AZURE_AI_PROJECT_ENDPOINT"] = base_env["AZURE_AI_PROJECT_ENDPOINT"] + "/"

    assert not Settings.from_env(base_env).project_endpoint.endswith("/")


def test_overrides_take_precedence(base_env: dict[str, str]) -> None:
    settings = Settings.from_env(base_env, connection_name="other-connection")

    assert settings.connection_name == "other-connection"


def test_empty_overrides_fall_back_to_environment(base_env: dict[str, str]) -> None:
    settings = Settings.from_env(base_env, connection_name=None, model_deployment="")

    assert settings.connection_name == "work-iq-a2a"
    assert settings.model_deployment == "gpt-4.1-mini"


def test_optional_values_are_parsed(base_env: dict[str, str]) -> None:
    base_env.update(
        {
            "WORK_IQ_AGENT_NAME": "custom-agent",
            "WORK_IQ_PROMPT": "hello",
            "WORK_IQ_KEEP_AGENT_VERSION": "true",
            "WORK_IQ_EVENT_LOG_PATH": "out/events.jsonl",
            "WORK_IQ_TIMEOUT_SECONDS": "45",
            "AZURE_TENANT_ID": "contoso.onmicrosoft.com",
        }
    )

    settings = Settings.from_env(base_env)

    assert settings.agent_name == "custom-agent"
    assert settings.prompt == "hello"
    assert settings.keep_agent_version is True
    assert settings.event_log_path == Path("out/events.jsonl")
    assert settings.timeout_seconds == 45.0
    assert settings.tenant_id == "contoso.onmicrosoft.com"


@pytest.mark.parametrize("value", ["not-a-number", "0", "-5"])
def test_invalid_timeout_is_rejected(base_env: dict[str, str], value: str) -> None:
    base_env["WORK_IQ_TIMEOUT_SECONDS"] = value

    with pytest.raises(ConfigurationError, match="WORK_IQ_TIMEOUT_SECONDS"):
        Settings.from_env(base_env)


def test_describe_does_not_leak_secrets(base_env: dict[str, str]) -> None:
    base_env["WORK_IQ_OAUTH_CLIENT_SECRET"] = "super-secret-value"

    described = Settings.from_env(base_env).describe()

    assert "super-secret-value" not in described
    assert "work-iq-a2a" in described


def test_work_iq_endpoint_keeps_required_trailing_slash() -> None:
    assert WORK_IQ_A2A_ENDPOINT.endswith("/a2a/")
    assert WORK_IQ_SCOPE.endswith("/WorkIQAgent.Ask")
