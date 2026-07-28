"""Call Microsoft Work IQ from an Azure AI Foundry agent over the A2A protocol.

The public entry points are :class:`Settings`, :class:`WorkIqFoundryAgent`, and the
event helpers used to interpret the Foundry response stream.
"""

from work_iq_a2a_foundry.config import (
    WORK_IQ_A2A_ENDPOINT,
    WORK_IQ_APP_ID,
    WORK_IQ_SCOPE,
    WORK_IQ_SCOPE_ID,
    ConfigurationError,
    Settings,
)
from work_iq_a2a_foundry.events import (
    AgentRunResult,
    classify_event,
    describe_failure,
    event_to_dict,
    find_consent_url,
    strip_consent_prefix,
)
from work_iq_a2a_foundry.runner import WorkIqFoundryAgent

__all__ = [
    "WORK_IQ_A2A_ENDPOINT",
    "WORK_IQ_APP_ID",
    "WORK_IQ_SCOPE",
    "WORK_IQ_SCOPE_ID",
    "AgentRunResult",
    "ConfigurationError",
    "Settings",
    "WorkIqFoundryAgent",
    "classify_event",
    "describe_failure",
    "event_to_dict",
    "find_consent_url",
    "strip_consent_prefix",
]
