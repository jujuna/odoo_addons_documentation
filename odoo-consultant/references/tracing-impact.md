# Tracing what really happens

Before saying "this affects X", find it in the code. These five traces answer almost every
"what happens if..." question. Tell the user the result in business words.

## 1. What does this button really do?

A button is `<button name="method_name" type="object">` in the view. Find the method, then
find **every app that extends it**. Each extension is something extra that happens.

```
rg -n "def (_action_confirm|action_confirm)\b" addons enterprise -g "*.py"
```

Worked example: **Confirm** on a quotation. The base `sale` module turns it into a Sales
Order. Then, depending on installed apps:

| App installed | Extra thing that happens on Confirm | Source |
|---|---|---|
| Inventory (`sale_stock`) | Delivery order created from the order lines | `addons/sale_stock/models/sale_order.py` `_action_confirm` |
| Project (`sale_project`) | Project and/or task created for service lines set up for it | `addons/sale_project/models/sale_order.py` `_action_confirm` |
| Purchase (`sale_purchase`) | Purchase order created for services bought from a vendor | `addons/sale_purchase/models/sale_order.py` `_action_confirm` |
| CRM (`sale_crm`) | Linked opportunity's revenue updated from the order | `addons/sale_crm/models/sale_order.py` `action_confirm` |

About 25 apps extend this one button. That's why "just confirm the order" can mean very
different things per client. Always ask which apps they will install.

## 2. What happens later, automatically?

Find `ir.cron` records across the relevant module, including files under `views/` and
`data/`. Check which files its manifest loads, whether the job is active by default, its
interval and called method, and any date/state conditions in that method. Database
configuration can override defaults. Also consider queued jobs and external integrations.

A daily interval does not prove “the next day.” Explain the eligibility condition and next
scheduled run; do not promise an exact time without runtime evidence.

## 3. What will Odoo refuse later?

Search the model for `raise UserError` / `raise ValidationError` inside `write`,
`unlink` and `@api.constrains`. These are the decisions that are **hard to undo**, so flag
them before the client starts working.

Example: `addons/account/models/company.py`: *"You cannot change the currency of the
company since some journal items already exist"*. Company currency must be right before
the first invoice.

## 4. Who else uses this data?

```
rg -n 'hr\.leave' addons enterprise -g '*.py'
```

Inheritance searches find candidate extensions; also inspect relations, calls and data
consumers. Verify the relevant installed extensions before claiming an effect. Example: `hr.leave` (time off) is
extended by Payroll (`hr_payroll`), Timesheets (`project_timesheet_holidays`), Attendances
(`hr_holidays_attendance`), Documents and several country payrolls. Changing time off rules
therefore changes payroll and timesheet results.

## 5. What gets sent to people?

Emails: `data/mail_template_data.xml`. Reminders and to-dos: `data/mail_activity_type_data.xml`
and `activity_schedule(` calls in the model. Tell the client who will receive what. Many
clients are surprised by automatic emails to customers or employees.

## Walk through these cases

Select the cases relevant to the process and requirements, and check their behavior.
An unverified case is an open question; a confirmed unmet requirement is a gap. Do not
label an irrelevant or merely unresearched case as missing functionality.

| Case | Ask, for example |
|---|---|
| Rejected / cancelled | Quotation cancelled after confirm: what happens to the delivery already created? |
| Partial | Client accepts 3 of 5 lines; half-day leave; partial payment |
| Change after approval | Leave approved, then dates change: is it re-approved? |
| Period boundaries | Employee joins mid-month; year-end carry-over; invoice dated in a locked period |
| Existing vs new | New customer vs existing one: duplicate contacts? |
| Missing setup | No manager on the employee, no product account, no working schedule: what breaks? |
| Several companies | A branch sells from another company's stock |

## Keep the business view short

End a recommendation with at most three lines:
**Better:** what improves (time, errors, control, visibility).
**Cost:** setup and change in daily work.
**Risk:** what can go wrong, and how we prevent it.
