"""promptbatch MCP server: lets an agent (such as Claude Code) hand bulk work over to the API.

Few tools and short answers, on purpose: tool definitions and answers take up the agent's context. The tools return
summaries (how many, cost, what to review), never the generated content: to see a result, the agent reads the file.

    claude mcp add promptbatch -e PROMPTBATCH_KEY_FILE=… -e PROMPTBATCH_TASK_DIRS=… -- <venv>/bin/promptbatch-mcp
"""

from __future__ import annotations

import contextlib
import functools
import io
import json
import os
import threading
import time
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer

from . import config, runner, tasks

server = MCPServer(
    "promptbatch",
    instructions=(
        "Runs a task (a prompt in a .md file) over many files with the Anthropic API and the user's key, without "
        'passing the content through this conversation. Always start with mode "estimate" and show the estimate to '
        'the user before spending; for many files use "batch" (half price, up to 24 h) and then "status". The '
        "available tasks are in the promptbatch://tasks resource."
    ),
)

_running: dict[str, dict] = {}  # output folder -> background job (direct mode)


def _no_hang(f):
    """An error inside a tool (also SystemExit, which tasks.load and config use to report problems) is returned as
    text. If it escaped, the server would close without answering and the client would wait until its timeout."""

    @functools.wraps(f)
    def wrapper(*a, **k):
        try:
            return f(*a, **k)
        except SystemExit as e:
            return f"Error: {e}"
        except Exception as e:  # noqa: BLE001
            return f"Error: {type(e).__name__}: {e}"

    return wrapper


def _quiet(f, *a, **k):
    """The runner writes to stdout, which in MCP is the protocol channel: it is captured."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = f(*a, **k)
    return r, buf.getvalue()


@server.tool()
@_no_hang
def launch(
    task: str,
    inputs: list[str],
    output: str,
    mode: Literal["estimate", "direct", "batch"] = "estimate",
    limit: int | None = None,
    max_cost: float | None = None,
    variables: dict[str, str] | None = None,
    context: list[str] | None = None,
    model: str | None = None,
) -> str:
    """Runs the task (path to its .md) over the files or folders in `inputs`, writing one file per input to `output`.
    What is already in `output` is skipped. Modes: "estimate" (only counts tokens and cost, free), "direct" (now; for
    a few files) or "batch" (Batch API: half price, check with status later). `max_cost` in USD is required to spend:
    in direct mode it stops when reached; in batch mode nothing is submitted if the estimate is over it."""
    t = tasks.load(task)
    if model:
        t.model = model
    out = Path(output)
    jobs = runner.prepare(tasks.input_files(inputs, t.extensions), out, False, t)[:limit]
    if not jobs:
        return "Nothing to do: everything is already in the output."
    client = config.client()
    prices = config.load_prices(os.environ.get("PROMPTBATCH_PRICES"))
    ctx = [Path(c) for c in context or []]
    est = runner.estimate(client, t, jobs, variables, prices, mode == "batch", ctx)
    cost = est["estimated_cost_usd"]
    summary = (
        f"{est['files']} file{'' if est['files'] == 1 else 's'}, {est['input_tokens']} input tokens, estimated cost ≈ "
        f"{f'${cost:.3f}' if cost is not None else 'unknown (no price for this model)'} "
        f"({t.model}{', in batch' if mode == 'batch' else ''})."
    )
    if mode == "estimate":
        return summary
    if max_cost is None:
        return summary + " Not launched: pass max_cost (USD) to spend, after the user agrees to the estimate."
    if mode == "batch":
        if cost is not None and cost > max_cost:
            return summary + f" Not submitted: over max_cost (${max_cost})."
        batch_id = runner.submit_batch(client, t, jobs, out, variables, ctx)
        return summary + f' Batch submitted: {batch_id}. Use status(output="{output}") later.'
    # In the background: a long job must not leave the tool hanging (MCP clients cut off idle calls).
    key = str(out.resolve())
    if key in _running and _running[key]["thread"].is_alive():
        return f"There is already a job running in {output}: use status."
    state = {"total": len(jobs), "start": time.time(), "log": "", "error": None}

    def work():
        try:
            state["log"] = runner.execute(client, t, jobs, out, variables, prices, 4, max_cost, ctx, quiet=True)
        except Exception as e:  # noqa: BLE001 — reported by status
            state["error"] = f"{type(e).__name__}: {e}"

    state["thread"] = threading.Thread(target=work, daemon=True)
    state["thread"].start()
    _running[key] = state
    return summary + f' Running in the background ({len(jobs)} files): use status(output="{output}") to follow it.'


@server.tool()
@_no_hang
def status(output: str) -> str:
    """Status of an output folder. With a batch running, how it is going; if the batch has finished, it collects the
    results. Returns the summary: done, to review (with the reason), cost and tokens."""
    out = Path(output)
    job = _running.get(str(out.resolve()))
    if job:
        # Only the results written since this job started (the folder may hold older ones).
        meta = out / ".meta"
        done = sum(1 for f in meta.glob("*.json") if f.stat().st_mtime >= job["start"]) if meta.is_dir() else 0
        if job["error"]:
            return f"The job failed: {job['error']}. " + json.dumps(runner.report(out), ensure_ascii=False)
        if job["thread"].is_alive():
            return f"Running: {done} files with a result (of {job['total']} launched), {time.time() - job['start']:.0f} s."
    if (out / ".batch.json").exists():
        client = config.client()
        info, batch = runner.batch_status(client, out)
        if batch.processing_status != "ended":
            c = batch.request_counts
            return f"Batch {info['id']} running: {c.processing} pending, {c.succeeded} done, {c.errored} with errors."
        if not info.get("collected"):
            if not info.get("task_path"):
                return f'Batch {info["id"]} finished, but I don\'t know which task it used: collect it with "promptbatch batch collect".'
            prices = config.load_prices(os.environ.get("PROMPTBATCH_PRICES"))
            _quiet(runner.collect_batch, client, tasks.load(info["task_path"]), out, prices)
            stored = json.loads((out / ".batch.json").read_text())
            stored["collected"] = True
            (out / ".batch.json").write_text(json.dumps(stored, indent=1))
    return json.dumps(runner.report(out), ensure_ascii=False)


@server.resource("promptbatch://tasks", name="tasks", description="Available tasks: path and what each one is for")
def available_tasks() -> str:
    folders = [d for d in os.environ.get("PROMPTBATCH_TASK_DIRS", "").split(os.pathsep) if d] or ["tasks"]
    lines = []
    for d in folders:
        for f in sorted(Path(d).expanduser().glob("*.md")):
            text = f.read_text(encoding="utf-8")
            description = next((line.lstrip("# ").strip() for line in text.splitlines()[1:6] if line.startswith("#")), "")
            if text.startswith("+++"):
                lines.append(f"- {f.resolve()}: {description}")
    return "\n".join(lines) or "No tasks in PROMPTBATCH_TASK_DIRS."


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
