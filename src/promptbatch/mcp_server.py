"""Servidor MCP de promptbatch: para que un agente (Claude Code) delegue trabajo masivo en la API.

Pocas herramientas y respuestas cortas, a propósito: las definiciones y las respuestas ocupan contexto del
agente. Las herramientas devuelven resúmenes (cuántos, coste, qué revisar), nunca el contenido generado: si
el agente quiere ver un resultado, lee el fichero.

    claude mcp add promptbatch -e PROMPTBATCH_KEY_FILE=… -e PROMPTBATCH_TASK_DIRS=… -- <venv>/bin/python -m promptbatch.mcp_server
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import threading
import time
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer

from . import config, runner, tasks

servidor = MCPServer(
    "promptbatch",
    instructions=(
        "Lanza una tarea (un prompt en un fichero .md) sobre muchos ficheros con la API de Anthropic y la "
        "clave del usuario, sin pasar el contenido por esta conversación. Empieza siempre con modo «estimar»; "
        "para muchos ficheros usa «lote» (mitad de precio, hasta 24 h) y luego «consultar». Las tareas "
        "disponibles están en el recurso promptbatch://tareas."
    ),
)


_en_curso: dict[str, dict] = {}   # carpeta de salida -> trabajo en segundo plano (modo directo)


def _silencioso(f, *a, **k):
    """El runner escribe por stdout, que en MCP es el canal del protocolo: se captura."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = f(*a, **k)
    return r, buf.getvalue()


@servidor.tool()
def lanzar(
    tarea: str,
    entradas: list[str],
    salida: str,
    modo: Literal["estimar", "directo", "lote"] = "estimar",
    limite: int | None = None,
    max_coste: float | None = None,
    variables: dict[str, str] | None = None,
    contexto: list[str] | None = None,
    modelo: str | None = None,
) -> str:
    """Ejecuta la tarea (ruta al .md) sobre los ficheros o carpetas de `entradas`, dejando un fichero por entrada
    en `salida`. Lo ya hecho en `salida` se salta. Modos: «estimar» (solo cuenta tokens y coste, gratis),
    «directo» (ahora; para pocos ficheros) o «lote» (Batch API: mitad de precio, consultar después).
    `max_coste` en USD: en directo para al alcanzarlo; en lote no envía si la estimación lo supera."""
    t = tasks.cargar(tarea)
    if modelo:
        t.model = modelo
    sal = Path(salida)
    trabajos = runner.preparar(tasks.ficheros_de_entrada(entradas, t.extensions), sal, False, t)[:limite]
    if not trabajos:
        return "Nada que hacer: todo está ya en la salida."
    client = config.cliente()
    precios = config.cargar_precios(os.environ.get("PROMPTBATCH_PRICES"))
    ctx = [Path(c) for c in contexto or []]
    est = runner.estimar(client, t, trabajos, variables, precios, modo == "lote", ctx)
    resumen = f"{est['ficheros']} ficheros, {est['tokens_entrada']} tokens de entrada, coste estimado ≈ ${est['coste_estimado_usd'] or 0:.3f} ({t.model}{', en lote' if modo == 'lote' else ''})."
    if modo == "estimar":
        return resumen
    if modo == "lote":
        if max_coste is not None and (est["coste_estimado_usd"] or 0) > max_coste:
            return resumen + f" No se envía: supera max_coste (${max_coste})."
        lote = runner.enviar_lote(client, t, trabajos, sal, variables, ctx)
        return resumen + f" Lote enviado: {lote}. Usa consultar(salida=\"{salida}\") más tarde."
    # En segundo plano: una tarea larga no debe dejar colgada la herramienta (el cliente MCP corta por inactividad).
    clave = str(sal.resolve())
    if clave in _en_curso and _en_curso[clave]["hilo"].is_alive():
        return f"Ya hay un trabajo en curso en {salida}: usa consultar."
    estado = {"total": len(trabajos), "inicio": time.time(), "log": "", "error": None}

    def trabajar():
        try:
            estado["log"] = runner.ejecutar(client, t, trabajos, sal, variables, precios, 4, max_coste, ctx, silencioso=True)
        except Exception as e:   # noqa: BLE001 — se informa en consultar
            estado["error"] = f"{type(e).__name__}: {e}"

    estado["hilo"] = threading.Thread(target=trabajar, daemon=True)
    estado["hilo"].start()
    _en_curso[clave] = estado
    return resumen + f" En marcha en segundo plano ({len(trabajos)} ficheros): usa consultar(salida=\"{salida}\") para ver el avance."


@servidor.tool()
def consultar(salida: str) -> str:
    """Estado de una carpeta de salida. Si tiene un lote en curso dice cómo va; si el lote ha terminado, recoge
    los resultados. Devuelve el resumen: hechos, a revisar (con el motivo), coste y tokens."""
    sal = Path(salida)
    trabajo = _en_curso.get(str(sal.resolve()))
    if trabajo:
        hechos = len(list((sal / ".meta").glob("*.json"))) if (sal / ".meta").is_dir() else 0
        if trabajo["error"]:
            return f"El trabajo falló: {trabajo['error']}. " + json.dumps(runner.informe(sal), ensure_ascii=False)
        if trabajo["hilo"].is_alive():
            return f"En curso: {hechos} ficheros con resultado (de {trabajo['total']} lanzados), {time.time() - trabajo['inicio']:.0f} s."
    if (sal / ".batch.json").exists():
        client = config.cliente()
        info, lote = runner.estado_lote(client, sal)
        if lote.processing_status != "ended":
            c = lote.request_counts
            return f"Lote {info['id']} en curso: {c.processing} pendientes, {c.succeeded} hechos, {c.errored} con error."
        if not info.get("recogido"):
            if not info.get("ruta_tarea"):
                return f"Lote {info['id']} terminado, pero no sé qué tarea usó: recógelo con «promptbatch batch collect»."
            precios = config.cargar_precios(os.environ.get("PROMPTBATCH_PRICES"))
            _silencioso(runner.recoger_lote, client, tasks.cargar(info["ruta_tarea"]), sal, precios)
            info["recogido"] = True
            (sal / ".batch.json").write_text(json.dumps(info, indent=1))
    return json.dumps(runner.informe(sal), ensure_ascii=False)


@servidor.resource("promptbatch://tareas", name="tareas", description="Tareas disponibles: ruta y para qué sirve")
def tareas_disponibles() -> str:
    dirs = [d for d in os.environ.get("PROMPTBATCH_TASK_DIRS", "").split(os.pathsep) if d] or ["tasks"]
    lineas = []
    for d in dirs:
        for f in sorted(Path(d).expanduser().glob("*.md")):
            texto = f.read_text(encoding="utf-8")
            desc = next((l.lstrip("# ").strip() for l in texto.splitlines()[1:6] if l.startswith("#")), "")
            if texto.startswith("+++"):
                lineas.append(f"- {f.resolve()}: {desc}")
    return "\n".join(lineas) or "No hay tareas en PROMPTBATCH_TASK_DIRS."


def main():
    servidor.run("stdio")


if __name__ == "__main__":
    main()
