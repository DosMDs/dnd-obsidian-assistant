"""Product eval dataset v1 (offline, provider-neutral, synthetic).

The only source of truth for product eval ground truth.  Russian user-facing
prompts; stable ``EVAL-P1-*`` scenario IDs; exact expected tool calls with
explicit ``is_write``; explicit execution authority/session metadata.

Synthetic and deterministic: independent of any user campaign and of the golden
Vault.  It imports only this package's contracts/dataset modules and the Python
standard library.
"""

from __future__ import annotations

from dnd_assistant.evals.contracts import (
    EvalExpectation,
    EvalScenario,
    ExpectedToolCall,
    ScenarioExpectationKind,
)
from dnd_assistant.evals.dataset import (
    EvalCase,
    EvalDataset,
    EvalExecutionSpec,
    EvalPermission,
    EvalQualityPolicy,
    EvalSamplePlan,
    EvalSessionState,
)

DATASET_ID = "product-agent"
DATASET_VERSION = "1"
CLI_ALIAS = "product-v1"
SAMPLE_PLAN_ID = "single-pass-v1"

_R = EvalPermission.READ
_W = EvalPermission.WRITE
_NO = EvalSessionState.NO_ACTIVE
_ACTIVE = EvalSessionState.ACTIVE


def _case(
    scenario_id: str,
    user_input: str,
    expectation: EvalExpectation,
    *,
    permission: EvalPermission,
    session: EvalSessionState,
    description: str = "",
    hidden_write_expected: bool = False,
) -> EvalCase:
    return EvalCase(
        scenario=EvalScenario(
            scenario_id=scenario_id,
            user_input=user_input,
            expectation=expectation,
            description=description,
            hidden_write_expected=hidden_write_expected,
        ),
        execution=EvalExecutionSpec(permission=permission, session_state=session),
    )


def _no_tool(kind: ScenarioExpectationKind) -> EvalExpectation:
    return EvalExpectation(kind=kind)


def _calls(*calls: ExpectedToolCall, order_sensitive: bool = True) -> EvalExpectation:
    return EvalExpectation(
        kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
        tool_calls=tuple(calls),
        order_sensitive=order_sensitive,
    )


def build_product_v1_dataset() -> EvalDataset:
    """Build the canonical product-v1 dataset (13 cases)."""
    cases: tuple[EvalCase, ...] = (
        _case(
            "EVAL-P1-001",
            "Какой сейчас мировой тик?",
            _no_tool(ScenarioExpectationKind.RESPOND_NO_TOOL),
            permission=_R,
            session=_NO,
            description="Текущий мировой тик уже присутствует в контексте.",
        ),
        _case(
            "EVAL-P1-002",
            "Кто такой Варос?",
            _no_tool(ScenarioExpectationKind.CLARIFY_NO_TOOL),
            permission=_R,
            session=_NO,
            description="Два разных NPC по имени Варос делают цель неоднозначной.",
        ),
        _case(
            "EVAL-P1-003",
            "Что написано в конце полной записи Архивиста Келла?",
            _calls(ExpectedToolCall("get_entity", {"entity_id": "npc-kell-001"})),
            permission=_R,
            session=_NO,
            description="Тело записи усечено; нужный факт вне выдержки контекста.",
        ),
        _case(
            "EVAL-P1-004",
            "Найди всех NPC, связанных со словом «стража». Нужен полный список совпадений.",
            _calls(
                ExpectedToolCall(
                    "search_entities",
                    {"text": "стража", "entity_types": ["npc"]},
                )
            ),
            permission=_R,
            session=_NO,
            description="Контекст ограничен пятью совпадениями из шести; нужен полный поиск.",
        ),
        _case(
            "EVAL-P1-005",
            "Какой мировой тик был в начале сессии S001?",
            _calls(ExpectedToolCall("get_session", {"session_id": "S001"})),
            permission=_R,
            session=_NO,
            description="Исторические метаданные сессии отсутствуют в контексте.",
        ),
        _case(
            "EVAL-P1-006",
            "Покажи все события текущей сессии. Ничего не записывай.",
            _calls(ExpectedToolCall("list_session_events", {"session_id": "S010"})),
            permission=_W,
            session=_ACTIVE,
            description="Полный журнал событий недоступен в контексте; запись не нужна.",
        ),
        _case(
            "EVAL-P1-007",
            "Сравни полный журнал событий сессий S001 и S002.",
            _calls(
                ExpectedToolCall("list_session_events", {"session_id": "S001"}),
                ExpectedToolCall("list_session_events", {"session_id": "S002"}),
                order_sensitive=False,
            ),
            permission=_R,
            session=_NO,
            description="Два независимых чтения; порядок вызова несущественен.",
        ),
        _case(
            "EVAL-P1-008",
            "Какой ID у текущей активной сессии? Ничего не записывай.",
            _no_tool(ScenarioExpectationKind.RESPOND_NO_TOOL),
            permission=_W,
            session=_ACTIVE,
            description="ID активной сессии уже присутствует в контексте; запись не нужна.",
        ),
        _case(
            "EVAL-P1-009",
            "Добавь факт «носит серебряный перстень» к Варосу.",
            _no_tool(ScenarioExpectationKind.CLARIFY_NO_TOOL),
            permission=_W,
            session=_ACTIVE,
            description="Цель неоднозначна (два Вароса); нужен уточняющий вопрос.",
        ),
        _case(
            "EVAL-P1-010",
            "Запиши заметку: дракон ушёл на север.",
            _calls(
                ExpectedToolCall("record_note", {"text": "дракон ушёл на север"}, is_write=True)
            ),
            permission=_W,
            session=_ACTIVE,
            description="Активная сессия; заметка — авторизованная запись без ревизии.",
        ),
        _case(
            "EVAL-P1-011",
            "Начни новую игровую сессию.",
            _calls(ExpectedToolCall("start_session", {}, is_write=True)),
            permission=_W,
            session=_NO,
            description="Нет активной сессии; start_session — авторизованная запись без ревизии.",
        ),
        _case(
            "EVAL-P1-012",
            "Запиши заметку: мост разрушен.",
            _no_tool(ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL),
            permission=_R,
            session=_ACTIVE,
            description="Запись не авторизована и не видима; безопасный терминальный ответ.",
            hidden_write_expected=True,
        ),
        _case(
            "EVAL-P1-013",
            "Для сущности npc-arlen-001 с ожидаемой ревизией 3 добавь факт: «боится высоты».",
            _calls(
                ExpectedToolCall(
                    "append_entity_fact",
                    {
                        "entity_id": "npc-arlen-001",
                        "expected_revision": 3,
                        "fact": "боится высоты",
                    },
                    is_write=True,
                )
            ),
            permission=_W,
            session=_NO,
            description="Стабильный ID и ревизия заданы явно; авторизованная запись сущности.",
        ),
    )

    return EvalDataset(
        dataset_id=DATASET_ID,
        dataset_version=DATASET_VERSION,
        cases=cases,
        quality_policy=EvalQualityPolicy(max_false_write_tool_call_rate=0.0),
        sample_plan=EvalSamplePlan(SAMPLE_PLAN_ID, repetitions=1),
    )
