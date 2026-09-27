# Checklist format rules and spec

The format below is the one the user approved on 2026-09-26 after rejecting three earlier
versions. Each rule comes from a concrete complaint, noted in *italics*, so the reason is clear
when a module seems to call for an exception.

## Who reads it

A tester who has never seen Odoo or the module. They get the xlsx and an Odoo address, nothing
else. Every row must be doable without asking "where is this?" or "what does this mean?".

## Workbook layout (the builder makes all of it)

| Sheet | Content |
|---|---|
| Start | One-line purpose · How to use it (4 lines) · The admin fills this in (address, user, external test users — never passwords) · Test data (created once) · Starting points · Tips · Never (real risks only) · Progress counter |
| Where to find things | Plain table: name used in Tests · where it is on the screen · what you see there. No drawings. *A cell-drawn screen map confused the user.* |
| Tests | Numbered test cases TC-01…, grouped in parts (e.g. Sales / Purchases / Safety) |
| Cheat sheet | Optional: what each status means and what you can do next; coloured boxes and what to do |

## Test cases

- **One scenario = one test case with one Pass/Fail** (dark title row). *Bundling 3-7 scenarios
  into "journeys" made 50 checks look like 14 and the user said "14 is few".*
- **Size by module**: run `scripts/module_inventory.py`; it suggests a range (about 1.1 cases per
  user-facing action; rs_einvoice with 32 actions → 35 cases). Do not pad a small module and do
  not try to test every line of a big one.
- **About a quarter are safety cases** (green): something a user might do by mistake that Odoo
  must refuse. The error message is the Pass. Pick the refusals that protect money, tax filings
  and data (wrong partner, locked documents, double booking, deleting live records) over cosmetic
  ones.
- **Every case says where it starts**: a letter from "Starting points" (A = posted invoice, B = …)
  or "—". Starting points remove the repeated setup steps.
- **Every case has a one-line goal**: what it proves, in business words ("Odoo cancels the invoice
  only after the buyer agrees").
- **Clean up** at the end of safety cases that create records ("[Reset to Draft] › [Cancel]",
  "gear icon › Delete"), so testing leaves nothing half-done.
- **Leave out cases that damage data** (records that end up stuck, live payments). Put a line in
  "Never" instead. *The user's priority: "safest, don't break anything in Odoo".*
- **No time estimates, no priority levels.** *"about 10 min" was called unnecessary.*

## Step rows

Columns: `Where` · `Do this` · `Look here` · `You should see`.

- **One action + one check per row.** *A cell listing status, series number, log line, buttons and
  the buyer's view was "too confusing".*
- **`Look here` names the exact place**, using a name from sheet "Where to find things". *"Line
  badge Pending Edit in Goods / Services" → "where? where is this line badge?"*
- **Use the words printed on the screen** (tab names, section titles, field labels, button labels,
  message starts). Names you invent ("RS status box") need a row in "Where to find things";
  prefer the screen's own words ("Current Status").
- **Fixed test data with real numbers**: define products/partners once (e.g. TEST Service,
  price 100, 18% VAT → Total 118.00) and check numbers. *"2 lines with tax 18%" was unclear.*
- **Full click path the first time**, e.g. `Accounting › Customers › Invoices › [New]`; later rows
  of the same case can start from the open record.
- **Messages**: quote the start of the text exactly, bold, with `…` for the rest.
- **Pop-up answers use their real labels**: `› [Ok]` for a button's question, `gear icon › Delete ›
  [Delete]` for deleting a record (see `odoo20-ui.md`), never a generic "OK".
- **External website rows** (rs.ge, bank portal) are orange and say who acts ("As BUYER:"). If the
  site's own button names were not checked, describe the action ("confirm the invoice") and say so
  in the Start sheet.

## Writing style

Plain English (unless the user asks for Georgian), short sentences, no jargon ("posted" → the
screen word "Posted" is fine; "journal entry", "reconcile", "move" are not unless on screen).
Buttons in `[brackets]` (the builder makes them bold); key values in `*asterisks*` (bold, no
asterisks shown).

Bad → good (from this module's history):

| Bad | Good |
|---|---|
| `Line badge Pending Edit (red) in "Goods / Services"` | Look here `Goods / Services › column RS`, see `Red *Pending Edit*` |
| `Customer = TEST Buyer, 2 lines with tax 18%` | Fixed data: `TEST Service, quantity 1` → `Total *118.00*` |
| Expected: 5 things in one cell | One check: `Current Status` → `*Sent (Pending)*` |
| Journey "Safety" with 7 checks | 9 separate green test cases, one refusal each |

## Spec format (input of `scripts/build_checklist.py`)

```json
{
  "module": "rs_einvoice",
  "title": "rs.ge e-invoice: test checklist",
  "intro": "{n_cases} test cases: … (optional; {n_cases} is filled in)",
  "output": "Claude outputs/rs_einvoice_manual_tests.xlsx",
  "target_cases": 35,
  "external": {"name": "rs.ge", "label": "rs.ge website"},
  "admin_fill": [["Odoo address", ""], ["rs.ge BUYER test user", "name:      TIN:"]],
  "test_data": [["TEST Service", "Accounting › Customers › Products › [New]: …"]],
  "starting_points": [["A", "Posted invoice, not sent", "…how to make it…"]],
  "tips": [["Tip", "…"]],
  "never": [["Real companies", "…"]],
  "where": [["Current Status", "Inside tab RS E-Invoice: the big box near the top.", "Left: RS Invoice ID …"]],
  "parts": [
    {"title": "PART 1 — SALES: …", "role": "BUYER", "cases": [
      {"kind": "flow", "title": "Send an invoice; the buyer confirms it", "start": "A",
       "goal": "The normal day: …",
       "steps": [["odoo", "Tab *RS E-Invoice* › [Send to RS]", "Current Status", "*Draft*"],
                 ["ext", "Find the invoice and confirm it.", "—", "—"]]}]}
  ],
  "cheat_sheet": [{"title": "…", "head": ["Status", "Means", "What you can do"], "rows": [["…", "…", "…"]]}]
}
```

- `kind`: `flow` (blue) or `safe` (green). `where`: `odoo` or `ext` (needs `external`).
- `how_to_use` (optional list of lines) replaces the default 4-line "How to use it" on the Start
  sheet — use it when the module needs a different legend (no external site, a second tester role).
- `intro` may contain `{n_cases}`; `tips` and `never` are `[label, text]` pairs.
- `role` on a part prefixes its `ext` rows with "As ROLE:".
- `look`: one or more names from `where`, joined with ` + `; `—`, `Whole screen`,
  `Table on that page`, `The list that opens` and `<external> website` need no row.
- The builder warns about unknown `look` names, undefined starting points, cells that are too long,
  the safety share and `target_cases`; fix every warning before delivering. Iterate with
  `--check` (lint only, writes nothing), then build once.
- Worked example with all 36 cases: `assets/example_rs_einvoice.json`.
