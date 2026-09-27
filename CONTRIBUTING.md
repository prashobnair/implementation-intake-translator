# Contributing

Use synthetic fixtures only. Create a branch and PR; do not commit to `main`.
Describe the behavior change, related requirement ID, tests and any trade-offs.
Keep the pure core free of network and runtime dependencies.

```sh
uv sync --python 3.11 --extra dev
uv run --python 3.11 ruff check src tests
uv run --python 3.11 ruff format --check src tests
uv run --python 3.11 mypy --strict src
uv run --python 3.11 pytest -q
```

The local mock is not a Zoho write path. New external integrations need a
separate review, explicit safety constraints and contract tests.
