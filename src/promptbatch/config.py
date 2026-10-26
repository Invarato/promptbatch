"""API key and prices. The key is never written to the repository or to the results."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import anthropic

# Approximate prices in USD per million tokens, from the public price list as of 2026-10: (input, output, cache read).
# Check the current ones at https://platform.claude.com/docs/en/about-claude/pricing and, if they change, pass them
# with --prices FILE.toml:
#   ["claude-sonnet-5-5"]
#   input = 2.0
#   output = 10.0
#   cache_read = 0.20      # optional: 0.1 × input by default
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.00),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
# Models whose price goes up when a request's input passes a threshold: (threshold in tokens, prices above it).
LONG_INPUT_PRICES = {
    "claude-haiku-5-5": (100_000, (0.50, 2.50, 0.05)),
}
CACHE_WRITE = 1.25  # writing to the (5-minute) cache costs 1.25 × input
BATCH_DISCOUNT = 0.5


def read_key(key_file: str | None = None) -> str:
    """Order: ANTHROPIC_API_KEY, --key-file, PROMPTBATCH_KEY_FILE, ~/.config/promptbatch/api.key."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    candidates = [key_file, os.environ.get("PROMPTBATCH_KEY_FILE"), "~/.config/promptbatch/api.key"]
    for c in filter(None, candidates):
        p = Path(c).expanduser()
        if p.is_file():
            key = p.read_text().strip()
            if key:
                return key
    raise SystemExit(
        "API key not found. Set ANTHROPIC_API_KEY, or pass --key-file, "
        "or set PROMPTBATCH_KEY_FILE, or save it in ~/.config/promptbatch/api.key"
    )


def client(key_file: str | None = None) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=read_key(key_file))


def load_prices(path: str | None) -> dict[str, tuple[float, float, float]]:
    prices = dict(PRICES)
    if path:
        for model, v in tomllib.loads(Path(path).read_text()).items():
            prices[model] = (float(v["input"]), float(v["output"]), float(v.get("cache_read", 0.1 * float(v["input"]))))
    return prices


def cost(
    prices: dict,
    model: str,
    input_tokens: int,
    output_tokens: int,
    batch: bool = False,
    cache_written: int = 0,
    cache_read: int = 0,
) -> float | None:
    """USD of ONE request, or None if the model's price is unknown. `input_tokens` does not include the cache."""
    if model not in prices:
        return None
    p_in, p_out, p_cache = prices[model]
    if model in LONG_INPUT_PRICES and input_tokens + cache_written + cache_read > LONG_INPUT_PRICES[model][0]:
        p_in, p_out, p_cache = LONG_INPUT_PRICES[model][1]
    total = (input_tokens * p_in + cache_written * p_in * CACHE_WRITE + cache_read * p_cache + output_tokens * p_out) / 1_000_000
    return total * (BATCH_DISCOUNT if batch else 1)
