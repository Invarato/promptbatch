"""Checks on the result. If one fails, the file goes to "_review/" instead of the output folder.

Each check takes (input, output) and returns a list of problems (empty if everything is fine).
"""

from __future__ import annotations

import json
import re
from collections import Counter

_TAG = re.compile(r"<\s*/?\s*([a-zA-Z][\w:-]*)")
_ATTRIBUTE = re.compile(r'\b(href|src)\s*=\s*"([^"]*)"')
_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)


def html(source: str, result: str) -> list[str]:
    """The result keeps the same tags, links and images as the input (for translating or fixing HTML)."""
    problems = []
    a, b = Counter(_TAG.findall(source)), Counter(_TAG.findall(result))
    if a != b:
        diff = {k: (a[k], b[k]) for k in set(a) | set(b) if a[k] != b[k]}
        problems.append("different tags (input, output): " + ", ".join(f"{k} {x}→{y}" for k, (x, y) in sorted(diff.items())[:8]))
    attrs_in, attrs_out = Counter(_ATTRIBUTE.findall(source)), Counter(_ATTRIBUTE.findall(result))
    lost = [f"{attr}={url}" for (attr, url) in attrs_in if (attr, url) not in attrs_out and attr == "src"]
    if lost:
        problems.append("images changed or lost: " + ", ".join(lost[:4]))
    if sum(1 for k in attrs_in if k[0] == "href") != sum(1 for k in attrs_out if k[0] == "href"):
        problems.append("different number of links (href)")
    comments_in = [m.strip().split("\n")[0][:40] for m in _COMMENT.findall(source)]
    comments_out = [m.strip().split("\n")[0][:40] for m in _COMMENT.findall(result)]
    if len(comments_in) != len(comments_out):
        problems.append(f"block comments: {len(comments_in)}→{len(comments_out)}")
    return problems


def non_empty(source: str, result: str) -> list[str]:
    problems = []
    if not result.strip():
        problems.append("empty output")
    elif len(result) < 0.2 * len(source):
        problems.append("output much shorter than the input (cut off?)")
    return problems


# "no-vacio" is the name of non-empty in version 0.1: tasks written for it keep working.
CHECKS = {"html": html, "non-empty": non_empty, "no-vacio": non_empty}


def run(names: list[str], source: str, result: str, is_json: bool = False) -> list[str]:
    """With "name:field" the check runs on that field of the JSON answer."""
    problems = []
    data = None
    try:  # if the input is also JSON, "name:field" compares field with field
        source_json = json.loads(source)
    except json.JSONDecodeError:
        source_json = None
    if is_json:
        try:
            data = json.loads(result)
        except json.JSONDecodeError as e:
            return [f"the answer is not valid JSON: {e}"]
    for n in ["non-empty" if not is_json else "", *names]:
        if not n:
            continue
        name, _, field_name = n.partition(":")
        if name not in CHECKS:
            raise SystemExit(f"Unknown check: {name} (available: {', '.join(CHECKS)})")
        if field_name:
            if not isinstance(data, dict) or not isinstance(data.get(field_name), str):
                problems.append(f'missing text field "{field_name}" in the answer')
                continue
            base = (
                source_json[field_name]
                if isinstance(source_json, dict) and isinstance(source_json.get(field_name), str)
                else source
            )
            problems += [f"{field_name}: {p}" for p in CHECKS[name](base, data[field_name])]
        else:
            problems += CHECKS[name](source, result)
    return problems
