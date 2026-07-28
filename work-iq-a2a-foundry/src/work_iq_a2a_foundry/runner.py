"""Drives an Azure AI Foundry agent that calls Work IQ over the A2A protocol."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import A2APreviewTool, AgentVersionDetails, PromptAgentDefinition
from azure.core.credentials import TokenCredential
from azure.identity import AzureCliCredential, ChainedTokenCredential, DefaultAzureCredential
from openai import OpenAI

from work_iq_a2a_foundry.config import Settings
from work_iq_a2a_foundry.events import (
    AgentRunResult,
    append_event_log,
    classify_event,
    describe_failure,
    error_message,
    event_to_dict,
    find_consent_url,
    remote_tool_name,
    text_delta,
)


def build_credential(settings: Settings) -> ChainedTokenCredential:
    """Return a credential that works both locally and on a CI/hosted runner.

    ``AzureCliCredential`` is tried first because it is the most predictable choice for
    a developer running the sample after ``az login``. ``DefaultAzureCredential`` then
    covers managed identity, environment variables, and other hosted scenarios.

    ``DefaultAzureCredential`` does not accept a single ``tenant_id``; each credential in
    its chain takes its own tenant keyword, so they are set individually.
    """
    tenant = settings.tenant_id
    cli_kwargs: dict[str, Any] = {"tenant_id": tenant} if tenant else {}
    default_kwargs: dict[str, Any] = (
        {
            "interactive_browser_tenant_id": tenant,
            "shared_cache_tenant_id": tenant,
            "visual_studio_code_tenant_id": tenant,
            "workload_identity_tenant_id": tenant,
        }
        if tenant
        else {}
    )
    return ChainedTokenCredential(
        AzureCliCredential(**cli_kwargs),
        DefaultAzureCredential(
            exclude_interactive_browser_credential=False,
            **default_kwargs,
        ),
    )


class WorkIqFoundryAgent:
    """Creates a temporary Foundry agent wired to a Work IQ A2A connection.

    The agent version is deleted on exit unless ``settings.keep_agent_version`` is set,
    so repeated runs do not accumulate resources.

    Example:
        >>> with WorkIqFoundryAgent(Settings.from_env()) as agent:  # doctest: +SKIP
        ...     result = agent.ask("What did I work on this week?")
        ...     print(result.answer_text)
    """

    def __init__(self, settings: Settings, *, credential: TokenCredential | None = None) -> None:
        self.settings = settings
        self._credential = credential or build_credential(settings)
        self._project = AIProjectClient(
            endpoint=settings.project_endpoint,
            credential=self._credential,
            allow_preview=True,
        )
        self._openai: OpenAI | None = None
        self._agent: AgentVersionDetails | None = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> WorkIqFoundryAgent:
        self.create_agent()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def create_agent(self) -> AgentVersionDetails:
        """Resolve the A2A connection and create a temporary agent version."""
        connection = self._project.connections.get(self.settings.connection_name)
        tool = A2APreviewTool(project_connection_id=connection.id)
        self._agent = self._project.agents.create_version(
            agent_name=self.settings.agent_name,
            definition=PromptAgentDefinition(
                model=self.settings.model_deployment,
                instructions=self.settings.instructions,
                tools=[tool],
            ),
        )
        return self._agent

    def close(self) -> None:
        """Delete the temporary agent version and release clients."""
        if self._openai is not None:
            self._openai.close()
            self._openai = None
        if self._agent is not None and not self.settings.keep_agent_version:
            version = self._agent.version
            try:
                if version is not None:
                    self._project.agents.delete_version(
                        agent_name=self._agent.name, agent_version=str(version)
                    )
                else:
                    self._project.agents.delete(agent_name=self._agent.name)
            except Exception as exc:  # noqa: BLE001 - cleanup must never mask a real error
                print(f"[cleanup] could not delete agent version: {exc}")
            self._agent = None
        self._project.close()
        if hasattr(self._credential, "close"):
            self._credential.close()

    # -- execution ---------------------------------------------------------

    @property
    def agent_version(self) -> str | None:
        """Version string of the temporary agent, once created."""
        return None if self._agent is None else str(self._agent.version or "") or None

    def ask(self, prompt: str | None = None, *, echo: bool = True) -> AgentRunResult:
        """Ask the coordinator agent a question and stream the response.

        Args:
            prompt: Question to send. Defaults to ``settings.prompt``.
            echo: Print streamed text and progress markers to stdout.

        Returns:
            An :class:`AgentRunResult` describing what happened. A run that stops for
            OAuth consent is not an error: inspect ``needs_consent`` and ``consent_url``.
        """
        if self._agent is None:
            self.create_agent()
        if self._openai is None:
            self._openai = self._project.get_openai_client()

        result = AgentRunResult()
        deadline = time.monotonic() + self.settings.timeout_seconds
        chunks: list[str] = []

        try:
            stream = self._openai.responses.create(
                stream=True,
                tool_choice="required",
                input=prompt or self.settings.prompt,
                extra_body={"agent_reference": {"name": self._agent.name, "type": "agent_reference"}},
            )
            for index, event in enumerate(stream):
                if time.monotonic() > deadline:
                    result.error = (
                        f"Timed out after {self.settings.timeout_seconds:.0f}s waiting for "
                        "the Work IQ response."
                    )
                    break

                event_type = str(getattr(event, "type", "") or "")
                payload = event_to_dict(event)
                append_event_log(self.settings.event_log_path, index, event_type, payload)
                result.event_count = index + 1

                kind = classify_event(event, payload)
                if kind == "text_delta":
                    delta = text_delta(event)
                    chunks.append(delta)
                    if echo:
                        print(delta, end="", flush=True)
                elif kind == "a2a_call":
                    result.called_remote_agent = True
                    name = remote_tool_name(event, payload) or self.settings.connection_name
                    if name not in result.tool_names:
                        result.tool_names.append(name)
                    if echo:
                        print(f"[a2a] calling remote agent via '{name}'")
                elif kind == "consent_required":
                    url = find_consent_url(payload)
                    if url and url != result.consent_url:
                        result.consent_url = url
                        if echo:
                            print(f"\n[oauth] sign-in required: {url}")
                elif kind == "failed":
                    result.error = describe_failure(error_message(event, payload))

                # Some consent prompts arrive on events that are not typed as OAuth.
                if result.consent_url is None:
                    url = find_consent_url(payload)
                    if url:
                        result.consent_url = url
                        if echo:
                            print(f"\n[oauth] sign-in required: {url}")
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a result
            result.error = describe_failure(str(exc))

        result.answer_text = "".join(chunks)
        if echo and result.answer_text and not result.answer_text.endswith("\n"):
            print()
        return result
