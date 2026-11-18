# TBC Bank BIS API reference

TBC Bank's **Business Integration Services** (BIS) REST API, as published on the TBC developer
portal, collected for `tbc_bank`. Each part notes where the module uses it.

| | |
|---|---|
| Source | 19 BIS pages on developers.tbcbank.ge ([list](#15-sources)) |
| Collected | 2026-10-02 |
| Newest change | Import Single Transfer, updated 2026-09-24 |
| Refresh a page | `curl -s https://developers.tbcbank.ge/docs/<slug>.md` returns the page as Markdown |
| Sandbox walkthrough | [TESTING.md](TESTING.md) |

Sections 1-11 state what TBC's pages say; lines starting with **Module** describe this module.
Anything the pages leave open is in [Open questions](#13-open-questions), and the places where the
pages contradict each other are in [section 12](#12-where-tbcs-pages-contradict-themselves).

## Contents

1. [Environments and data format](#1-environments-and-data-format)
2. [Credentials and permissions](#2-credentials-and-permissions)
3. [Authentication](#3-authentication)
4. [Endpoints and module coverage](#4-endpoints-and-module-coverage)
5. [Account movements](#5-account-movements)
6. [Movement by ID, statement, balance](#6-movement-by-id-statement-balance)
7. [Transfer types and fields per type](#7-transfer-types-and-fields-per-type)
8. [Import single and batch transfers](#8-import-single-and-batch-transfers)
9. [Transfer status and ID lookup](#9-transfer-status-and-id-lookup)
10. [Errors](#10-errors)
11. [Sandbox test data](#11-sandbox-test-data)
12. [Where TBC's pages contradict themselves](#12-where-tbcs-pages-contradict-themselves)
13. [Open questions](#13-open-questions)
14. [Module assumptions checked against the pages](#14-module-assumptions-checked-against-the-pages)
15. [Sources](#15-sources)

---

## 1. Environments and data format

| Environment | Base URL | Credentials from | Money moves |
|---|---|---|---|
| Test / sandbox | `https://test-api.tbcbank.ge` | developer-portal app (Key / Secret) | no, responses are mocked |
| Production | `https://api.tbcbank.ge` | Business Internet Banking, API Integration | yes |

- Full URL = base URL + endpoint path, e.g. `https://api.tbcbank.ge/bab/v1/accounts/movements`.
- Test credentials work only on test, production credentials only on production.
- Requests and responses are JSON in UTF-8. Text may contain Georgian Unicode, Latin letters,
  digits, spaces and common punctuation.
- A field with no value comes back as `null`.
- `exchangeRate` is a string such as `"1 EUR = 3.175 GEL"`, or `null` when no conversion happened.
- Date-times are ISO 8601 without a zone offset: `2026-04-22T00:00:00`. No page names the time
  zone ([Q1](#13-open-questions)).
- Errors come as `application/problem+json` ([section 10](#10-errors)).

**Module** - hosts in `DEFAULT_HOSTS` ([services/tbc_bank_service.py:18](services/tbc_bank_service.py#L18)),
chosen by the connection's Environment; `API Host (override)` replaces it.

---

## 2. Credentials and permissions

### Test credentials

1. Create a developer account on developers.tbcbank.ge.
2. Create an App.
3. On the App page enable the products you need:
   - **BIS - Accounts - Test** - account services
   - **BIS - Transfers - Test** - transfer services
4. The App's **Key** is the `client_id`, its **Secret** the `client_secret`.

Sandbox limits: only the exact requests listed in [section 11](#11-sandbox-test-data) return
defined data, other parameter combinations may return undefined results; the data is fake; nothing
reaches real banking systems.

### Production credentials

Created in Business Internet Banking (`https://tbconline.ge/business/`), section **API
Integration**, by an admin user (company director or authorized person):

1. Create an API integration and name it.
2. Link an active Business Internet Banking user.
3. Select the API permissions (table below).
4. Review, accept the API terms, confirm with the SMS code.
5. Receive `client_id` and `client_secret`. If the admin linked another user, only that user can
   view and copy them on the API Integration page.

| Permission | Unlocks | Token scope for the same services |
|---|---|---|
| Viewing transaction history and account statements | movements, statements, balances | `bab_accounts` |
| Transaction initiation | transfer import, status, ID lookup | `bab_transfers` |

The linked user must also hold the matching action right inside Business Internet Banking itself.
No page mentions an IP allowlist or any agreement beyond the API terms accepted in step 4.

---

## 3. Authentication

OAuth 2.0 **client credentials**. Every BIS call needs a bearer token.

```http
POST {BASE_URL}/oauth/token
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&scope=bab_accounts bab_transfers
```

| Body parameter | Required | Value |
|---|---|---|
| `grant_type` | yes | `client_credentials` |
| `scope` | yes | `bab_accounts`, `bab_transfers`, or both, space-separated |

| Scope | Covers |
|---|---|
| `bab_accounts` | movements, movement by ID, statement, balance |
| `bab_transfers` | single and batch import, status, ID lookups |

Token response:

| Field | Meaning |
|---|---|
| `access_token` | the bearer token |
| `token_type` | `Bearer` |
| `scope` | scopes granted to this token, space-separated |
| `issued_at` | issue time, Unix seconds |
| `expires_in` | lifetime in seconds |

- Send `Authorization: Bearer {access_token}` on every call.
- A token lives **1 hour**. Then request a new one; the pages describe no refresh token.
- Missing, invalid or expired token: `401 Unauthorized`.
- The page shows only the test token URL; production follows the base-URL rule
  (`https://api.tbcbank.ge/oauth/token`).

**Module** - `authenticate` ([services/tbc_bank_service.py:50](services/tbc_bank_service.py#L50))
always asks for both scopes (`SCOPES`, line 24) and does not read the granted `scope`. The token is
cached on the connection and renewed 60 s before expiry
(`gec_bank` `gec.bank.oauth.mixin.token_is_valid`). A 401 clears it and re-authenticates
once before retrying the call ([services/tbc_bank_service.py:159](services/tbc_bank_service.py#L159)).

---

## 4. Endpoints and module coverage

| # | Method | Path | Scope | Module method | Used by |
|---|---|---|---|---|---|
| A0 | POST | `/oauth/token` | - | [`authenticate`](services/tbc_bank_service.py#L50) | every call, Test Connection |
| A1 | GET | `/bab/v1/accounts/movements` | `bab_accounts` | [`get_account_movements`](services/tbc_bank_service.py#L207), [`fetch_all_movements`](services/tbc_bank_service.py#L244) | Import Statement wizard; daily sync cron |
| A2 | GET | `/bab/v1/accounts/movements/{id}` | `bab_accounts` | - | not implemented |
| A3 | GET | `/bab/v1/accounts/statements` | `bab_accounts` | [`get_account_statement`](services/tbc_bank_service.py#L227) | statement snapshots, cron every 2 h |
| A4 | GET | `/bab/v1/accounts/{iban}/balances/{currency}` | `bab_accounts` | - | not implemented |
| T1 | POST | `/bab/v1/transfers/single` | `bab_transfers` | [`import_single_transfer`](services/tbc_bank_service.py#L274) | Send to TBC; batch payments and payroll, one request per payment |
| T2 | POST | `/bab/v1/transfers/batch` | `bab_transfers` | not implemented | - |
| T3 | GET | `/bab/v1/transfers/single/{transferId}/status` | `bab_transfers` | [`get_single_transfer_status`](services/tbc_bank_service.py#L283) | Refresh Status; hourly poll cron |
| T4 | GET | `/bab/v1/transfers/batch/{batchId}/status` | `bab_transfers` | not implemented | - |
| T5 | GET | `/bab/v1/transfers/single/{transferExternalId}` | `bab_transfers` | [`get_single_transfer_by_external_id`](services/tbc_bank_service.py#L279) | Recover from TBC; duplicate-request handling |
| T6 | GET | `/bab/v1/transfers/batch/{batchTransferExternalId}` | `bab_transfers` | not implemented | - |

- In use: A0, A1, A3, T1, T3, T5. Implemented, never called: T2, T4, T6. Not implemented: A2, A4.
- T3 and T5 share a prefix: T5 takes **your** `transferExternalId`, T3 takes the **bank's**
  `transferId` plus `/status`. Calling T5 with a bank id asks for the wrong thing.

---

## 5. Account movements

`GET /bab/v1/accounts/movements` - the account's transactions, paged (at most 700 per page), with
the total count of matches.

### Query parameters

| Parameter | Type | Notes |
|---|---|---|
| `AccountNumber` | string | IBAN |
| `AccountCurrencyCode` | string | required when `AccountNumber` is given |
| `PeriodFrom` | date-time | period start |
| `PeriodTo` | date-time | period end |
| `LastMovementTimeStamp` | date-time | movements after this moment |
| `PageIndex` | integer | starts at 0 |
| `PageSize` | integer | maximum 700 |

### Allowed filter combinations

| Filters | Result |
|---|---|
| `PeriodFrom` + `PeriodTo` + paging | movements in the period, no account filter |
| `AccountNumber` + `AccountCurrencyCode` + `PeriodFrom` + `PeriodTo` + paging | one account in one currency |
| `AccountNumber` without `AccountCurrencyCode` | validation error |
| `LastMovementTimeStamp` + paging | movements after the timestamp |
| `LastMovementTimeStamp` + any other filter | not allowed |

The sandbox also answers paging alone (scenario 5 in [section 11](#11-sandbox-test-data)).

### Response

| Field | Type | Notes |
|---|---|---|
| `transactions` | array of Movement | |
| `pager` | array of `{pageIndex, pageSize}` | an array, not an object |
| `total` | integer | all movements matching the filter, across pages |

### Movement object

| Field | Type | Meaning |
|---|---|---|
| `movementId` | string | Unique movement id, e.g. `018745219864.1`. In the sandbox the suffix `.1` is the debit side, `.2` the credit side |
| `paymentId` | string / null | Filled only for transfers created through the API, so the ERP can recognise its own transfers. `null` for everything else and for anything before February 2024 |
| `externalPaymentId` | string | Payment-order id when a non-digital channel created the movement: POS terminal, PAYBOX, ATM, cash desk |
| `amount` | number | Positive in TBC's example; the direction comes from `isDebit` |
| `currency` | string | ISO code |
| `isDebit` | boolean | `true` = money left the account |
| `purpose` | string | Payment purpose |
| `date` | date-time | Transaction date |
| `documentDate` | date-time | Document date |
| `documentNumber` | string / null | Document number |
| `customerAccountInfo` | object | Own account: `accountName`, `accountIban` |
| `partnerAccountInfo` | object | Counterparty, table below |
| `additionalInformation` | string / null | Free text; TBC's example packs partner name, BIC, IBAN and invoice number into it |
| `additionalDescription` | string / null | Additional description |
| `exchangeRate` | string / null | Only on conversions |
| `opCode` | string / null | Operation code (example `GIB`); no code list is published |
| `transactionType` | integer | Table below |
| `statusCode` | integer | Authorization status, table below |
| `transactionReference` | string / null | Transaction reference |
| `parentExternalPaymentId` | integer | On a commission line: links it to the main transaction (`0` in the example) |
| `chargeDetail` | string / null | SWIFT charges: `SHA` or `OUR` |
| `taxpayerCode`, `taxpayerName` | string / null | Taxpayer id and name |
| `intermediaryBankCode`, `intermediaryBankName` | string / null | Intermediary bank, when there is one |

`partnerAccountInfo` (all string / null, except `docTypeId` integer / null):

| Field | Meaning |
|---|---|
| `accountIban` | counterparty IBAN |
| `bankCode`, `bankName` | counterparty bank, e.g. `TBCBGE22`, `JSC TBC Bank` |
| `partnerName` | counterparty name |
| `taxCode` | counterparty tax / identification code |
| `treasuryCode` | treasury code on budget payments |
| `docTypeId` | ID document type, cash operations only (table below) |
| `personalNumber` | personal number, cash operations only |
| `documentNumber` | ID document number, cash operations only |

`transactionType`:

| Code | Meaning |
|---|---|
| 1 | Transfer between own accounts |
| 5 | Currency conversion |
| 20 | Credit / incoming |
| 30 | Outgoing transfer or cash withdrawal |
| 31 | Utility payment, mobile top-up, fine and similar |
| 32 | Budget (treasury) transfer |
| 33 | Other expense, including commission |

`statusCode`:

| Code | Meaning |
|---|---|
| 0 | Authorized |
| 1 | Waiting for second authorization |
| 2 | Waiting for authorization |

`docTypeId` (there is no code 7):

| Code | Document | Code | Document |
|---|---|---|---|
| 0 | Without passport | 12 | ID card - residence permit |
| 1 | Georgian citizen ID | 13 | Georgian living abroad ID |
| 2 | Georgian citizen passport | 14 | Diplomatic card |
| 3 | Foreign citizen passport | 15 | Neutral ID |
| 4 | Permanent residence permit ID | 16 | Neutral travel document |
| 5 | Soviet Union passport | 17 | Travel document |
| 6 | Birth certificate | 18 | Diplomatic passport, Georgian citizen |
| 8 | Refugee ID | 19 | Job passport, Georgian citizen |
| 9 | IDP temporary document | 20 | Temporary ID card |
| 10 | Temporary ID, Georgian citizen | 21 | Unidentified |
| 11 | ID card | 22 | ID card - temporary residence permit, electronic |

### Old SOAP service to REST

For integrations built on the old SOAP `GetAccountMovements`. Renamed or moved fields:

| SOAP | REST |
|---|---|
| `debitCredit` | `isDebit` |
| `valueDate` | `date` |
| `description` | `purpose` |
| `amount.amount` / `amount.currency` | `amount` / `currency` |
| `accountNumber` / `accountName` | `customerAccountInfo.accountIban` / `.accountName` |
| `partnerAccountNumber` | `partnerAccountInfo.accountIban` |
| `partnerName` | `partnerAccountInfo.partnerName` |
| `partnerTaxCode` | `partnerAccountInfo.taxCode` |
| `partnerBankCode` / `partnerBank` | `partnerAccountInfo.bankCode` / `.bankName` |
| `treasuryCode` | `partnerAccountInfo.treasuryCode` |
| `partnerPersonalNumber` | `partnerAccountInfo.personalNumber` |
| `partnerDocumentType` | `partnerAccountInfo.docTypeId` |
| `partnerDocumentNumber` | `partnerAccountInfo.documentNumber` |
| `operationCode` | `opCode` |
| `intermediaryBank` | `intermediaryBankName` |

All other fields keep their name. `transactionReference` exists only in REST.

### Module

Always filters by account + currency + period, `PageSize` 700; stops on a short page or once
`total` is reached and refuses to go past 200 pages
([services/tbc_bank_service.py:244](services/tbc_bank_service.py#L244)). Odoo's UTC period is
converted to Asia/Tbilisi local time before sending
([services/tbc_bank_service.py:220](services/tbc_bank_service.py#L220)).

Movement to statement line ([wizard/tbc_statement_import_wizard.py:91](wizard/tbc_statement_import_wizard.py#L91)):

| Movement | Statement line |
|---|---|
| `movementId` | `unique_import_id` = `tbcbank-<journal id>-<movementId>` (re-imports are skipped) |
| `amount` + `isDebit` | `amount`, negative when `isDebit` |
| `documentDate`, else `date` | `date` |
| `purpose` | `payment_ref` |
| `partnerAccountInfo.partnerName` | `partner_name` |
| `partnerAccountInfo.accountIban` | `account_number` |
| `documentNumber`, else `movementId` | `ref` |
| `paymentId` | `gec_bank_match_keys`, which confirms the sent payment (gec_bank `account_bank_statement_line.py`, `_gec_bank_auto_match`; keys `gec_bank_reference`, `gec_bank_request_id`) |
| `statusCode` not 0 | not imported; a later import picks it up once authorized |

The daily cron re-imports the last 7 days for each TBC journal
([models/tbc_connection.py:57](models/tbc_connection.py#L57)). `LastMovementTimeStamp` is not
used: it cannot be combined with `AccountNumber`, so a per-journal import would have to split its
result by `customerAccountInfo.accountIban` and `currency`.

---

## 6. Movement by ID, statement, balance

### Movement by ID (A2)

`GET /bab/v1/accounts/movements/{id}` - `id` is a `movementId`, e.g. `018745219864.1`.

The response wraps one Movement ([section 5](#movement-object)) in `transaction` (singular):
`{"transaction": {"movementId": "018745219864.1", ...}}`.

**Module** - not implemented.

### Account statement (A3)

`GET /bab/v1/accounts/statements` - balances and turnover for one account, currency and period.

All four parameters are required: `AccountNumber`, `AccountCurrencyCode`, `PeriodFrom`, `PeriodTo`
(date-time).

| Field | Type | Meaning |
|---|---|---|
| `openingDate` | date-time | period start |
| `openingBalance` | number | opening balance at `openingDate` (TBC: "booked/available") |
| `closingDate` | date-time | period end |
| `closingBalance` | number | closing available balance at `closingDate` |
| `creditSum` | number | total credits in the period |
| `debitSum` | number | total debits in the period |
| `currency` | string | account currency |
| `accountNumber` | string | IBAN |

In TBC's example `closingBalance = openingBalance + creditSum - debitSum`
(0 + 10172.60 - 10181.50 = -8.90), so the summary can check that an imported period is complete.

**Module** - `get_account_statement` sends `PeriodFrom` at `T00:00:00` and `PeriodTo` at
`T23:59:59` so the last day is included ([services/tbc_bank_service.py:227](services/tbc_bank_service.py#L227));
results are stored as statement snapshots, month to date every 2 hours
([models/tbc_statement.py:64](models/tbc_statement.py#L64)).

### Account balance (A4)

`GET /bab/v1/accounts/{iban}/balances/{currency}`

| Field | Type | Meaning |
|---|---|---|
| `currentBalance` | number | balance recorded on the account |
| `availableBalance` | number | amount usable now |
| `overdraftLimit` | number / null | approved overdraft; `null` when there is none |
| `currency` | string | account currency |

Show `availableBalance` as returned. TBC says not to compute it from `currentBalance` and
`overdraftLimit`: blocks and other restrictions also reduce it (sandbox EUR: current 50000,
available 42000, no overdraft).

**Module** - not implemented.

---

## 7. Transfer types and fields per type

The API only **creates** the order in Business Internet Banking. Whether and when it executes
depends on the signing and authorization rules set there, so an order can wait in
`Waiting for certification` until someone signs it.

| `transferType` | Meaning | Module `tbc_transfer_type` |
|---|---|---|
| `TransferToOwnAccount` | between the company's own accounts | `own` |
| `TransferWithinBank` | to another TBC account | `internal` |
| `TransferToOtherBankNationalCurrency` | to another bank, in GEL | `national` |
| `TransferToOtherBankForeignCurrency` | to another bank, in a foreign currency (SWIFT) | `foreign` |
| `TreasuryTransfer` | to the State Treasury | `treasury` |
| "TreasuryTransfer instead of 3rd person" | treasury payment for someone else; TBC's example sends `TreasuryTransfer` with `taxpayerCode` / `taxpayerName` | `treasury` + Taxpayer fields |

### Fields per type

**R** required by a stated rule - **E** in every TBC example of the type and marked "depends on
type", treat as required - **O** optional - **-** not used or never shown for the type.

| Field | Own | Within TBC | Other bank GEL | Other bank FX | Treasury |
|---|---|---|---|---|---|
| `transferType` | R | R | R | R | R |
| `debitAccount` (single only; batch has it once at the top) | R | R | R | R | R |
| `amount` (`amount` > 0, `currency`) | R | R | R | R | R, GEL only |
| `creditAccount` | E | E | E | E | - (not used) |
| `description`, max 140 | E | E | E | E | E |
| `additionalDescription`, max 210 | O | O | O | O | O |
| `beneficiaryName` | - | O | E | R | - |
| `beneficiaryTaxCode` | - | O | E | - | - |
| `beneficiaryAddress` | - | - | - | R | - |
| `beneficiaryBankCode` | - | - | O | R | - |
| `beneficiaryBankName` | - | - | O | O | - |
| `intermediaryBankCode`, `intermediaryBankName` (single only) | - | - | - | O | - |
| `chargeDetails`: `SHA` or `OUR` | - | - | - | R | - |
| `treasuryCode`, 9 digits | - | - | - | - | R |
| `taxpayerCode`, `taxpayerName` | - | - | - | - | O, third-person payment |
| `transferExternalId` (single only) | O | O | O | O | O |
| `documentNumber` (integer) | O | O | O | O | O |
| `position` (integer) | O | O | O | O | O |

For FX the rule says "beneficiary details and chargeDetails are required"; name, address and bank
code are the beneficiary fields marked "depends on type".

`debitAccount` / `creditAccount` are `{"accountNumber": IBAN, "accountCurrencyCode": ISO}`;
`amount` is `{"amount": number, "currency": ISO}`. All four inner fields are required.

**Module**

- Type from the recipient account ([models/account_payment.py:89](models/account_payment.py#L89)):
  TBC IBAN, company's own account -> `own`; TBC IBAN, anyone else -> `internal`; other Georgian
  IBAN in GEL -> `national`; anything else -> `foreign`. No account (treasury) keeps the chosen
  type, `national` by default.
- Checked before anything is sent ([models/account_payment.py:314](models/account_payment.py#L314)):
  amount > 0; treasury in GEL with a 9-digit code; FX name, address, bank code and SHA/OUR;
  IBAN bank code consistent with the type.
- Order built in [models/account_payment.py:420](models/account_payment.py#L420): `description`
  from the memo (cut to 140), `additionalDescription` cut to 210, `beneficiaryTaxCode` only on
  `national`, treasury drops `creditAccount` and `beneficiaryName`, empty keys are removed.
  `debitAccount.accountCurrencyCode` is the journal currency, `amount.currency` the payment currency.

---

## 8. Import single and batch transfers

### Single transfers (T1)

`POST /bab/v1/transfers/single` with `{"singleTransferOrders": [ ... ]}`, 1 to 10 orders.

Rules:

| Rule | Detail |
|---|---|
| Orders | array required, not empty, at most 10 |
| `transferExternalId` | optional; unique within the request |
| Repeated request | a request already received with the same id returns 400 `DUPLICATED_SINGLE_TRANSFER_REQUEST` |
| `position` | on all orders or on none; unique; greater than 0 |
| `description` / `additionalDescription` | max 140 / 210 characters |
| Treasury | GEL, 9-digit `treasuryCode` |
| FX to another bank | beneficiary details and `chargeDetails` (`SHA` / `OUR`) |
| Partial acceptance | invalid orders are rejected, valid ones still go to Internet Banking |

Request (sandbox accounts):

```json
{
  "singleTransferOrders": [
    {
      "transferType": "TransferWithinBank",
      "transferExternalId": "12345",
      "position": 1,
      "debitAccount":  {"accountNumber": "GE29TB7777777777777777", "accountCurrencyCode": "GEL"},
      "creditAccount": {"accountNumber": "GE29TB9999999999999999", "accountCurrencyCode": "GEL"},
      "amount": {"amount": 3.45, "currency": "GEL"},
      "description": "Transfer within TBC",
      "additionalDescription": "Test transfer"
    }
  ]
}
```

Type-specific parts:

| Type | Change to the order above |
|---|---|
| Other bank GEL | `creditAccount` `GE90BG0000000589021505`; add `"beneficiaryName": "Test Beneficiary"`, `"beneficiaryTaxCode": "12345678901"` |
| Other bank FX | debit, credit and amount in `EUR`; `creditAccount` `CZ6508000000192000145399`; add `beneficiaryName`, `beneficiaryAddress`, `"beneficiaryBankCode": "0800"`, `beneficiaryBankName`, `"chargeDetails": "SHA"`; intermediary fields optional |
| Treasury | remove `creditAccount`; GEL; add `"treasuryCode": "101001000"`; for a third person also `"taxpayerCode": "123456789"`, `"taxpayerName": "..."` |

Response - **HTTP 207 Multi-Status** instead of 201, so accepted and rejected orders come back in
one answer:

```json
{
  "succeeded": [{"position": 1, "transferId": 19806}],
  "failed":    [{"position": 2, "errors": ["..."]}]
}
```

| Field | Content |
|---|---|
| `succeeded[]` | `position`, `transferId` (integer, the bank's id) - the field table calls the array `succeed` |
| `failed[]` | `position`, `errors` (array of strings); TBC says each rejection names an error code and a reason |

**Module** - one order per request, 60 s timeout
([services/tbc_bank_service.py:274](services/tbc_bank_service.py#L274)). The `transferExternalId`
(a random numeric string under 10^9) and the state `sending` are committed on their own cursor
before the call ([models/account_payment.py:216](models/account_payment.py#L216)), so a crash
cannot lead to a resend with a new id. The module never relies on TBC to refuse a resend: the
sandbox accepted the same id twice ([section 12](#12-where-tbcs-pages-contradict-themselves),
#14). Outcome handling
([models/account_payment.py:221](models/account_payment.py#L221)):

| TBC answer | Payment `gec_bank_state` |
|---|---|
| no response, timeout, 5xx | `unknown` - only Recover from TBC may decide |
| 400 `DUPLICATED_SINGLE_TRANSFER_REQUEST` | `unknown`, then T5 lookup at once ([line 286](models/account_payment.py#L286)) |
| other 4xx | `failed`, payment set to Rejected |
| 207, `failed[]` mentions a duplicate | as the duplicate row |
| 207, `failed[]` | `failed` |
| 207, `succeeded[0].transferId` | `sent`; in Direct mode the status is refreshed right away |
| 207 without a `transferId` | `unknown` |

### Batch transfer (T2)

`POST /bab/v1/transfers/batch` - one batch per request, up to 1000 orders, one common debit account.

| Field | Type | Required | Notes |
|---|---|---|---|
| `batchTransferExternalId` | string / integer | no | your id; used by the T6 lookup |
| `batchName` | string | no | |
| `debitAccount` | `{accountNumber, accountCurrencyCode}` | yes | common to all orders |
| `transferOrders` | array of TransferOrder | yes | 1 to 1000 |
| `validateReceiverIdentifier` | string | no | "receiver identifier validation"; values not documented |

A TransferOrder carries the single-order fields except `transferExternalId`, `debitAccount`,
`intermediaryBankCode` and `intermediaryBankName`.

Rules: `debitAccount` required; orders not empty, at most 1000; `position` on all or none; account
and ISO currency formats are validated; type rules as in [section 7](#7-transfer-types-and-fields-per-type).

Response - **201 Created**: `{"batchTransferId": 184729}`.

Not stated: whether a repeated `batchTransferExternalId` is refused, and whether one invalid order
rejects the whole batch ([Q4, Q5](#13-open-questions)).

**Module** - no batch call is implemented. Batch payments and payroll send one T1 request per payment
([models/account_batch_payment.py:22](models/account_batch_payment.py#L22)), so each payment keeps
its own `transferId` and idempotency key.

---

## 9. Transfer status and ID lookup

### Status (T3, T4)

`GET /bab/v1/transfers/single/{transferId}/status` - `transferId` from T1 or T5.
`GET /bab/v1/transfers/batch/{batchId}/status` - `batchId` = `batchTransferId` from T2, or from T6.

| Field | Type | Content |
|---|---|---|
| `status` | string | overall status |
| `singleTransferData` | TransferStatusData | single transfer |
| `batchTransferData` | array of TransferStatusData | one entry per batch order |

TransferStatusData:

| Field | Type | Content |
|---|---|---|
| `position` | integer | order position from the request |
| `transferId` | string | the bank's transfer / payment id (a string here, an integer elsewhere) |
| `transferStatus` | string | status of this order |
| `errorDetailEN`, `errorDetailGE` | string / null | error detail in English / Georgian |
| `failureReasonEn`, `failureReasonGe` | string / null | failure reason in English / Georgian |

The four error fields are filled when processing cannot finish or an upstream system adds detail.
Mind the casing: `EN`/`GE` versus `En`/`Ge`.

Single transfer statuses:

| Status | Meaning | Module `gec_bank_state` |
|---|---|---|
| `Initial state` | created | stays `sent` |
| `Draft` | saved as draft | stays `sent` |
| `Registered` | registered | stays `sent` |
| `Waiting for certification` | waiting for signature / authorization in Internet Banking | stays `sent` |
| `In progress` | processing | stays `sent` |
| `Finished` | completed | `confirmed` |
| `Error` | error | `failed` |
| `Failed` | failed | `failed` |
| `Cancelled` | cancelled | `failed` |
| `Deleted` | deleted | `failed` |
| `Completed` | only in TBC's example, in no table | `confirmed` |

Batch statuses: `Uploading`, `Registered`, `Waiting for certification`, `In progress`, `Finished`,
`Finished with errors` (one or more orders failed), `Failed`, `Cancelled`, `Error`.

**Module** - `_tbc_refresh_status` ([models/account_payment.py:468](models/account_payment.py#L468))
reads the top-level `status` first, then `singleTransferData.transferStatus`; the error text is
`errorDetailEN`, else `failureReasonEn`. Status sets at
[models/account_payment.py:29](models/account_payment.py#L29). The hourly cron polls `sent` and
`unknown` payments that have a `transferId` ([line 497](models/account_payment.py#L497)). Batch
status is not used.

### ID lookup (T5, T6)

For an import that reached TBC while its response was lost (timeout, crash):

| Call | Response |
|---|---|
| `GET /bab/v1/transfers/single/{transferExternalId}` | `{"transferId": 502341}` (integer) |
| `GET /bab/v1/transfers/batch/{batchTransferExternalId}` | `{"batchId": 184729}` (integer, the same number T2 returned as `batchTransferId`) |

An id TBC never received is documented as `404 ObjectNotFound`; the sandbox answered `400` with the
title `external id is not found` ([models/account_payment.py:37](models/account_payment.py#L37)).

**Module** - Recover from TBC ([models/account_payment.py:382](models/account_payment.py#L382))
treats either answer as "never received, safe to resend" ([line 401](models/account_payment.py#L401));
a found `transferId` moves the payment to `sent` and refreshes its status. A payment still
`sending` is refused for 15 minutes (`TBC_SENDING_STALE_MINUTES`,
[line 394](models/account_payment.py#L394)): its request may still reach TBC, and a "not found"
read before it arrives would allow a second transfer that the sandbox does not refuse.

---

## 10. Errors

Errors from Accounts and Transfers come as `application/problem+json`:

| Field | Type | Content |
|---|---|---|
| `type` | string | error type URI, e.g. `/error-codes#ValidationError` |
| `title` | string | error title |
| `status` | integer | HTTP status |
| `detail` | string / null | extra description |
| `code` | string | error code |
| `traceId` | string | request id; quote it when asking TBC to investigate |
| `errors` | object / null | messages per field, e.g. `{"PageSize": ["PageSize must be between 0 and 700."]}` |
| `objectType`, `objectId` | string / null | 404 only: what was not found |

Where the specific error is:

- **Accounts**: in `title` (`INCORRECT_INPUT_DATA`, `USER_IS_BLOCKED`, ...); `code` holds the
  category (`ValidationError`, `DomainError`, ...).
- **Transfers**: in `code` (`DUPLICATED_SINGLE_TRANSFER_REQUEST`, `VALIDATION_ERROR`, ...);
  `title` is readable text.

Accounts:

| HTTP | `code` | `title` | Meaning |
|---|---|---|---|
| 400 | `ValidationError` | `INCORRECT_INPUT_DATA` | request parameters wrong |
| 400 | `DomainError` | `INVALID_ACCOUNT` | account and currency not found or not available |
| 400 | `DomainError` | `USER_IS_DELETED` | integration user does not exist or is deleted |
| 400 | `DomainError` | `USER_IS_NOT_ACTIVE` | integration user not active |
| 400 | `DomainError` | `USER_IS_BLOCKED` | integration user blocked |
| 403 | `ForbiddenError` | `NOT_AUTHORIZED` | the user lacks this permission in Business Internet Banking |
| 500 | `SystemError` | `GENERAL_ERROR` | system error |

Transfers:

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `ValidationError` | body, query parameter or a field is wrong |
| 400 | `DUPLICATED_SINGLE_TRANSFER_REQUEST` | this single-transfer request was already received |
| 400 | `VALIDATION_ERROR` | business validation failed |
| 400 | `DomainError` | domain validation failed |
| 401 | `Unauthorized` | token missing, invalid or expired |
| 404 | `ObjectNotFound` | transfer, batch or request id not found |
| 500 | `SystemError` | system error |
| 500 | `ApplicationError` | application logic error |

**Module**

- `USER_IS_BLOCKED`, `USER_IS_NOT_ACTIVE`, `USER_IS_DELETED` in `title` set the connection to
  Blocked, written durably ([services/tbc_bank_service.py:191](services/tbc_bank_service.py#L191)).
- 401 -> one re-authentication and retry ([services/tbc_bank_service.py:159](services/tbc_bank_service.py#L159)).
- `DUPLICATED_SINGLE_TRANSFER_REQUEST` -> duplicate path ([section 8](#single-transfers-t1)).
- Every request and response, secrets redacted, is in TBC Bank -> API Logs, `traceId` included.

---

## 11. Sandbox test data

Mocked: only these exact requests return the listed results. [TESTING.md](TESTING.md) uses the
same accounts.

### Accounts

Account `GE48TB7873440574631292`. Movements (`GET /bab/v1/accounts/movements?...`):

| # | Query | Expected |
|---|---|---|
| 1 | `AccountNumber=GE48TB7873440574631292&AccountCurrencyCode=GEL&PeriodFrom=2026-06-01&PeriodTo=2026-06-30&PageIndex=0&PageSize=100` | 200, 11 GEL movements |
| 2 | same with `AccountCurrencyCode=USD` | 200, 20 USD movements |
| 3 | `PeriodFrom=2026-02-01&PeriodTo=2026-06-30&PageSize=20&PageIndex=0`, `1`, `2` | 20, 15, 0 records; `total` 35 |
| 4 | `PeriodFrom=2026-02-01&PeriodTo=2026-06-30&PageIndex=0&PageSize=100` | 200, 60 movements |
| 5 | `PageIndex=0&PageSize=100` | 200, 60 movements |
| 7 | `GET .../movements/018383341565.1` | 200, one movement |
| 8 | `GET .../movements/018716808825.1` and `.2` | the debit and the credit side |
| 9 | `LastMovementTimeStamp=2026-06-09&PageIndex=0&PageSize=100` | 200, 50 movements |
| 10 | `PeriodFrom=2025-01-01&PeriodTo=2025-01-31&PageIndex=0&PageSize=100` | 200, `transactions` empty, `total` 0 |
| 11 | `PeriodFrom=2024-01-01&PeriodTo=2024-01-31&PageIndex=0&PageSize=100` | 403 `NOT_AUTHORIZED` |
| 12 | `PeriodFrom=2024-02-01&PeriodTo=2024-03-31&PageIndex=0&PageSize=100` | 500 `GENERAL_ERROR` |
| 13 | movements call with TBC's inactive test client (its id and secret are on the [Test Scenarios - Accounts](https://developers.tbcbank.ge/docs/bis-test-scenarios-accounts) page) | 400 `USER_IS_NOT_ACTIVE` |

The page has no scenario 6.

Statement: `GET /bab/v1/accounts/statements?AccountNumber=GE48TB7873440574631292&AccountCurrencyCode=GEL&PeriodFrom=2025-01-01&PeriodTo=2025-03-01`
(also with `USD`) -> 200 with balances and sums.

Balance (`GET /bab/v1/accounts/GE48TB7873440574631292/balances/{currency}`):

| Currency | `currentBalance` | `availableBalance` | `overdraftLimit` | Case |
|---|---|---|---|---|
| GEL | 50000 | 50000 | `null` | plain account |
| USD | 40000 | 140000 | 100000 | overdraft |
| EUR | 50000 | 42000 | `null` | blocked funds |

### Transfers

Debit accounts allowed: `GE29TB7777777777777777` and `GE29TB9999999999999999`, each in GEL, USD,
EUR. Credit accounts in TBC's scenarios: `GE29TB9999999999999999`, `GE90BG0000000589021505`
(other bank), `CZ6508000000192000145399` (foreign), `GE44TB0600051509630891` and
`GE41TB7849963286076183` (batch).

| # | Call | Key values | Expected |
|---|---|---|---|
| 1 | T1 `TransferToOwnAccount` | `...7777` -> `...9999`, 3.45 GEL | 207, `transferId` 19827 |
| 2 | T1 `TransferWithinBank` | `...7777` -> `...9999`, 3.45 GEL | 207, 19806 |
| 3 | T1 `TreasuryTransfer` | 1 GEL, `treasuryCode` 101001000 | 207, 19808 |
| 4 | T1 `TreasuryTransfer`, third person | + `taxpayerCode` 123456789, `taxpayerName` | 207, 19811 |
| 5 | T1 `TransferToOtherBankNationalCurrency` | -> `GE90BG0000000589021505`, 100 GEL, `beneficiaryTaxCode` 12345678901 | 207, 19801 |
| 6 | T1 `TransferToOtherBankForeignCurrency` | EUR -> `CZ6508000000192000145399`, 1 EUR, bank code 0800, `SHA` | 207, 19802 |
| 7 | T1 with 3 orders | within TBC, own, other bank GEL | 207, 4 results (mock) |
| 8 | T2 batch, 3 orders | debit `...7777` GEL | 201, `batchTransferId` 3364 |
| 9 | T3 `GET /bab/v1/transfers/single/19806/status` | | overall status and `singleTransferData` |
| 10 | T4 `GET /bab/v1/transfers/batch/3364/status` | | overall status and `batchTransferData` |
| 11 | T5 `GET /bab/v1/transfers/single/12345` | | `transferId` |
| 12 | T6 `GET /bab/v1/transfers/batch/12345` | | `batchId` |

---

## 12. Where TBC's pages contradict themselves

| # | Page | Contradiction | Read it as / module |
|---|---|---|---|
| 1 | Import Single Transfer | success array is `succeed` in the field table, `succeeded` in every example | read both - module does |
| 2 | Get Transfer Status | tables say `Finished`; the example returns `Completed`, which is in no table | treat both as success - module does |
| 3 | Transfer types | "TreasuryTransfer instead of 3rd person" listed as a type; the example sends `TreasuryTransfer` + taxpayer fields | send `TreasuryTransfer` - module does |
| 4 | Single-transfer rules | duplicate rule speaks of `requestId`, a field the request does not have | the lookup pages use "requestId" for `transferExternalId` |
| 5 | Errors vs sandbox | unknown external id: 404 `ObjectNotFound` in the docs, 400 `external id is not found` in the sandbox | accept both - module does |
| 6 | Several | `transferId` is an integer in T1/T5 and a string in status data; the batch id is `batchTransferId` in T2, `batchId` in T4/T6 | store ids as strings |
| 7 | Transfer examples | curly quotes in scenarios 3-6 and in the batch example, `batchTrasnferExternalId` misspelled, one order uses `transferexternalId` | the examples are not valid JSON as printed; use the field tables |
| 8 | Transfer scenario 7 | 3 orders in, 4 results out | mock data; do not assert result count = order count in the sandbox |
| 9 | Account scenarios 3 and 4 | same filter, same Feb-Jun 2026 period: `total` 35 with PageSize 20, but 60 movements with PageSize 100 | mock counts do not agree across scenarios; assert each scenario on its own |
| 10 | Transfer scenarios 9-12 | GET calls described as "201 OK" | probably 200 |
| 11 | Movement by ID | "returns the same Movement object" | it is wrapped in `{"transaction": ...}` |
| 12 | Failed orders | `errors` typed "array / string"; the callout promises an error code and a description per order | keep the raw text, do not parse a structure |
| 13 | Batch example | `beneficiaryBankCode` `TB` / "TBC Bank" on a Bank of Georgia IBAN (`GE90BG...`) | example values only |
| 14 | Single-transfer rules vs sandbox | a repeated `transferExternalId` returns 400 `DUPLICATED_SINGLE_TRANSFER_REQUEST`; in the sandbox the same id sent twice created two transfers ([TESTING.md](TESTING.md) section 3) | never count on TBC to refuse a resend; the module resends only after T5 answers "not found" and never while a send may still run ([Q10](#13-open-questions)) |

---

## 13. Open questions

None of the 19 pages answers these, or the sandbox contradicts the answer. Ask TBC, or test in the
sandbox where it can show the answer.

| # | Question | Why it matters | Module today |
|---|---|---|---|
| Q1 | Which time zone do `PeriodFrom`/`PeriodTo`, `date` and `documentDate` use? | a 4-hour shift moves movements across midnight | assumes Asia/Tbilisi ([services/tbc_bank_service.py:26](services/tbc_bank_service.py#L26)) |
| Q2 | Is a movement's `paymentId` the bank `transferId` or our `transferExternalId`? | auto-confirming sent payments from the statement | matches either (gec_bank `_gec_bank_auto_match`, keys from `account.journal._gec_bank_match_key_fields`) |
| Q3 | Token request with both scopes when the integration has only one permission: error, or a token with fewer scopes? | read-only production integrations | always asks for both, ignores the granted `scope` |
| Q4 | Is a repeated `batchTransferExternalId` refused like a single duplicate? | safe batch retry | batch import unused |
| Q5 | Does one invalid order reject the whole batch, or only that order? | batch error handling | batch import unused |
| Q6 | Is a cross-currency order allowed (debit account GEL, amount EUR), and is `amount.currency` the debit or the credit currency? | SWIFT from a GEL account | sends the journal currency as debit currency and the payment currency as amount ([models/account_payment.py:420](models/account_payment.py#L420)) |
| Q7 | What values does `validateReceiverIdentifier` take? | receiver-ID check on batches | not sent |
| Q8 | Which `opCode` values exist? | classifying movements | not used |
| Q9 | Are there rate limits or request quotas? | crons and large payroll runs | none documented; payroll sends one request per payment |
| Q10 | Does production refuse a repeated `transferExternalId` with `DUPLICATED_SINGLE_TRANSFER_REQUEST`, and how long does TBC remember an id? | the pages say yes, the sandbox does not; it is the only bank-side guard against paying twice | handles the code when it comes, does not rely on it; checked in production by [TESTING.md](TESTING.md) section 4, item 4 |

---

## 14. Module assumptions checked against the pages

What the pages settle about the assumptions the module was built on:

| Item | Answer |
|---|---|
| Transfer field names | documented ([sections 7-8](#7-transfer-types-and-fields-per-type)); the module's names match |
| `transferType` values | five values; `TBC_TRANSFER_TYPE_API` ([models/account_payment.py:20](models/account_payment.py#L20)) matches |
| Idempotency | documented: `transferExternalId` unique within a request, a repeat returns 400 `DUPLICATED_SINGLE_TRANSFER_REQUEST`, and T5 finds the transfer. Not so in the sandbox: the same id twice made two transfers ([section 12](#12-where-tbcs-pages-contradict-themselves), #14). The module handles the 400 but does not depend on it: it keeps one id per payment, resends only after T5 answers "not found", and refuses that lookup while a send may still run ([Q10](#13-open-questions)). For batches only the T6 lookup is documented |
| `transferExternalId` type ([models/account_payment.py:168](models/account_payment.py#L168)) | string; the lookup path accepts integer or string; the module's numeric string is valid either way |
| IP allowlist / agreement for the write scope | no page mentions an IP allowlist; transfers need the "Transaction initiation" permission, chosen when the integration is created in Business Internet Banking, plus the API terms accepted there with an SMS code |


---

## 15. Sources

All under `https://developers.tbcbank.ge/docs/`. Add `.md` to any URL for the raw page.

| Page | Slug | Updated |
|---|---|---|
| Overview | `bis-overview` | 2026-09-21 |
| Authentication | `bis-authentication` | 2026-09-21 |
| Test Environment | `bis-test-environment` | 2026-06-26 |
| Production Environment | `bis-production-environment` | 2026-09-21 |
| BIS - Accounts | `bis-accounts` | 2026-09-21 |
| Get Account Movements | `bis-get-account-movements` | 2026-06-26 |
| Get Account Movement By Id | `bis-get-account-movement-by-id` | 2026-06-26 |
| Get Account Statement | `bis-get-account-statement` | 2026-06-26 |
| Get Account Balance | `bis-get-account-balance` | 2026-09-22 |
| Mapping to the old SOAP service | `bis-account-movements-soap-rest-map` | 2026-06-26 |
| BIS - Transfers | `bis-transfers` | 2026-06-26 |
| Import Single Transfer | `bis-import-single-transfer` | 2026-09-24 |
| Import Batch Transfers | `bis-import-batch-transfers` | 2026-08-04 |
| Get Transfer Status | `bis-get-transfer-status` | 2026-08-04 |
| Get Single Transfer Id | `bis-get-single-transfer-id` | 2026-06-26 |
| Get Batch Transfer Id | `bis-get-batch-transfer-id` | 2026-06-26 |
| Errors | `bis-errors` | 2026-06-26 |
| Test Scenarios - Accounts | `bis-test-scenarios-accounts` | 2026-09-21 |
| Test Scenarios - Transfers | `bis-test-scenarios-transfers` | 2026-08-04 |

`bis-services` exists in the menu but is an empty heading page.
