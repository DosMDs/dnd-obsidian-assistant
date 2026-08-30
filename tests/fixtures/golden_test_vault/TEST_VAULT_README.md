# Golden Test Vault

Постоянный regression fixture для D&D Session Assistant.

## Scale

- 10 NPC
- 5 locations
- 3 quests
- 5 items
- 5 completed sessions
- 20 timeline events
- 20 raw session events
- 1 compact CampaignState snapshot

## Deliberate test cases

1. `npc_varos` и `npc_varos_junior` оба имеют alias `Варос` — exact alias ambiguity.
2. `npc_ender` и `npc_endrin` — fuzzy-name ambiguity.
3. `npc_archivist_kell` и `event_020` имеют `visibility: dm`.
4. Knowledge status покрывает confirmed/reported/rumor/inferred/unknown.
5. Extra frontmatter покрывает aliases, source_type/source_ref, priority,
   current_location и deadline_event.
6. Revisions различаются между сущностями.
7. Markdown body содержит wikilinks и должен переживать repository mutations.
8. Timeline покрывает exact/approximate/range/unknown temporal certainty.
9. Raw `events.jsonl` — append-only fixture; `conversation.jsonl` оставлен пустым,
   потому что его schema в текущих project sources ещё не определена.
10. `_system/indexes`, cache и другие derived directories не содержат канонических данных.

## Current-stage compatibility

Текущий Stage 3 `VaultRepository` должен сканировать только:
- Characters/NPCs
- Locations
- Quests
- Items

Sessions, Events и State заложены для следующих stages и не должны случайно
восприниматься как MVP Entity files текущим repository discovery.

## Suggested repository location

`tests/fixtures/golden_vault/`
