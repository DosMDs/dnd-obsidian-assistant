"""Atomic derived-artifact writing for the eval runner.

Eval reports are derived, disposable, rebuildable artifacts.  They never become
campaign Source of Truth and are never written inside the Vault.  Writes are
fully serialized in memory, written to a temporary file in the destination
directory and promoted with ``os.replace``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


class EvalArtifactError(Exception):
    """Raised when a derived eval artifact cannot be safely written."""


def write_report_atomic(path: Path, text: str, *, overwrite: bool) -> None:
    """Write ``text`` to ``path`` atomically (UTF-8, LF).

    Raises:
        EvalArtifactError: The parent directory is missing, the target is a
            directory, the target exists and ``overwrite`` is ``False``, or the
            write/replace fails.
    """
    parent = path.parent
    if not parent.is_dir():
        raise EvalArtifactError(f"output directory does not exist: {parent}")
    if path.is_dir():
        raise EvalArtifactError(f"output path is a directory: {path}")
    if path.exists() and not overwrite:
        raise EvalArtifactError(f"output file already exists (use --overwrite): {path}")

    descriptor, temp_name = tempfile.mkstemp(dir=str(parent), prefix=".eval-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except OSError as exc:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise EvalArtifactError(f"failed to write report artifact: {exc}") from exc
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def read_report_text(path: Path) -> str:
    """Read a report artifact as UTF-8 text.

    Raises:
        EvalArtifactError: The file is missing, not a regular file or unreadable.
    """
    if not path.is_file():
        raise EvalArtifactError(f"report file not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvalArtifactError(f"failed to read report artifact: {exc}") from exc
