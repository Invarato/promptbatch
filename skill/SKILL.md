---
name: promptbatch
description: Delegar trabajo masivo o repetitivo con IA (traducir, revisar, clasificar o resumir muchos ficheros) en la API de Anthropic mediante el MCP de promptbatch, en vez de hacerlo en la conversación. Úsala cuando la misma tarea se aplica a más de unos pocos ficheros o la salida es larga.
---

# Delegar en promptbatch

Hacerlo en la conversación gasta el contexto y los tokens de la sesión. Con el MCP `promptbatch`, el trabajo
lo hace la API con la clave del usuario (en lote, a mitad de precio) y aquí solo llegan resúmenes.

## Cuándo
- La misma instrucción sobre muchos ficheros (más de 3–5) o con salidas largas: traducir, corregir erratas,
  clasificar, generar descripciones, resumir.
- No para tareas que necesitan iterar con el usuario o decisiones caso a caso: eso, en la conversación.

## Cómo
1. Elige la tarea en el recurso `promptbatch://tareas`, o escribe una nueva (`.md` con cabecera TOML entre
   `+++`, system, `---prompt---` y el prompt con `{{contenido}}`; ver el README de promptbatch).
2. `lanzar(..., modo="estimar")` siempre primero. **Enseña la estimación al usuario y pide permiso antes de
   gastar**, salvo que ya haya fijado un tope para esa tarea.
3. Prueba con `limite` pequeño (2–3) en modo `directo` y revisa tú una muestra leyendo los ficheros.
4. El resto en modo `lote` con `max_coste`, y `consultar(salida)` más tarde.
5. Lo que quede en `_revisar/` (no pasó las comprobaciones) se mira a mano o se relanza tras mejorar la tarea.

## Reglas
- No leas en la conversación todas las salidas: solo una muestra y las de `_revisar/`.
- Relanzar no repite (ni paga) lo ya hecho: para rehacer algo, borra su fichero de salida.
- Si una tarea falla a menudo por lo mismo, mejora su guía o su prompt antes de seguir.
