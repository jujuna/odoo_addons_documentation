# Odoo 20 screen names (verified)

Core Odoo labels that checklists use again and again. Each was read from the 20.0 source or the
`gec20_prod1` database on 2026-09-25/26. Anything not listed here must be looked up in the module
or in `addons/` before it goes into a checklist.

## Navigation

| Tester sees | Where | Source |
|---|---|---|
| Grid icon (all apps) | Top left corner | web client |
| Accounting › Customers › Invoices / Credit Notes / Payments / Products / Customers | Accounting app menus | `ir_ui_menu` in gec20_prod1 |
| Accounting › Vendors › Bills / Refunds / Payments / Products / Vendors | Accounting app menus | `ir_ui_menu` |
| Accounting › Configuration › Accounting › Currencies / Journals / Taxes | Note the second "Accounting" | `ir_ui_menu` |
| Settings › Users & Companies › Users / Companies / Groups | Settings app | `ir_ui_menu` |
| Settings › Technical › Automation › Scheduled Actions | Needs developer mode: add `?debug=1` to the address | `ir_ui_menu` |
| Sales › Orders › Orders / Quotations / Customers | Sales app | `ir_ui_menu` |
| My Preferences, Log out | User menu (avatar, top right) | `web/static/src/webclient/user_menu/user_menu_items.js` |

Live menu paths of any module (the inventory script runs this with `--db`):

```sql
WITH RECURSIVE m AS (
  SELECT id, parent_id, (name->>'en_US')::text AS path FROM ir_ui_menu WHERE parent_id IS NULL AND active
  UNION ALL
  SELECT c.id, c.parent_id, m.path || ' > ' || (c.name->>'en_US') FROM ir_ui_menu c JOIN m ON c.parent_id = m.id WHERE c.active)
SELECT m.path FROM m JOIN ir_model_data d ON d.model = 'ir.ui.menu' AND d.res_id = m.id WHERE d.module = '<module>';
```

## Form controls

| Tester sees | Meaning | Source |
|---|---|---|
| Gear icon › Duplicate / Delete | Next to the record name at the top | `web/.../form/form_controller.js` |
| Cloud icon / X icon | Save / discard unsaved changes, next to the record name | web client (Odoo 17+) |
| Status words top right, e.g. Draft › Posted | The record's state; current one highlighted | statusbar widget |
| Diagonal corner ribbon | `web_ribbon` widget: Paid, In Payment, Reversed on invoices | `account/views/account_move_views.xml` |
| Small boxes top right of the page | Smart buttons (`oe_stat_button`), open linked records | view XML |
| Pop-up window | Errors (UserError / ValidationError) and `confirm="…"` questions | web client |
| [Ok] / [Discard] | Buttons of a `confirm="…"` question, unless the button sets `confirm-label` | `web/.../confirmation_dialog.js`, `view_button_hook.js` |
| [Delete] / [No, keep it] | Buttons of the gear-menu Delete question | `web/.../views/view_hook.js` |
| Small message top right that fades | Notifications (`display_notification`) | web client |
| Chatter | Messages and To-Do activities, right side (or under the form on small screens) | mail |
| Object buttons save first | Clicking any button saves the form before the button runs: a value typed just before a failing button stays saved | `form_controller.js` `beforeExecuteActionButton` |

## Invoices and bills (`account.move` form)

| Tester sees | Notes | Source |
|---|---|---|
| [Confirm] | Posts an invoice or bill (entries use [Post]) | `account_move_views.xml` header |
| [Reset to Draft], [Cancel] | Cancel only shows on drafts | same |
| [Credit Note] | Opens the reversal window on posted invoices/bills | same |
| [Pay] › [Create Payment] | Register payment (several: [Create Payments]) | `account_payment_register_views.xml` |
| [Send], [Print], [Preview] | Customer invoices | same |
| Customer / Vendor, Invoice Date / Bill Date | Field labels change with the document type | same |
| Tabs Invoice Lines, Other Info | Module tabs are added after Other Info | same |
| Add a line | Link under the invoice lines | same |
| Total | Bottom right of tab Invoice Lines | tax totals widget |
| Unreconcile | Payment info icon next to a paid amount › [Unreconcile] | `account_payment.xml` |

Credit note window (`account.move.reversal`): fields "Reason displayed on Credit Note", "Journal",
"Reversal date"; buttons [Reverse] and [Reverse and Create Invoice]
(`account/wizard/account_move_reversal_view.xml`). Modules can add fields and hide buttons here.

Vendor bill warning window "Confirm Entries" appears on [Confirm] only when a draft *bill* has an
abnormal amount/date compared with 10+ earlier bills of the same vendor
(`_compute_abnormal_warnings`); fresh test vendors never trigger it.

## Sales

| Tester sees | Notes | Source |
|---|---|---|
| Sales order [Confirm] | Quotation → order | `sale/views/sale_order_views.xml` |
| [Create Invoice] › "Regular invoice" / "Down payment (percentage)" / "Down payment (fixed amount)" › [Create Draft] | Opens the new invoice | `sale/wizard/sale_make_invoice_advance*.py/xml` |

## Products and contacts

| Tester sees | Notes | Source |
|---|---|---|
| Product Type = Goods / Service / Combo; Sales Price; Sales Taxes; Purchase Taxes | New products get the company's default taxes (gec20_prod1: 18% sale and purchase) | `product_template.py`, `account/views/product_view.xml`, `res_company` |
| Tax ID | Partner field label; the country's VAT label replaces it when set (Georgia: none) | `res_partner.py`, `res_country` |

## Scheduled actions

Form button [Run Manually] (`base/views/ir_cron_views.xml`). Most of our crons ship inactive; say
so in the checklist and have the tester run them by hand.

## Base rows for sheet "Where to find things"

Copy the rows that the checklist uses, then add the module's own places (its tab, status box,
tables) with the words printed on its screen:

```json
[
 ["Buttons at the top", "Top of the record, on the left, just under its name.", "[Confirm] [Reset to Draft] … (list the ones the tests use)"],
 ["Top right (status)", "Top of the record, on the right, same line as those buttons.", "The status words; the current one is highlighted."],
 ["Tab <Name>", "In the middle of the record, next to the other tabs.", "Click it."],
 ["Pop-up window", "Opens in the middle of the screen.", "An error or a question. Read it, then close it."],
 ["Small message (top right)", "Top right corner of the screen; goes away by itself.", "For example: <a real message>."],
 ["Corner ribbon", "A diagonal band in the top right corner of the page.", "<the ribbons the tests use>"],
 ["Small boxes (top right of the page)", "Top right of the page, above the fields.", "<smart button labels> — click one to open that document."],
 ["Gear icon · cloud icon · X icon", "Next to the record name at the very top.", "Gear: Duplicate, Delete. Cloud: save. X: discard your changes."],
 ["Grid icon", "Top left corner of the screen.", "Opens the list of apps."],
 ["Chatter", "Right side of the screen (or under the record).", "Messages and To-Do tasks."]
]
```
