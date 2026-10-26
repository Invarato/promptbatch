# promptbatch

*[Read in English](README.md)*

Lanza **una tarea** (un prompt) sobre **muchos ficheros** con la API de Anthropic: en directo, o en lote con la Batch
API (la mitad de precio, resultado en menos de 24 horas). Pensada para trabajos grandes y repetitivos: traducir
cientos de artículos, corregir erratas, escribir meta descripciones, clasificar…

- **Sin nada específico de ningún proyecto:** las tareas son ficheros Markdown; tu proyecto aporta las suyas.
- **Segura de relanzar:** lo que ya está en la carpeta de salida no se rehace (ni se paga otra vez).
- **Con control de gasto:** estima el coste antes (`--dry-run`) y para al llegar a `--max-cost`.
- **Con comprobaciones:** si un resultado no pasa una comprobación (por ejemplo, el HTML perdió etiquetas), va a
  `_review/` en lugar de a la salida.
- **También para agentes:** un servidor MCP deja que un agente como Claude Code delegue el trabajo masivo en la API
  sin pasar el contenido por su conversación.

## Instalación

```bash
pip install promptbatch            # la herramienta de línea de órdenes
pip install 'promptbatch[mcp]'     # y además el servidor MCP
```

O desde el código: `pip install 'git+https://github.com/Invarato/promptbatch'`. Necesita Python 3.11 o posterior.

## La clave de la API

Nunca va en un repositorio. Se busca en este orden: la variable `ANTHROPIC_API_KEY`, la opción `--key-file`, la
variable `PROMPTBATCH_KEY_FILE` o el fichero `~/.config/promptbatch/api.key` (con permisos `600`).

## Una tarea

Un fichero `.md` con cabecera TOML entre líneas `+++`, el system prompt (opcional) y, tras `---prompt---`, el prompt,
con `{{content}}` (el fichero) y `{{name}}` (su nombre sin extensión). Más variables con `--var clave=valor`. Las
tareas escritas para la versión 0.1, con `{{contenido}}` y `{{nombre}}`, siguen funcionando.

```markdown
+++
model = "claude-sonnet-5-5"
max_tokens = 16000
effort = "low"                     # low, medium, high, xhigh, max (en traducciones suele bastar low)
checks = ["html:content"]          # comprobaciones: html, non-empty; «nombre:campo» la aplica a un campo del JSON
extensions = [".html"]             # qué ficheros coger de una carpeta
context = ["guia-de-estilo.md", "glosario.md"]   # se añaden al system prompt (con caché)
schema = "traduccion.schema.json"               # respuesta en JSON con este esquema (salida .json)
+++
Eres un traductor profesional…
---prompt---
Traduce al {{idioma}} este HTML conservando todas las etiquetas:

{{content}}
```

Ver [tasks/example-summary.md](tasks/example-summary.md). Sin `model`, se usa `claude-opus-5-5`.

- **Contexto** (`context`, o `--context fichero` en la línea de órdenes): guías de estilo, glosarios… Van al system
  prompt, que se cachea: a partir de la segunda petición se cobran a 0,1×. El mínimo cacheable depende del modelo (de
  512 a 4096 tokens); por debajo, no se cachea nada.
- **Herramientas del servidor** (`tools = ["web_fetch"]` o `"web_search"`): las ejecuta Anthropic, así que sirven
  aunque el equipo que lanza la tarea no tenga acceso a internet. `web_fetch` solo descarga direcciones que aparezcan
  en el prompt. Límites: `tool_max_uses` y `fetch_max_tokens` (lo descargado se cobra como entrada). Si la respuesta se
  para a medias (`pause_turn`), en directo se reanuda sola; en lote va a `_review/`.
- **Imágenes** (`images = "campo"`): la entrada es JSON y ese campo lista rutas de imágenes (relativas a la carpeta del
  fichero) que se adjuntan, en orden, antes del prompt. Para describir imágenes, textos alternativos, etc.
- **Esquema** (`schema`): la API devuelve JSON que cumple el esquema (salida estructurada). Útil para devolver varios
  campos a la vez (título, slug, meta descripción, contenido) o listas de correcciones.

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

En la salida: un fichero por entrada (con el mismo nombre); `_review/` con los que no pasaron las comprobaciones;
`.meta/<fichero>.json` con tokens, coste y motivo de parada; `.batch.json` con el lote en curso.

## Desde un agente (servidor MCP)

`promptbatch-mcp` ofrece dos herramientas y un recurso, para que un agente como Claude Code delegue el trabajo masivo
sin pasar el contenido por su conversación (solo recibe resúmenes):

- `launch(task, inputs, output, mode="estimate"|"direct"|"batch", limit, max_cost, variables, context, model)`. Para
  gastar (`direct` o `batch`) hace falta `max_cost`, en USD.
- `status(output)`: cómo va el lote; si ha terminado, lo recoge. Resumen de hechos, a revisar y coste.
- recurso `promptbatch://tasks`: las tareas de las carpetas de `PROMPTBATCH_TASK_DIRS`.

```bash
claude mcp add -s project promptbatch -e PROMPTBATCH_KEY_FILE=~/.config/promptbatch/api.key \
  -e PROMPTBATCH_TASK_DIRS=./tasks -- promptbatch-mcp
```

La skill [skill/SKILL.md](skill/SKILL.md) le explica al agente cuándo y cómo usarlo (estimar antes, pedir permiso
antes de gastar, probar con pocos, el resto en lote). Cópiala a `.claude/skills/promptbatch/` de tu proyecto.

## Costes

Los precios con los que estima están en `config.py` y son orientativos: compruébalos y, si cambian, pásalos con
`--prices fichero.toml` (`["modelo"]` con `input` y `output` en USD por millón de tokens y, si quieres, `cache_read`).
El coste real de cada petición queda en `.meta/`.

## Si vienes de la 0.1

Ver el [CHANGELOG](CHANGELOG.md): las herramientas del MCP cambian de nombre (al inglés) y las tareas de la 0.1 siguen
funcionando.

## Desarrollo

```bash
pip install -e '.[dev,mcp]'
pytest
ruff check src tests && ruff format --check src tests
```

Para publicar una versión, sube `version` en `pyproject.toml` y añade su sección en `CHANGELOG.md`. Cuando llega a
`main`, GitHub Actions la prueba, la publica en PyPI y crea su etiqueta y su *release* de GitHub.

## Licencia

[MIT](LICENSE).
