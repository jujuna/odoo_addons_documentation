# Playbook: Sales, CRM and Helpdesk

Use this as a research starting point, not a ready-made recommendation. Historical
verification notes below do not certify the current checkout or client database. Re-check
material rules, defaults, calculations and labels before using them. Follow SKILL.md and
the implementation protocol for discovery and decisions.


Use when designing how a client sells: where requests come in, how a proposal starts for
new vs. existing clients, and how support connects to sales. Verified against Odoo 20
source (2026-09-22). Re-check a label in the source before giving it as a click-path.

## How Odoo thinks (explain these first)

| Idea | In plain words |
|---|---|
| **Lead** | An unqualified request: "someone contacted us". Optional step. Exists only if the **Leads** setting is on |
| **Opportunity** | A real possible deal with an expected revenue, moving through pipeline stages (default: New, Qualified, Proposition, Won) |
| **Quotation** | The offer document. It becomes a **Sales Order** when confirmed. States: Quotation, Quotation Sent, Sales Order, Cancelled |
| **Customer (contact)** | One contact record used everywhere: CRM, Sales, Helpdesk, Accounting. Duplicate contacts are the most common data problem |
| **Ticket** | A support request in Helpdesk. Separate from CRM, but it can be converted to a lead or opportunity and back |
| **Sales team** | Groups salespeople. It also carries the email alias that turns incoming emails into leads or opportunities |

Two things that surprise people:
- **Confirming a quotation does not mark the opportunity Won.** It only raises the expected
  revenue to the order amount. The salesperson must click **Won**
  (`addons/sale_crm/models/sale_order.py`, `action_confirm`). Decide whether that's fine,
  or whether it needs an automation rule.
- **Converting a lead is one click, with no dialog** (new in Odoo 20). **Convert to
  Opportunity** links an existing customer with the same email, or **creates a new
  customer** if none matches (`addons/crm/models/crm_lead.py`,
  `action_convert_to_opportunity`). A different email means a duplicate customer.

## Where requests come in

| Channel | What Odoo creates | Where it's set |
|---|---|---|
| Email to a sales address | Lead or opportunity (depends on the Leads setting) | Sales team form: **Email Alias**, **Accept Emails From** |
| Website contact form | Opportunity (form action **Create an Opportunity**) | Website form builder (`website_crm`) |
| Live chat | Lead via **Create Lead** or chatbot step | `crm_livechat` |
| Phone / walk-in | Created by hand in CRM, or a quotation directly in Sales | |
| Support request | Ticket in Helpdesk | Helpdesk team (email alias, **Website Form**, **Live Chat** toggles) |

## Starting a proposal: the routes

### A. New client

| Route | How it works | Best when | Watch out |
|---|---|---|---|
| Lead, then opportunity, then quotation | Request lands as a lead, gets qualified, **Convert to Opportunity**, then **New Quotation** | Many unqualified requests; you want to filter before salespeople spend time | Extra step. Conversion creates the customer automatically |
| Opportunity, then quotation (Leads off) | Every request is directly an opportunity in the pipeline | Fewer, serious requests; small team | Pipeline fills with junk if requests aren't filtered |
| Quotation directly in Sales | **Sales > Orders > Quotations > New** | One-off quick price for a walk-in | No pipeline, no win/loss statistics |

On an opportunity with no customer, **New Quotation** asks *"Who should be linked to this new
Quotation?"*: **Create a new customer**, **Link to an existing customer**, or **Do not link
to a customer**. It pre-selects "existing" when the email matches
(`addons/sale_crm/wizard/crm_opportunity_to_quotation.py`).

### B. Existing client, new deal

| Route | Best when |
|---|---|
| New opportunity on the existing customer, then **New Quotation** | Bigger deals where you want to track the pipeline and win rate per client |
| Quotation directly in Sales | Repeat orders at known prices. Faster, and no CRM tracking needed |

Odoo shows a **Similar Leads** smart button when other leads share the same email domain,
customer or phone. It only warns: nothing is merged automatically. Merging is manual
(**Merge**, or bulk **Convert & Merge with Opportunities**).

### C. Existing client, support request that becomes a sale

- Ticket: gear menu **Convert to Opportunity/Lead**. The ticket is archived, and its
  messages and attachments move to the new lead (`enterprise/crm_helpdesk`).
- The other way: a lead can **Convert to Ticket** (leads only, not opportunities). Useful
  when a "sales" email is really a support problem.
- There is **no "create quotation from ticket"** in Helpdesk. The path is ticket, then
  opportunity, then **New Quotation**.

### D. Selling services / projects

- A product's **Create on Order** (Nothing, Task, Project & Task, Project) creates the
  project or task when the order is confirmed (`sale_project`).
- From an opportunity, gear **Create Project** starts a project before the sale is closed
  (`crm_sale_project`). A quotation made later from that opportunity is linked to the project.

## Decisions to make with the client

| Decision | Options | What changes |
|---|---|---|
| Use the Leads step? | **CRM > Configuration > Settings**, **Leads** on/off | On: adds **CRM > Leads** menu and a qualification step. Off: everything is an opportunity |
| How many sales teams? | One, or per product/region/channel | Each team has its own pipeline, email alias and reporting |
| Who wins the opportunity? | Salesperson clicks **Won**, or an automation on order confirmation | Win-rate reports are only correct if this is done consistently |
| Quotation templates | **Sales > Configuration > Sales Orders > Templates** | Standard offers with fixed lines, optional sections, validity. Always available in Odoo 20 (no setting) |
| Online approval | Settings **Online Signature** (on by default), **Online Payment** + **Prepayment** % | Customer signs or pays from the link in the email. No PDF back-and-forth |
| Quote validity | Settings **Default Quotation Validity** (days, 0 = none); field **Expiration** on the quote | After expiry the customer can't sign or pay online |
| Support and sales link | Helpdesk team toggles: **Refunds**, **Returns**, **Repairs**, **Coupons**, **Time Billing**, **Timesheets** | **Each toggle installs an app.** Decide deliberately |
| Duplicate control | Rely on **Similar Leads**, plus a rule "search the customer before creating" | Duplicates break reporting and the customer history |

## Traps

- **Time Billing auto-confirms quotations:** with `helpdesk_sale_timesheet`, creating a
  ticket linked to a *draft* quotation's line confirms that quotation
  (`enterprise/helpdesk_sale_timesheet/models/helpdesk_ticket.py`).
- The ticket's sales order field (**Ref. Sales Order**) exists but is hidden on the ticket
  form. It's used by the refund and return wizards, and it's searchable.
- The Sales app menu only appears once `sale_management` is installed.
- Menus depend on access: **CRM > Configuration** needs Sales: Administrator. Helpdesk
  **Stages** and **Tags** menus are visible only in developer mode.

## Quick menu map

| Where | Path |
|---|---|
| Pipeline | **CRM > Sales > My Pipeline** |
| Leads | **CRM > Leads** (only with Leads setting) |
| Quotations from CRM | **CRM > Sales > My Quotations** |
| Quotations | **Sales > Orders > Quotations** |
| Lost reasons, stages, tags | **CRM > Configuration > Pipeline** |
| Sales teams | **CRM > Configuration > Sales Teams** |
| Tickets | **Helpdesk > Tickets > All Tickets** |
| Helpdesk teams | **Helpdesk > Configuration > Helpdesk Teams** |
