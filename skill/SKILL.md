---
name: promptbatch
description: Hand bulk or repetitive AI work (translating, reviewing, classifying or summarizing many files) over to the Anthropic API through the promptbatch MCP server, instead of doing it in the conversation. Use it when the same task applies to more than a few files or the output is long.
---

# Delegating to promptbatch

Doing it in the conversation uses up the session's context and tokens. With the `promptbatch` MCP server, the API does
the work with the user's key (as a batch, at half price) and only summaries come back here.

## When

- The same instruction over many files (more than 3 to 5) or with long outputs: translating, fixing typos,
  classifying, writing descriptions, summarizing.
- Not for work that needs back-and-forth with the user or case-by-case decisions: that stays in the conversation.

## How

1. Pick the task from the `promptbatch://tasks` resource, or write a new one (a `.md` with a TOML header between
   `+++`, the system prompt, `---prompt---` and the prompt with `{{content}}`; see the promptbatch README).
2. Always `launch(..., mode="estimate")` first. **Show the estimate to the user and ask before spending**, unless they
   have already set a limit for that task.
3. Try a small `limit` (2 or 3) in `direct` mode, with `max_cost`, and review a sample yourself by reading the files.
4. The rest in `batch` mode with `max_cost`, and `status(output)` later.
5. Whatever ends up in `_review/` (it failed a check) is looked at by hand or relaunched after improving the task.

## Rules

- Don't read every output in the conversation: only a sample and the ones in `_review/`.
- Relaunching doesn't repeat (or pay for) what is done: to redo something, delete its output file.
- If a task often fails for the same reason, improve its guide or its prompt before going on.
