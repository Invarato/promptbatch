+++
# Example task: summarize each file in two sentences.
model = "claude-haiku-5-5"
max_tokens = 1000
extensions = [".txt", ".md", ".html"]
+++
You are a concise editor. You answer only with the summary, without any introduction.
---prompt---
Summarize this file ("{{name}}") in two sentences, in the same language as the text:

{{content}}
