# Changelog

## 0.2.0 — 2026-10-26

First public release.

- **Everything in English**: code, messages, README (with a Spanish version, `README.es.md`), skill and example task.
- **MCP tools renamed**: `lanzar` → `launch` (modes `estimate`, `direct`, `batch`) and `consultar` → `status`; the
  resource `promptbatch://tareas` → `promptbatch://tasks`. Arguments: `task`, `inputs`, `output`, `mode`, `limit`,
  `max_cost`, `variables`, `context`, `model`.
- **The MCP server needs `max_cost` to spend**: `direct` and `batch` modes don't start without it.
- **Placeholders** `{{content}}` and `{{name}}`. The 0.1 ones, `{{contenido}}` and `{{nombre}}`, still work.
- **Checks**: `non-empty` (the 0.1 name, `no-vacio`, still works).
- **Results to review** go to `_review/`. Files in a `_revisar/` folder of 0.1 still count as done.
- **`.meta/` and `.batch.json` use English keys**; the 0.1 ones are still read.
- **Prices**: `claude-fable-5` added, and the higher price of `claude-haiku-5-5` above 100,000 input tokens. Estimates
  are now computed request by request.
- `promptbatch --version`.
- Requires `anthropic>=2.3`.
- Continuous integration (tests and lint on Python 3.11 to 3.13) and automatic publishing to PyPI, with its tag and
  GitHub release, when the version in `pyproject.toml` changes on `main`.

## 0.1.0 — 2026-10-19

First version (private): tasks in Markdown, direct and batch runs, checks, spending limits, server tools, attached
images and MCP server.
