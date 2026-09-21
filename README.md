# D&D Session Assistant

Локальный помощник для долговременной памяти кампании D&D/RPG. Приложение
хранит каноническое состояние кампании в обычном Obsidian Vault и даёт
ассистенту, который умеет искать сущности, вести сессии и предлагать изменения
в понятном человеку виде.

Продукт построен **local-first и provider-neutral**: Vault, доменная логика,
хранилище и поиск работают локально, а инференс может выполняться как локально
(Ollama), так и через удалённого провайдера (DeepSeek). Интернет нужен только
для выбранного вами удалённого провайдера.

- Obsidian Vault — единственный источник правды (Source of Truth) по кампании.
- Python владеет доменной логикой, валидацией, файловыми операциями, календарём,
  поиском, исполнением инструментов и персистентностью.
- LLM — заменяемый и недоверенный механизм. Модель никогда не получает
  произвольного доступа к файловой системе Vault.

## Статус

```text
MVP                  RELEASE_READY
Этапы 0–14           DONE
Textual TUI          интегрирован
v0.5.0 baseline      DONE / CLOSED

канонический AGENT-baseline квалификации:
    deepseek / deepseek-flash / role=agent / thinking=true / reasoning_effort=high
```

`deepseek / deepseek-flash / thinking=true / reasoning_effort=high` — это
**принятый эталон квалификации**, а не автоматический режим по умолчанию. Выбор
провайдера и модели остаётся локальной настройкой машины; Ollama поддерживается
и не требует удалённого доступа.

Текущее состояние roadmap и истории: `DEVELOPMENT_STATUS.md`.

## Что это умеет

- Инициализировать структуру помощника в выбранном Obsidian Vault.
- Вести каноническое игровое время (мировой такт) и календарные преобразования.
- Искать сущности (NPC, локации, квесты, предметы) и разрешать имена в устойчивые
  идентификаторы.
- Вести игровые сессии: старт, заметки, события, завершение, сырые журналы.
- Отвечать на вопросы по кампании через агента с набором безопасных инструментов.
- Обрабатывать завершённую сессию: извлекать сводку/пересказ и предложение
  изменений (ChangeSet).
- Проверять и применять ChangeSet только после явного человеческого одобрения.
- Материализовать производное «Состояние кампании» и полнотекстовый индекс.
- Импортировать существующую кампанию (bootstrap) из уже созданного Vault.

## Основные принципы

```text
Obsidian Vault  = единственный источник правды по кампании
Python          = доверенная доменная / прикладная / storage-логика
ToolExecutor    = граница авторизации побочных эффектов
LLM / framework = недоверенный, заменяемый механизм
```

Путь записи всегда проходит через доверенную границу:

```text
agent runtime
  → policy / tool bridge
  → ToolExecutor
  → application / domain / storage
  → VaultRepository
```

- LLM никогда не владеет мутацией Vault или файловой системы.
- Вывод модели недоверенный, пока не проверен Python-кодом.
- Сырые журналы сессий append-only и допускают повторную обработку.
- Изменения от модели после сессии идут как ChangeSet: validate → review → apply.
- Производные индексы, состояние и кэш можно перестроить из Vault.

Подробнее: `docs/development/project-invariants.md` и `docs/adr/`.

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Obsidian (или любая папка, используемая как Vault)
- Для локального инференса: [Ollama](https://ollama.com/) с установленной моделью
- Для DeepSeek: сеть и переменная окружения `DEEPSEEK_API_KEY`
- Поддерживаемые ОС: Windows и macOS. Реальный терминальный smoke-тест TUI на
  macOS пока не подтверждён (см. «Известные ограничения»).

## Установка

Проект распространяется как исходный код; пакет не публикуется в PyPI, готового
бинарника нет. Установка одинакова на Windows и macOS:

```bash
git clone https://github.com/DosMDs/dnd-obsidian-assistant.git
cd dnd-obsidian-assistant
uv sync
```

После синхронизации CLI доступен через `uv run`:

```bash
uv run dnd --help
```

## Настройка моделей

Конфигурация моделей **локальна для машины** и не хранится в Vault. Это обычный
TOML-файл, содержащий таблицы `[profiles.<имя>]`. Например `models.toml`:

```toml
[profiles.agent-deepseek]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
role = "agent"
thinking = true
reasoning_effort = "high"

[profiles.post-session]
provider = "ollama"
model = "<installed-model>"
base_url = "http://localhost:11434"
role = "post_session"

[profiles.bootstrap]
provider = "ollama"
model = "<installed-model>"
base_url = "http://localhost:11434"
role = "bootstrap"
```

Загрузчик читает только секцию `[profiles.*]`; другие верхнеуровневые секции
игнорируются. У профиля обязательны `provider`, `model`, `base_url` и `role`.
Ключ `base_url` должен начинаться с `http://` или `https://`.

### Роли моделей (важно)

Провайдеры различаются по ролям, и один профиль не покрывает все команды:

```text
AGENT        → Ollama или DeepSeek
POST_SESSION → только Ollama
BOOTSTRAP    → только Ollama
```

Поэтому `agent-deepseek` достаточен для `dnd ask` и `dnd tui`, но **не является
полной конфигурацией** для `dnd session process` и `dnd bootstrap ...`: этим
командам нужны профили с ролями `post_session` и `bootstrap` соответственно.
Поддержки DeepSeek для ролей `POST_SESSION` и `BOOTSTRAP` сейчас нет.

Чтобы команда использовала нужный профиль, передавайте конкретное имя профиля
через `--profile`.

### Ollama

```toml
[profiles.agent-ollama]
provider = "ollama"
model = "<installed-model>"
base_url = "http://localhost:11434"
role = "agent"
```

Ollama требует запущенного локального сервера и не требует API-ключа. Убедитесь,
что модель под этим именем установлена (`ollama pull <model>`). Поля `thinking`
и `reasoning_effort` для Ollama-профилей недопустимы.

### DeepSeek

```toml
[profiles.agent-deepseek]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
role = "agent"
thinking = true
reasoning_effort = "high"
```

Учётные данные берутся из переменной окружения `DEEPSEEK_API_KEY` (локально для
машины):

```powershell
# PowerShell
$env:DEEPSEEK_API_KEY = "<your-key>"
```

```bash
# bash / zsh
export DEEPSEEK_API_KEY="<your-key>"
```

Правила, проверяемые схемой профиля:

- `thinking` и `reasoning_effort` допустимы только для `provider="deepseek"` и
  роли `agent`;
- для DeepSeek-агента `thinking` нужно задавать явно; `thinking=true` требует
  `reasoning_effort`, а `thinking=false` его запрещает;
- канонические значения `reasoning_effort`: `low`, `high`, `max`. Значение
  `medium` — совместимостный псевдоним провайдера, а не проектное значение, и
  отклоняется.

Не коммитьте ключ и не храните его в Vault. Ключ читается только в момент
создания транспорта провайдера и возвращается как `SecretStr`; при отсутствии,
пустом или пробельном значении команда завершается ошибкой.

`deepseek / deepseek-flash / thinking=true / reasoning_effort=high` — принятый
эталон квалификации (зафиксирован в `docs/evidence/evals/`), а не обязательный
режим по умолчанию.

## Быстрый старт (новая кампания)

1. Создайте или выберите папку Vault.

2. Инициализируйте структуру:

   ```bash
   uv run dnd init --vault <vault-path>
   ```

   `dnd init` создаёт структурную заготовку и `_system/campaign.yaml`. Vault
   становится пригодным для сессий только после инициализации мирового времени.

3. Инициализируйте мировое время (однократно, без модели). `--world-tick` —
   сырое знаковое целое (минуты от эпохи):

   ```bash
   uv run dnd time init --vault <vault-path> --world-tick 0
   ```

4. Создайте локальный `models.toml` (см. раздел выше). Если выбран DeepSeek,
   задайте `DEEPSEEK_API_KEY`.

5. Запустите TUI или задайте разовый вопрос:

   ```bash
   uv run dnd tui --vault <vault-path> --config models.toml --profile agent-deepseek
   uv run dnd ask "Кто такой Бартоломеу?" --vault <vault-path> --config models.toml --profile agent-deepseek
   ```

   По умолчанию агент работает в режиме только-чтение. Флаг `--allow-write`
   разрешает запись в Vault инструментами модели.

6. Проведите сессию:

   ```bash
   uv run dnd session start --vault <vault-path>
   uv run dnd note "Герои вошли в таверну." --vault <vault-path>
   uv run dnd session end --vault <vault-path> --touched-id <entity-id>
   ```

7. Обработайте завершённую сессию профилем роли `post_session`:

   ```bash
   uv run dnd session process --latest --vault <vault-path> \
     --config models.toml --profile post-session
   ```

   Команда только **создаёт предложение** ChangeSet; она ничего не одобряет и не
   применяет.

8. Проверьте и примените предложение:

   ```bash
   uv run dnd changeset review  <changeset-id> --vault <vault-path>
   uv run dnd changeset approve <changeset-id> --vault <vault-path> --reviewer <your-id>
   uv run dnd changeset apply   <changeset-id> --vault <vault-path>
   ```

### Существующая кампания (bootstrap)

Если у вас уже есть наполненный Vault, используйте bootstrap-процедуру с
профилем роли `bootstrap` (Ollama). Сначала выполните шаги 1–3 выше (`dnd init`,
`dnd time init`). Затем:

```bash
# 1) Маппинг существующих материалов; при необходимости сначала посмотреть:
uv run dnd bootstrap map --vault <vault-path> --config models.toml --profile bootstrap --dry-run

# 2) Финализация: выполняет маппинг, сохраняет предложение и, если оно есть,
#    возвращает статус PENDING_CHANGESET.
uv run dnd bootstrap finalize --vault <vault-path> --config models.toml --profile bootstrap

# 3) Проверка и применение bootstrap-предложения:
uv run dnd bootstrap review  <changeset-id> --vault <vault-path>
uv run dnd bootstrap approve <changeset-id> --vault <vault-path> --reviewer <your-id> [--acknowledge-unresolved]
uv run dnd bootstrap apply   <changeset-id> --vault <vault-path> [--acknowledge-unresolved]

# 4) Повторная финализация: пересобирает «Состояние кампании» и FTS и
#    подтверждает готовность (COMPLETE / COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED).
uv run dnd bootstrap finalize --vault <vault-path> --config models.toml --profile bootstrap
```

`dnd bootstrap finalize` сам по себе не применяет предложенные канонические
изменения сущностей. Канонические данные кампании меняются только при явном
применении проверенного bootstrap-ChangeSet:

```text
dnd bootstrap review → approve → apply
  → явное применение проверенного bootstrap-предложения к каноническим данным
```

Структурные записи инициализации выполняются отдельными командами `dnd init` и
`dnd time init`.

## TUI

Запуск:

```bash
uv run dnd tui --vault <vault-path> --config models.toml --profile <agent-profile> [--allow-write]
```

Интерфейс состоит из шапки, трёх вкладок и нижней панели:

- **Ассистент** — индикатор режима (только чтение / запись), поле ввода запроса,
  кнопки «Отправить» и переключатель записи.
- **Сессия** — статус сессии, поле заметки, поле затронутых ID, кнопки
  «Обновить», «Начать», «Заметка», «Завершить».
- **Состояние кампании** — содержимое, кнопки «Обновить» и «Перестроить».

Горячие клавиши (текущий реестр команд):

```text
ctrl+q   выход
ctrl+p   палитра команд
? / f1   справка (открыть/скрыть)
f2/f3/f4 вкладки: Ассистент / Сессия / Состояние кампании
f5       отправить запрос (только вкладка «Ассистент»)
```

В поле ассистента `Enter` вставляет перенос строки и не отправляет запрос;
отправка — это кнопка, палитра команд или `f5`. `f5` — удобный псевдоним, а не
гарантия переносимости между терминалами: надёжные способы отправки — кнопка и
палитра команд. `--allow-write` задаёт потолок записи на запуск; переключатель
записи в панели ассистента доступен только когда этот потолок разрешает запись.

## Рабочие сценарии CLI

```text
dnd init --vault PATH
dnd note TEXT --vault PATH
dnd ask QUERY --vault PATH --config PATH --profile NAME [--allow-write]
dnd tui --vault PATH --config PATH --profile NAME [--allow-write]

dnd time init --vault PATH --world-tick INT

dnd session start   --vault PATH
dnd session status  --vault PATH
dnd session end     --vault PATH [--touched-id ID ...]
dnd session process [SESSION_ID] --vault PATH --config PATH --profile NAME [--latest]
dnd session outputs SESSION_ID --vault PATH

dnd changeset save   FILE --vault PATH
dnd changeset review CHANGESET_ID --vault PATH
dnd changeset approve CHANGESET_ID --vault PATH --reviewer ID [--reason TEXT]
dnd changeset reject  CHANGESET_ID --vault PATH --reviewer ID [--reason TEXT]
dnd changeset apply   CHANGESET_ID --vault PATH
dnd changeset status  CHANGESET_ID --vault PATH

dnd bootstrap map      --vault PATH --config PATH --profile NAME [--dry-run]
dnd bootstrap finalize --vault PATH --config PATH --profile NAME [--acknowledge-unresolved]
dnd bootstrap review   CHANGESET_ID --vault PATH
dnd bootstrap approve  CHANGESET_ID --vault PATH --reviewer ID [--reason TEXT] [--acknowledge-unresolved]
dnd bootstrap reject   CHANGESET_ID --vault PATH --reviewer ID [--reason TEXT]
dnd bootstrap apply    CHANGESET_ID --vault PATH [--acknowledge-unresolved]

dnd index rebuild --vault PATH

dnd eval run    [--runtime scripted|ollama|deepseek] [--dataset product-v1] \
                --output FILE [--overwrite] [--config PATH --profile NAME] [--trace FILE]
dnd eval report --input FILE [--baseline FILE]
```

Примечания:

- `dnd session process` требует ровно одно из: `SESSION_ID` или `--latest`.
- `dnd changeset apply` отказывается применять bootstrap-предложения и направляет
  к `dnd bootstrap apply`.
- `dnd index rebuild` пересобирает только производный FTS-индекс.
- `dnd changeset status` и `dnd session outputs` — только чтение.

## Жизненный цикл сессии

```text
dnd session start
  → события заметок и игровые события (dnd note, инструменты)
  → dnd session end [--touched-id ...]
  → сырые журналы сохранены (append-only)
  → dnd session process --profile <post_session>
      → ChangeSet (предложение) ИЛИ «без изменений»
      → сводка / пересказ / рабочие доказательства
  → dnd changeset review / approve / apply
  → следующая сессия
```

Обработка сессии не одобряет и не применяет изменения. Повторный запуск уже
завершённой попытки распознаётся как идемпотентный и не вызывает модель заново.
Сырые журналы остаются неизменяемыми свидетельствами и допускают повторную
обработку новой попыткой.

## Данные и модель Vault

`dnd init` создаёт управляемую структуру внутри Vault:

```text
Sessions/
_system/
_system/raw/
_system/raw/sessions/
_system/audit/
Characters/NPCs/
Locations/
Quests/
Items/
_system/campaign.yaml
```

Классификация данных:

```text
Канонические данные кампании (Source of Truth):
    Characters/NPCs/…, Locations/…, Quests/…, Items/…   (Markdown-сущности)
    _system/campaign.yaml                                 (маркер инициализации)
    _system/world_time.json                               (текущее игровое время)
    Sessions/<id>/                                        (материалы сессии)

Неизменяемые / append-only свидетельства:
    _system/raw/sessions/<id>/metadata.json
    _system/raw/sessions/<id>/events.jsonl
    _system/audit/audit.jsonl

Состояние workflow / ревью:
    _system/changesets/<id>.proposal.json / .approval.json / .apply.jsonl
    _system/bootstrap/<id>.mapping.json

Производные / перестраиваемые проекции и индексы:
    State/World State.md, State/Recently Touched.md, State/.campaign-state-manifest.json
    _system/indexes/entities.sqlite3   (FTS-индекс)
```

**Source of Truth — только Vault и канонические данные кампании.** Перестраиваемые
проекции — это «Состояние кампании» (Campaign State) и FTS/SQLite-индекс: их
можно пересобрать из канонических данных, и они не являются источником правды.
Сырые журналы сессий и свидетельства ChangeSet (предложение, одобрение, попытки
применения) — это **не** одноразовый кэш: их нельзя считать производным мусором.
SQLite-индекс и производные артефакты никогда не должны рассматриваться как
канонические.

Перестроить FTS-индекс:

```bash
uv run dnd index rebuild --vault <vault-path>
```

Материализация «Состояния кампании» перестраивается в TUI (кнопка «Перестроить»)
и в ходе `dnd bootstrap finalize`.

## Безопасность и модель ревью

- `ToolExecutor` — финальная граница авторизации побочных эффектов.
- WRITE-инструмент не авторизуется только потому, что модель его запросила.
- Неоднозначное разрешение сущности должно уточняться, а не угадываться.
- Изменения от модели после сессии проходят через ChangeSet: проверка человеком и
  явное применение; команда обработки сессии никогда не применяет их сама.
- Сырые журналы сессий append-only.
- Учётные данные провайдера хранятся локально на машине и не попадают в Vault,
  отчёты или ошибки.
- Скрытое «рассуждение» модели является только транспортным состоянием и не
  сохраняется, не отображается и не попадает в сводки/пересказы.

## Тестирование

```bash
# канонический офлайн-набор
uv run pytest

# проверка типов (обязательно 0 ошибок)
uv run pyright

# линт и проверка формата
uv run ruff check .
uv run ruff format --check .
```

Опциональные live-проверки провайдеров выполняются только явно. Указанные ниже
команды — это лишь **выбор тестов pytest**, а не достаточная активация live-
режима: сначала нужно задать требуемую machine-local конфигурацию и явный opt-in.
Без явного селектора/конфигурации live-тесты могут быть `SKIP`, а не реально
обратиться к провайдеру. Порядок и детали: `docs/development/provider-runtime-upgrade.md`.

```bash
# офлайн-выборка provider_upgrade (без live-провайдеров)
uv run pytest -m "provider_upgrade and not ollama and not deepseek"

# live Ollama (требует настроенного локального сервера/профиля)
uv run pytest -m "provider_upgrade and ollama"

# live DeepSeek (требует явного opt-in; сам селектор не активирует live-режим)
uv run pytest -m "provider_upgrade and deepseek"
```

Для DeepSeek перед запуском задайте machine-local окружение:

```text
DND_ASSISTANT_DEEPSEEK_LIVE=1
DND_ASSISTANT_DEEPSEEK_CONFIG=<path-to-models.toml>
DND_ASSISTANT_DEEPSEEK_AGENT_PROFILE=<profile-name>
DEEPSEEK_API_KEY=<secret>
```

Используйте собственный ключ; никогда не коммитьте его. Обычный `uv run pytest`
не зависит от сети и секретов.

## Live-оценка и канонический baseline

Eval-набор запускается либо офлайн со scripted-моделью, либо через явный live-путь:

```bash
# офлайн scripted
uv run dnd eval run --runtime scripted --dataset product-v1 --output <report.json>

# live Ollama или DeepSeek (AGENT-профиль)
uv run dnd eval run --runtime ollama   --dataset product-v1 --config models.toml --profile agent-ollama   --output <report.json>
uv run dnd eval run --runtime deepseek --dataset product-v1 --config models.toml --profile agent-deepseek --output <report.json>

# просмотр сохранённого отчёта (и сравнение с baseline)
uv run dnd eval report --input <report.json> [--baseline <baseline.json>]
```

Различайте три вещи:

- обычные офлайн-тесты;
- opt-in live-тесты провайдеров;
- **потреблённые и замороженные свидетельства квалификации** (например, принятый
  эталон `deepseek-flash`), которые уже измерены и **не должны запускаться
  повторно**.

Принятый канонический AGENT-baseline — `deepseek` / `deepseek-flash` / `agent` /
`thinking=true` / `reasoning_effort=high`, заморожен в
`docs/evidence/evals/rm-05-product-v1-deepseek-flash-high-candidate.json`. Это
эталон квалификации, а не режим по умолчанию и не то, что следует перезапускать.
DeepSeek structured-output поведение не квалифицировано; поддержка DeepSeek
ограничена ролью `agent`.

## Известные ограничения

- Реальный терминальный smoke-тест TUI на macOS пока не подтверждён
  (`SKIPPED_CAPABILITY`), хотя Windows Terminal проверен вручную.
- `f5` — удобный псевдоним отправки, а не гарантия переносимости; надёжные
  способы — кнопка и палитра команд.
- TUI не может предотвратить принудительное завершение процесса/терминала или
  выключение машины; защищены только штатные пути завершения.
- Маршрутизация удалённого DeepSeek может измениться на стороне провайдера;
  запись `documented_route` в эталоне — свидетельство на момент квалификации.
- Structured-output поведение DeepSeek не квалифицировано; текущая поддержка
  DeepSeek — только роль `agent`.
- Роли `POST_SESSION` и `BOOTSTRAP` в продакшене работают только через Ollama.

## Документация

| Тема | Файл |
|---|---|
| Текущий статус roadmap | `DEVELOPMENT_STATUS.md` |
| Инварианты проекта | `docs/development/project-invariants.md` |
| Обновление провайдера/runtime | `docs/development/provider-runtime-upgrade.md` |
| Квалификация DeepSeek | `docs/development/deepseek-provider-qualification.md` |
| Принятый live-baseline | `docs/milestones/V0_5_ACCEPTED_LIVE_MODEL_BASELINE.md` |
| Архитектура удалённого провайдера | `docs/adr/0010-remote-deepseek-provider-architecture.md` |
| Область релиза MVP | `docs/adr/0009-release-scope-defers-live-model-qualification.md` |
| Архитектура Textual TUI | `docs/adr/0008-textual-tui-presentation-architecture.md` |
| Трек TUI | `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` |
| Bootstrap (init vs bootstrap) | `docs/stages/13_BOOTSTRAP.md` |
| Evals / hardening | `docs/stages/14_EVALS_AND_HARDENING.md` |
| Состояние кампании | `docs/adr/0007-campaign-state-materialized-derived-projection.md` |
| Терминальный smoke-протокол TUI | `docs/development/tui-terminal-smoke.md` |
| ADR | `docs/adr/` |

## Разработка

Проект разрабатывается с учётом инвариантов из `AGENTS.md` и политик в
`docs/development/`. Перед изменением кода прочитайте `DEVELOPMENT_STATUS.md` и
соответствующие ADR.

Дисциплина качества:

- `uv run pyright` — канонический общепроектный тип-гейт (0 ошибок);
- `uv run pytest` — поведенческое свидетельство;
- `uv run ruff check .` и `uv run ruff format --check .` — линт и формат;
- тесты запускаются focused-first, полный набор — финальный интеграционный гейт.

Конфигурация инструментов разработки opencode: `docs/development/opencode-setup.md`.
