---
name: coding-assertions
description: Code quality verification checklist
---

# Coding Guidelines

> Those rules must be minimal because they MUST be checked after EVERY CODE GENERATION.

## Requirements to complete a feature

**A feature is really completed if ALL of the above are satisfied.**

- Markdown files are valid and well-formed
- JSON config files pass syntax validation
- No broken `@include` references in `.claude/` files
- Frontmatter fields match naming conventions

## Python-specific assertions

- Module-level objects (singletons, clients, constants) must be declared **after all imports** — placing them between import groups causes E402 and breaks PEP 8 grouping.
- `spacy.load()` disable lists must be per-model (see `LESSONS.md` L13).
- Never use `Optional[X]` — use `X | None` (Python 3.10+, PEP 604).

## Commands to run

### Before commit

N/A - no build system configured

### Before push

N/A - no build system configured
