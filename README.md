# promptbatch

Lanza **una tarea** (un prompt) sobre **muchos ficheros** con la API de Anthropic: en directo, o en lote con la
Batch API (la mitad de precio, resultado en menos de 24 h). Pensada para trabajos grandes y repetitivos:
traducir cientos de artículos, revisar erratas, escribir meta descripciones, clasificar…

- **Sin nada específico de ningún proyecto:** las tareas son ficheros Markdown; tu proyecto aporta las suyas.
- **Seguro de relanzar:** lo que ya está en la carpeta de salida no se rehace (ni se paga otra vez).
- **Con control de gasto:** estima el coste antes (`--dry-run`) y para al llegar a `--max-cost`.
- **Con comprobaciones:** si el resultado no pasa una comprobación (p. ej. el HTML cambió de etiquetas), va a `_revisar/` en lugar de a la salida.

## Instalación

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

## La clave de la API

Nunca va en el repositorio. Se busca, en este orden: la variable `ANTHROPIC_API_KEY`, la opción `--key-file`,
la variable `PROMPTBATCH_KEY_FILE` o el fichero `~/.config/promptbatch/api.key` (con permisos `600`).

## Una tarea

Un fichero `.md` con cabecera TOML entre líneas `+++`, el system prompt (opcional) y, tras `---prompt---`, el
prompt, con `{{contenido}}` (el fichero) y `{{nombre}}`. Más variables con `--var clave=valor`.

```markdown
+++
model = "claude-sonnet-5-5"
max_tokens = 16000
effort = "low"          # low, medium, high, xhigh, max (en traducciones suele bastar low)
checks = ["html"]       # comprobaciones del resultado: html, no-vacio
extensions = [".html"]  # qué ficheros coger de una carpeta
+++
Eres un traductor profesional…
---prompt---
Traduce al {{idioma}} este HTML conservando todas las etiquetas:

{{contenido}}
```

Ver [tasks/ejemplo-resumen.md](tasks/ejemplo-resumen.md). Sin `model`, se usa `claude-opus-5-5`.

## Uso

```bash
# 1. Estimar sin gastar (solo cuenta tokens)
promptbatch run tasks/mi-tarea.md entradas/ -o salida/ --dry-run

# 2. Probar con 3 ficheros y un tope de gasto
promptbatch run tasks/mi-tarea.md entradas/ -o salida/ --limit 3 --max-cost 1

# 3. Todo, a mitad de precio con la Batch API
promptbatch batch submit tasks/mi-tarea.md entradas/ -o salida/ --max-cost 20
promptbatch batch status salida/
promptbatch batch collect tasks/mi-tarea.md salida/
```

En la salida: un fichero por entrada (mismo nombre); `_revisar/` con los que no pasaron las comprobaciones;
`.meta/<fichero>.json` con tokens, coste y motivo de parada; `.batch.json` con el lote en curso.

## Costes

Los precios que usa para estimar están en `config.py` (orientativos): compruébalos y, si cambian, pásalos con
`--prices fichero.toml` (`["modelo"]` con `input` y `output` en USD por millón de tokens). El coste real queda
en `.meta/`.

## Desarrollo

```bash
.venv/bin/pip install -e '.[dev]' && .venv/bin/pytest
```
