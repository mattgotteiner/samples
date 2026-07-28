# Samples

Runnable, self-contained samples for Azure AI Foundry and Microsoft 365 developer
scenarios. Every sample stands on its own: clone the repo, change into the sample
directory, and follow its README.

## Available samples

| Sample | Language | What it shows |
| --- | --- | --- |
| [`work-iq-a2a-foundry`](./work-iq-a2a-foundry) | Python | Call the **Microsoft Work IQ** agent from an **Azure AI Foundry** agent over the **Agent2Agent (A2A)** protocol, using OAuth identity passthrough so answers are grounded in the signed-in user's own Microsoft 365 data. Includes an `azd` template, an end-to-end test, and a scripted Microsoft Entra setup. |

## Repository conventions

Each sample directory contains:

- a `README.md` with prerequisites, a quickstart, and troubleshooting,
- an `azure.yaml` plus `infra/` when the sample provisions Azure resources,
- a `tests/` directory with offline unit tests and an opt-in end-to-end test,
- a `pyproject.toml` (or equivalent) pinning its own dependencies.

Samples never hardcode a tenant, subscription, or endpoint. Everything
environment-specific is read from environment variables or the `azd` environment.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). Bug reports and pull requests are welcome.

## Security

To report a security issue, see [SECURITY.md](./SECURITY.md). Please do not open
public issues for security reports.

## License

Licensed under the [MIT License](./LICENSE).

## Trademarks

This project may contain trademarks or logos for projects, products, or services.
Use of Microsoft trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of third-party trademarks or logos is subject to those third parties' policies.
