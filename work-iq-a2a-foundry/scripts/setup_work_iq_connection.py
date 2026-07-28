# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Create the Microsoft Entra OAuth client and the Work IQ RemoteA2A project connection.

Run automatically by ``azd`` as a post-provision hook, or by hand:

    uv run scripts/setup_work_iq_connection.py

The script is idempotent: running it again reuses the existing application
registration and updates the connection in place.

What it does:

1. Ensures the Work IQ service principal exists in your tenant.
2. Creates (or reuses) a confidential-client app registration for Foundry to use.
3. Adds the ``WorkIQAgent.Ask`` delegated permission and grants admin consent.
4. Creates a fresh client secret.
5. Creates the ``RemoteA2A`` project connection with Custom OAuth identity passthrough.
6. Reads the connection's redirect URI back and registers it on the app.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any

# Public Work IQ identifiers. See:
# https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/
WORK_IQ_APP_ID = "fdcc1f02-fc51-4226-8753-f668596af7f7"
WORK_IQ_SCOPE_ID = "0b1715fd-f4bf-4c63-b16d-5be31f9847c2"
WORK_IQ_A2A_ENDPOINT = "https://workiq.svc.cloud.microsoft/a2a/"
WORK_IQ_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"

CONNECTIONS_API_VERSION = "2026-03-15-preview"
SECRET_DISPLAY_NAME = "foundry-a2a"


class SetupError(RuntimeError):
    """Raised when a required provisioning step cannot be completed."""


def _tool(name: str) -> str:
    for candidate in (name, f"{name}.cmd", f"{name}.exe", f"{name}.bat"):
        found = shutil.which(candidate)
        if found:
            return found
    raise SetupError(f"'{name}' was not found on PATH. Install it and try again.")


def run(
    args: list[str], *, check: bool = True, capture: bool = True, merge_stderr: bool = True
) -> tuple[int, str]:
    """Run a CLI command and return ``(returncode, output)``.

    ``merge_stderr=False`` returns stdout only, which matters for commands whose
    JSON output would otherwise be polluted by CLI warnings written to stderr.
    """
    exe = _tool(args[0])
    proc = subprocess.run(
        [exe, *args[1:]],
        capture_output=capture,
        text=True,
        check=False,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    output = ((stdout + stderr) if merge_stderr or proc.returncode != 0 else stdout).strip()
    if check and proc.returncode != 0:
        raise SetupError(f"Command failed: {' '.join(args)}\n{output}")
    return proc.returncode, output


def az_json(args: list[str], *, check: bool = True) -> Any:
    """Run an ``az`` command that returns JSON."""
    code, output = run(["az", *args, "-o", "json"], check=check, merge_stderr=False)
    if code != 0:
        return None
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def env(name: str, *, required: bool = True, default: str = "") -> str:
    value = (os.environ.get(name) or "").strip()
    if not value and required:
        raise SetupError(
            f"Environment variable {name} is not set. Run this through 'azd provision', "
            "or set the variable yourself before running the script directly."
        )
    return value or default


def log(message: str) -> None:
    print(f"[work-iq-setup] {message}", flush=True)


# --------------------------------------------------------------------------
# Entra application registration
# --------------------------------------------------------------------------


def ensure_work_iq_service_principal() -> None:
    """JIT-provision the Work IQ service principal so consent can be granted."""
    existing = az_json(["ad", "sp", "show", "--id", WORK_IQ_APP_ID], check=False)
    if existing:
        log("Work IQ service principal already present.")
        return
    log("Creating the Work IQ service principal in this tenant...")
    code, output = run(["az", "ad", "sp", "create", "--id", WORK_IQ_APP_ID], check=False)
    if code != 0 and "already exists" not in output.lower():
        raise SetupError(
            "Could not create the Work IQ service principal. You need the Cloud Application "
            f"Administrator role (or higher) in this tenant.\n{output}"
        )


def ensure_app_registration(display_name: str) -> dict[str, str]:
    """Create or reuse a confidential-client app registration."""
    matches = az_json(
        ["ad", "app", "list", "--display-name", display_name, "--query", "[].{appId:appId,id:id}"],
        check=False,
    )
    if matches:
        app = matches[0]
        log(f"Reusing existing app registration '{display_name}'.")
        return {"appId": app["appId"], "objectId": app["id"]}

    log(f"Creating app registration '{display_name}'...")
    created = az_json(
        [
            "ad",
            "app",
            "create",
            "--display-name",
            display_name,
            "--sign-in-audience",
            "AzureADMyOrg",
        ]
    )
    if not created:
        raise SetupError("Failed to create the app registration.")
    app_id = created["appId"]
    run(["az", "ad", "sp", "create", "--id", app_id], check=False)
    return {"appId": app_id, "objectId": created["id"]}


def wait_for_app_replication(app_id: str, timeout_seconds: int = 180) -> None:
    """Block until a freshly created app registration is visible tenant-wide.

    Entra replicates new objects asynchronously. Calling admin-consent too soon
    fails with "has been removed or is configured to use an incorrect application
    identifier", which is misleading -- the app exists, it just is not visible yet
    to the endpoint serving the consent request.
    """
    log("Waiting for the app registration to replicate...")
    deadline = time.monotonic() + timeout_seconds
    delay = 5
    while True:
        code, _ = run(["az", "ad", "sp", "show", "--id", app_id], check=False)
        if code == 0:
            return
        if time.monotonic() >= deadline:
            raise SetupError(
                f"App registration {app_id} did not become visible within "
                f"{timeout_seconds}s. Re-run 'azd provision' to continue."
            )
        time.sleep(delay)
        delay = min(delay * 2, 20)


def ensure_work_iq_permission(app_id: str) -> None:
    """Add the WorkIQAgent.Ask delegated permission and grant admin consent."""
    log("Adding the WorkIQAgent.Ask delegated permission...")
    run(
        [
            "az",
            "ad",
            "app",
            "permission",
            "add",
            "--id",
            app_id,
            "--api",
            WORK_IQ_APP_ID,
            "--api-permissions",
            f"{WORK_IQ_SCOPE_ID}=Scope",
        ],
        check=False,
    )

    log("Granting tenant-wide admin consent...")
    # Consent can also transiently fail while the new permission grant settles.
    deadline = time.monotonic() + 120
    delay = 5
    while True:
        code, output = run(["az", "ad", "app", "permission", "admin-consent", "--id", app_id], check=False)
        if code == 0:
            return
        if time.monotonic() >= deadline:
            break
        log(f"Consent not ready yet, retrying in {delay}s...")
        time.sleep(delay)
        delay = min(delay * 2, 20)

    raise SetupError(
        "Admin consent failed. Ask a Privileged Role Administrator (or Cloud Application "
        "Administrator) to run:\n"
        f"    az ad app permission admin-consent --id {app_id}\n"
        "Then re-run 'azd provision'.\n\n"
        f"Original error:\n{output}"
    )


def reset_client_secret(app_id: str) -> str:
    """Create a fresh client secret for the app and return its value."""
    log("Creating a client secret for the Foundry connection...")
    result = az_json(
        [
            "ad",
            "app",
            "credential",
            "reset",
            "--id",
            app_id,
            "--display-name",
            SECRET_DISPLAY_NAME,
            "--years",
            "1",
            "--append",
        ]
    )
    if not result or not result.get("password"):
        raise SetupError("Could not create a client secret for the app registration.")
    return str(result["password"])


def add_redirect_uri(app_id: str, redirect_uri: str) -> None:
    """Add a web redirect URI to the app registration, preserving existing ones."""
    current = az_json(["ad", "app", "show", "--id", app_id, "--query", "web.redirectUris"], check=False)
    uris = list(current or [])
    if redirect_uri in uris:
        log("Redirect URI already registered.")
        return
    uris.append(redirect_uri)
    log(f"Registering redirect URI on the app: {redirect_uri}")
    run(["az", "ad", "app", "update", "--id", app_id, "--web-redirect-uris", *uris])


# --------------------------------------------------------------------------
# Foundry project connection
# --------------------------------------------------------------------------


def connection_resource_id(
    subscription_id: str, resource_group: str, account: str, project: str, connection: str
) -> str:
    return (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.CognitiveServices/accounts/{account}"
        f"/projects/{project}/connections/{connection}"
    )


def put_connection(resource_id: str, tenant_id: str, client_id: str, client_secret: str) -> None:
    """Create or update the RemoteA2A connection with Custom OAuth identity passthrough."""
    authority = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0"
    body = {
        "properties": {
            "authType": "OAuth2",
            "category": "RemoteA2A",
            "group": "ServicesAndApps",
            # The trailing slash on the target is required by the Work IQ gateway.
            "target": WORK_IQ_A2A_ENDPOINT,
            "isSharedToAll": True,
            "sharedUserList": [],
            "AuthorizationUrl": f"{authority}/authorize",
            "TokenUrl": f"{authority}/token",
            "RefreshUrl": f"{authority}/token",
            "Scopes": [WORK_IQ_SCOPE],
            "Credentials": {"ClientId": client_id, "ClientSecret": client_secret},
            "metadata": {"ApiType": "Azure"},
        }
    }
    log("Creating the RemoteA2A connection to Work IQ...")
    run(
        [
            "az",
            "rest",
            "--method",
            "PUT",
            "--url",
            f"https://management.azure.com{resource_id}?api-version={CONNECTIONS_API_VERSION}",
            "--headers",
            "Content-Type=application/json",
            "--body",
            json.dumps(body),
        ]
    )


def get_connection_redirect_uri(resource_id: str) -> str | None:
    """Read the per-connection redirect URI that Foundry generated."""
    result = az_json(
        [
            "rest",
            "--method",
            "GET",
            "--url",
            f"https://management.azure.com{resource_id}?api-version={CONNECTIONS_API_VERSION}",
        ],
        check=False,
    )
    if not result:
        return None
    properties = result.get("properties") or {}
    for key in ("redirectUrl", "redirectUri", "RedirectUrl"):
        value = properties.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def azd_env_set(key: str, value: str) -> None:
    """Persist a value into the current azd environment, if azd is available."""
    try:
        run(["azd", "env", "set", key, value], check=False)
    except SetupError:
        log(f"azd not available; set {key} yourself before running the sample.")


# --------------------------------------------------------------------------


def main() -> int:
    try:
        subscription_id = env("AZURE_SUBSCRIPTION_ID")
        resource_group = env("AZURE_RESOURCE_GROUP")
        account = env("AZURE_AI_ACCOUNT_NAME")
        project = env("AZURE_AI_PROJECT_NAME")
        environment_name = env("AZURE_ENV_NAME", required=False, default="dev")
        connection_name = env("WORK_IQ_CONNECTION_NAME", required=False, default="work-iq-a2a")

        tenant_id = env("AZURE_TENANT_ID", required=False)
        if not tenant_id:
            account_info = az_json(["account", "show"])
            tenant_id = str((account_info or {}).get("tenantId") or "")
        if not tenant_id:
            raise SetupError("Could not determine the tenant ID. Run 'az login' and retry.")

        display_name = f"work-iq-a2a-foundry-{environment_name}"

        ensure_work_iq_service_principal()
        app = ensure_app_registration(display_name)
        wait_for_app_replication(app["appId"])
        ensure_work_iq_permission(app["appId"])
        client_secret = reset_client_secret(app["appId"])

        resource_id = connection_resource_id(
            subscription_id, resource_group, account, project, connection_name
        )
        put_connection(resource_id, tenant_id, app["appId"], client_secret)

        redirect_uri = get_connection_redirect_uri(resource_id)
        if redirect_uri:
            add_redirect_uri(app["appId"], redirect_uri)
        else:
            log(
                "The connection did not report a redirect URI. Open the connection in the "
                "Foundry portal, copy its redirect URI, and add it to the app registration "
                "under Authentication > Web."
            )

        azd_env_set("WORK_IQ_CONNECTION_NAME", connection_name)
        azd_env_set("WORK_IQ_OAUTH_CLIENT_ID", app["appId"])
        azd_env_set("WORK_IQ_OAUTH_APP_DISPLAY_NAME", display_name)

        log("Done.")
        print()
        print("Work IQ A2A connection is ready.")
        print(f"  connection name : {connection_name}")
        print(f"  OAuth client    : {app['appId']}")
        print()
        print("Next: run the sample. The first run prints a sign-in URL; open it as the")
        print("user whose Microsoft 365 data you want Work IQ to use, then run it again.")
        print()
        print('    uv run -m work_iq_a2a_foundry "What did I work on this week?"')
        return 0
    except SetupError as exc:
        print(f"\nSetup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
