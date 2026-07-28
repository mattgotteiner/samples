"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

BASE_ENV = {
    "AZURE_AI_PROJECT_ENDPOINT": "https://example-resource.services.ai.azure.com/api/projects/demo",
    "WORK_IQ_CONNECTION_NAME": "work-iq-a2a",
    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-4.1-mini",
}


@pytest.fixture
def base_env() -> dict[str, str]:
    """A minimal, valid environment mapping for :meth:`Settings.from_env`."""
    return dict(BASE_ENV)
