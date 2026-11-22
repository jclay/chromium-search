- Single-file Python 3.11+ tool (`chromium-search.py`), run with `python chromium-search.py` (must work on Windows, macOS, Linux)
- Zero dependencies — stdlib only
- Keep it simple: no build system, no packaging; Windows install is `chromium-search.cmd` + PowerShell snippet in README

## Dev commands

- Format: `uvx ruff format chromium-search.py`
- Lint: `uvx ruff check chromium-search.py`
- Typecheck: `uvx ty check chromium-search.py`
