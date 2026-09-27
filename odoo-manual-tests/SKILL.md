---
name: odoo-manual-tests
description: >
  Build a plain-language manual test checklist (xlsx) for an Odoo 20 module that someone who has
  never used Odoo can follow: numbered test cases sized to the module (about 35 for a big one),
  each with one Pass/Fail, one-line steps "Do this / Look here / You should see", exact button,
  menu and message names taken from the module's code and the live database, starting points,
  fixed test data, and green safety cases where Odoo must refuse a dangerous action. Use this
  whenever the user asks for manual test cases, test scenarios, a test plan, a QA or UAT
  checklist, "what should I check manually", a user guide with test cases, or wants to hand a
  module to a tester — for any module in custom_addons (rs_einvoice, rs_waybill, basis_bank,
  geo_payroll, employee_registry_rs, gec_localization …) or a core app. Not for automated
  Python/unit tests (use odoo-dev).
---

# Odoo manual test checklist

Turns a module into an xlsx a newcomer can test with: they get the file and an Odoo address, and
every row tells them what to click, where to look and what they must see. The format was settled
with the user on rs_einvoice (four rounds, 2026-09-25/26); `references/format-rules.md` records
each rule and the complaint behind it.

## Workflow

1. **Scope.** Module path, database (default `gec20_prod1`, PostgreSQL port 5433), UI language
   (English unless the user asks for Georgian), external systems (rs.ge, a bank) and which test
   users exist there. Ask only what the code and database cannot tell you.

2. **Research** — follow `references/research.md`. In short: read `documentations/<module>.md`
   and any `CODE_REVIEW.md`, then run
   ```bash
   python3 .claude/skills/odoo-manual-tests/scripts/module_inventory.py <module_dir> --db gec20_prod1 --full
   ```
   and read the action methods behind the main buttons. Build the state machine (which button is
   visible in which state, where it leads). If the module has no doc, the project rule in
   `CLAUDE.md` asks for one — write it with odoo-dev's doc template after the checklist.

3. **Size and pick the cases.** Use the inventory's suggested range (about 1.1 cases per
   user-facing action, a quarter of them safety cases). Flows first (the normal day, then every
   change / cancel / correction path, then the incoming side, then options that change what is
   sent), then safety cases that protect money, tax filings, external links and live records.
   Leave out anything that leaves records stuck or touches real money; warn about it in "Never".

4. **Write the spec** in the session scratchpad, copying the structure of
   `assets/example_rs_einvoice.json`: test data with round numbers, starting points (A, B, C …),
   "Where to find things" rows (base rows in `references/odoo20-ui.md` plus the module's own
   screen words), parts, cases, cheat sheet.

5. **Lint, then build.**
   ```bash
   python3 .claude/skills/odoo-manual-tests/scripts/build_checklist.py <spec.json> --check
   python3 .claude/skills/odoo-manual-tests/scripts/build_checklist.py <spec.json> --out "Claude outputs/<module>_manual_tests.xlsx"
   ```
   Repeat `--check` until it reports 0 warnings (unknown "Look here" names, missing starting
   points, long cells, size), then build.
   The builder refuses to overwrite an existing file (`--force` overrides) and never touches a
   file that is open in Excel.

6. **Look at it.**
   ```bash
   python3 .claude/skills/odoo-manual-tests/scripts/preview.py "Claude outputs/<module>_manual_tests.xlsx" --outdir <scratchpad>/preview
   ```
   Read every PNG (add `--sheet Tests --from-row N` for the lower part). Check that nothing is
   cut off and the colours are right.

7. **Deliver.** Save the spec beside the xlsx as `Claude outputs/<module>_manual_tests.json`, so
   a later "add a case" rebuilds the same file. Send the xlsx with SendUserFile. When a checklist
   already exists, ask or pick a new file name: the user may be filling it in (the builder's
   overwrite guard exists for this reason).

## Rules that matter most

- **Exact names only.** Every button, menu, field, tab and message comes from the inventory, the
  view XML, `references/odoo20-ui.md` or a `psql SELECT`. When a label cannot be checked (an
  external website), describe the action instead of naming a button, and say so on the Start
  sheet.
- **One action + one check per row, and `Look here` names the place** using the words printed on
  the screen. A tester should never have to ask "where is this?".
- **One scenario = one test case = one Pass/Fail.** Don't bundle scenarios into journeys.
- **Safety cases are green and end in an error, which counts as the Pass.** Each one cleans up
  after itself.
- **Plain English, fixed test data, real numbers**, no time estimates or priority levels, no
  drawings.
- **Read-only research.** `psql SELECT` only; don't create test data or log in to Odoo yourself
  unless asked. Never write passwords into the file.

## Reply to the user

Short. Say:
- what the file covers (cases per part, how many safety cases);
- what was verified in code or the database, and what was not (for example the external site's
  button names);
- what was left out and why;
- any defect found while reading the code, with file:line. Offer the fix as separate work; don't
  fix it inside this task.

## Files

| File | Use |
|---|---|
| `references/format-rules.md` | Layout, row rules, style, bad → good examples, spec format |
| `references/research.md` | How to research a module, pick cases, check labels and data, known traps |
| `references/odoo20-ui.md` | Verified Odoo 20 screen names and base "Where to find things" rows |
| `scripts/module_inventory.py` | Buttons, menus, tabs, boxes, crons, errors, live menus, suggested size |
| `scripts/build_checklist.py` | Spec JSON → xlsx, with lint |
| `scripts/preview.py` | One PNG per sheet (macOS Quick Look) |
| `assets/example_rs_einvoice.json` | Complete worked spec: 36 cases (27 flows, 9 safety) |
