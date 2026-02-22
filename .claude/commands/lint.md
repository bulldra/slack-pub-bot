# lint - Run mypy and ruff, then fix issues

Run mypy and ruff to check for type errors and lint issues, then fix any problems found.

## Steps

1. Run `uv run ruff check --fix src/ tests/` to auto-fix lint issues
2. Run `uv run ruff format src/ tests/` to format code
3. Run `uv run mypy src/ tests/` to check types
4. If mypy reports errors, fix them in the source code
5. Re-run mypy to confirm all errors are resolved
6. Run `uv run pytest tests/` to confirm tests still pass
