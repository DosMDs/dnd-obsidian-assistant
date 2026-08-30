"""ModelGateway — deferred contract for LLM model inference.

Responsibility
──────────────
Owns: model interaction — prompt completion, structured output, tool calling.
Must not own: prompt templates, domain logic, storage, tool execution.
Called by: application layer (FastAgent, PostSessionProcessor, etc.).
Failure boundary: raises ModelError on provider/network failure.

Canonical logical operations
────────────────────────────
chat                — multi-turn conversation (text in, text out).
chat_with_tools     — multi-turn conversation with tool-calling support.
generate_structured — produce structured output matching a Pydantic schema.
embed               — produce vector embeddings for text inputs.
health              — check provider reachability and model availability.

Stage 1 inventories these logical operations only. Executable typed
signatures and the sync/async implementation choice are deferred until
Stage 8 (Model Gateway / Ollama).
"""
