---
applyTo: "**"
---

# educational_games: quick navigation and coding intent

This addon targets **Odoo 18 Community Edition** and delivers classroom mini-games plus a quiz builder/player.

## Primary models

- `quiz.quiz` in `models/quiz.py`: quiz configuration, question import/parsing, tokenized game URL params, preview actions.
- `game.data` in `models/game_data.py`: game sentence pools and AI sentence generation workflows.
- `game.result` in `models/game_result.py`: stores student game scores and raw logs.

## Primary UI and actions

- Quiz admin list/form: `views/quiz_views.xml`
- Quiz actions (`act_window` + `client action`): `views/quiz_actions.xml`
- Game actions: `views/actions.xml`
- Menus under APEX teacher root: `views/educational_games_menu.xml`

## Frontend entry points

- Shared submission helper: `static/src/js/utils/aps_submission.js`
- Quiz player: `static/src/js/quiz/quiz_game.js`
- Lonely S game: `static/src/js/lonely_s/lonely_s_game.js`
- Binary conversions: `static/src/js/binary_conversions/binary_conversions.js`
- Generic wrapper: `static/src/js/html_game_wrapper.js`

## Odoo 18 requirements for generated code

- Use `<list>` (not `<tree>`) in XML views.
- Do not introduce `attrs` or `states`; use direct expression attributes.
- Keep action/view wiring explicit and valid for Odoo 18 (`ir.actions.act_window.view` for fixed view binding).
- Do not add deprecated model naming patterns (use `display_name` behavior; avoid `name_get`).

## Change routing hints

- "Add new quiz setting": edit `quiz.quiz` fields + quiz form/list views.
- "Add new game": create JS under `static/src/js/...`, define `ir.actions.client`, add menu item, register assets in manifest.
- "Add permissions": edit `security/ir.model.access.csv` and any relevant record rules.
- "Broken game load": verify action tag in XML matches JS action registration and that asset order is correct in `__manifest__.py`.
