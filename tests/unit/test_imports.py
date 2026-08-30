"""Smoke tests: verify all sub-packages import cleanly."""

from __future__ import annotations


def test_domain_imports() -> None:
    import dnd_assistant.domain  # noqa: F401


def test_storage_imports() -> None:
    import dnd_assistant.storage  # noqa: F401


def test_models_imports() -> None:
    import dnd_assistant.models  # noqa: F401


def test_retrieval_imports() -> None:
    import dnd_assistant.retrieval  # noqa: F401


def test_tools_imports() -> None:
    import dnd_assistant.tools  # noqa: F401


def test_application_imports() -> None:
    import dnd_assistant.application  # noqa: F401


def test_cli_imports() -> None:
    import dnd_assistant.cli  # noqa: F401


def test_prompts_imports() -> None:
    import dnd_assistant.prompts  # noqa: F401


def test_evals_imports() -> None:
    import dnd_assistant.evals  # noqa: F401


def test_calendar_module_import() -> None:
    import dnd_assistant.domain.calendar  # noqa: F401


def test_gateway_module_import() -> None:
    import dnd_assistant.models.gateway  # noqa: F401


def test_audit_module_import() -> None:
    import dnd_assistant.storage.audit  # noqa: F401


def test_registry_module_import() -> None:
    import dnd_assistant.tools.registry  # noqa: F401
