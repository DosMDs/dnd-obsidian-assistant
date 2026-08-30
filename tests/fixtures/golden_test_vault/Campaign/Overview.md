# Тени над Серым Бродом

Небольшая тестовая кампания для regression/integration/e2e сценариев D&D Session Assistant.

## Завязка

Караван из Серого Брода исчез на северной дороге. Расследование вывело партию
на руины старой заставы, серебряный ключ, знак Чёрного Солнца и противоречивые
сведения о магистре Варосе.

## Назначение fixture

Данные намеренно содержат:
- стабильные ID, не связанные с filename;
- alias-коллизии и fuzzy-похожие имена;
- confirmed/reported/rumor/inferred/unknown знания;
- player и dm visibility;
- extra YAML frontmatter с provenance;
- разные revision;
- wikilinks и пользовательский Markdown body;
- активные/закрытые квесты;
- exact/approximate/range/unknown timeline events;
- пять завершённых сессий и append-only raw JSONL.
