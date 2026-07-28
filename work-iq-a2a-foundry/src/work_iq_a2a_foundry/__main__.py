"""Command line entry point for the Work IQ on Foundry sample."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from work_iq_a2a_foundry.config import ConfigurationError, Settings
from work_iq_a2a_foundry.runner import WorkIqFoundryAgent

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONSENT_REQUIRED = 2
EXIT_CONFIG_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="work-iq-a2a-foundry",
        description=(
            "Ask a question through an Azure AI Foundry agent that calls Microsoft Work IQ "
            "over the Agent2Agent (A2A) protocol using the signed-in user's identity."
        ),
    )
    parser.add_argument("prompt", nargs="?", help="Question to ask. Defaults to WORK_IQ_PROMPT.")
    parser.add_argument("--project-endpoint", help="Overrides AZURE_AI_PROJECT_ENDPOINT.")
    parser.add_argument("--connection-name", help="Overrides WORK_IQ_CONNECTION_NAME.")
    parser.add_argument("--model-deployment", help="Overrides AZURE_AI_MODEL_DEPLOYMENT_NAME.")
    parser.add_argument(
        "--event-log",
        type=Path,
        help="Append the raw response stream to this file as JSON Lines, for debugging.",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress progress output; print only the answer."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the sample. Returns a process exit code."""
    args = build_parser().parse_args(argv)

    overrides: dict[str, object] = {
        "project_endpoint": args.project_endpoint,
        "connection_name": args.connection_name,
        "model_deployment": args.model_deployment,
    }
    if args.event_log:
        overrides["event_log_path"] = args.event_log
    if args.prompt:
        overrides["prompt"] = args.prompt

    try:
        settings = Settings.from_env(**overrides)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    if not args.quiet:
        print(settings.describe())
        print("-" * 60)

    with WorkIqFoundryAgent(settings) as agent:
        if not args.quiet and agent.agent_version:
            print(f"[agent] created temporary version {agent.agent_version}")
        result = agent.ask(echo=not args.quiet)

    if args.quiet and result.answer_text:
        print(result.answer_text)

    if result.error:
        print(f"\nRun failed: {result.error}", file=sys.stderr)
        return EXIT_FAILED

    if result.needs_consent:
        print(
            "\nSign-in required. Open the URL above as the same user you signed in with, "
            "complete consent, then run this sample again.",
            file=sys.stderr,
        )
        return EXIT_CONSENT_REQUIRED

    if not result.called_remote_agent:
        print(
            "\nThe agent answered without calling the Work IQ A2A tool. "
            "Check that the connection name is correct and that the tool is attached.",
            file=sys.stderr,
        )
        return EXIT_FAILED

    return EXIT_OK if result.succeeded else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
