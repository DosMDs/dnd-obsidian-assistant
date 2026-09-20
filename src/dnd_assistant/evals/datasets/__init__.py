"""Versioned product eval datasets.

Each module exposes a ``build_*`` factory returning an ``EvalDataset``.  All
modules are provider-neutral (stdlib + ``dnd_assistant.evals`` only).
"""

from __future__ import annotations

from dnd_assistant.evals.datasets.product_v1 import (
    CLI_ALIAS,
    DATASET_ID,
    DATASET_VERSION,
    SAMPLE_PLAN_ID,
    build_product_v1_dataset,
)

__all__ = [
    "CLI_ALIAS",
    "DATASET_ID",
    "DATASET_VERSION",
    "SAMPLE_PLAN_ID",
    "build_product_v1_dataset",
]
