---
apply: ALWAYS
mode: ALL
---
# Python and package boundaries

- Target Python 3.12+.
- Use explicit typing for public APIs and Pydantic schemas for external/model-facing structured data.
- Keep Typer/Rich concerns in `cli/`; do not put business logic in CLI callbacks.
- Keep orchestration in `application/`.
- Keep deterministic business rules in `domain/`.
- Keep Markdown/YAML persistence, audit and locking in `storage/`.
- Keep Ollama-specific behavior behind `ModelGateway` provider implementations in `models/`.
- Avoid circular dependencies and provider-specific types leaking into domain/application contracts.
- Do not add abstractions that are not required by the current roadmap stage.
