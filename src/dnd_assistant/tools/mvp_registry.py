"""MVP tool registry composition — trusted dependency wiring.

This module provides a single composition point that builds the complete
accepted Stage-7 MVP ``ToolRegistry`` with all 18 tools across six
families.

It is an explicit composition module and must NOT depend on:

    models, cli, ollama

It MAY depend on:

    tools family modules
    application session services
    retrieval contracts
    storage protocols
    calendar contract

No global singleton.
No module-level mutable registry.
No service locator.
No DI framework.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dnd_assistant.tools.entity_mutations import register_entity_mutation_tools
from dnd_assistant.tools.entity_reads import register_entity_read_tools
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.session_mutations import register_session_mutation_tools
from dnd_assistant.tools.session_reads import register_session_read_tools
from dnd_assistant.tools.world_time_mutations import (
    register_world_time_mutation_tools,
)
from dnd_assistant.tools.world_time_reads import register_world_time_read_tools

if TYPE_CHECKING:
    from dnd_assistant.application.session_recovery import SessionRecoveryService
    from dnd_assistant.application.session_runtime import SessionRuntimeService
    from dnd_assistant.domain.calendar import CalendarService
    from dnd_assistant.retrieval.service import SearchService
    from dnd_assistant.storage.types import (
        SessionEventRepository,
        SessionMetadataRepository,
        VaultRepository,
        WorldTimeRepository,
    )


def build_mvp_tool_registry(
    *,
    search_service: SearchService,
    repository: VaultRepository,
    runtime_service: SessionRuntimeService,
    recovery_service: SessionRecoveryService,
    session_repository: SessionMetadataRepository,
    event_repository: SessionEventRepository,
    world_time_repository: WorldTimeRepository,
    calendar_service: CalendarService,
) -> ToolRegistry:
    """Build the complete MVP ``ToolRegistry`` with all 18 accepted tools.

    Registers all six tool families by delegating to the accepted family
    registration functions.  No individual tool definitions are created
    or duplicated in this module.

    Args:
        search_service: Player-visibility gate for entity tools.
        repository: ``VaultRepository`` for entity persistence.
        runtime_service: ``SessionRuntimeService`` for session mutations.
        recovery_service: ``SessionRecoveryService`` for preflight checks.
        session_repository: ``SessionMetadataRepository`` for session reads.
        event_repository: ``SessionEventRepository`` for event reads.
        world_time_repository: ``WorldTimeRepository`` for world-time persistence.
        calendar_service: ``CalendarService`` for date arithmetic.

    Returns:
        A populated ``ToolRegistry`` with exactly 18 registered tools.

    Raises:
        ValidationError: A registration API received an invalid argument.
        ConflictError: A tool name conflict occurred (should not happen
            with the accepted definitions).
    """
    registry = ToolRegistry()

    register_entity_read_tools(
        registry,
        search_service=search_service,
        repository=repository,
    )

    register_entity_mutation_tools(
        registry,
        search_service=search_service,
        repository=repository,
    )

    register_session_read_tools(
        registry,
        runtime_service=runtime_service,
        session_repository=session_repository,
        event_repository=event_repository,
    )

    register_session_mutation_tools(
        registry,
        runtime_service=runtime_service,
        recovery_service=recovery_service,
    )

    register_world_time_read_tools(
        registry,
        world_time_repository=world_time_repository,
        calendar_service=calendar_service,
    )

    register_world_time_mutation_tools(
        registry,
        world_time_repository=world_time_repository,
        calendar_service=calendar_service,
    )

    return registry
