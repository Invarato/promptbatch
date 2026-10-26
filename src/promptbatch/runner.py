"""Running a task: one request per file (run) or as a batch (Batch API, half price)."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import anthropic

from . import checks, config
from .tasks import Task

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
REVIEW_DIR = "_review"
# Folders that already hold a result: the current one and the one of version 0.1.
DONE_DIRS = ("", REVIEW_DIR, "_revisar")


def image_blocks(task: Task, source: str, folder: Path) -> list[dict]:
    """Image blocks (base64) for the paths listed in the `images` field of a JSON input."""
    if not task.images_field:
        return []
    paths = json.loads(source).get(task.images_field) or []
    blocks = []
    for p in paths:
        f = Path(p) if Path(p).is_absolute() else folder / p
        media_type = IMAGE_TYPES.get(f.suffix.lower())
        if not media_type or not f.is_file():
            raise ValueError(f"image does not exist or has an unsupported type: {f}")
        blocks.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(f.read_bytes()).decode()},
            }
        )
    return blocks


@dataclass
class Job:
    file: Path
    source: str
    custom_id: str


def final_text(message) -> str:
    """The final text of the answer: with tools, what comes after the last non-text block (the earlier text is the
    model's commentary between calls)."""
    blocks = list(message.content)
    last = max((i for i, b in enumerate(blocks) if b.type != "text"), default=-1)
    return "".join(b.text for b in blocks[last + 1 :] if b.type == "text")


def output_name(task: Task, file: Path) -> str:
    return file.stem + task.output_extension if task.output_extension else file.name


def request_params(
    task: Task, source: str, name: str, variables: dict | None, context: list[Path] | None = None, folder: Path | None = None
) -> dict:
    text = task.build(source, name, variables)
    images = image_blocks(task, source, folder or Path("."))
    p: dict = {
        "model": task.model,
        "max_tokens": task.max_tokens,
        "messages": [{"role": "user", "content": [*images, {"type": "text", "text": text}] if images else text}],
    }
    system = task.full_system(context)
    if system:
        # The system prompt (with the guide and the glossary) repeats in every request: with the cache, only the
        # first request pays it in full (the rest read it at 0.1×). It must be byte-identical: nothing variable here.
        p["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    if task.tools:
        p["tools"] = task.tool_definitions()
    output_config = {}
    if task.effort:
        output_config["effort"] = task.effort
    if task.schema:
        output_config["format"] = {"type": "json_schema", "schema": task.schema}
    if output_config:
        p["output_config"] = output_config
    return p


def prepare(files: list[Path], output: Path, force: bool, task: Task | None = None) -> list[Job]:
    jobs = []
    for i, f in enumerate(files):
        n = output_name(task, f) if task else f.name
        if not force and any((output / d / n).exists() for d in DONE_DIRS):
            continue  # already done: a run can be relaunched without repeating (or paying for) earlier work
        cid = f"f{i:05d}-{hashlib.sha1(f.name.encode()).hexdigest()[:8]}"
        jobs.append(Job(f, f.read_text(encoding="utf-8"), cid))
    return jobs


def save(output: Path, job: Job, task: Task, text: str, usage, stop_reason: str, prices: dict, batch: bool) -> dict:
    problems = checks.run(task.checks, job.source, text, is_json=bool(task.schema))
    if stop_reason == "max_tokens":
        problems.append("answer cut off by max_tokens: raise it in the task")
    if stop_reason == "refusal":
        problems.append("the API declined the request (refusal)")
    if stop_reason == "pause_turn":
        problems.append("stopped halfway through tool use (pause_turn): relaunch it in direct mode")
    target = output / (REVIEW_DIR if problems else "") / output_name(task, job.file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    cache_written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    meta = {
        "file": job.file.name,
        "task": task.name,
        "model": task.model,
        "batch": batch,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_write_tokens": cache_written,
        "cache_read_tokens": cache_read,
        "cost_usd": config.cost(prices, task.model, usage.input_tokens, usage.output_tokens, batch, cache_written, cache_read),
        "stop_reason": stop_reason,
        "problems": problems,
    }
    (output / ".meta").mkdir(exist_ok=True)
    (output / ".meta" / f"{job.file.name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def estimate(client, task: Task, jobs: list[Job], variables: dict | None, prices: dict, batch: bool, context=None) -> dict:
    """Counts the input tokens (free, nothing is generated). The output is estimated from the input."""
    total_in = total_out = 0
    total_cost = 0.0
    known = True
    for job in jobs:
        p = request_params(task, job.source, job.file.stem, variables, context, job.file.parent)
        extra = {k: p[k] for k in ("system", "output_config") if k in p}
        n = client.messages.count_tokens(model=p["model"], messages=p["messages"], **extra).input_tokens
        # Output: at most the input (translating, fixing) and never more than max_tokens (classifying,
        # summarizing). It is a ceiling, not a prediction: the real cost goes to .meta/.
        out = min(n, task.max_tokens)
        total_in += n
        total_out += out
        c = config.cost(prices, task.model, n, out, batch)
        if c is None:
            known = False
        else:
            total_cost += c
    return {
        "files": len(jobs),
        "input_tokens": total_in,
        "estimated_output_tokens": total_out,
        "estimated_cost_usd": round(total_cost, 4) if known else None,
    }


def execute(
    client,
    task: Task,
    jobs: list[Job],
    output: Path,
    variables,
    prices,
    concurrency: int,
    max_cost: float | None,
    context=None,
    quiet: bool = False,
) -> float:
    """One request per file, several at a time. Stops when spending reaches max_cost. Returns what was spent.
    `quiet`: writes nothing to stdout or stderr (in the MCP server, stdout is the protocol channel)."""
    say = (lambda *a, **k: None) if quiet else print
    spent = 0.0
    stop = False

    def call(p):
        # Streaming when the answer can be long (the SDK requires it) or with server tools (without it, a request
        # that fetches many pages can wait until the timeout and be retried).
        if task.max_tokens > 16000 or task.tools:
            with client.messages.stream(**p) as s:
                return s.get_final_message()
        return client.messages.create(**p)

    def one(job: Job):
        p = request_params(task, job.source, job.file.stem, variables, context, job.file.parent)
        m = call(p)
        usage = [m.usage]
        # With server tools the answer can pause (pause_turn): it is sent back as it is and the server continues
        # where it left off. Up to 5 times.
        for _ in range(5):
            if m.stop_reason != "pause_turn":
                break
            p = {**p, "messages": [*p["messages"], {"role": "assistant", "content": m.content}]}
            m = call(p)
            usage.append(m.usage)
        if len(usage) > 1:  # add up the usage of every round
            for f in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                setattr(m.usage, f, sum(getattr(u, f, 0) or 0 for u in usage))
        return job, m

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = {}
        queue = iter(jobs)

        def launch():
            job = next(queue, None)
            if job:
                pending[pool.submit(one, job)] = job
            return job

        for _ in range(concurrency):
            launch()
        while pending:
            for fut in as_completed(list(pending)):
                job = pending.pop(fut)
                try:
                    _, m = fut.result()
                    meta = save(output, job, task, final_text(m), m.usage, m.stop_reason, prices, False)
                    spent += meta["cost_usd"] or 0
                    mark = "REVIEW" if meta["problems"] else "ok"
                    say(
                        f"[{mark}] {job.file.name}  ({meta['input_tokens']}→{meta['output_tokens']} tokens, ${meta['cost_usd'] or 0:.4f})",
                        flush=True,
                    )
                    for problem in meta["problems"]:
                        say(f"        · {problem}", flush=True)
                except anthropic.APIError as e:
                    say(f"[ERROR] {job.file.name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                if max_cost is not None and spent >= max_cost and not stop:
                    stop = True
                    say(f"** Spending limit reached (${spent:.2f} ≥ ${max_cost:.2f}): no more requests are launched.", flush=True)
                if not stop:
                    launch()
                break
    return spent


# ---------------------------------------------------------------- batch (Batch API)


def submit_batch(client, task: Task, jobs: list[Job], output: Path, variables, context=None) -> str:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    requests = [
        Request(
            custom_id=j.custom_id,
            params=MessageCreateParamsNonStreaming(
                **request_params(task, j.source, j.file.stem, variables, context, j.file.parent)
            ),
        )
        for j in jobs
    ]
    batch = client.messages.batches.create(requests=requests)
    output.mkdir(parents=True, exist_ok=True)
    (output / ".batch.json").write_text(
        json.dumps(
            {
                "id": batch.id,
                "task": task.name,
                "task_path": str(task.path) if task.path else None,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "files": {j.custom_id: str(j.file) for j in jobs},
            },
            indent=1,
        )
    )
    return batch.id


def read_batch_info(output: Path) -> dict:
    """The .batch.json of an output folder (also the Spanish keys of version 0.1)."""
    info = json.loads((output / ".batch.json").read_text())
    for new, old in (("task_path", "ruta_tarea"), ("files", "ficheros"), ("collected", "recogido"), ("task", "tarea")):
        if new not in info and old in info:
            info[new] = info[old]
    return info


def batch_status(client, output: Path):
    info = read_batch_info(output)
    return info, client.messages.batches.retrieve(info["id"])


def collect_batch(client, task: Task, output: Path, prices: dict) -> dict:
    info, batch = batch_status(client, output)
    if batch.processing_status != "ended":
        raise SystemExit(f"Batch {info['id']} is still running ({batch.processing_status}): {batch.request_counts}")
    counts = {"ok": 0, "review": 0, "error": 0}
    spent = 0.0
    for r in client.messages.batches.results(info["id"]):
        path = Path(info["files"][r.custom_id])
        job = Job(path, path.read_text(encoding="utf-8"), r.custom_id)
        if r.result.type != "succeeded":
            print(f"[ERROR] {path.name}: {r.result.type}", file=sys.stderr)
            counts["error"] += 1
            continue
        m = r.result.message
        meta = save(output, job, task, final_text(m), m.usage, m.stop_reason, prices, True)
        spent += meta["cost_usd"] or 0
        counts["review" if meta["problems"] else "ok"] += 1
    counts["cost_usd"] = round(spent, 4)
    return counts


def _meta(f: Path) -> dict:
    """A .meta/ file (also the Spanish keys of version 0.1)."""
    m = json.loads(f.read_text())
    return {
        "file": m.get("file", m.get("fichero")),
        "problems": m.get("problems", m.get("problemas", [])),
        "cost_usd": m.get("cost_usd", m.get("coste_usd")) or 0,
        "input_tokens": m.get("input_tokens", m.get("tokens_entrada", 0)),
        "output_tokens": m.get("output_tokens", m.get("tokens_salida", 0)),
    }


def report(output: Path, max_detail: int = 10) -> dict:
    """Summary of an output folder from .meta/: how many are fine, how many to review (and why), and the cost."""
    metas = [_meta(f) for f in sorted((output / ".meta").glob("*.json"))] if (output / ".meta").is_dir() else []
    review = [m for m in metas if m["problems"]]
    return {
        "folder": str(output),
        "done": len(metas) - len(review),
        "to_review": len(review),
        "cost_usd": round(sum(m["cost_usd"] for m in metas), 4),
        "tokens": {"input": sum(m["input_tokens"] for m in metas), "output": sum(m["output_tokens"] for m in metas)},
        "review": [{"file": m["file"], "problem": m["problems"][0][:200]} for m in review[:max_detail]],
    }
