# Contributing

Thanks for your interest in improving these samples.

## Ground rules

- **Samples must actually run.** If you change code, run the sample's offline
  tests and, where you can, its end-to-end test.
- **Never commit environment-specific values.** No tenant IDs, subscription IDs,
  resource names, endpoints, client secrets, tokens, or consent URLs. Everything
  environment-specific belongs in environment variables, the `azd` environment,
  or a `.env` file that is git-ignored.
- **Keep each sample self-contained.** A reader should be able to copy one
  directory and have everything they need.

## Development workflow

1. Fork the repo and create a branch off `main`.
2. Change into the sample directory you are editing.
3. Install dependencies and run the checks:

   ```bash
   uv sync
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest -m "not e2e"
   ```

4. If your change affects provisioning, validate the template:

   ```bash
   az bicep build --file infra/main.bicep --stdout
   ```

5. Open a pull request describing what you changed and how you verified it.

## Running end-to-end tests

End-to-end tests are excluded from the default test run because they create real
Azure resources and require an authenticated user. Opt in explicitly:

```bash
uv run pytest -m e2e
```

Each sample's README documents the environment variables its end-to-end test needs.

## Commit and PR expectations

- One logical change per pull request.
- Update the sample's README when you change its behavior or prerequisites.
- CI must be green before review.

## Code of conduct

This project has adopted a [Code of Conduct](./CODE_OF_CONDUCT.md). By
participating, you are expected to uphold it.
