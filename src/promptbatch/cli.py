"""promptbatch run|batch ... (see the README)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__, config, runner, tasks


def _variables(items: list[str] | None) -> dict[str, str]:
    variables = {}
    for item in items or []:
        k, _, v = item.partition("=")
        variables[k.strip()] = v
    return variables


def _common(p: argparse.ArgumentParser):
    p.add_argument("task", help="task file (.md)")
    p.add_argument("inputs", nargs="+", help="input files or folders")
    p.add_argument("-o", "--output", required=True, help="output folder")
    p.add_argument("--var", action="append", help="extra prompt variable: key=value (used as {{key}})")
    p.add_argument("--limit", type=int, help="only the first N files (to try it out)")
    p.add_argument("--force", action="store_true", help="also redo the files already in the output")
    p.add_argument("--max-cost", type=float, help="spending limit in USD")
    p.add_argument("--prices", help="TOML file with your own prices")
    p.add_argument("--key-file", help="file with the API key")
    p.add_argument("--model", help="overrides the task's model")
    p.add_argument("--context", action="append", help="extra context file for the system prompt (repeatable)")


def _prepare(a):
    task = tasks.load(a.task)
    if a.model:
        task.model = a.model
    files = tasks.input_files(a.inputs, task.extensions)
    output = Path(a.output)
    jobs = runner.prepare(files, output, a.force, task)
    if a.limit:
        jobs = jobs[: a.limit]
    a.context_files = [Path(c) for c in (a.context or [])]
    return task, jobs, output, _variables(a.var), config.load_prices(a.prices)


def _summary(est: dict, task, batch: bool) -> str:
    cost = est["estimated_cost_usd"]
    price = f"${cost:.3f}" if cost is not None else "unknown (no price for this model: pass --prices)"
    return (
        f"{est['files']} file{'' if est['files'] == 1 else 's'}, {est['input_tokens']} input tokens, estimated cost{' in batch' if batch else ''} "
        f"≈ {price} with {task.model}"
    )


def cmd_run(a):
    task, jobs, output, variables, prices = _prepare(a)
    if not jobs:
        print("Nothing to do (everything is already in the output; use --force to redo it).")
        return 0
    client = config.client(a.key_file)
    print(_summary(runner.estimate(client, task, jobs, variables, prices, False, a.context_files), task, False))
    if a.dry_run:
        return 0
    output.mkdir(parents=True, exist_ok=True)
    spent = runner.execute(client, task, jobs, output, variables, prices, a.concurrency, a.max_cost, a.context_files)
    print(f"Spent: ${spent:.4f}. Details per file in {output}/.meta/")
    return 0


def cmd_batch_submit(a):
    task, jobs, output, variables, prices = _prepare(a)
    if not jobs:
        print("Nothing to do.")
        return 0
    client = config.client(a.key_file)
    est = runner.estimate(client, task, jobs, variables, prices, True, a.context_files)
    cost = est["estimated_cost_usd"]
    print(_summary(est, task, True))
    if a.max_cost is not None and cost is not None and cost > a.max_cost:
        raise SystemExit(f"The estimated cost (${cost:.2f}) is over --max-cost (${a.max_cost:.2f}). Not submitted.")
    if a.dry_run:
        return 0
    print("Batch submitted:", runner.submit_batch(client, task, jobs, output, variables, a.context_files))
    print(f"Check it with: promptbatch batch status {output}   and collect it with: promptbatch batch collect {a.task} {output}")
    return 0


def cmd_batch_status(a):
    client = config.client(a.key_file)
    info, batch = runner.batch_status(client, Path(a.output))
    print(info["id"], batch.processing_status, batch.request_counts)
    return 0


def cmd_batch_collect(a):
    task = tasks.load(a.task)
    client = config.client(a.key_file)
    print(json.dumps(runner.collect_batch(client, task, Path(a.output), config.load_prices(a.prices)), indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="promptbatch", description=__doc__)
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="one request per file, right now")
    _common(r)
    r.add_argument("--dry-run", action="store_true", help="only count tokens and estimate the cost")
    r.add_argument("--concurrency", type=int, default=4)
    r.set_defaults(f=cmd_run)

    b = sub.add_parser("batch", help="Batch API (half price, up to 24 h)").add_subparsers(dest="sub", required=True)
    s = b.add_parser("submit", help="submit the batch")
    _common(s)
    s.add_argument("--dry-run", action="store_true", help="only count tokens and estimate the cost")
    s.set_defaults(f=cmd_batch_submit)
    st = b.add_parser("status", help="status of the batch of an output folder")
    st.add_argument("output")
    st.add_argument("--key-file")
    st.set_defaults(f=cmd_batch_status)
    c = b.add_parser("collect", help="collect the results of a finished batch")
    c.add_argument("task")
    c.add_argument("output")
    c.add_argument("--prices")
    c.add_argument("--key-file")
    c.set_defaults(f=cmd_batch_collect)

    a = ap.parse_args(argv)
    return a.f(a)
