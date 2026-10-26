# Security

## Your API key

promptbatch uses your own Anthropic API key and never writes it to the output, to `.meta/` or to `.batch.json`. Keep it
out of any repository: use the `ANTHROPIC_API_KEY` variable or a key file with permissions `600` (see the README).

Everything a task sends (the task, its context files and the input files) goes to the Anthropic API. Don't point a
task at files you don't want to send, and keep in mind that an agent using the MCP server can launch tasks over any
path it can read: give it the key only in projects where that is acceptable.

## Reporting a vulnerability

Please report it privately through GitHub: on the repository page, **Security → Report a vulnerability**. Don't open a
public issue for it.
