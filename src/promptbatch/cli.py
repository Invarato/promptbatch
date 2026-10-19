"""promptbatch run|batch ... (ver README)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import config, runner, tasks


def _variables(lista: list[str] | None) -> dict[str, str]:
    r = {}
    for v in lista or []:
        k, _, valor = v.partition("=")
        r[k.strip()] = valor
    return r


def _comun(p: argparse.ArgumentParser):
    p.add_argument("tarea", help="fichero de la tarea (.md)")
    p.add_argument("entradas", nargs="+", help="ficheros o carpetas de entrada")
    p.add_argument("-o", "--salida", required=True, help="carpeta de salida")
    p.add_argument("--var", action="append", help="variable extra para el prompt: clave=valor (se usa como {{clave}})")
    p.add_argument("--limit", type=int, help="solo los N primeros (para probar)")
    p.add_argument("--force", action="store_true", help="rehacer también los que ya están en la salida")
    p.add_argument("--max-cost", type=float, help="tope de gasto en USD")
    p.add_argument("--prices", help="fichero TOML con precios propios")
    p.add_argument("--key-file", help="fichero con la clave de la API")
    p.add_argument("--model", help="sustituye el modelo de la tarea")
    p.add_argument("--context", action="append", help="fichero de contexto extra para el system prompt (se puede repetir)")


def _preparar(a):
    tarea = tasks.cargar(a.tarea)
    if a.model:
        tarea.model = a.model
    ficheros = tasks.ficheros_de_entrada(a.entradas, tarea.extensions)
    salida = Path(a.salida)
    trabajos = runner.preparar(ficheros, salida, a.force, tarea)
    if a.limit:
        trabajos = trabajos[: a.limit]
    a.contexto = [Path(c) for c in (a.context or [])]
    return tarea, trabajos, salida, _variables(a.var), config.cargar_precios(a.prices)


def cmd_run(a):
    tarea, trabajos, salida, variables, precios = _preparar(a)
    if not trabajos:
        print("Nada que hacer (todo está ya en la salida; usa --force para rehacerlo).")
        return 0
    client = config.cliente(a.key_file)
    est = runner.estimar(client, tarea, trabajos, variables, precios, False, a.contexto)
    print(f"{est['ficheros']} ficheros, {est['tokens_entrada']} tokens de entrada, coste estimado ≈ ${est['coste_estimado_usd'] or 0:.3f} con {tarea.model}")
    if a.dry_run:
        return 0
    salida.mkdir(parents=True, exist_ok=True)
    gastado = runner.ejecutar(client, tarea, trabajos, salida, variables, precios, a.concurrency, a.max_cost, a.contexto)
    print(f"Gastado: ${gastado:.4f}. Detalle por fichero en {salida}/.meta/")
    return 0


def cmd_batch_submit(a):
    tarea, trabajos, salida, variables, precios = _preparar(a)
    if not trabajos:
        print("Nada que hacer.")
        return 0
    client = config.cliente(a.key_file)
    est = runner.estimar(client, tarea, trabajos, variables, precios, True, a.contexto)
    coste = est["coste_estimado_usd"]
    print(f"{est['ficheros']} ficheros, {est['tokens_entrada']} tokens de entrada, coste estimado en lote ≈ ${coste or 0:.3f} con {tarea.model}")
    if a.max_cost is not None and coste is not None and coste > a.max_cost:
        raise SystemExit(f"El coste estimado (${coste:.2f}) supera --max-cost (${a.max_cost:.2f}). No se envía.")
    if a.dry_run:
        return 0
    print("Lote enviado:", runner.enviar_lote(client, tarea, trabajos, salida, variables, a.contexto))
    print(f"Consulta con: promptbatch batch status {salida}   y recoge con: promptbatch batch collect {a.tarea} {salida}")
    return 0


def cmd_batch_status(a):
    client = config.cliente(a.key_file)
    info, lote = runner.estado_lote(client, Path(a.salida))
    print(info["id"], lote.processing_status, lote.request_counts)
    return 0


def cmd_batch_collect(a):
    tarea = tasks.cargar(a.tarea)
    client = config.cliente(a.key_file)
    print(json.dumps(runner.recoger_lote(client, tarea, Path(a.salida), config.cargar_precios(a.prices)), indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="promptbatch", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="una petición por fichero, en directo")
    _comun(r)
    r.add_argument("--dry-run", action="store_true", help="solo cuenta tokens y estima el coste")
    r.add_argument("--concurrency", type=int, default=4)
    r.set_defaults(f=cmd_run)

    b = sub.add_parser("batch", help="Batch API (mitad de precio, hasta 24 h)").add_subparsers(dest="sub", required=True)
    s = b.add_parser("submit", help="envía el lote")
    _comun(s)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(f=cmd_batch_submit)
    st = b.add_parser("status", help="estado del lote de una carpeta de salida")
    st.add_argument("salida")
    st.add_argument("--key-file")
    st.set_defaults(f=cmd_batch_status)
    c = b.add_parser("collect", help="recoge los resultados de un lote terminado")
    c.add_argument("tarea")
    c.add_argument("salida")
    c.add_argument("--prices")
    c.add_argument("--key-file")
    c.set_defaults(f=cmd_batch_collect)

    a = ap.parse_args(argv)
    return a.f(a)
