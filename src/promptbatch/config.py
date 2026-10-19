"""Clave de la API y precios. La clave nunca se escribe en el repositorio ni en los resultados."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import anthropic

# Precios orientativos en USD por millón de tokens (entrada, salida), de la tabla pública a 2026-10.
# Comprueba los vigentes antes de fiarte del coste, o sobrescribe con --prices FICHERO.toml:
#   ["claude-opus-5-5"]
#   input = 4.0
#   output = 20.0
PRECIOS = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
DESCUENTO_BATCH = 0.5


def leer_clave(key_file: str | None = None) -> str:
    """Orden: ANTHROPIC_API_KEY, --key-file, PROMPTBATCH_KEY_FILE, ~/.config/promptbatch/api.key."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    candidatos = [key_file, os.environ.get("PROMPTBATCH_KEY_FILE"), "~/.config/promptbatch/api.key"]
    for c in filter(None, candidatos):
        p = Path(c).expanduser()
        if p.is_file():
            clave = p.read_text().strip()
            if clave:
                return clave
    raise SystemExit(
        "No encuentro la clave de la API. Define ANTHROPIC_API_KEY, o pasa --key-file, "
        "o PROMPTBATCH_KEY_FILE, o guárdala en ~/.config/promptbatch/api.key"
    )


def cliente(key_file: str | None = None) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=leer_clave(key_file))


def cargar_precios(fichero: str | None) -> dict[str, tuple[float, float]]:
    precios = dict(PRECIOS)
    if fichero:
        for modelo, v in tomllib.loads(Path(fichero).read_text()).items():
            precios[modelo] = (float(v["input"]), float(v["output"]))
    return precios


def coste(precios: dict, modelo: str, entrada: int, salida: int, batch: bool = False) -> float | None:
    """USD de una petición, o None si no se conoce el precio del modelo."""
    if modelo not in precios:
        return None
    pi, po = precios[modelo]
    total = (entrada * pi + salida * po) / 1_000_000
    return total * (DESCUENTO_BATCH if batch else 1)
