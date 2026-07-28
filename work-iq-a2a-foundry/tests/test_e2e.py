"""End-to-end test against a real Foundry project and the live Work IQ A2A endpoint.

This test is excluded from the default run. Opt in with:

    uv run pytest -m e2e

It requires:

* ``azd up`` to have completed in this directory (or the equivalent variables set),
* an Azure sign-in (``az login``) as a user who has completed the Work IQ OAuth
  consent flow at least once for this connection,
* that user to be assigned to the tenant's usage-based billing plan for Work IQ.

The test asserts the full path: the coordinator agent invokes the A2A tool, the
request is authenticated through the OAuth connection, and Work IQ returns text.
A run that stops at the consent step fails with the sign-in URL in the message,
because an unconsented connection cannot prove the end-to-end path.
"""

from __future__ import annotations

import os

import pytest

from work_iq_a2a_foundry.config import ConfigurationError, Settings
from work_iq_a2a_foundry.runner import WorkIqFoundryAgent

pytestmark = pytest.mark.e2e

E2E_PROMPT = (
    "Ask Work IQ for a one sentence summary of what it can help me with, based on my Microsoft 365 data."
)


@pytest.fixture(scope="module")
def settings() -> Settings:
    """Resolve settings, skipping the test when the environment is not provisioned."""
    try:
        return Settings.from_env(
            prompt=E2E_PROMPT,
            agent_name=os.environ.get("WORK_IQ_AGENT_NAME") or "work-iq-e2e",
        )
    except ConfigurationError as exc:
        pytest.skip(f"Environment is not provisioned for the end-to-end test: {exc}")


@pytest.fixture(scope="module")
def agent(settings: Settings):
    """Create the temporary agent once and clean it up after the module finishes."""
    with WorkIqFoundryAgent(settings) as running_agent:
        yield running_agent


def test_connection_is_a_remote_a2a_connection(settings: Settings) -> None:
    """The configured connection must exist and point at the Work IQ A2A gateway."""
    from azure.ai.projects import AIProjectClient

    from work_iq_a2a_foundry.config import WORK_IQ_A2A_ENDPOINT
    from work_iq_a2a_foundry.runner import build_credential

    credential = build_credential(settings)
    project = AIProjectClient(endpoint=settings.project_endpoint, credential=credential, allow_preview=True)
    try:
        connection = project.connections.get(settings.connection_name)
    finally:
        project.close()
        if hasattr(credential, "close"):
            credential.close()

    assert connection.id, "connection has no resource id"
    target = str(getattr(connection, "target", "") or "")
    if target:
        assert target.rstrip("/") == WORK_IQ_A2A_ENDPOINT.rstrip("/"), (
            f"connection target {target!r} does not point at the Work IQ A2A gateway"
        )


def test_agent_version_is_created(agent: WorkIqFoundryAgent) -> None:
    """Creating an agent with the A2A tool attached must succeed."""
    assert agent.agent_version, "no agent version was created"


def test_work_iq_answers_through_the_a2a_tool(agent: WorkIqFoundryAgent) -> None:
    """The full path must work: agent -> A2A tool -> OAuth -> Work IQ -> text answer."""
    result = agent.ask(E2E_PROMPT, echo=False)

    if result.needs_consent:
        pytest.fail(
            "Work IQ requires OAuth consent for the signed-in user, so the end-to-end "
            "path could not be verified. Open this URL as that user, complete consent, "
            f"then re-run the test:\n{result.consent_url}"
        )

    assert result.error is None, f"the run reported an error:\n{result.error}"
    assert result.called_remote_agent, (
        "the agent answered without calling the Work IQ A2A tool; "
        f"observed {result.event_count} events, tools={result.tool_names}"
    )
    assert result.answer_text.strip(), "Work IQ returned no text"
    assert result.succeeded
