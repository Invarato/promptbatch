"""Comprobaciones del resultado. Si una falla, el fichero va a «_revisar/» en vez de a la carpeta de salida.

Cada comprobación recibe (entrada, salida) y devuelve una lista de problemas (vacía si todo bien).
"""

from __future__ import annotations

import re
from collections import Counter

_ETIQUETA = re.compile(r"<\s*/?\s*([a-zA-Z][\w:-]*)")
_ATRIBUTO = re.compile(r'\b(href|src)\s*=\s*"([^"]*)"')
_COMENTARIO = re.compile(r"<!--(.*?)-->", re.S)


def html(entrada: str, salida: str) -> list[str]:
    """La salida conserva las mismas etiquetas, enlaces e imágenes que la entrada (para traducir/corregir HTML)."""
    problemas = []
    e, s = Counter(_ETIQUETA.findall(entrada)), Counter(_ETIQUETA.findall(salida))
    if e != s:
        dif = {k: (e[k], s[k]) for k in set(e) | set(s) if e[k] != s[k]}
        problemas.append("etiquetas distintas (entrada, salida): " + ", ".join(f"{k} {a}→{b}" for k, (a, b) in sorted(dif.items())[:8]))
    ue, us = Counter(_ATRIBUTO.findall(entrada)), Counter(_ATRIBUTO.findall(salida))
    perdidos = [f"{a}={u}" for (a, u) in ue if (a, u) not in us and a == "src"]
    if perdidos:
        problemas.append("imágenes que cambian o se pierden: " + ", ".join(perdidos[:4]))
    if sum(1 for k in ue if k[0] == "href") != sum(1 for k in us if k[0] == "href"):
        problemas.append("distinto número de enlaces (href)")
    ce = [m.strip().split("\n")[0][:40] for m in _COMENTARIO.findall(entrada)]
    cs = [m.strip().split("\n")[0][:40] for m in _COMENTARIO.findall(salida)]
    if len(ce) != len(cs):
        problemas.append(f"comentarios de bloque: {len(ce)}→{len(cs)}")
    return problemas


def no_vacio(entrada: str, salida: str) -> list[str]:
    problemas = []
    if not salida.strip():
        problemas.append("salida vacía")
    elif len(salida) < 0.2 * len(entrada):
        problemas.append("salida muy corta respecto a la entrada (¿cortada?)")
    return problemas


COMPROBACIONES = {"html": html, "no-vacio": no_vacio}


def pasar(nombres: list[str], entrada: str, salida: str) -> list[str]:
    problemas = []
    for n in ["no-vacio", *nombres]:
        if n not in COMPROBACIONES:
            raise SystemExit(f"Comprobación desconocida: {n} (hay: {', '.join(COMPROBACIONES)})")
        problemas += COMPROBACIONES[n](entrada, salida)
    return problemas
