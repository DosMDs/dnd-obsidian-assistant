---
name: eval-harness
description: Design, implement or review deterministic model/runtime eval and benchmark harnesses with truthful reference/candidate identity, frozen measured datasets, literal counters, safe live opt-in execution and evidence-driven metrics.
---
# Eval harness

Use for model/runtime/provider comparison, PAIM eval, tool/model selection, latency sampling, or any suite that reports quality/performance metrics from repeated model runs. Not for ordinary unit tests without measurement semantics. General gate/evidence rules are in [quality-and-evidence](../../../docs/development/quality-and-evidence.md).

## Define the question first
Write down systems compared, stable ground truth, scenario set, repetition count, hard safety blockers, quality/performance metrics and the live/offline boundary. Do not tune the scenario set after observing one side's results unless the original scenario is objectively malformed; if changed, restart the measured run for both systems.

## Deterministic ground truth and identity
Ground truth is Python data, never another LLM (no LLM-as-judge, no chain-of-thought grading or storage). Prefer exact evaluation of terminal outcome, tool names/arguments, schema validity, WRITE classification, model request count, executor/handler count, side effects and latency. Before a live run, add an offline architecture guard proving reference and candidate are the intended distinct systems (e.g. reference FastAgent + native ModelGateway vs candidate PydanticAIFastAgent + Pydantic Model); do not trust fixture variable names. If both sides share a runtime/provider, STOP.

## Same logical input
Both systems receive equivalent user input, application context, permissions/session/audit state, tool definitions/schemas, and model/settings/profile where comparison requires it. Drive both from one scenario object and keep independent mutable tool/repository state per system.

## Live preflight
Before any expensive external run: construct the full test-owned object graph offline, validate concrete framework type requirements and test-double contracts, unit-test scorers/counters/percentiles, and prove env-unset tests skip before network. A skipped live module is not constructor evidence.

## Wrappers and literal counters
Measurement wrappers must not alter measured behavior: for framework `Model` wrappers preserve the required concrete/base type, model/provider identity, settings/profile/base_url, request/response/exceptions and lifecycle; count the attempt at the semantic request boundary and delegate unchanged; add offline equivalence tests. Where a claim names a count, measure that boundary directly (semantic model requests, ToolExecutor attempts, handler invocations, WRITE side effects); never infer one count from another.

## Samples and datasets
Warm up symmetrically inside setup before timing (never via pytest ordering), collect measured samples exactly once, freeze observations, and reuse them for every classification/metric/latency report. Do not rerun the model to compute aggregates. Own one dataset object per measurement layer containing reference/candidate observations, scenario/repetition keys, comparisons, metric summaries, latency samples and safety counts; assert expected sample count and uniqueness.

## Order, error and metric semantics
Use a predeclared deterministic execution order (e.g. rep0 ref→cand, rep1 cand→ref, rep2 ref→cand); do not change it after results. An error is not a successful no-tool decision: fail an observation first when `error_type is not None` unless the scenario expects that error, and never silently convert malformed terminal output. Every metric defines numerator, denominator, unit, applicability and error treatment; tie labels to identity/position, not observed values. Define false-WRITE, hidden-WRITE and correct-abstention semantics explicitly (multiple WRITE calls increment the run-level numerator once; abstention requires no error and zero calls). Compute a stable per-scenario majority (`BOTH_PASS`/`REFERENCE_ONLY_PASS`/`CANDIDATE_ONLY_PASS`/`BOTH_FAIL`) and never hide critical reference-only passes inside averages.

## Safety, latency and live discipline
Fail the measured suite automatically for agreed hard regressions (candidate false WRITE, unauthorized WRITE execution, exceeded model-request bound, critical reference-only success). Measure latency with `time.perf_counter()` around the intended operation; report p50/p95 and ratios without inventing a hardware SLA or inferring causation from timing alone. Live runs use explicit opt-in env vars: absent → skip before network; present → missing/invalid config/server/model is FAIL, not SKIP. Never mutate the real campaign Vault for evaluation; use synthetic data and in-memory WRITE handlers.

## Reporting
Report exact environment/model/profile identity (no secrets/absolute paths), sample counts/repetitions, metric numerator/denominator values, scenario majority matrix, safety counts, p50/p95 and ratios, exact command identity, the measured/inferred/historical distinction, and limitations. Never report a different sample set than the one asserted. Finish with [pre-finalization-audit](../pre-finalization-audit/SKILL.md).
