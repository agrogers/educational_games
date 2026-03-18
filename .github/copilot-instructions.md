## Copilot Instructions for `educational_games` (Odoo 18)

This repository is a custom **Odoo Community 18** addon for educational mini-games and quizzes integrated with APEX/SIS workflows.

Use **Odoo 18 syntax and behaviors only**.

### What this module is about

- Provides teacher-facing and student-facing game/quiz experiences.
- Includes backend quiz administration and frontend OWL/client-action gameplay.
- Stores game content and quiz results in Odoo models.
- Integrates with `aps_sis` (menu and workflow dependencies).

### Fast file map

- `__manifest__.py`: module metadata, dependencies (`base`, `web`, `aps_sis`), data files, and backend assets.
- `models/quiz.py`: core quiz domain logic, parsing/import helpers, token signing, and quiz actions.
- `models/game_data.py`: game content storage and AI-assisted sentence generation.
- `models/game_result.py`: score persistence.
- `controllers/main.py`: routes such as `/educational_games/dashboard`.
- `views/quiz_actions.xml`: window/client actions for quiz admin and quiz game.
- `views/quiz_views.xml`: list/form UI for `quiz.quiz` and nested questions/answers.
- `views/educational_games_menu.xml`: menus under APEX teacher root.
- `static/src/js/`: frontend game clients (Lonely S, quiz game, binary conversions, wrapper).
- `static/src/js/utils/aps_submission.js`: shared submission utility used by game JS files.

### Odoo 18 coding rules

- XML list views: use `<list>`, never `<tree>`.
- Avoid `attrs` and `states`; use direct boolean expressions (e.g. `invisible="condition"`).
- Prefer explicit `ir.actions.act_window.view` bindings when an action must open specific list/form views.
- Use `display_name` behavior for record naming (do not introduce deprecated `name_get`).
- Keep ORM logic in models; avoid raw SQL unless strictly necessary.

### Frontend and assets

- Use ES modules and OWL-compatible patterns only.
- Do not add legacy patterns (`odoo.define`, `require`, legacy widget extension APIs).
- When adding JS/XML assets, register them in `__manifest__.py` under `web.assets_backend` in dependency order.
- If one JS module imports another, keep imported utility files listed earlier in asset order.

### Common tasks and where to edit

- Add a new quiz field: `models/quiz.py` + `views/quiz_views.xml` (+ search/list view if relevant).
- Add a new game action/menu: `views/actions.xml` and `views/educational_games_menu.xml`.
- Add a new playable JS game: `static/src/js/...` plus corresponding action XML and manifest asset entry.
- Add access rights: `security/ir.model.access.csv`.
- Add dashboard route/template behavior: `controllers/main.py` and related templates/assets.

### Validation checklist after changes

- Upgrade module with Odoo CLI: `-u educational_games`.
- Verify no deprecated XML syntax (`<tree>`, `attrs`, `states`) was introduced.
- Confirm all referenced external IDs exist and load order is valid.
- Confirm client action tags match JS registrations.
- Verify teacher menu visibility still respects `aps_sis.group_aps_teacher` where expected.