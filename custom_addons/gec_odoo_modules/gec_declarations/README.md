# Declarations (`gec_declarations`)

One app for the rs.ge declarations: VAT, Income Tax (Form 30), Profit Tax (II-086) and Property Tax. It takes
their menus out of Accounting, so Accounting keeps only Odoo's own menus.

**Who this is for:** accountants who file declarations, and the administrator who installs the app.
Developers: see [README_DEV.md](README_DEV.md).

## What it does

| Feature | What you get |
|---|---|
| Overview | A card per declaration: latest declaration and its status, the next due date of monthly ones, the number of drafts |
| One place | The declaration menus, their registers and their settings menus, all in the **Declarations** app |
| Nothing else changes | Each declaration opens exactly the screen it opened before; calculations, files and rules are the declaration modules' own |
| Only what you have | A card and its menus appear only when that declaration module is installed and you may see it |

## Quick facts

| | |
|---|---|
| App | **Declarations** on the home screen |
| Menus | **Declarations > Overview**, **Declarations > Declarations**, **Declarations > Registers**, **Declarations > Configuration** (accounting administrators) |
| Who can use it | Anyone with access to accounting; Configuration is for accounting administrators, **Settings** for administrators |
| Needs | Accounting. Each card needs its declaration module |

## Where the menus are now

| Before, in Accounting | Now |
|---|---|
| Reporting > VAT Declaration (rs.ge) | Declarations > Declarations |
| Reporting > Income Tax Declaration (Form 30) | Declarations > Declarations |
| Reporting > Profit Tax Declaration (II-086) | Declarations > Declarations |
| Reporting > Property Tax Declaration (Form V-01) | Declarations > Declarations |
| Reporting > Profit Tax Taxed Items | Declarations > Registers |
| Configuration > Land Plots | Declarations > Registers |
| Configuration > rs.ge Form 30 (Advanced) | Declarations > Configuration |
| Configuration > rs.ge Property Tax (Advanced) | Declarations > Configuration |
| Configuration > Accounting > Profit Tax Declaration Rows | Declarations > Configuration |

**Activity-Based Costing** stays in Accounting > Reporting. The declarations' settings sections stay on the
Accounting settings page; **Declarations > Configuration > Settings** opens that page.

## The overview cards

| On the card | Meaning |
|---|---|
| **Latest** | The most recent declaration and its status (Draft, Exported, Filed, Confirmed…) |
| **Next due** | Monthly declarations only: the 15th of this month, or of next month after the 15th |
| **Open** | The declaration list, as the old menu opened it |
| **New** | A new declaration form |
| **… Drafts** | The declarations still in draft |

The order and the texts of the cards can be changed in **Declarations > Configuration > Declaration Cards**.

## Common questions

**Where did the Form 30 menu go?** Declarations > Declarations > Income Tax Declaration (Form 30).

**What if I uninstall the app?** The menus go back to their old places in Accounting.

**Is the property tax due date shown?** No: the card shows due dates only for the monthly declarations.
