# Declarations (`gec_declarations`) — Developer guide

For developers who change this module. User steps are in [README.md](README.md).

## Purpose and facts

A hub app: an overview of `gec.declaration.card` records and a menu tree that the declaration modules' menus
are moved into. It never imports, inherits or depends on the declaration modules: it reaches them only through
xmlids and model names looked up at run time, so any subset of them can be installed.

| | |
|---|---|
| Depends | `account`: accounting groups, the Settings action and the menus the declarations come back to |
| New models | `gec.declaration.card` |
| Extended models | none |
| Hooks | `post_init_hook` and `_register_hook` move the menus in; `uninstall_hook` moves them back |
| Crons, controllers | none |

Data files, in manifest order:
1. `security/ir.access.csv`.
2. `data/gec_declaration_card_data.xml`: the four cards (not `noupdate`, so updating this module resets
   their texts and order).
3. `views/gec_declaration_card_views.xml`: the kanban, the list, the actions and the menus.

## File map

| File | Holds |
|---|---|
| `__init__.py`, `models/__init__.py`, `tests/__init__.py` | Imports |
| `__manifest__.py` | Manifest, hooks |
| `hooks.py` | `post_init_hook`, `uninstall_hook` |
| `models/gec_declaration_card.py` | `MENU_MOVES`, `gec.declaration.card`, `_gec_place_menus`, `_register_hook` |
| `data/gec_declaration_card_data.xml` | Cards: VAT, Form 30, Profit Tax, Property Tax |
| `views/gec_declaration_card_views.xml` | Kanban, list, actions, menu tree |
| `security/ir.access.csv` | Access rows |
| `static/description/icon.png` | App icon |
| `i18n/ka_GE.po` | Georgian translation |
| `tests/test_declarations.py` | Tests |

## Moving the menus

`MENU_MOVES` lists each menu as (menu xmlid, parent here, sequence here, parent in Accounting, sequence
there). The "in Accounting" pair repeats what the declaration module's own XML sets.

1. `_gec_place_menus(restore=False)` writes `parent_id` and `sequence` on each menu that exists, skipping
   missing modules. Writes happen only when a value differs.
2. `post_init_hook` runs it once on install.
3. `_register_hook` runs it after every registry load while the module is `installed`. Updating a declaration
   module reloads its XML, which puts the menu back under Accounting; the hook moves it here again.
4. `uninstall_hook` runs it with `restore=True`. This is required: `ir.ui.menu.parent_id` is
   `ondelete="restrict"`, so this module's menus could not be deleted while they still have children.

## The cards

- `_model()` returns the declaration model when it is in the registry and `has_access('read')`, else `None`.
- `_compute_stats` reads, per card: the first record in the model's own order (`date_from desc` in all four),
  the label of its `state`, the number of `state = 'draft'` records, and for monthly cards the next 15th.
- `available` is searchable (`_search_available`); the overview action filters on it.
- `action_open` returns the declaration module's own window action via `_for_xml_id`. `action_new` and
  `action_open_drafts` are that action with a form view or a draft domain.

The stats assume each declaration model has `state` with a `draft` value and an order that puts the latest
first. A new card for a model without these needs its own branch in `_compute_stats`.

## Security

| Model | Group | Rights |
|---|---|---|
| `gec.declaration.card` | Accounting read-only, Billing | read |
| `gec.declaration.card` | Accounting administrator | all |

`_gec_place_menus` writes menus with `sudo()`: it runs from hooks and the registry load, and touches only the
menus in `MENU_MOVES`. Record rules of the declaration models still apply to the counts.

## Tests

```bash
odoo-bin -d <db> -u gec_declarations --test-enable --test-tags /gec_declarations --stop-after-init --http-port=8099
```

`tests/test_declarations.py` covers:
- moving the menus here, putting them back with `restore=True`, and moving them here again;
- a card is available only when its model exists;
- counts and actions of an available card.

## Extending safely

- **A new declaration:** add a card record and a `MENU_MOVES` row. Copy the "in Accounting" parent and
  sequence from that module's XML, or uninstalling this module would put the menu somewhere else.
- **No dependencies on declaration modules, ever:** the app must install with any subset of them.
- **Never change a declaration module from here** beyond the parent and sequence of its menus.

## Known limitations

- A menu a declaration module adds later lands in Accounting until it is added to `MENU_MOVES`.
- If a declaration module changes a menu's parent or sequence in its XML, `MENU_MOVES` must follow, or an
  uninstall restores the old place.
