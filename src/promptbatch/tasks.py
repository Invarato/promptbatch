"""Una tarea es un fichero Markdown con cabecera TOML entre líneas «+++» y el prompt debajo.

    +++
    model = "claude-sonnet-5-5"
    max_tokens = 16000
    effort = "low"          # opcional: low, medium, high, xhigh, max
    checks = ["html"]       # opcional: comprobaciones del resultado (ver checks.py); «html:campo» con esquema
    extensions = [".html"]  # opcional: qué ficheros coger de una carpeta
    context = ["guia.md"]   # opcional: ficheros que se añaden al system prompt (cacheado), rutas relativas a la tarea
    schema = "esquema.json" # opcional: la respuesta es JSON que cumple este esquema; la salida se guarda como .json
    tools = ["web_fetch"]   # opcional: herramientas del servidor (web_fetch, web_search); las ejecuta Anthropic
    tool_max_uses = 20      # opcional: máximo de usos de cada herramienta por fichero
    fetch_max_tokens = 3000 # opcional: tokens máximos de cada página descargada (se cobran como entrada)
    +++
    Texto del system prompt (opcional)
    ---prompt---
    Prompt del usuario, con {{contenido}} y {{nombre}} (y las variables de --var clave=valor).
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SEPARADOR = "---prompt---"
# Herramientas del servidor: las ejecuta Anthropic (el equipo que lanza la tarea no necesita acceso a internet).
HERRAMIENTAS = {"web_fetch": "web_fetch_20260209", "web_search": "web_search_20260209"}
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
    contexto: list[Path] = field(default_factory=list)
    esquema: dict | None = None
    ruta: Path | None = None
    herramientas: list[str] = field(default_factory=list)
    max_usos: int = 20
    max_tokens_pagina: int = 3000

    @property
    def extension_salida(self) -> str | None:
        """Con esquema, la salida es JSON; sin él, conserva la extensión de la entrada."""
        return ".json" if self.esquema else None

    def definicion_herramientas(self) -> list[dict]:
        r = []
        for h in self.herramientas:
            d = {"type": HERRAMIENTAS[h], "name": h, "max_uses": self.max_usos}
            if h == "web_fetch":
                d["max_content_tokens"] = self.max_tokens_pagina
            r.append(d)
        return r

    def system_completo(self, extra: list[Path] | None = None) -> str:
        partes = [self.system] if self.system else []
        for f in [*self.contexto, *(extra or [])]:
            partes.append(f"<documento nombre=\"{f.name}\">\n{f.read_text(encoding='utf-8').strip()}\n</documento>")
        return "\n\n".join(partes)

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
    desconocidas = set(cab) - {"model", "max_tokens", "effort", "checks", "extensions", "context", "schema", "tools", "tool_max_uses", "fetch_max_tokens"}
    malas = set(cab.get("tools", [])) - set(HERRAMIENTAS)
    if malas:
        raise SystemExit(f"{ruta}: herramientas desconocidas: {', '.join(sorted(malas))} (hay: {', '.join(HERRAMIENTAS)})")
    if desconocidas:
        raise SystemExit(f"{ruta}: claves desconocidas en la cabecera: {', '.join(sorted(desconocidas))}")
    return Tarea(
        ruta=ruta.resolve(),
        nombre=ruta.stem,
        system=system.strip(),
        prompt=prompt.strip(),
        model=cab.get("model", MODELO_POR_DEFECTO),
        max_tokens=int(cab.get("max_tokens", 16000)),
        effort=cab.get("effort"),
        checks=list(cab.get("checks", [])),
        extensions=list(cab.get("extensions", [])),
        contexto=[_relativa(ruta, c) for c in cab.get("context", [])],
        esquema=json.loads(_relativa(ruta, cab["schema"]).read_text(encoding="utf-8")) if "schema" in cab else None,
        herramientas=list(cab.get("tools", [])),
        max_usos=int(cab.get("tool_max_uses", 20)),
        max_tokens_pagina=int(cab.get("fetch_max_tokens", 3000)),
    )


def _relativa(tarea: Path, f: str) -> Path:
    p = Path(f).expanduser()
    p = p if p.is_absolute() else tarea.parent / p
    if not p.is_file():
        raise SystemExit(f"{tarea}: no existe {p}")
    return p


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
