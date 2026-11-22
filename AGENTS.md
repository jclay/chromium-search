- Single-module Python 3.11+ tool (`chromium_search.py`), run with `python chromium_search.py` (must work on Windows, macOS, Linux)
- Zero dependencies — stdlib only
- Keep it simple: minimal packaging (pyproject.toml, one module, console script `chromium-search`); no-git Windows install is `chromium-search.cmd` + PowerShell snippet in README

## Dev commands

- Format: `uvx ruff format chromium_search.py`
- Lint: `uvx ruff check chromium_search.py`
- Typecheck: `uvx ty check chromium_search.py`
