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

## Engineering principles

Apply these principles together with `CODEX.md`. Explicit user requirements, the paper-first safety boundary, persisted-data integrity, and documented public contracts take precedence over cleanup preferences.

- Before significant product, UX, or architecture work, study how established products and well-maintained libraries solve the same problem. Prefer proven patterns and conventions when they fit this project's modular-monolith and paper-first boundaries; do not copy them blindly or turn trivial changes into open-ended research.
- Choose the simplest implementation that fully meets the current requirement. Avoid speculative abstractions, configuration, indirection, or features.
- Grow the system through small end-to-end vertical slices. Each slice must leave the product working and preserve the applicable safety and regression gates; do not replace a working path with partially integrated complexity.
- Keep components modular, bounded-context responsibilities clear, and external integrations behind adapters. Preserve the existing FastAPI + SQLAlchemy modular monolith unless a demonstrated need justifies a different boundary.
- Use capabilities and dependencies already present in the project before writing custom infrastructure or adding packages. Check the relevant documentation, APIs, and types before concluding that a dependency lacks a capability.
- Add an established, well-maintained dependency only when it reduces total complexity or materially improves reliability, and document the reason when the choice is not obvious. Do not reimplement common functionality without a clear project-specific need.
- Treat backward compatibility as an explicit contract, not an automatic requirement:
  - For obsolete internal code paths, prefer removing the old path and updating all in-repo callers, tests, and documentation in the same verified change. Do not add fallback or dual-path behavior by default.
  - Public routes, operator workflows, persisted records, and database schemas are compatibility surfaces. Preserve their documented contract or provide an intentional migration and rollback/recovery path.
  - Continue using Alembic for schema evolution, and never delete or bypass historical migrations that are required to build or upgrade a database. Destructive or externally breaking changes require explicit user approval.
- Make architectural decisions that are maintainable for the expected life of the product. Do not ship a knowingly disposable stopgap as the default solution. If an explicitly requested emergency workaround is the only safe option, keep it narrow and document its limitation, removal trigger, and verification path.

## Context note

This file is meant to improve continuity across new conversations, but it is still a repository convention rather than a hard platform guarantee. If project state looks inconsistent, reconcile the codebase with `docs/session-summary.md` before making irreversible changes.
