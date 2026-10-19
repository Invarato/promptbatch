"""Una tarea es un fichero Markdown con cabecera TOML entre líneas «+++» y el prompt debajo.

    +++
    model = "claude-sonnet-5-5"
    max_tokens = 16000
    effort = "low"          # opcional: low, medium, high, xhigh, max
    checks = ["html"]       # opcional: comprobaciones del resultado (ver checks.py)
    extensions = [".html"]  # opcional: qué ficheros coger de una carpeta
    +++
    Texto del system prompt (opcional)
    ---prompt---
    Prompt del usuario, con {{contenido}} y {{nombre}} (y las variables de --var clave=valor).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SEPARADOR = "---prompt---"
MODELO_POR_DEFECTO = "claude-opus-5-5"


@dataclass
class Tarea:
    nombre: str
    system: str
    prompt: str
    model: str = MODELO_POR_DEFECTO
    max_tokens: int = 16000
    effort: str | None = None
    checks: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)

    def construir(self, contenido: str, nombre: str, variables: dict[str, str] | None = None) -> str:
        texto = self.prompt
        for k, v in {"contenido": contenido, "nombre": nombre, **(variables or {})}.items():
            texto = texto.replace("{{" + k + "}}", v)
        return texto


def cargar(ruta: str | Path) -> Tarea:
    ruta = Path(ruta)
    texto = ruta.read_text(encoding="utf-8")
    cab: dict = {}
    if texto.startswith("+++"):
        _, cabecera, texto = texto.split("+++", 2)
        cab = tomllib.loads(cabecera)
    texto = texto.strip("\n")
    system, _, prompt = texto.partition(SEPARADOR) if SEPARADOR in texto else ("", "", texto)
    if "{{contenido}}" not in prompt:
        raise SystemExit(f"{ruta}: el prompt de la tarea debe llevar {{{{contenido}}}}")
    desconocidas = set(cab) - {"model", "max_tokens", "effort", "checks", "extensions"}
    if desconocidas:
        raise SystemExit(f"{ruta}: claves desconocidas en la cabecera: {', '.join(sorted(desconocidas))}")
    return Tarea(
        nombre=ruta.stem,
        system=system.strip(),
        prompt=prompt.strip(),
        model=cab.get("model", MODELO_POR_DEFECTO),
        max_tokens=int(cab.get("max_tokens", 16000)),
        effort=cab.get("effort"),
        checks=list(cab.get("checks", [])),
        extensions=list(cab.get("extensions", [])),
    )


def ficheros_de_entrada(entradas: list[str], extensiones: list[str]) -> list[Path]:
    """Ficheros sueltos tal cual; carpetas, sus ficheros (filtrados por extensión si la tarea las define)."""
    r: list[Path] = []
    for e in entradas:
        p = Path(e)
        if p.is_dir():
            r += sorted(f for f in p.iterdir() if f.is_file() and not f.name.startswith(".") and (not extensiones or f.suffix in extensiones))
        elif p.is_file():
            r.append(p)
        else:
            raise SystemExit(f"No existe: {e}")
    return r
