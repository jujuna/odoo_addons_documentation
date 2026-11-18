# TBC Bank (BIS) — Test environment setup and test plan

For Odoo 20, module `tbc_bank`, against the **TBC test environment** (`test-api.tbcbank.ge`).
In the test environment nothing moves real money.

---

## 1. Setup

### 1.1 Database and module
1. Create a database (no demo data is needed).
2. Apps → install **TBC Bank** (also installs Accounting and Bank Channels). For the payroll test also install **Payroll Bank Channels** and Payroll.
3. The admin user gets the **TBC Bank: Manager** group automatically. For the payroll test the
   user also needs **Payroll: Administrator**.

### 1.2 Company
Do this **before any journal entry exists**, or the currency can no longer be changed.

- Settings → Companies → your company → Country **Georgia**, Currency **GEL**.
  If the currency is read-only there: Accounting → Configuration → Settings → Main Currency = GEL.
- Accounting → Configuration → Currencies → activate **EUR** (for the foreign transfer test).

### 1.3 TBC API credentials
Use either:
- your own app from the TBC developer portal with the products **BIS - Accounts - Test** and
  **BIS - Transfers - Test** enabled, or
- the keys from the Postman environment "TBC Integration Service Test Environment" (`apikey` / `apisecret`).

Never commit or paste the keys into documents.

### 1.4 Connection
TBC Bank → Connections → New:

| Field | Value |
|---|---|
| Environment | **Test** |
| Client ID / Client Secret | from 1.3 |
| API Host | empty |
| Processing Mode | **Direct (bank auto-confirms)** |

Save → **Test Connection** → expect "Connection successful", state **Active**.
TBC Bank → API Logs: `oauth/token` 200, scope `bab_accounts bab_transfers`, token shown as `[REDACTED]`.

### 1.5 Journals
Accounting → Configuration → Journals → New, type **Bank**. Type the **Journal Name** in the title field at the top
(if left empty Odoo names the journal after the account number).

| Journal Name | Account Number | SWIFT Code | Currency | Used for |
|---|---|---|---|---|
| TBC Bank | `GE29TB7777777777777777` | `TBCBGE22` | GEL (empty = company) | sending transfers |
| TBC Statements | `GE48TB7873440574631292` | `TBCBGE22` | GEL | statement import |
| TBC EUR | same bank account as TBC Bank | `TBCBGE22` | EUR | foreign transfer |

- The **SWIFT Code** is what makes a journal a TBC journal (first 8 characters `TBCBGE22`). The "Bank" text field does nothing.
- After saving, each journal must have a **TBC Bank Transfer** line in the *Outgoing Payments* tab and the bank feed **TBC Bank**.
- On every TBC Bank Transfer line set **Outstanding Payments** = `101404 Outstanding Payments` (or your equivalent).
  Without it payroll refuses to run and payments get no proper journal entry.

### 1.6 Partners (recipients)
Contacts → New → Accounting tab → Bank Accounts. Tick **Send Money** on every account.

| Partner | Bank account | Other |
|---|---|---|
| Test Within TBC | `GE29TB9999999999999999` | |
| Test Within TBC 2 | `GE44TB0600051509630891` | |
| Test National | `GE90BG0000000589021505` | Tax ID `12345678901` |
| Test Foreign CZ | `CZ6508000000192000145399` | Street `Beneficiary Address`, Country Czech Republic |
| Treasury (Revenue Service) | none | |
| Test No Bank Account | none | |

### 1.7 Second user and approver (approval test)
1. Settings → Users → New: **TBC Approver**, login `approver`, password `approver`,
   rights **TBC Bank: User** and **Accounting: Administrator**.
2. TBC Bank → Approvers → New: Primary Approver = TBC Approver.
3. Connection → Approver = that record. Leave Processing Mode on **Direct** until the approval test.

### 1.8 Payroll (payroll test only)
1. Accounting → Configuration → Settings: **Batch Payroll Move Lines** must be **off** (each employee is paid separately).
2. Chart of accounts:
   - `230100 Salaries Payable` — type **Payable**, Allow Reconciliation **on**
   - `620000 Salary Expense` — type **Expenses**
3. Journal **Salaries** — type Miscellaneous, code `SAL`, default account 230100.
4. Payroll → Configuration → Structure Types → **TBC Test**; Structures → **TBC Test Salary** (type TBC Test, journal Salaries) with two rules:
   - `BASIC` — category Basic, 100 % of `version.wage`, Debit account **620000**
   - `NET` — category Net, 100 % of `version.wage`, Credit account **230100**, **Set employee on account line** on
   (Set TBC Test Salary as the default structure of TBC Test.)
5. Employees (the private bank account goes on the employee; tick **Send Money** on it):

| Employee | Bank account | Wage | Expected transfer type |
|---|---|---|---|
| TBC Employee A | `GE29TB9999999999999999` | 1 | Within TBC |
| TBC Employee B (other bank) | `GE90BG0000000589021505` | 2 | To other bank (national) |
| TBC Employee C | `GE44TB0600051509630891` | 3 | Within TBC |

   Contract start 01/01/2026, structure type TBC Test.

---

## 2. Tests

For each new payment: Accounting → Vendors → Payments → New, Payment Type **Send**, Journal **TBC Bank**,
Payment Method **TBC Bank Transfer**, amount **1.00**, a memo. Click **Send to TBC once** and wait.
After each test, TBC Bank → API Logs shows the request and TBC's answer. The **TBC Transfer** group of the
payment form shows **Bank State**, **Bank Reference** (TBC's transfer ID), **Bank Request ID**, **Approved By**,
**Bank Error** and **TBC Status (raw)**; none of them can be edited by hand.

### A. Basics
| # | Do | Expect |
|---|---|---|
| 1 | Connection → **Test Connection** | Connection successful; secret redacted in the log |
| 1a | Connection → Actions (gear) → **Delete** (the connection has API logs now) | Refused: "A bank connection with API logs cannot be deleted" |
| 2 | New payment, partner **Test Within TBC** | TBC Transfer Type fills itself: **Within TBC** |
| 3 | The same payment, still Draft | **No** "Send to TBC" button |
| 4 | **Confirm** → **Send to TBC** | Bank State **Confirmed**, Bank Reference set, **TBC Status (raw)** `Finished`; chatter: "TBC Bank state: Sending → Sent", then "Sent → Confirmed" |
| 5 | The same payment afterwards | No Send button: it cannot be sent twice. **Reset to Pending** and **Recover from TBC** are not shown either |

### B. Transfer types
| # | Do | Expect |
|---|---|---|
| 6 | Partner **Test National** → type auto **To Other Bank (national)**; Beneficiary Tax Code `12345678901` → Confirm → Send | Confirmed; the request carries the IBAN **without spaces** |
| 7 | Partner **Treasury (Revenue Service)**, no bank account, type **Treasury**, code `101001000` → Confirm → Send | Confirmed; no `creditAccount` in the request |
| 8 | Journal **TBC EUR**, currency EUR, partner **Test Foreign CZ** → type auto **Foreign**; Address, Bank Code `0800`, Charge **SHA** → Confirm → Send | Confirmed; debit currency EUR |

### C. Safety checks
| # | Do | Expect |
|---|---|---|
| 9 | Treasury payment with code `12345` → Confirm → Send | Error "needs a 9-digit Treasury Code"; **no** API log row |
| 10 | Partner Test Within TBC, set the type by hand to **To Other Bank (national)** → Confirm → Send | Error "The recipient account is a TBC account; use 'Within TBC'" |
| 11 | Connection → API Host `10.255.255.1` → Save. New Within-TBC payment → Confirm → Send; wait ~60 s | Bank State **Unknown**; Send hidden; **Recover from TBC** and **Refresh TBC Status** shown, **Confirm Manually** hidden |
| 12 | Clear API Host → Save. On that payment → **Recover from TBC** at once, then again after 15 minutes | At once: "TBC has no record of this transfer yet ... Try again after 15 minutes", still Unknown. After 15 minutes: "TBC has no record of this transfer. You can resend it." → Pending; **Recover from TBC** is no longer shown |
| 13 | **Send to TBC** | Confirmed (same request id reused) |

### D. Batch and approval
| # | Do | Expect |
|---|---|---|
| 14 | Create and **Confirm** 2 Within-TBC payments (one to Test Within TBC 2). Select both → Action → **Create Batch Payment** → **Send to TBC** | Both Confirmed, each its own Bank Reference; batch state **Sent** |
| 15 | Connection → Processing Mode **Approve in Odoo first**. New payment → Confirm → **Submit for TBC Approval** → **Approve TBC Transfer** (as admin) | Bank State **Awaiting Approval**; the approver is notified; approving as admin is refused: "You are not authorized to approve TBC Bank transfers." |
| 16 | Log in as `approver` → TBC Bank → **Pending Approval** → open the payment → **Approve TBC Transfer** | Approved; the banner shows "Approved by TBC Approver" |
| 17 | As admin → **Send to TBC**; then Processing Mode back to **Direct** | Sent |
| 17a | Processing Mode **Direct**: new payment → Confirm | **Submit for TBC Approval** is not shown; **Send to TBC** is |
| 17b | Processing Mode **Approve in Odoo first**. TBC Bank → Approvers → add the admin as a Delegate. New payment → Confirm → Submit → **Approve TBC Transfer** (as admin, who created it) | Refused: "You created this transfer, so you cannot approve it". Tick **Allow Self-Approval** on the connection → approving works. Untick it and remove the admin from the Delegates again |
| 17c | New payment → Confirm → Submit → approve as `approver`. Then set the Primary Approver of the approver record to Administrator. As admin → **Send to TBC** | Refused: "… approved this transfer but may no longer approve, so the approval was withdrawn"; Bank State back to **Pending**. Set the Primary Approver back to TBC Approver, then Processing Mode **Direct** |

### E. Statements, payroll, scheduled jobs
| # | Do | Expect |
|---|---|---|
| 18 | TBC Bank → **Import Statement** → TBC Statements, From `01/05/2026` | **Currency** is filled from the journal (GEL) and cannot be typed. First time: 58 lines (21/05–09/06/2026). Second time: **0 new** (no duplicates) |
| 19 | Accounting dashboard → TBC Statements | The imported lines, ready to reconcile |
| 20 | TBC Bank → **Fetch Statement** → TBC Statements, `01/01/2025`–`01/03/2025` | Opening **1000.50**, closing **1250.00**, credit 500.25, debit 250.75 |
| 21 | Payroll → new pay run for one month, the 3 TBC employees → Generate → Compute → Validate → **Pay Salaries** → Bank **TBC Bank Transfer** for all three → **Create Payments** → open the payroll batch → **Send to TBC** | 3 Confirmed; A and C Within TBC, B national; payslips **Paid**; batch **Sent** |
| 21a | As 21, but one employee with the account `CZ6508000000192000145399` | **Create Payments** refuses: "TBC pays payroll only into Georgian IBANs"; nothing is created, the payslips stay confirmed |
| 22 | Settings → Technical → Scheduled Actions → **TBC Bank — Transfer status poll** → Run Manually | No error; the payment from test 17 → Confirmed |
| 23 | Same for **TBC Bank — Daily statement sync** and **Live statement snapshots** | Run without stopping; TBC Bank / TBC EUR fail with INVALID_ACCOUNT (expected, see 3) and this is posted on the connection |

### F. Automated tests
```
docker exec odoo20_odoo python3 /opt/odoo/odoo-bin -c /etc/odoo.conf -d <db> -u tbc_bank \
  --test-enable --test-tags /tbc_bank --stop-after-init --http-port 8099 --gevent-port 8098 --max-cron-threads 0
```
Expect `0 failed, 0 error(s)`. The tests mock TBC; they never call it.

---

## 3. How the TBC test environment really behaves

As observed, it differs from the documentation in places.

- Success: `207 {"succeeded": [{"position": 1, "transferId": ...}], "failed": []}`; status `{"status": "Finished"}`.
- Wrong transfer type for the account (e.g. national to a `GE..TB..` account): `'Account Number' is not in the correct format.`
  The module picks the type from the IBAN and blocks a mismatch before sending.
- **No duplicate protection**: the same `transferExternalId` sent twice creates two transfers. Only the module's own state lock prevents a double payment.
- Looking up an unknown request id returns **400** "Specified single transfer external id is not found for a current client" (not 404).
- The transfer account `GE29TB7777777777777777` is a mock: it has **no movements or statements** (`INVALID_ACCOUNT`).
  Movements exist only for `GE48TB7873440574631292` (May–June 2026); balances only for the 2025 periods of the Postman samples.
- Any TBC-looking recipient is accepted, even `GE00TB0000000000000000`.

## 4. Not testable in the test environment — check in production

Before the first customer uses it, with production keys:
1. One small transfer (e.g. 0.01 GEL) → Confirmed.
2. Import the statement of that account → does the line confirm the payment automatically?
   This shows whether TBC's `paymentId` equals the `transferId` (unknown so far).
3. A national transfer to another bank → is `beneficiaryTaxCode` required? (Payroll sends none.)
4. Sending the same request id twice → does production return `DUPLICATED_SINGLE_TRANSFER_REQUEST`?
5. A transfer TBC refuses (Bank State **Failed**, the payment turns Rejected): **Send to TBC** is refused until
   the payment is reset to draft, corrected, confirmed and **Reset to Pending**; the resend carries a new
   Bank Request ID when the payment had a TBC reference, the same one otherwise. The test environment accepts almost everything, so a refusal cannot be provoked there.
6. A later "failed" status for a transfer that is already Confirmed: the state stays and a note is posted.
