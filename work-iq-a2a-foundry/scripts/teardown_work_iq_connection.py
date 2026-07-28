# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Delete the Microsoft Entra application registration created for this sample.

Run automatically by ``azd down`` as a pre-down hook, or by hand:

    uv run scripts/teardown_work_iq_connection.py

``azd down`` removes the Azure resources, but an app registration lives in Microsoft
Entra rather than in a resource group, so it has to be cleaned up separately.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any


def _tool(name: str) -> str | None:
    for candidate in (name, f"{name}.cmd", f"{name}.exe", f"{name}.bat"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def az_json(args: list[str]) -> Any:
    exe = _tool("az")
    if exe is None:
        return None
    proc = subprocess.run([exe, *args, "-o", "json"], capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def log(message: str) -> None:
    print(f"[work-iq-teardown] {message}", flush=True)


def main() -> int:
    exe = _tool("az")
    if exe is None:
        log("Azure CLI not found; skipping app registration cleanup.")
        return 0

    display_name = (os.environ.get("WORK_IQ_OAUTH_APP_DISPLAY_NAME") or "").strip()
    app_id = (os.environ.get("WORK_IQ_OAUTH_CLIENT_ID") or "").strip()

    if not app_id and display_name:
        matches = az_json(["ad", "app", "list", "--display-name", display_name])
        if matches:
            app_id = str(matches[0].get("appId") or "")

    if not app_id:
        log("No app registration recorded for this environment; nothing to delete.")
        return 0

    log(f"Deleting app registration {app_id}...")
    proc = subprocess.run(
        [exe, "ad", "app", "delete", "--id", app_id], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        log(
            "Could not delete the app registration automatically. Delete it by hand with:\n"
            f"    az ad app delete --id {app_id}"
        )
        return 0

    log("App registration deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
