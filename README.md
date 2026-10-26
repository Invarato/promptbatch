# promptbatch

[![Tests](https://github.com/Invarato/promptbatch/actions/workflows/tests.yml/badge.svg)](https://github.com/Invarato/promptbatch/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/promptbatch)](https://pypi.org/project/promptbatch/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

*[Leer en español](README.es.md)*

Run **one task** (a prompt) over **many files** with the Anthropic API: directly, or as a batch with the Batch API
(half price, results within 24 hours). Built for large, repetitive jobs: translating hundreds of articles, fixing
typos, writing meta descriptions, classifying…

- **Nothing project-specific:** tasks are Markdown files; your project brings its own.
- **Safe to relaunch:** whatever is already in the output folder is not redone (or paid for again).
- **Spending under control:** it estimates the cost first (`--dry-run`) and stops at `--max-cost`.
- **With checks:** if a result fails a check (for example, the HTML lost tags), it goes to `_review/` instead of the
  output.
- **For agents too:** an MCP server lets an agent such as Claude Code hand bulk work over to the API without passing
  the content through its conversation.

## Install

```bash
pip install promptbatch            # the command-line tool
pip install 'promptbatch[mcp]'     # plus the MCP server
```

Or from source: `pip install 'git+https://github.com/Invarato/promptbatch'`. It needs Python 3.11 or later.

## The API key

It never goes into a repository. It is looked up in this order: the `ANTHROPIC_API_KEY` variable, the `--key-file`
option, the `PROMPTBATCH_KEY_FILE` variable, or the file `~/.config/promptbatch/api.key` (with permissions `600`).

## A task

A `.md` file with a TOML header between `+++` lines, the system prompt (optional) and, after `---prompt---`, the
prompt, with `{{content}}` (the file) and `{{name}}` (its name without extension). More variables with
`--var key=value`.

```markdown
+++
model = "claude-sonnet-5-5"
max_tokens = 16000
effort = "low"                     # low, medium, high, xhigh, max (low is usually enough for translations)
checks = ["html:content"]          # checks: html, non-empty; "name:field" applies it to a field of the JSON answer
extensions = [".html"]             # which files to take from a folder
context = ["style-guide.md", "glossary.md"]   # appended to the system prompt (cached)
schema = "translation.schema.json"            # JSON answer matching this schema (the output is .json)
+++
You are a professional translator…
---prompt---
Translate this HTML into {{language}}, keeping every tag:

{{content}}
```

See [tasks/example-summary.md](tasks/example-summary.md). Without `model`, `claude-opus-5-5` is used.

- **Context** (`context`, or `--context file` on the command line): style guides, glossaries… They go into the system
  prompt, which is cached: from the second request on they are billed at 0.1×. The minimum cacheable size depends on
  the model (from 512 to 4096 tokens); below it, nothing is cached.
- **Server tools** (`tools = ["web_fetch"]` or `"web_search"`): Anthropic runs them, so they work even if the machine
  launching the task has no internet access. `web_fetch` only fetches URLs that appear in the prompt. Limits:
  `tool_max_uses` and `fetch_max_tokens` (fetched content is billed as input). If an answer pauses halfway
  (`pause_turn`), direct mode resumes it on its own; in a batch it goes to `_review/`.
- **Images** (`images = "field"`): the input is JSON and that field lists image paths (relative to the input file's
  folder), which are attached, in order, before the prompt. For describing images, alt text, etc.
- **Schema** (`schema`): the API returns JSON that matches the schema (structured output). Useful to return several
  fields at once (title, slug, meta description, content) or lists of corrections.

## Usage

```bash
# 1. Estimate without spending (it only counts tokens)
promptbatch run tasks/my-task.md inputs/ -o output/ --dry-run

# 2. Try 3 files with a spending limit
promptbatch run tasks/my-task.md inputs/ -o output/ --limit 3 --max-cost 1

# 3. Everything, at half price with the Batch API
promptbatch batch submit tasks/my-task.md inputs/ -o output/ --max-cost 20
promptbatch batch status output/
promptbatch batch collect tasks/my-task.md output/
```

In the output: one file per input (same name); `_review/` with the ones that failed a check; `.meta/<file>.json` with
tokens, cost and stop reason; `.batch.json` with the batch in progress.

## From an agent (MCP server)

`promptbatch-mcp` exposes two tools and a resource, so that an agent such as Claude Code can delegate bulk work
without passing the content through its conversation (it only gets summaries):

- `launch(task, inputs, output, mode="estimate"|"direct"|"batch", limit, max_cost, variables, context, model)`.
  To spend (`direct` or `batch`), `max_cost` in USD is required.
- `status(output)`: how the batch is going; when it has finished, it collects it. Summary of done, to review and cost.
- resource `promptbatch://tasks`: the tasks in the folders of `PROMPTBATCH_TASK_DIRS`.

```bash
claude mcp add -s project promptbatch -e PROMPTBATCH_KEY_FILE=~/.config/promptbatch/api.key \
  -e PROMPTBATCH_TASK_DIRS=./tasks -- promptbatch-mcp
```

The skill [skill/SKILL.md](skill/SKILL.md) tells the agent when and how to use it (estimate first, ask before
spending, try a few, the rest as a batch). Copy it to `.claude/skills/promptbatch/` in your project.

## Costs

The prices used for estimates are in `config.py` and are approximate: check them and, if they change, pass them with
`--prices file.toml` (`["model"]` with `input` and `output` in USD per million tokens, and optionally `cache_read`).
The real cost of each request is recorded in `.meta/`.

## Upgrading from 0.1

See the [CHANGELOG](CHANGELOG.md): the MCP tools were renamed to English, and tasks written for 0.1 keep working.

## Development

```bash
pip install -e '.[dev,mcp]'
pytest
ruff check src tests && ruff format --check src tests
```

## License

[MIT](LICENSE).
