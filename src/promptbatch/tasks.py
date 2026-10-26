"""A task is a Markdown file with a TOML header between "+++" lines and the prompt below it.

    +++
    model = "claude-sonnet-5-5"
    max_tokens = 16000
    effort = "low"          # optional: low, medium, high, xhigh, max
    checks = ["html"]       # optional: checks on the result (see checks.py); "html:field" with a schema
    extensions = [".html"]  # optional: which files to take from a folder
    context = ["guide.md"]  # optional: files appended to the system prompt (cached), relative to the task
    schema = "schema.json"  # optional: the answer is JSON matching this schema; the output is saved as .json
    tools = ["web_fetch"]   # optional: server tools (web_fetch, web_search), run by Anthropic
    tool_max_uses = 20      # optional: maximum uses of each tool per file
    fetch_max_tokens = 3000 # optional: maximum tokens of each fetched page (billed as input)
    images = "images"       # optional: the input is JSON and this field lists image paths to attach
                            # (in order, before the prompt; paths relative to the input file's folder)
    +++
    System prompt (optional)
    ---prompt---
    User prompt, with {{content}} and {{name}} (and the variables given with --var key=value).

The Spanish placeholders of version 0.1 ({{contenido}}, {{nombre}}) still work.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SEPARATOR = "---prompt---"
# Server tools: Anthropic runs them, so the machine that launches the task needs no internet access.
SERVER_TOOLS = {"web_fetch": "web_fetch_20260209", "web_search": "web_search_20260209"}
DEFAULT_MODEL = "claude-opus-5-5"
HEADER_KEYS = {
    "model",
    "max_tokens",
    "effort",
    "checks",
    "extensions",
    "context",
    "schema",
    "tools",
    "tool_max_uses",
    "fetch_max_tokens",
    "images",
}
# Placeholder -> the names it may be written with (English, and the Spanish of version 0.1).
PLACEHOLDERS = {"content": ("content", "contenido"), "name": ("name", "nombre")}


@dataclass
class Task:
    name: str
    system: str
    prompt: str
    model: str = DEFAULT_MODEL
    max_tokens: int = 16000
    effort: str | None = None
    checks: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    context: list[Path] = field(default_factory=list)
    schema: dict | None = None
    path: Path | None = None
    tools: list[str] = field(default_factory=list)
    tool_max_uses: int = 20
    fetch_max_tokens: int = 3000
    images_field: str | None = None

    @property
    def output_extension(self) -> str | None:
        """With a schema the output is JSON; without one it keeps the input's extension."""
        return ".json" if self.schema else None

    def tool_definitions(self) -> list[dict]:
        definitions = []
        for name in self.tools:
            d = {"type": SERVER_TOOLS[name], "name": name, "max_uses": self.tool_max_uses}
            if name == "web_fetch":
                d["max_content_tokens"] = self.fetch_max_tokens
            definitions.append(d)
        return definitions

    def full_system(self, extra: list[Path] | None = None) -> str:
        parts = [self.system] if self.system else []
        for f in [*self.context, *(extra or [])]:
            parts.append(f'<document name="{f.name}">\n{f.read_text(encoding="utf-8").strip()}\n</document>')
        return "\n\n".join(parts)

    def build(self, content: str, name: str, variables: dict[str, str] | None = None) -> str:
        text = self.prompt
        values = {alias: value for key, value in (("content", content), ("name", name)) for alias in PLACEHOLDERS[key]}
        for k, v in {**values, **(variables or {})}.items():
            text = text.replace("{{" + k + "}}", v)
        return text


def load(path: str | Path) -> Task:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    header: dict = {}
    if text.startswith("+++"):
        _, raw_header, text = text.split("+++", 2)
        header = tomllib.loads(raw_header)
    text = text.strip("\n")
    system, _, prompt = text.partition(SEPARATOR) if SEPARATOR in text else ("", "", text)
    if not any("{{" + alias + "}}" in prompt for alias in PLACEHOLDERS["content"]):
        raise SystemExit(f"{path}: the task prompt must contain {{{{content}}}}")
    unknown_tools = set(header.get("tools", [])) - set(SERVER_TOOLS)
    if unknown_tools:
        raise SystemExit(f"{path}: unknown tools: {', '.join(sorted(unknown_tools))} (available: {', '.join(SERVER_TOOLS)})")
    unknown_keys = set(header) - HEADER_KEYS
    if unknown_keys:
        raise SystemExit(f"{path}: unknown keys in the header: {', '.join(sorted(unknown_keys))}")
    return Task(
        path=path.resolve(),
        name=path.stem,
        system=system.strip(),
        prompt=prompt.strip(),
        model=header.get("model", DEFAULT_MODEL),
        max_tokens=int(header.get("max_tokens", 16000)),
        effort=header.get("effort"),
        checks=list(header.get("checks", [])),
        extensions=list(header.get("extensions", [])),
        context=[_relative(path, c) for c in header.get("context", [])],
        schema=json.loads(_relative(path, header["schema"]).read_text(encoding="utf-8")) if "schema" in header else None,
        tools=list(header.get("tools", [])),
        tool_max_uses=int(header.get("tool_max_uses", 20)),
        fetch_max_tokens=int(header.get("fetch_max_tokens", 3000)),
        images_field=header.get("images"),
    )


def _relative(task: Path, f: str) -> Path:
    p = Path(f).expanduser()
    p = p if p.is_absolute() else task.parent / p
    if not p.is_file():
        raise SystemExit(f"{task}: {p} does not exist")
    return p


def input_files(inputs: list[str], extensions: list[str]) -> list[Path]:
    """Single files as given; folders, their files (filtered by extension if the task defines them)."""
    files: list[Path] = []
    for i in inputs:
        p = Path(i)
        if p.is_dir():
            files += sorted(
                f
                for f in p.iterdir()
                if f.is_file() and not f.name.startswith(".") and (not extensions or f.suffix in extensions)
            )
        elif p.is_file():
            files.append(p)
        else:
            raise SystemExit(f"Does not exist: {i}")
    return files
