# Bank Journal Setup — Multi-Currency Accounts at the Same Bank

> **Module:** `account` + `account_online_synchronization` | **Path:** [`addons/account/`](../addons/account/), [`enterprise/account_online_synchronization/`](../enterprise/account_online_synchronization/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

A company often holds several accounts at one bank, for example GEL, USD and EUR at Bank of Georgia. Each currency needs its own bank journal, so that statements, balances and reconciliation stay in that currency. This doc shows how the records fit together, which creation path to use, how the currency rules work, and how to find and clean duplicates.

`res.bank` does not exist in 20.0. The bank name, BIC and bank address are plain fields on each bank account (`res.partner.bank`, [res_partner_bank.py:58](../odoo/addons/base/models/res_partner_bank.py#L58)). There is no bank record shared by several accounts, so there is nothing at bank level to duplicate.

---

## The Big Picture

| Layer | Model | How many | What it holds |
|---|---|---|---|
| Bank account | `res.partner.bank` | one per account number | account number (IBAN), bank name, BIC, bank address; the holder is the company partner |
| Journal | `account.journal` | one per currency | currency, link to the bank account, bank feed, payment methods |
| Bank GL account | `account.account` | one per journal | created with the journal, type Bank and Cash, carries the journal currency |

Two layouts, depending on how the bank numbers its accounts:

```
A. One account number per currency         B. One account number, several currencies
   GE..01 ── journal "BoG"     (GEL)          GE..01 ──┬── journal "BoG"     (GEL)
   GE..02 ── journal "BoG USD" (USD)                   ├── journal "BoG USD" (USD)
   GE..03 ── journal "BoG EUR" (EUR)                   └── journal "BoG EUR" (EUR)
```

Layout B is supported. The company cannot hold the same number twice (the number is unique per partner, [res_partner_bank.py:89](../odoo/addons/base/models/res_partner_bank.py#L89)), so every currency journal links to the same bank account. Statement import finds the journal by account number **and** currency ([account_journal.py:217](../enterprise/account_bank_statement_import/models/account_journal.py#L217)), and online sync does the same when it links an account ([account_online.py:116](../enterprise/account_online_synchronization/models/account_online.py#L116)). The project's `bog_bank` and `tbc_bank` connectors request statements with the journal's account number plus its currency ([bog_connection.py:137](../custom_addons/gec_odoo_modules/bog_bank/models/bog_connection.py#L137)).

### Why one journal per currency

- Statement lines take the journal currency ([account_bank_statement_line.py:176](../addons/account/models/account_bank_statement_line.py#L176)). A transaction in another currency is kept as a foreign amount on the line.
- Saving the journal currency copies it to the journal's bank GL account ([account_journal.py:821](../addons/account/models/account_journal.py#L821)). An account with a currency accepts only journal items in that currency ([account_move_line.py:1841](../addons/account/models/account_move_line.py#L1841)).
- The dashboard balance of a foreign-currency journal is the sum of the foreign amounts on its GL account ([account_journal.py:1205](../addons/account/models/account_journal.py#L1205)).

Moving money between these journals goes through the transfer account. See [currency_exchange_transit.md](currency_exchange_transit.md).

---

## Creating the Journals

### Entry points (Enterprise)

| Where | What opens |
|---|---|
| Accounting → Configuration → Journals → **New**, or the dashboard's gear menu → **Add journal** | "What type of journal do you want to add?" ([journal_create_wizard.js:67](../enterprise/account_accountant/static/src/components/journal_create_wizard/journal_create_wizard.js#L67)) |
| That wizard → **Bank** card | The online bank search. `account_online_synchronization` is auto-installed with Accounting and replaces the manual setup action ([company.py:10](../enterprise/account_online_synchronization/models/company.py#L10)) |
| Dashboard card of an empty bank journal that is not connected | Bank logos and "Search over 26 000 banks" for that journal ([bank_configure.xml:14](../enterprise/account_online_synchronization/static/src/components/bank_configure/bank_configure.xml#L14)) |
| Journal form of an existing bank journal (or Action → Duplicate of one) | Journal Entries tab: Currency, Bank Account Number, BIC, Bank Feeds |

The Accounting dashboard has no New button of its own ([account_journal_dashboard_views.xml:8](../enterprise/account_accountant/views/account_journal_dashboard_views.xml#L8)).

### Path 1 — the bank is in the online-sync catalog

Log in to the bank through the search dialog. Odoo reads the bank's accounts with their numbers and currencies ([account_online.py:732](../enterprise/account_online_synchronization/models/account_online.py#L732)). A single account is linked at once; several accounts open "Select a Bank Account", where you link them one by one ([account_online.py:1065](../enterprise/account_online_synchronization/models/account_online.py#L1065)). For each account, `_assign_journal()` ([account_online.py:100](../enterprise/account_online_synchronization/models/account_online.py#L100)):

- started from a journal's dashboard card: links that journal and sets its currency to the bank's, unless it holds entries in another currency (statement lines in another currency raise an error);
- otherwise reuses the bank journal with the same account number and currency, or creates one named after the account number, with the bank's currency;
- sets the feed to online sync, links the company bank account for that number (creating it if needed), and fills an empty BIC from the provider.

Archived company bank accounts with the same numbers are reactivated ([account_online.py:773](../enterprise/account_online_synchronization/models/account_online.py#L773)).

### Path 2 — the bank is not in the catalog

Use the search dialog's option to add the bank manually. It calls `action_create_manual_bank_account()` ([account_online.py:408](../enterprise/account_online_synchronization/models/account_online.py#L408), [odoo_fin_connector.js:83](../enterprise/account_online_synchronization/static/src/js/odoo_fin_connector.js#L83)):

1. Finds the company bank account with that number, or creates it with the typed bank name and BIC ([res_partner_bank.py:214](../odoo/addons/base/models/res_partner_bank.py#L214)). Name and BIC are written only when the bank account is new.
2. **Always creates a new bank journal**, named after the account number, or after the bank name when no number was typed.
3. Sets no currency.

Then open the journal, set its **Currency** and rename it. For layout B, repeat with the same number: the existing bank account is reused and a new journal is created for the next currency.

### Path 3 — the journal form

Open an existing bank journal: the chart's default "Bank" journal, or a copy made with Action → Duplicate (the copy gets a new code, a new GL account and no bank account). On the **Journal Entries** tab ([account_journal_views.xml:110](../addons/account/views/account_journal_views.xml#L110)):

| Field | What to do |
|---|---|
| Currency | Set it before the first transaction |
| Bank Account (the GL account) | Already set. A new or duplicated journal gets its own, created with the company's bank prefix (120 on the Georgian chart) and the journal currency ([account_journal.py:942](../addons/account/models/account_journal.py#L942)). Keep one GL account per journal |
| Bank Account Number | Pick the company bank account, or type a new number and create it. Only bank accounts held by the company partner are listed |
| BIC | Shown once a bank account is set. It is the bank account's BIC, so editing it here edits the bank account for every journal using it |
| Bank Feeds | How transactions arrive: manual, file import, online sync (options depend on installed modules) |

The bank name and address are not on the journal form. Open the bank account from the Bank Account Number field and use its **Bank Information** tab.

### Without `account_online_synchronization`

The Bank card opens "Setup Bank Account" (`account.setup.bank.manual.config`, [setup_wizards.py:95](../addons/account/wizard/setup_wizards.py#L95)) with Account Number, Bank Identifier Code and Journal. Journal is pre-filled with the first bank journal that has no bank account and no entries ([setup_wizards.py:148](../addons/account/wizard/setup_wizards.py#L148)); clear it to create a new journal. The wizard renames that journal to the account number and sets no currency ([setup_wizards.py:125](../addons/account/wizard/setup_wizards.py#L125), [setup_wizards.py:166](../addons/account/wizard/setup_wizards.py#L166)). It creates a new bank account every time, so it cannot attach a second journal to an existing number (layout B): use the journal form for that.

---

## Currency Rules

| Rule | Source |
|---|---|
| Set the currency before the first transaction. The journal writes it on its GL account, which refuses if it already holds items in any other currency, company currency included: "You cannot set a currency on this account as it already has some journal entries having a different foreign currency." | [account_account.py:1063](../addons/account/models/account_account.py#L1063) |
| Clearing the currency is not blocked, but every statement line of the journal then takes the company currency: the line currency is a stored compute of the journal currency | [account_bank_statement_line.py:75](../addons/account/models/account_bank_statement_line.py#L75) |
| Online sync sets the journal currency from the bank, and refuses a journal whose statement lines are in another currency | [account_online.py:137](../enterprise/account_online_synchronization/models/account_online.py#L137) |
| Statement import refuses a file in another currency than the journal's | [account_journal.py:239](../enterprise/account_bank_statement_import/models/account_journal.py#L239) |
| When the GL account or an outstanding account of a foreign-currency journal has a currency, it must be the journal's | [account_account.py:175](../addons/account/models/account_account.py#L175) |

An empty currency means the company currency.

---

## Display Names and Search

- **Bank account:** "account number - bank name", or the number alone when the bank name is empty ([res_partner_bank.py:172](../odoo/addons/base/models/res_partner_bank.py#L172)).
- **Bank account dropdowns** search the account number only, ignoring spaces and case ([res_partner_bank.py:148](../odoo/addons/base/models/res_partner_bank.py#L148)). Typing "Bank of Georgia" finds nothing; type part of the IBAN. The Bank Accounts list's search box matches bank name or number ([res_partner_bank_views.xml:85](../odoo/addons/base/views/res_partner_bank_views.xml#L85)).
- **Journal:** the name, followed by the currency in brackets when it differs from the company currency, for example "BoG USD (USD)" ([account_journal.py:1121](../addons/account/models/account_journal.py#L1121)).

---

## Duplicates: What Can Happen and How to Fix It

| Situation | What Odoo does |
|---|---|
| Same number twice for the company | Blocked: "The combination Account Number/Partner must be unique." An archived copy gives "...already exists for Partner ..., but is archived. Please unarchive it instead." ([res_partner_bank.py:346](../addons/account/models/res_partner_bank.py#L346)) |
| Same number on another partner | Allowed. The bank account form warns "The Bank Account could be a duplicate of ..." ([res_partner_bank.py:71](../addons/account/models/res_partner_bank.py#L71)) |
| Bank name typed differently on two accounts | Kept as typed: it is free text. Only the BIC is normalized (upper case, [res_partner_bank.py:187](../odoo/addons/base/models/res_partner_bank.py#L187)) |
| Two journals for the same account in the same currency | Possible. Each manual add in the search dialog creates a new journal, and the journal form lists bank accounts already in use. The check "A bank account can belong to only one journal" ([res_partner_bank.py:59](../addons/account/models/res_partner_bank.py#L59)) runs only when the bank account record is saved with its journal list, not when a journal links to it |
| An extra journal named like a GL account | Creating an account of type Bank and Cash (or Credit Card) in the chart of accounts creates a bank (or credit card) journal for it, with no currency and no bank account ([account_account.py:1129](../addons/account/models/account_account.py#L1129)). Loading a chart of accounts skips this; installing a module that adds such accounts to an existing company does not ([ir_module.py:80](../addons/account/models/ir_module.py#L80)) |

### Fixing a duplicate journal

1. Keep the journal that holds the entries. A journal with entries cannot be deleted.
2. Open the extra journal's **Journal Items**. Post or delete its drafts: a journal with draft entries cannot be archived ([account_journal.py:691](../addons/account/models/account_journal.py#L691)).
3. Delete the empty journal, or archive it. Deleting also removes its payment methods and archives its bank account, unless another journal still uses that account ([account_journal.py:734](../addons/account/models/account_journal.py#L734)).
4. Check the currency of each remaining journal.

### Fixing bank details

Open the bank account from the journal's Bank Account Number field, from the company contact's **Invoicing** tab, or from Contacts → Configuration → Bank Accounts (administrators, developer mode). Correct Bank Name, BIC and address; every journal linked to that account shows the change.

Linking a bank account to a bank journal also marks it trusted ("Send Money") when your user may trust accounts ([account_journal.py:1072](../addons/account/models/account_journal.py#L1072)). The number and holder of a trusted account are locked ([res_partner_bank.py:393](../addons/account/models/res_partner_bank.py#L393)). To fix a wrong number, untrust the account first; that needs the bank-account validation right.

---

## Dependencies

| Requires | Why |
|---|---|
| `account` | Journals, bank accounts on journals, bank GL accounts |

| Works With (optional) | What It Adds |
|---|---|
| `account_online_synchronization` | Online bank search on the Bank card; one journal per online account, with its currency |
| `account_bank_statement_import` | File import; picks the journal by account number and currency |
| `gec_localization` (custom) | Fills an empty bank name and BIC from a Georgian IBAN's bank code ([res_partner_bank.py:30](../custom_addons/gec_odoo_modules/gec_localization/models/res_partner_bank.py#L30)) |
| `bog_bank`, `tbc_bank`, `basis_bank` (custom) | Bank APIs; statements requested per journal, by account number and currency |

---

## Gotchas & Non-Obvious Behavior

- **The Bank card is not a manual form in Enterprise.** It opens the online bank search. Manual setup is the search dialog's add-manually option or the journal form.
- **Every manual add creates a journal.** Adding the same number twice gives two journals on one bank account. That is right for layout B only if you then give each journal a different currency.
- **Do not create the bank GL account first.** A new Bank and Cash account creates its own journal. Create the journal and let it create its GL account, or link the journal that was auto-created instead of making a second one.
- **New journals are named after the IBAN.** The manual add, the setup wizard and online sync all name new journals after the account number, and only online sync sets a currency. Rename them and check the currency before the first transaction.
- **The Georgian chart's suspense account.** `l10n_ge` sets the company's bank suspense account to 120210 "Cash in Bank Foreign Currency" (a Bank and Cash account), not to 120001 "Bank Suspense" ([template_ge.py:33](../addons/l10n_ge/models/template_ge.py#L33)). Every new bank journal takes it as its suspense account. Do not also use 120210 as a currency journal's bank GL account: unmatched transactions would post both sides to one account.
- **Multi-company:** the holder of a journal's bank account must be the journal's company partner, and a bank account restricted to a company must match the journal's company ([account_journal.py:599](../addons/account/models/account_journal.py#L599)). Each company keeps its own bank accounts and journals.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`currency_exchange_transit.md`](currency_exchange_transit.md) — transfers between the currency journals, exchange differences
- [`accounting_coa.md`](accounting_coa.md) — chart of accounts, where the bank GL accounts sit
- [`basis_bank.md`](basis_bank.md) — a custom bank connector built on these journals
