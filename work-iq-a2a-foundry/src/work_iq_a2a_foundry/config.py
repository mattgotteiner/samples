"""Configuration for the Work IQ on Foundry sample.

Nothing here is specific to a particular tenant, subscription, or Foundry project.
Every environment-specific value is read from the environment. ``azd`` exports the
same variable names after ``azd up``, so no manual copying is required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Public, Microsoft-published Work IQ constants.
# See https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/
# ---------------------------------------------------------------------------

#: Work IQ A2A gateway. The trailing slash is required by the gateway.
WORK_IQ_A2A_ENDPOINT = "https://workiq.svc.cloud.microsoft/a2a/"

#: Delegated permission that lets an app ask Work IQ questions for the signed-in user.
WORK_IQ_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"

#: Application ID of Microsoft's multi-tenant Work IQ resource application.
WORK_IQ_APP_ID = "fdcc1f02-fc51-4226-8753-f668596af7f7"

#: Identifier of the ``WorkIQAgent.Ask`` delegated scope on the Work IQ application.
WORK_IQ_SCOPE_ID = "0b1715fd-f4bf-4c63-b16d-5be31f9847c2"

DEFAULT_AGENT_NAME = "work-iq-coordinator"

DEFAULT_PROMPT = "Ask Work IQ what it can help me with, grounded in my Microsoft 365 data."

DEFAULT_INSTRUCTIONS = (
    "You are a coordinator agent. Answer every user request by calling the Work IQ "
    "A2A tool and grounding your answer only in what the remote Work IQ agent returns. "
    "Do not answer from your own knowledge. If the tool reports that OAuth sign-in or "
    "consent is required, relay that sign-in instruction to the user verbatim."
)

REQUIRED_ENV_VARS = (
    "AZURE_AI_PROJECT_ENDPOINT",
    "WORK_IQ_CONNECTION_NAME",
    "AZURE_AI_MODEL_DEPLOYMENT_NAME",
)


class ConfigurationError(RuntimeError):
    """Raised when a required setting is missing or invalid."""


def _env_flag(source: dict[str, str], name: str, *, default: bool = False) -> bool:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from environment variables.

    Attributes:
        project_endpoint: Foundry project endpoint, for example
            ``https://<resource>.services.ai.azure.com/api/projects/<project>``.
        connection_name: Name of the ``RemoteA2A`` project connection pointing at Work IQ.
        model_deployment: Name of a model deployment in the Foundry project.
        agent_name: Name used for the temporary agent this sample creates.
        prompt: Question to send to the coordinator agent.
        instructions: System instructions for the coordinator agent.
        tenant_id: Optional tenant to force during local sign-in.
        keep_agent_version: Keep the temporary agent version instead of deleting it.
        event_log_path: Optional path to append the raw response stream to, as JSON Lines.
        timeout_seconds: Maximum wall-clock time to spend streaming a single response.
    """

    project_endpoint: str
    connection_name: str
    model_deployment: str
    agent_name: str = DEFAULT_AGENT_NAME
    prompt: str = DEFAULT_PROMPT
    instructions: str = DEFAULT_INSTRUCTIONS
    tenant_id: str | None = None
    keep_agent_version: bool = False
    event_log_path: Path | None = None
    timeout_seconds: float = 300.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, **overrides: object) -> Settings:
        """Build settings from environment variables.

        Args:
            env: Mapping to read from. Defaults to ``os.environ``.
            **overrides: Values that take precedence over the environment. Empty values
                are ignored so that callers can pass optional CLI arguments directly.

        Returns:
            A fully populated, immutable :class:`Settings`.

        Raises:
            ConfigurationError: If a required variable is missing or malformed.
        """
        source = {k: str(v) for k, v in (os.environ if env is None else env).items()}
        supplied = {k: v for k, v in overrides.items() if v not in (None, "")}

        def pick(key: str, env_name: str) -> str:
            value = supplied.pop(key, None)
            if value:
                return str(value).strip()
            return source.get(env_name, "").strip()

        project_endpoint = pick("project_endpoint", "AZURE_AI_PROJECT_ENDPOINT")
        connection_name = pick("connection_name", "WORK_IQ_CONNECTION_NAME")
        model_deployment = pick("model_deployment", "AZURE_AI_MODEL_DEPLOYMENT_NAME")

        missing = [
            env_name
            for env_name, value in zip(
                REQUIRED_ENV_VARS,
                (project_endpoint, connection_name, model_deployment),
                strict=False,
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "Missing required environment variable(s): "
                + ", ".join(missing)
                + ". Run 'azd up' in this directory, or copy .env.example to .env and fill it in."
            )

        if not project_endpoint.startswith("https://"):
            raise ConfigurationError(
                f"AZURE_AI_PROJECT_ENDPOINT must be an https URL, got {project_endpoint!r}."
            )

        timeout_raw = source.get("WORK_IQ_TIMEOUT_SECONDS", "").strip() or "300"
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise ConfigurationError(
                f"WORK_IQ_TIMEOUT_SECONDS must be a number, got {timeout_raw!r}."
            ) from exc
        if timeout_seconds <= 0:
            raise ConfigurationError("WORK_IQ_TIMEOUT_SECONDS must be greater than zero.")

        log_value = source.get("WORK_IQ_EVENT_LOG_PATH", "").strip()

        resolved: dict[str, object] = {
            "project_endpoint": project_endpoint.rstrip("/"),
            "connection_name": connection_name,
            "model_deployment": model_deployment,
            "agent_name": source.get("WORK_IQ_AGENT_NAME", "").strip() or DEFAULT_AGENT_NAME,
            "prompt": source.get("WORK_IQ_PROMPT", "").strip() or DEFAULT_PROMPT,
            "instructions": source.get("WORK_IQ_INSTRUCTIONS", "").strip() or DEFAULT_INSTRUCTIONS,
            "tenant_id": source.get("AZURE_TENANT_ID", "").strip() or None,
            "keep_agent_version": _env_flag(source, "WORK_IQ_KEEP_AGENT_VERSION"),
            "event_log_path": Path(log_value) if log_value else None,
            "timeout_seconds": timeout_seconds,
        }
        resolved.update(supplied)
        return cls(**resolved)  # type: ignore[arg-type]

    def describe(self) -> str:
        """Return a human-readable, secret-free summary of the active settings."""
        lines = [
            f"project endpoint : {self.project_endpoint}",
            f"connection       : {self.connection_name}",
            f"model deployment : {self.model_deployment}",
            f"agent name       : {self.agent_name}",
        ]
        if self.tenant_id:
            lines.append(f"tenant           : {self.tenant_id}")
        return "\n".join(lines)
