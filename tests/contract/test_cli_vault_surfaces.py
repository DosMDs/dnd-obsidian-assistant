"""Structural contract for production Vault option surfaces (CFG-02).

Proves that **every** Vault-using CLI surface is wired through the one shared
presentation resolver rather than ad-hoc environment access, and that the
option is consistently optional (machine-default capable) with the explicit
path checks preserved.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from typer.models import OptionInfo

from dnd_assistant.cli.main import app

_SRC_CLI = Path(__file__).resolve().parents[2] / "src" / "dnd_assistant" / "cli"

# Canonical set of Vault-using production surfaces (PLAN inventory).
_EXPECTED_VAULT_COMMANDS = {
    "note",
    "ask",
    "init",
    "tui",
    "session start",
    "session status",
    "session end",
    "session process",
    "session outputs",
    "changeset save",
    "changeset review",
    "changeset approve",
    "changeset reject",
    "changeset apply",
    "changeset status",
    "bootstrap map",
    "bootstrap review",
    "bootstrap approve",
    "bootstrap reject",
    "bootstrap apply",
    "bootstrap finalize",
    "time init",
    "index rebuild",
}


def _iter_commands(typer_app: Any, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, Any]]:
    for command in typer_app.registered_commands:
        callback = command.callback
        name = command.name or callback.__name__
        yield " ".join(prefix + (name,)), callback
    for group in typer_app.registered_groups:
        instance = group.typer_instance
        group_name = group.name or (instance.info.name if hasattr(instance, "info") else "")
        child_prefix = prefix + ((group_name,) if group_name else ())
        yield from _iter_commands(instance, child_prefix)


def _vault_option(callback: Any) -> OptionInfo | None:
    for parameter in inspect.signature(callback).parameters.values():
        default = parameter.default
        if isinstance(default, OptionInfo) and "--vault" in (default.param_decls or ()):
            return default
    return None


def _commands_with_vault() -> dict[str, OptionInfo]:
    found: dict[str, OptionInfo] = {}
    for name, callback in _iter_commands(app):
        option = _vault_option(callback)
        if option is not None:
            found[name] = option
    return found


def test_vault_option_surface_matches_inventory() -> None:
    assert set(_commands_with_vault()) == _EXPECTED_VAULT_COMMANDS


def test_every_vault_option_is_optional_and_preserves_explicit_checks() -> None:
    for name, option in _commands_with_vault().items():
        # ``init`` intentionally keeps lenient explicit-path semantics (no
        # Typer existence check) so a bad explicit target stays a project error.
        if name == "init":
            assert option.default is None, name
            continue
        assert option.default is None, name
        assert option.exists is True, name
        assert option.file_okay is False, name
        assert option.dir_okay is True, name
        assert option.readable is True, name
        assert option.resolve_path is True, name


def test_every_vault_surface_uses_shared_resolver() -> None:
    """Each CLI file declaring ``--vault`` must use the shared resolver."""
    offenders: list[str] = []
    for path in sorted(_SRC_CLI.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if '"--vault"' in text and "resolve_vault_root" not in text:
            offenders.append(path.name)
    assert not offenders, f"ad-hoc Vault resolution in {offenders}"


def test_no_ad_hoc_vault_path_resolution_in_cli() -> None:
    """No CLI command may re-implement the former inline path resolution."""
    offenders: list[str] = []
    for path in sorted(_SRC_CLI.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "vault.resolve(strict=False)" in text or "vault.expanduser()" in text:
            offenders.append(path.name)
    assert not offenders, f"inline Vault resolution remains in {offenders}"
