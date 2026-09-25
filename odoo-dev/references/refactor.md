# Code Quality Review and Behavior-Preserving Refactor — Odoo 20

Load for: "make my code better / shorter / organized / easier to read", "check the code
quality of module X", "optimize without changing logic". Not for bug fixes (`fix`) or new
features. Built from the rs_einvoice + rs_base_methods refactor (2026-09-23, 4 phases,
commits `6e777ba` `89ca0cb` `358c5ec` in `custom_addons/gec_odoo_modules`).

---

## 1. Say the uncomfortable number first

"Much shorter" is rarely true for a working integration module. Measure before promising:

```bash
python .claude/skills/odoo-dev/scripts/code_inventory.py snapshot <module_dir> -o /tmp/before.json
```

| rs_einvoice / rs_base_methods | Before | After 4 phases |
|---|---|---|
| Python lines | 8,577 / 2,655 | 8,385 / 2,495 (−2% / −6%) |
| Translatable texts | 332 / 99 | 331 / 98 (the 2 removed belonged to deleted code: a dead wrapper, a duplicate reader) |
| rs.ge requests | — | byte-identical (recorded old vs new) |

Most of such a module is user messages, docstrings and guard branches; they only shrink by
rewording, which loses translations. The honest gain is readability: named steps instead of
a 250-line method, one helper instead of 6 copies, files that hold one concern. Tell the
user that up front, with the measured numbers.

## 2. A review doc is a bug list, not a refactor plan

`CODE_REVIEW.md`-style findings are mostly behavior changes (wrong company check, missing
validation, rounding). Putting them into a "no behavior change" refactor makes the diff
impossible to review. Sort every finding before planning:

| Kind | Goes into |
|---|---|
| Dead code, duplication, magic tuples, file layout, long methods | this refactor |
| Anything a user, the GL or the external system would notice | a separate fix, after the refactor |

For rs_einvoice the refactor closed 9 of 26 review items (all from the cleanup section) and
0 of the 65-item fix plan; the rest are behavior changes and wait for their own fixes.

Review output format: findings ranked by severity, each with a confidence tag, `file:line`,
kind (bug / risk / duplication / readability / dead code / convention), and **behavior change:
yes/no**. Bugs found while refactoring are listed, not fixed.

## 3. The contract (put it in the plan; each line is a promise to the user)

| Promise | Why | Proof |
|---|---|---|
| External calls identical | the integration is already certified in production | `oldnew.Recorder`, old vs new |
| User texts identical | translations are looked up by (module, exact text) | `code_inventory.py compare`: 0 removed/added |
| Public names kept | overrides in other modules, XML buttons, cron `code` in the DB, JS, RPC | `dependencies.md` sweep + `dead_names.py` |
| Transactions untouched | commits, savepoints and lock order are the durability design | diff review: no `commit`/savepoint/lock moved |
| No bug fixes mixed in | the diff must read as "no change" | bugs listed separately |
| Plan first, each phase approved | the user decides scope | plan table (section 7) |
| One commit per phase, the user commits | bisectable, easy to revert | report ends with the commit hint |

## 4. Phases — in this order, each its own commit

| # | Phase | Typical content | Proof |
|---|---|---|---|
| 0 | Safety net (ask) | tests for the flows touched; the user may skip | test run |
| 1 | Dead code + duplication inside files | unused methods, twin helpers merged (`*keys`), `Command` for tuples, repeated dicts → helper | `dead_names.py`, `oldnew` for merged helpers |
| 2 | Files — moves only | split a 1,000+ line file by concern (`models/`, `wizard/`, cron, service), rename files to what they hold | `code_inventory.py compare`: removed/added/changed 0, only "moved" |
| 3 | Inside methods | long method → outline + named steps cut verbatim; N single-field assignments → one `write()`; repeated pattern → helper | `split_check.py`, `oldnew` |
| 4 | Across modules | a dependent module re-implementing its dependency → call the dependency | `oldnew` on the normal and the failure path |

After every phase: `pyflakes`, `odoo_import_check.py --compare`, and `-u <module>` on a test
database when one exists (ask; never probe a production copy).

## 5. Hidden behavior changes — the traps

Each row happened or nearly happened on rs_einvoice. They look like pure cleanup.

| Refactor move | What silently changes | Do instead |
|---|---|---|
| Reword or fix a typo in a `_()` text | translation lost, ka_GE users see English (`translate.py:2599` keys by source text) | keep the text; or change it and the `.po` in the same commit |
| Move `_()` into a module-level function | `_()` guesses the language from the caller frame's `context`/`kwargs`/`self.env` (`translate.py:1084`); without them it falls back to a guess | pass `env`, call `env._()` |
| Move code with `_()` to another addon | lookup uses the calling file's addon `.po` (`translate.py:1021`, `environments.py:373`) | the text must exist in that addon's `.po` |
| Move `%` formatting out of `_()` or reorder placeholders | the msgstr keeps its own placeholders | check the placeholders in the `.po` |
| `_(...)` → `self.env._(...)` | `Environment._(self, source, *args, **kwargs)` has a plain `source` parameter (`environments.py:344`), the old `_` a positional-only one (`translate.py:1135`): a `source=` or `self=` placeholder keyword now raises `TypeError: got multiple values for argument 'source'`, and a text-inventory compare shows no difference (geo_payroll 2026-09-24: 91 tests broke on one call) | scan converted calls for `source=`/`self=` keywords and rename those placeholders; re-align continuation lines (the opening is 9 characters longer) |
| Raw `SELECT ... FOR UPDATE NOWAIT` → `lock_for_update()` | v20 uses SKIP LOCKED and raises `LockError("Cannot grab a lock on records")` (`models.py:5056-5081`) | `except LockError: raise UserError(<old text>)` |
| `UserError` → `ValidationError` in a constraint | dialog title "Invalid Operation" → "Validation Error" (`error_dialogs.js:36-37`); `except UserError` still catches it (`exceptions.py:99`) | fine to do; state it as the one visible change |
| N `self.f = v` lines → one `write({...})` | each assignment was its own `write()`: overrides and constraints ran N times on partial states (`models.py:3957`) | sweep `write()` overrides; check no line in between reads a value just set |
| Shared helper that raises replaces a local one returning `[]` on error | callers that treated `[]` as "nothing there" now get an exception | check every caller catches it; list it as an intended difference |
| Rename a method | overrides in other modules silently stop running; XML buttons and DB-stored cron code fail at run time | keep the name |
| Delete an "unused" method | still called from `ir.cron`/server-action code in the DB, JS, or RPC | `dead_names.py` + its printed `SELECT` |
| Method → `@staticmethod` / module function | overrides calling `super()` break | sweep overrides first |
| Python filter → domain | `('f', 'not in', vals)` also matches NULL (`fields.py:1474`) | compare with the empty-value case |
| Field removed from a view | an onchange writing it is no longer saved (`web/models/models.py:2203` returns only `fields_spec`) | keep the field (invisible) |
| `Markup` body → plain `str` in `message_post` | a plain str is escaped, tags show as text (`mail_thread.py:2399`) | keep `Markup` |
| Params dict → another dict order | SOAP/XML element order changes; ASMX services can be order-sensitive | keep ordered `(name, value)` pairs |
| `bool(result)` → a stricter success helper | a reply the old code accepted is now a failure | keep per-call semantics; unify only identical checks |
| `self.env.user.company_id` → `self.env.company` | a real bug fix, visible to multi-company users | separate fix commit |

## 6. Smells worth fixing — with a grep to find them

| Smell | Find it | Fix |
|---|---|---|
| Same 5+ lines in several places | grep one distinctive line | one helper, same name style as core |
| Same dict built in N methods (credentials, headers) | `grep -n "'user_id':" models/*.py` | helper returning the dict, `**auth` at call sites |
| Two helpers doing nearly the same | similar names (`_row_value`, `_row_lookup`) | one helper with `*keys` |
| 150+ line method with `# 1.`, `# 2.` comments | `code_inventory.py long <module_dir>` | outline + named steps, blocks cut verbatim |
| Consecutive single-field assignments | `grep -n "^        self\.[a-z_]* = "` | one `write({...})` (trap table first) |
| `(0, 0, vals)` `(6, 0, ids)` `(5, 0, 0)` | `grep -nE "\((0|5|6), 0, "` | `Command.create/set/clear` |
| Hand-written row lock SQL | `grep -n "FOR UPDATE"` | `lock_for_update()` (trap table) |
| `search()` inside a loop | read loops over records | one search with `in` + dict |
| Same tuple literal in several methods | grep the literal | module constant |
| try/except around a stable core API "just in case" | `grep -n "except Exception"` | remove; keep excepts at real boundaries |
| A file mixing models, wizards, cron and service code | file size + class list | split by concern (phase 2) |
| A module re-implementing its dependency's service call | same remote operation name in both | call the dependency's method |
| Methods nobody calls | `dead_names.py` | delete after the DB check |
| `raise UserError` inside `@api.constrains` | `grep -n -A15 "@api.constrains" models/*.py \| grep "raise UserError"` | `ValidationError` (visible, see traps) |

## 7. Plan format — show this before touching code

Per phase, one table and a "not doing" list:

```
Phase 3 — inside methods (account_move_sync.py, account_move.py)
| Change | Where | Lines | Why easier to read | Risk / proof |
| action_rs_refresh_status → outline + 7 named steps | account_move_sync.py:19 | 250 → 24, steps 11-55 each | reads as a list of what happens | split_check: only the 11 intended lines differ |
| 5 header field assignments → one write() | _rs_refresh_header | 7 statements → 3 | one place for the header | the only custom account.move write() (rs_einvoice's guard) ignores these fields |
Not doing: company guard (bug, behavior change), accept-total check (new validation).
```

## 8. Report after each phase

- Table of what changed, lines per file before → after
- One line per proof run, with the script output
- Intended differences, stated plainly (e.g. "network failure now raises instead of returning []; both callers catch it")
- Deploy: Python-only → restart the server; manifest, XML or security changed → also `-u <module>`
- Commit hint for the user: `git add -A <module>`, so moves are recorded as renames. A file
  split in two keeps its history on one side only (git picked
  `rs_buyer_inbox_wizard.py => rs_einvoice_cron.py (51%)`); preview before committing:
  ```bash
  T=$(mktemp) && cp .git/index "$T" && GIT_INDEX_FILE="$T" git add -A <module> && GIT_INDEX_FILE="$T" git diff --cached -M --summary HEAD -- <module>; rm -f "$T"
  ```
- Review docs: delete the items that are fixed (do not mark them), leave the rest untouched

## 9. Proof toolkit — `.claude/skills/odoo-dev/scripts/`

| Script | Proves | Run with |
|---|---|---|
| `code_inventory.py snapshot/compare` | same code however files moved; texts unchanged; newly untranslated texts per `.po` | any python3; `--rev` reads a git revision |
| `code_inventory.py long` | the longest functions, where a split helps most | any python3 |
| `odoo_import_check.py` | addons import inside Odoo, same models/methods/fields as before | `data_venv/bin/python`, no DB |
| `dead_names.py` | methods nothing references (py/xml/js/csv) + SQL for DB-stored code | any python3, 4-8 s over addons+enterprise |
| `split_check.py` | a split method kept every statement; prints only the edited ones | any python3 |
| `oldnew.py` | old vs new side by side: `load_old(rev=)`, `fake_record`, `outcome`, `Recorder` | `data_venv/bin/python`, no DB |
| `pyflakes` | unused imports/names | `/opt/anaconda3/bin/pyflakes` (not in data_venv) |

Snapshot before each phase (the previous phase's commit is enough when the user commits
per phase). Scripts written for one check (a SOAP recorder table, a write() guard matrix)
go in the scratchpad, not in the module.
