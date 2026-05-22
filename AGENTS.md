# AGENTS.md

## First-read requirement

Before making changes or giving project-status advice in a new conversation, read these files first:

1. `docs/session-summary.md`
2. `README.md`
3. `CODEX.md`

Treat `docs/session-summary.md` as the current handoff document for this repository.
Treat `CODEX.md` as a mandatory local behavior/instruction document for this repository.

## Working rules for this project

- Do not print or copy `.env` secrets back into chat unless the user explicitly asks.
- Use the real local Longbridge paper account id `LBPT10087357` instead of the older placeholder `demo-paper-001`.
- The dashboard UI lives at `/`, while Swagger remains at `/docs`.
- Prefer extending the existing FastAPI + SQLAlchemy structure instead of introducing a second frontend or service stack.

## Context note

This file is meant to improve continuity across new conversations, but it is still a repository convention rather than a hard platform guarantee. If project state looks inconsistent, reconcile the codebase with `docs/session-summary.md` before making irreversible changes.
