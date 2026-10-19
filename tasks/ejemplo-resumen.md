+++
# Tarea de ejemplo: resume cada fichero en dos frases.
model = "claude-haiku-5-5"
max_tokens = 1000
extensions = [".txt", ".md", ".html"]
+++
Eres un editor conciso. Respondes solo con el resumen, sin introducciones.
---prompt---
Resume en dos frases, en el mismo idioma del texto, este fichero («{{nombre}}»):

{{contenido}}
