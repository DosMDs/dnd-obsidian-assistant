---
schema_version: 1
type: campaign_state
current_location: loc_grayford
active_quests:
- quest_missing_caravan
- quest_silver_key
party_goals:
- Найти пропавший караван
- Выяснить назначение серебряного ключа
- Проверить противоречия в словах магистра Вароса
important_npcs:
- npc_varos
- npc_elira_voss
- npc_rolan
upcoming_deadlines:
- event_magistrate_meeting
- event_ship_departure
- event_ransom_deadline
unresolved_threads:
- Кто стоит за знаком Чёрного Солнца
- Что находится в Затопленной крипте
- Почему Варос требует найденный амулет
revision: 1
---
# World State

Derived compact campaign state for fixture consumers.

Подробные факты остаются в canonical entity/event records; этот файл хранит
только ссылки и краткие актуальные цели.
