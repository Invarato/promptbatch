"""Ejecución de una tarea: petición a petición (run) o en lote (Batch API, a mitad de precio)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import anthropic

from . import checks, config
from .tasks import Tarea


@dataclass
class Trabajo:
    fichero: Path
    entrada: str
    custom_id: str


def extraer_texto(mensaje) -> str:
    """El texto final de la respuesta: con herramientas, el que va después del último bloque que no es texto
    (lo anterior son comentarios del modelo entre llamadas)."""
    bloques = list(mensaje.content)
    ultimo = max((i for i, b in enumerate(bloques) if b.type != "text"), default=-1)
    return "".join(b.text for b in bloques[ultimo + 1:] if b.type == "text")


def nombre_salida(tarea: Tarea, fichero: Path) -> str:
    return fichero.stem + tarea.extension_salida if tarea.extension_salida else fichero.name


def parametros(tarea: Tarea, entrada: str, nombre: str, variables: dict | None, contexto: list[Path] | None = None) -> dict:
    p: dict = {
        "model": tarea.model,
        "max_tokens": tarea.max_tokens,
        "messages": [{"role": "user", "content": tarea.construir(entrada, nombre, variables)}],
    }
    system = tarea.system_completo(contexto)
    if system:
        # El system (con la guía y el glosario) se repite en todas las peticiones: con caché se paga entero
        # solo la primera vez (las demás leen a 0,1×). Debe ser idéntico byte a byte: nada variable aquí.
        p["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    if tarea.herramientas:
        p["tools"] = tarea.definicion_herramientas()
    oc = {}
    if tarea.effort:
        oc["effort"] = tarea.effort
    if tarea.esquema:
        oc["format"] = {"type": "json_schema", "schema": tarea.esquema}
    if oc:
        p["output_config"] = oc
    return p


def preparar(ficheros: list[Path], salida: Path, forzar: bool, tarea: Tarea | None = None) -> list[Trabajo]:
    trabajos = []
    for i, f in enumerate(ficheros):
        n = nombre_salida(tarea, f) if tarea else f.name
        if not forzar and ((salida / n).exists() or (salida / "_revisar" / n).exists()):
            continue   # ya hecho: se puede relanzar sin repetir (ni pagar) lo anterior
        cid = f"f{i:05d}-{hashlib.sha1(f.name.encode()).hexdigest()[:8]}"
        trabajos.append(Trabajo(f, f.read_text(encoding="utf-8"), cid))
    return trabajos


def guardar(salida: Path, t: Trabajo, tarea: Tarea, texto: str, uso, parada: str, precios: dict, batch: bool) -> dict:
    problemas = checks.pasar(tarea.checks, t.entrada, texto, es_json=bool(tarea.esquema))
    if parada == "max_tokens":
        problemas.append("respuesta cortada por max_tokens: súbelo en la tarea")
    if parada == "refusal":
        problemas.append("la API rechazó la petición (refusal)")
    if parada == "pause_turn":
        problemas.append("se quedó a medias usando herramientas (pause_turn): relánzalo en directo")
    destino = salida / ("_revisar" if problemas else "") / nombre_salida(tarea, t.fichero)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    meta = {
        "fichero": t.fichero.name, "tarea": tarea.nombre, "modelo": tarea.model, "batch": batch,
        "tokens_entrada": uso.input_tokens, "tokens_salida": uso.output_tokens,
        "tokens_cache_escritos": getattr(uso, "cache_creation_input_tokens", 0) or 0,
        "tokens_cache_leidos": getattr(uso, "cache_read_input_tokens", 0) or 0,
        "coste_usd": config.coste(precios, tarea.model, uso.input_tokens, uso.output_tokens, batch,
                                  getattr(uso, "cache_creation_input_tokens", 0) or 0,
                                  getattr(uso, "cache_read_input_tokens", 0) or 0),
        "parada": parada, "problemas": problemas,
    }
    (salida / ".meta").mkdir(exist_ok=True)
    (salida / ".meta" / f"{t.fichero.name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def estimar(client, tarea: Tarea, trabajos: list[Trabajo], variables: dict | None, precios: dict, batch: bool, contexto=None) -> dict:
    """Cuenta los tokens de entrada (gratis, sin generar nada). La salida se estima igual que la entrada."""
    entrada = salida = 0
    for t in trabajos:
        p = parametros(tarea, t.entrada, t.fichero.stem, variables, contexto)
        extra = {k: p[k] for k in ("system", "output_config") if k in p}
        n = client.messages.count_tokens(model=p["model"], messages=p["messages"], **extra).input_tokens
        entrada += n
        # Salida: como mucho la entrada (traducir, corregir) y nunca más que max_tokens (clasificar, resumir).
        # Es un techo, no una predicción: el coste real queda en .meta/.
        salida += min(n, tarea.max_tokens)
    return {"ficheros": len(trabajos), "tokens_entrada": entrada, "tokens_salida_estimados": salida,
            "coste_estimado_usd": config.coste(precios, tarea.model, entrada, salida, batch)}


def ejecutar(client, tarea: Tarea, trabajos: list[Trabajo], salida: Path, variables, precios, concurrencia: int, max_coste: float | None, contexto=None) -> float:
    """Una petición por fichero, varias a la vez. Para si el gasto llega a max_coste. Devuelve lo gastado."""
    gastado = 0.0
    parar = False

    def llamar(p):
        if tarea.max_tokens > 16000:   # el SDK exige streaming para respuestas muy largas
            with client.messages.stream(**p) as s:
                return s.get_final_message()
        return client.messages.create(**p)

    def una(t: Trabajo):
        p = parametros(tarea, t.entrada, t.fichero.stem, variables, contexto)
        m = llamar(p)
        uso = [m.usage]
        # Con herramientas del servidor, la respuesta puede pararse (pause_turn): se reenvía tal cual y el
        # servidor continúa donde lo dejó. Hasta 5 veces.
        for _ in range(5):
            if m.stop_reason != "pause_turn":
                break
            p = {**p, "messages": [*p["messages"], {"role": "assistant", "content": m.content}]}
            m = llamar(p)
            uso.append(m.usage)
        if len(uso) > 1:   # sumar el consumo de todas las vueltas
            for campo in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                setattr(m.usage, campo, sum(getattr(u, campo, 0) or 0 for u in uso))
        return t, m

    with ThreadPoolExecutor(max_workers=concurrencia) as pool:
        pendientes = {}
        cola = iter(trabajos)
        def lanzar():
            t = next(cola, None)
            if t:
                pendientes[pool.submit(una, t)] = t
            return t
        for _ in range(concurrencia):
            lanzar()
        while pendientes:
            for fut in as_completed(list(pendientes)):
                t = pendientes.pop(fut)
                try:
                    _, m = fut.result()
                    meta = guardar(salida, t, tarea, extraer_texto(m), m.usage, m.stop_reason, precios, False)
                    gastado += meta["coste_usd"] or 0
                    marca = "REVISAR" if meta["problemas"] else "ok"
                    print(f"[{marca}] {t.fichero.name}  ({meta['tokens_entrada']}→{meta['tokens_salida']} tokens, ${meta['coste_usd'] or 0:.4f})", flush=True)
                    for pr in meta["problemas"]:
                        print(f"        · {pr}", flush=True)
                except anthropic.APIError as e:
                    print(f"[ERROR] {t.fichero.name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                if max_coste is not None and gastado >= max_coste and not parar:
                    parar = True
                    print(f"** Tope de gasto alcanzado (${gastado:.2f} ≥ ${max_coste:.2f}): no se lanzan más.", flush=True)
                if not parar:
                    lanzar()
                break
    return gastado


# ---------------------------------------------------------------- lote (Batch API)

def enviar_lote(client, tarea: Tarea, trabajos: list[Trabajo], salida: Path, variables, contexto=None) -> str:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    reqs = [Request(custom_id=t.custom_id, params=MessageCreateParamsNonStreaming(**parametros(tarea, t.entrada, t.fichero.stem, variables, contexto))) for t in trabajos]
    lote = client.messages.batches.create(requests=reqs)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / ".batch.json").write_text(json.dumps({
        "id": lote.id, "tarea": tarea.nombre, "ruta_tarea": str(tarea.ruta) if tarea.ruta else None,
        "creado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ficheros": {t.custom_id: str(t.fichero) for t in trabajos},
    }, indent=1))
    return lote.id


def estado_lote(client, salida: Path):
    info = json.loads((salida / ".batch.json").read_text())
    return info, client.messages.batches.retrieve(info["id"])


def recoger_lote(client, tarea: Tarea, salida: Path, precios: dict) -> dict:
    info, lote = estado_lote(client, salida)
    if lote.processing_status != "ended":
        raise SystemExit(f"El lote {info['id']} sigue en curso ({lote.processing_status}): {lote.request_counts}")
    contadores = {"ok": 0, "revisar": 0, "error": 0}
    gastado = 0.0
    for r in client.messages.batches.results(info["id"]):
        ruta = Path(info["ficheros"][r.custom_id])
        t = Trabajo(ruta, ruta.read_text(encoding="utf-8"), r.custom_id)
        if r.result.type != "succeeded":
            print(f"[ERROR] {ruta.name}: {r.result.type}", file=sys.stderr)
            contadores["error"] += 1
            continue
        m = r.result.message
        meta = guardar(salida, t, tarea, extraer_texto(m), m.usage, m.stop_reason, precios, True)
        gastado += meta["coste_usd"] or 0
        contadores["revisar" if meta["problemas"] else "ok"] += 1
    contadores["coste_usd"] = round(gastado, 4)
    return contadores


def informe(salida: Path, max_detalle: int = 10) -> dict:
    """Resumen de una carpeta de salida a partir de .meta/: cuántos bien, cuántos a revisar (y por qué) y el coste."""
    metas = [json.loads(f.read_text()) for f in sorted((salida / ".meta").glob("*.json"))] if (salida / ".meta").is_dir() else []
    revisar = [m for m in metas if m["problemas"]]
    return {
        "carpeta": str(salida),
        "hechos": len(metas) - len(revisar),
        "a_revisar": len(revisar),
        "coste_usd": round(sum(m["coste_usd"] or 0 for m in metas), 4),
        "tokens": {"entrada": sum(m["tokens_entrada"] for m in metas), "salida": sum(m["tokens_salida"] for m in metas)},
        "revisar": [{"fichero": m["fichero"], "problema": m["problemas"][0][:200]} for m in revisar[:max_detalle]],
    }
