# Bank of Georgia Business Online API reference

Bank of Georgia's **Business Online API**, as published on api.bog.ge, collected for `bog_bank`.
Each part notes where the module uses it.

| | |
|---|---|
| Source | 43 Business Online pages on api.bog.ge (40 in the menu, 3 reachable only by URL) and BOG's Postman collection v1.0.4 ([list](#18-sources)) |
| Collected | 2026-10-02 |
| Newest change | Postman collection v1.0.4, 2026-09-26. The pages carry no dates |
| Refresh a page | `curl -s https://api.bog.ge/docs/en/bonline/<slug>.md` returns the page as Markdown; drop `/en` for the Georgian page |
| Base URL | `https://api.businessonline.ge/api` |
| Token URL | `https://account.bog.ge/auth/realms/bog/protocol/openid-connect/token` |

Sections 1-13 state what BOG's pages say; **Postman** marks what only the collection says; lines
starting with **Module** describe this module as of 2026-10-02 19:45 (`models/account_payment.py`
was being edited in another session at the time, so re-check line links). Contradictions are in
[section 14](#14-where-bogs-sources-contradict-each-other), consequences for the module in
[section 15](#15-what-the-pages-change-for-this-module), open points in
[section 16](#16-open-questions-for-bog).

### Read first

What the pages say that the module does not do yet:

1. `Status` values are documented single letters (`P` Completed, `R` Rejected, `A` To be Signed,
   ...). The module's substring matching recognises none of them, and would read "Incomplete" as
   completed ([F1](#f1-statuses-are-letters)).
2. BOG refuses a repeated `UniqueId` only when the document carries `CheckUniqueId: true` (7 days,
   result code 702). The module never sends it, so a re-send after a timeout can create a second
   document ([F2](#f2-retries-are-not-deduplicated-without-checkuniqueid)).
3. Package status lines are in `DocumentStatuses[]`, keyed by `UniqueId`; the module reads them and
   matches by `UniqueId`, else `DocumentNo` ([F3](#f3-package-lines-never-reach-the-payments), fixed).
4. Foreign documents use `PaymentDetail` and `Charges`, not `Nomination` and `DispatchType`; the
   module sends the domestic shape and BOG drops the purpose
   ([F5](#f5-foreign-documents-are-sent-in-the-domestic-shape)).
5. A test environment exists on request (README: none), and rates allow 60 requests per minute
   (README: 1).

## Contents

1. [Environments and data format](#1-environments-and-data-format)
2. [App registration and credentials](#2-app-registration-and-credentials)
3. [Authentication](#3-authentication)
4. [Rate limits](#4-rate-limits)
5. [Endpoints and module coverage](#5-endpoints-and-module-coverage)
6. [Creating documents](#6-creating-documents)
7. [Package (bulk) transfers](#7-package-bulk-transfers)
8. [Status, cancellation, creation codes](#8-status-cancellation-creation-codes)
9. [Current day activities](#9-current-day-activities)
10. [Statements](#10-statements)
11. [Balance, rates, deposits, money request, file upload](#11-balance-rates-deposits-money-request-file-upload)
12. [Pages outside the menu](#12-pages-outside-the-menu)
13. [Statuses, result codes, error codes](#13-statuses-result-codes-error-codes)
14. [Where BOG's sources contradict each other](#14-where-bogs-sources-contradict-each-other)
15. [What the pages change for this module](#15-what-the-pages-change-for-this-module)
16. [Open questions for BOG](#16-open-questions-for-bog)
17. [README "Known unknowns", answered](#17-readme-known-unknowns-answered)
18. [Sources](#18-sources)

---

## 1. Environments and data format

| Environment | Base URL | Access | Money moves |
|---|---|---|---|
| Production | `https://api.businessonline.ge/api` | app registered in Business Online ([section 2](#2-app-registration-and-credentials)) | yes |
| Test | not published | "contact your business banking personal assistant or fill the application" (Introduction) | not stated |

- Full URL = base URL + path. The pages write paths as `api/documents/domestic`; the base URL
  already ends in `/api`, so the call is `https://api.businessonline.ge/api/documents/domestic`.
- RESTful, HTTP/1.1, HTTPS mandatory, synchronous calls, OAuth 2.0, JWT tokens.
- Documents, statements, balance and the older rate pages show JSON and XML; deposits, money
  request, file upload and rate details show JSON only. XML uses the .NET data-contract namespace
  `http://schemas.datacontract.org/2004/07/CIBApi.Models`.
- Casing in the JSON examples: documents, statuses, balance, V1 rates and the Documents-section
  current day activities use PascalCase (`UniqueKey`); Statement V2, the Statement-New current day
  activities, rate details and deposits use camelCase (`totalCount`). The V2 statement field lists
  are still written in PascalCase.
- Dates in bodies and responses carry the Tbilisi offset: `2021-06-17T10:31:50.2269037+04:00`.
  Dates in paths are `YYYY-MM-DD` (Georgian pages: "format: 2025-12-31").
- Response bodies are not always objects: an array (documents), a bare integer (package key), a
  bare quoted string (file hash), a bare decimal (NBG rate, cross rate), `201` with an empty body
  (money request), `200 OK` as the only documented answer (cancellations).
- Every response carries an `x-correlationid` header, also on `401` and `404` (Postman). Keep it;
  BOG support (`customerservice@bog.ge`) asks for it.
- **Postman**: v1.0.4 notes that `Nomination` sent on a foreign payment "was silently dropped".
  So a field the target model does not have can be ignored rather than rejected; that is one
  example, no page states it as a rule.

**Module** - hosts in [services/bog_service.py:16](services/bog_service.py#L16); no
Test/Production selector ([models/bog_connection.py:18](models/bog_connection.py#L18)) because the
README states there is no sandbox. The Introduction page says otherwise; the test host has to come
from BOG first.

---

## 2. App registration and credentials

1. The company has a Business Online account at bonline.bog.ge and credentials for it.
2. Register the application at `https://bonline.bog.ge/admin/api/`: application name, the name in
   an international language, a logo URL (https advised, at most 400x800) and, for a web client,
   the redirect URL.
3. The application details page then shows `client id`, `client secret` and, for web clients,
   `redirect uri`.

No page lists per-endpoint permissions, an IP allowlist, or whether documents created by the app
are signed by the app or by a person. **Postman** names two permission errors: `403` "you do not
have file upload permission" (file upload) and `403` "you do not have access to the account"
(money request).

---

## 3. Authentication

Three flows, all on the OpenID Connect endpoints of `account.bog.ge` (realm `bog`):

| Flow | Page | Parameter | User present | Module |
|---|---|---|---|---|
| Client credentials | Authentification using token | `grant_type=client_credentials` | no | used |
| Implicit | For a desktop application | `response_type=token` | yes, logs in in a browser | - |
| Authorization code | Authentification for a web application | `response_type=code`, then `grant_type=authorization_code` (Postman) | yes | - |

### Client credentials

```http
POST https://account.bog.ge/auth/realms/bog/protocol/openid-connect/token
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=<client_id>&client_secret=<client_secret>
```

The page asks for the credentials both in the body and in the Basic header. Every API call then
sends `Authorization: Bearer <access_token>`.

Token response. The client-credentials page lists no fields; the desktop and web pages list these,
and Postman 1.1.1 reads `access_token`, `expires_in` and `token_type` from the client-credentials
answer:

| Field | Meaning |
|---|---|
| `access_token` | the bearer token |
| `token_type` | `bearer` |
| `expires_in` | seconds the token is valid (typed "string") |
| `refresh_expires_in` | maximum lifetime of the refresh token |
| `not-before-policy` | revocation policy timestamp |
| `scope` | context the token is valid in |
| `app_id` | not used |
| `refresh_token` | authorization-code flow only (Postman 1.3.2) |

### Browser flows

`GET https://account.bog.ge/auth/realms/bog/protocol/openid-connect/auth?client_id=..&response_type=token|code&scope=corp&redirect_uri=..&kc_locale=ka`

- `kc_locale=ka` shows the login in Georgian; without it the page is English.
- Implicit: the redirect carries `access_token`, `expires_in`, `token_type` (Postman example:
  `expires_in=300`).
- Code: the redirect carries `code`. Exchange it with Basic auth and `grant_type=authorization_code`,
  `code`, `redirect_uri` (Postman 1.3.2; the pages say `client_credentials` here,
  [section 14](#14-where-bogs-sources-contradict-each-other) #14). The code is single-use. Refresh:
  `grant_type=refresh_token&refresh_token=..` with Basic auth (Postman 1.3.3).

Errors (Postman): wrong credentials -> `401` from the token URL; expired or malformed bearer ->
`401` from the API.

**Module** - [`authenticate`](services/bog_service.py#L81) sends body and Basic header as the page
does; `expires_in` is read, 300 s if absent ([services/bog_service.py:29](services/bog_service.py#L29));
the token is renewed 60 s early ([models/bog_connection.py:76](models/bog_connection.py#L76)); a
`401` gets one new token and one retry ([services/bog_service.py:258](services/bog_service.py#L258)).

---

## 4. Rate limits

| Applies to | Limit |
|---|---|
| every method | 5 requests per second per client (application) |
| `api/rates/*`, `api/v2/rates/{currency}` | 60 requests per minute per method |
| current day activities | 800 requests per day per account and currency |

- Counted per application and per method, sliding window.
- Over the limit: `429 Too Many Requests` with `Retry-After` in seconds.
- The Introduction table names the activities path `api/v2/documents/todayactivities/...`; the
  Documents-section page puts the same note on the unversioned path.
- **Postman** says rates allow "1 request per minute per method"
  ([section 14](#14-where-bogs-sources-contradict-each-other) #1).

**Module** - `_throttle` keeps one worker at 5 per second
([services/bog_service.py:164](services/bog_service.py#L164)); a `429` is retried once after
`Retry-After`, at most 60 s ([services/bog_service.py:252](services/bog_service.py#L252)). The pages
say 60 per minute.

---

## 5. Endpoints and module coverage

Paths are relative to the base URL.

| # | Method | Path | Module method | Used by |
|---|---|---|---|---|
| A0 | POST | token URL ([section 3](#3-authentication)) | [`authenticate`](services/bog_service.py#L81) | every call, Test Connection |
| D1 | POST | `documents/domestic` | [`create_domestic`](services/bog_service.py#L358) | Send to BOG (payment) |
| D2 | POST | `documents/foreign` | [`create_foreign`](services/bog_service.py#L364) | Send to BOG, transfer type Foreign |
| D3 | POST | `documents/conversion` | [`create_conversion`](services/bog_service.py#L456) | no caller |
| B1 | POST | `documents/bulk/domestic?fileName=` | [`create_bulk_domestic`](services/bog_service.py#L370) | Send to BOG (batch), payroll batches |
| B2 | POST | `documents/bulk/foreign?fileName=` | [`create_bulk_foreign`](services/bog_service.py#L377) | Send to BOG (batch), all lines foreign |
| S1 | GET | `documents/status/{key}` | [`get_document_status`](services/bog_service.py#L392) | Refresh Status, after each create, hourly cron |
| S2 | GET | `documents/statuses/{keys}` | not implemented | no caller |
| S3 | GET | `documents/bulk/status/{key}` | [`get_bulk_status`](services/bog_service.py#L383) | Refresh Batch Status, after a package create, hourly cron |
| X1 | DELETE | `documents/{keys}` | [`delete_document`](services/bog_service.py#L396) | Cancel at Bank (payment) |
| X2 | DELETE | `documents/bulk/{key}` | [`delete_bulk`](services/bog_service.py#L387) | Cancel at Bank (batch) |
| C1 | GET | `documents/code` | - | not implemented |
| T1 | GET | `documents/todayactivities/{accountNumber}/{currency}` | [`get_today_activities`](services/bog_service.py#L350) | Recover from BOG |
| T2 | GET | `v2/documents/todayactivities/{accountNumber}/{currency}` | - | not implemented (T1 used) |
| L1 | GET | `statement/{accountNumber}/{currency}/{startDate}/{endDate}` | - | deprecated (Postman) |
| L2 | GET | `statement/{accountNumber}/{currency}/{id}/{page}` | - | deprecated (Postman) |
| L3 | GET | `statement/summary/{accountNumber}/{currency}/{id}` | - | deprecated (Postman) |
| N1 | GET | `v2/statement/{accountNumber}/{currency}/{startDate}/{endDate}` | [`get_statement`](services/bog_service.py#L282) via [`fetch_all_records`](services/bog_service.py#L296) | Import Statement wizard, daily sync cron |
| N2 | GET | `v2/statement/{accountNumber}/{currency}/{id}/{page}` | [`get_statement_page`](services/bog_service.py#L290) | paging inside `fetch_all_records` |
| N3 | GET | `v2/statement/{accountNumber}/{currency}/{startDate}/{endDate}/{includeToday}/{orderByDate}?take=&revaluation=` | - | not implemented |
| N4 | GET | `v2/statement/summary/{accountNumber}/{currency}/{startDate}/{endDate}` | [`get_statement_summary`](services/bog_service.py#L342) | live snapshot cron, every 2 h |
| A1 | GET | `accounts/{accountNumber}/{currency}` | [`get_account_balance`](services/bog_service.py#L320) | no caller |
| R1 | GET | `rates/nbg/{currency}` | [`get_nbg_rate`](services/bog_service.py#L546) | no caller |
| R2 | GET | `rates/nbg/{currency}/{startDate}/{endDate}` | - | not implemented |
| R3 | GET | `rates/commercial/{currency}` | [`get_commercial_rate`](services/bog_service.py#L550) | no caller |
| R4 | GET | `rates/commercial/{sellCurrency}/{buyCurrency}` | `get_commercial_rate` with a buy currency | no caller |
| R5 | GET | `v2/rates/{currency}` | not implemented | no caller |
| P1 | GET | `deposits/agreements` | [`get_deposit_agreements`](services/bog_service.py#L566) | no caller |
| P2 | GET | `deposits/available-amount` | [`get_deposit_available_amount`](services/bog_service.py#L570) | no caller |
| M1 | POST | `moneyrequest/create` | [`create_money_request`](services/bog_service.py#L558) | no caller |
| F1 | POST | `files/upload` | [`upload_file`](services/bog_service.py#L401) | Upload Attachments; before Send when the payment has BOG attachments |
| U1 | POST | `otp/request` | - | not implemented (page outside the menu) |
| U2 | POST | `sign/document` | - | not implemented (page outside the menu) |
| U3 | POST | `BalanceSheet` | - | not implemented (page outside the menu) |

- In use: A0, D1, D2, B1, B2, S1, S3, X1, X2, T1, N1, N2, N4, F1. Implemented, never called: D3,
  A1, R1, R3, R4, P1, P2, M1. Not implemented: S2, R5, C1, T2, N3, R2, U1-U3. L1-L3 are deprecated.
- S1, S2 and X1 take BOG's `UniqueKey`, never the caller's `UniqueId`. No endpoint is queried by
  `UniqueId` or `DocumentNo`.

---

## 6. Creating documents

D1, D2, D3, B1 and B2 create **documents in Business Online**. Result code 0 reads "Document is
Ready to Sign": a created document is not an executed transfer. Its progress is read with S1/S2
([section 8](#8-status-cancellation-creation-codes)).

Common rules:

- The body is a bare array of documents, one or more per call. D1-D3 answer with an array of
  `DocumentKey` objects, one per document: `UniqueId` (yours, echoed), `UniqueKey` (BOG's id,
  integer), `ResultCode`, `Match`.
- `UniqueId` is the document's GUID in the caller's system; `UniqueKey` is BOG's id, used by status
  and cancel.
- `CheckUniqueId` (all five create endpoints): when `true`, BOG first checks whether a document with
  the same `UniqueId` was created in the last 7 days; if one was, no document is created and result
  code `702` is returned. `702` is not in the result-code table. No page says what happens to a
  repeated `UniqueId` without the flag.
- `Match`: for transfers within BOG, how well the given recipient name matches the owner of the
  IBAN, in percent - company name for legal entities, name and surname for individuals.
- A `200` can carry a business refusal in `ResultCode` ([section 13](#result-codes)).

### Fields per type

**R** marked required on the page - **O** optional - **-** not in that model.

| Field | Domestic D1 | Package domestic B1 | Foreign D2 | Package foreign B2 | Rule / limit |
|---|---|---|---|---|---|
| `UniqueId` | R | R | R | R | GUID |
| `DocumentNo` | R, max 16 | R | R | R | max 16 is stated on D1 only |
| `ValueDate` | R | R | R | R | "date of document entry in the bank system" |
| `Amount` | R | R | R | R | decimal |
| `Currency` | - (XML example: `GEL`) | - | R | R | ISO 4217 |
| `SourceAccountNumber` | R | R | R | R | sender IBAN |
| `BeneficiaryAccountNumber` | R | R | R | R | IBAN for GEL transfers within BOG or to other banks; the treasury code for the State Treasury; the existing account format for foreign currency |
| `BeneficiaryBankCode` | R | O | O | O | "RTGS code" of the recipient bank; BOG is `BAGAGE22` (Postman). Foreign: this or `BeneficiaryBankName` is mandatory |
| `BeneficiaryBankName` | - | - | O | O | see above |
| `BeneficiaryInn` | R | O, max 11 | O, max 11 | O, max 11 | personal number (individual) or identification code (legal entity) |
| `BeneficiaryName` | O | O | O | O | max 160 (code 43) |
| `CheckInn` | O, boolean | O | O, typed string | O | `true` asks BOG to check that the account belongs to that ID; within BOG only, `false` for other banks (code 28) |
| `Nomination` | R, max 250 | R, max 250 | - | - | purpose, domestic |
| `PaymentDetail` | - | - | O, 4x34 = 136 | O | purpose, foreign; allowed characters `a-z A-Z 0-9 / - ? ) . , ' + :` (codes -9 / 79) |
| `PayerInn` | R, max 11 | O, max 11 | - | - | its own description: fill only when paying the budget on behalf of a third party (code 59) |
| `PayerName` | O | O | - | - | same rule; max 160 (code 53) |
| `DispatchType` | O | O | - | - | "used for outbound transfers only and is a mandatory field": `BULK` standard, up to 10,000 GEL; `MT103` individual |
| `IsSalary` | O | O | - | - | `true` for salaries; salary only to individuals (code 155) |
| `Charges` | - | - | O | O | `SHA` or `OUR` |
| `CommissionAccountNumber` | O, individual transfers only | O | O, individual transfers only | O | fee account, IBAN with currency (`GE11BG1111111111111111GEL`); a wrong one -> fee taken from the source account |
| `IntermediaryBankCode`, `IntermediaryBankName` | - | - | O | O | SWIFT code and name of the intermediary bank |
| `BeneficiaryRegistrationCountryCode`, `BeneficiaryActualCountryCode` | - | - | O | O | recipient's registration and actual country |
| `RecipientAddress`, `RecipientCity` | - | - | O | O | |
| `RegReportingValue` | - | - | O | O | for transfers to the UAE (code 158 in packages) |
| `PurposeCode` | - | - | O | O | for currency-operation reporting |
| `AdditionalInformation` | O, "not used for national currency" | O | O | O | max 250 (code 56); foreign max 210 (codes -10 / 80) |
| `IsPayerResident` | O | O | - | - | Treasury payment for a third person: is that person a Georgian resident |
| `PayerTaxRegistrationCode`, `PayerPenaltyNumber` | O | O | - | - | Treasury payment by a non-resident (registration code, protocol number) |
| `AttachmentIds` | O | O | O | O | file hashes from F1 |
| `CheckUniqueId` | O | O | O | O | duplicate guard, see above |
| `fileName` (query) | - | in the URL | - | R | package name |

Conversion (D3), between the customer's own accounts (code 116: sender and beneficiary client
differ):

| Field | | Meaning |
|---|---|---|
| `UniqueId` | R | GUID |
| `DocumentNo` | O | |
| `SourceAccountNumber`, `SourceCurrency` | O | account and currency to sell |
| `DestinationAccountNumber`, `DestinationCurrency` | O | account and currency to buy |
| `Amount` | O | |
| `Rate` | O | only for a rate individually agreed with the bank |
| `AdditionalInfo` | O | |
| `CheckUniqueId` | O | |

Treasury payments: `BeneficiaryAccountNumber` holds the treasury code (code 40 "The Treasury code
is incorrect", error code 13 "Not Set Treasury code"); payer fields only when paying for someone
else.

**Module** - one builder for both types, [`_bog_build_document`](models/account_payment.py#L500):

| Sent | From |
|---|---|
| `Nomination` | memo, else partner name, cut to 250 - also on foreign documents |
| `UniqueId`, `DocumentNo` | reserved before the call ([`_bog_reserve_send`](models/account_payment.py#L262)); `DocumentNo` = `ODOO<payment id>`, max 16 |
| `Amount`, `Currency`, `ValueDate` | payment; date as `YYYY-MM-DD` |
| `SourceAccountNumber` | journal bank account, as stored |
| `BeneficiaryAccountNumber`, `BeneficiaryBankCode` | partner bank account and its BIC, or the override field |
| `BeneficiaryInn`, `BeneficiaryName` | override fields, else partner VAT and name, as stored |
| `PayerInn` | company VAT without a `GE` prefix ([models/account_payment.py:199](models/account_payment.py#L199)), on every document |
| `IsSalary`, `DispatchType` | payment fields; default `MT103`; payroll sets `BULK` up to 10,000 GEL ([models/account_payment_method_line.py:89](models/account_payment_method_line.py#L89)) |
| `CheckInn` | only when ticked |
| `AdditionalInformation` | foreign only, cut to 210 |
| `AttachmentIds` | hashes from F1, uploaded again at every send ([`_bog_ensure_attachments_uploaded`](models/account_payment.py)) |

Never sent: `CheckUniqueId`, `PaymentDetail`, `Charges`, `PurposeCode`, `BeneficiaryBankName`,
intermediary bank, recipient address, city and countries, `RegReportingValue`,
`CommissionAccountNumber`, the treasury payer fields. Empty values are removed before sending.
Consequences: [F2](#f2-retries-are-not-deduplicated-without-checkuniqueid),
[F5](#f5-foreign-documents-are-sent-in-the-domestic-shape),
[F6](#f6-payerinn-on-every-domestic-document).

---

## 7. Package (bulk) transfers

- `POST api/documents/bulk/domestic?fileName={fileName}` and
  `POST api/documents/bulk/foreign?fileName={fileName}`; `fileName` is the package name.
- Body: a flat array with the same fields as D1 / D2 ([fields per type](#fields-per-type)), no
  wrapper object, no nested `Payments[]` (Postman 5.1). Each line has its own `UniqueId`,
  `DocumentNo`, `ValueDate`, `SourceAccountNumber`.
- Response: a bare integer, the package's unique ID (`1`; XML `<long>`). No per-line result.
- S3 `GET api/documents/bulk/status/{key}` answers:

```json
{
  "Status": "<status letter>",
  "DocumentStatuses": [
    {"UniqueId": "<your GUID>", "UniqueKey": 1, "Status": "<status letter>",
     "BulkLineStatus": "<string>", "RejectCode": 1, "ResultCode": 1, "Match": 1.0}
  ]
}
```

  The page calls both `Status` fields "a document status". The package table in
  [section 13](#package-statuses) is the only list for a package; each line is a document.
  `BulkLineStatus` is a string "used in case of the package transfer", values not listed. A line
  has no `DocumentNo`.
- X2 `DELETE api/documents/bulk/{key}` cancels the package and every document in it; `200 OK` is
  success. Postman: only packages "in a cancellable status".
- Not stated anywhere: the maximum number of lines, whether one invalid line rejects the whole
  package, whether `DispatchType` matters inside a package. Postman 5.1 sends salary lines with
  `IsSalary: true` and `DispatchType: "MT103"`.

**Module** - [`action_bog_send_batch`](models/account_batch_payment.py#L123) reserves every payment,
builds each line with `_bog_build_document`, posts once and keeps the package key; at most 500
lines ([models/account_batch_payment.py:14](models/account_batch_payment.py#L14), self-imposed);
domestic and foreign cannot be mixed.
[`_bog_refresh_bulk_status`](models/account_batch_payment.py) reads the lines from `DocumentStatuses`
(`BulkLineStatus` as a fallback) and matches them by `UniqueId`, else `DocumentNo`
([F3](#f3-package-lines-never-reach-the-payments), fixed).

---

## 8. Status, cancellation, creation codes

| # | Call | Answer |
|---|---|---|
| S1 | `GET api/documents/status/{key}`, key = `UniqueKey` | `UniqueId`, `UniqueKey`, `Status`, `BulkLineStatus`, `RejectCode` (integer), `ResultCode`, `Match` |
| S2 | `GET api/documents/statuses/{keys}`, one or more keys (Postman: comma-separated) | array of the S1 object |
| X1 | `DELETE api/documents/{keys}`, one or more keys | `200 OK` = success; Postman: only documents "in a cancellable status" |
| C1 | `GET api/documents/code` | array of `DocumentTypeName`, `ResultType`, `ResultDescription`, `ResultCode`: the bank's current result-code list |

- `Status` takes the letters in [section 13](#document-statuses), `RejectCode` the
  [error codes](#error-codes).
- Unknown `UniqueKey` -> `404` (Postman, error folder 7.2). Invalid IBAN or missing fields -> `400`;
  "the error message will specify which fields are missing" (Postman 7.3, 7.4). No page shows the
  `400` body.

**Module** - S1 after each create, on Refresh Status and in the hourly cron
([models/account_payment.py:597](models/account_payment.py#L597),
[646](models/account_payment.py#L646)); the state comes from substrings of `Status`
([models/account_payment.py:62](models/account_payment.py#L62)): [F1](#f1-statuses-are-letters).
One S1 call per payment; S2 would check many in one call. X1 only from state Created
([models/account_payment.py:699](models/account_payment.py#L699)).

---

## 9. Current day activities

Two pages describe "all activities of the current day":

| | Documents section | Statement New section |
|---|---|---|
| Path | `GET api/documents/todayactivities/{accountNumber}/{currency}` | `GET api/v2/documents/todayactivities/{accountNumber}/{currency}` |
| JSON casing | PascalCase | camelCase |
| Limit | 800 per day per account and currency (page note) | the same; the Introduction table names this path |

Postman calls the unversioned path in both places (4.7, and 6.2 "Get Today's Activities (New)").

Each entry:

| Field | Meaning |
|---|---|
| `Id` | unique identifier (of the entry) |
| `DocKey` | the document's unique ID in Business Online (= `UniqueKey`) |
| `DocNo` | document number |
| `PostDate` | document creation date |
| `ValueDate` | value date |
| `EntryType` | `PMC` GEL operation, `PLC` card, `CDS` saving, `LND` loan, `PBS` Paybox, `INC` inkaso (debt collection), `PMD` national-currency transfer, `PMI` foreign-currency transfer, `COM` fee |
| `EntryComment`, `EntryCommentEn` | content of the transaction, Georgian and English |
| `Nomination` | purpose |
| `Credit`, `Debit`, `Amount`, `AmountBase` | amounts; `AmountBase` in GEL |
| `PayerName`, `PayerInn` | payer |
| `Sender`, `Beneficiary` | `Name`, `Inn`, `AccountNumber`, `BankCode`, `BankName` |

The entries are bookings (credit and debit, entry type, GEL equivalent). No page says whether a
created but unsigned document appears here.

**Module** - Recover from BOG ([models/account_payment.py:658](models/account_payment.py#L658))
looks for the payment's `DocumentNo` in T1 and stores the entry's `Id` as the document key
([line 681](models/account_payment.py#L681)):
[F4](#f4-recovery-stores-the-entry-id-not-the-document-key).

---

## 10. Statements

"Statement New" (V2) is current. Postman marks the V1 statement and summary "DEPRECATED - this
endpoint is no longer supported".

### Statement by period (N1)

`GET api/v2/statement/{accountNumber}/{currency}/{startDate}/{endDate}` - at most 1000 records per
request, more through N2. The currency is its own path segment and must not be appended to the IBAN
(Postman).

| Field | Meaning |
|---|---|
| `Id` | statement id, needed for N2 |
| `Count` | "a number of records" |
| `TotalCount` | "the total number of records in the requested period, regardless of paging" |
| `Records[]` | the entries |

### Next pages (N2)

`GET api/v2/statement/{accountNumber}/{currency}/{id}/{page}` - up to 1000 records per request.
Pages must be read in order: after page 3 comes page 4; page 6 cannot follow page 3. Page 1 is the
N1 answer, so paging starts at 2 (Postman 6.5). The field list says `Id`, `Count`, `TotalCount`,
`Records`; the example and Postman return a bare array of records.

### With revaluation (N3)

`GET api/v2/statement/{accountNumber}/{currency}/{startDate}/{endDate}/{includeToday}/{orderByDate}?take={take}&revaluation={revaluation}`

`includeToday` (path, boolean) includes today's operations; `orderByDate` (path, boolean); `take`
(query, record limit); `revaluation` (query, boolean) adds revaluation records. Postman: `take` and
`revaluation` can be sent without the optional path parameters. `DocumentRate` on this page is the
National Bank rate. No page says whether N1 includes today.

### Summary (N4)

`GET api/v2/statement/summary/{accountNumber}/{currency}/{startDate}/{endDate}`

- `GlobalSummary`: `AccountNumber`, `Currency`, `StartDate` / `EndDate` (first and last
  transaction), `PeriodStartDate`, `PeriodEndDate`, `InAmount`, `InAmountBase`, `InRate`,
  `OutAmount`, `OutAmountBase`, `OutRate`, `CreditSum`, `DebitSum`.
- `DailySummaries[]`: `Balance`, `BalanceBase`, `CreditSum`, `DebitSum`, `Rate`, `EntryCount`,
  `Date`.

There is no opening or closing balance for the period as such.

### Record fields (N1, N2, N3)

| Field | Meaning |
|---|---|
| `EntryId` | entry unique ID, typed decimal |
| `EntryDate` | entry date |
| `EntryDocumentNumber` | entry document number |
| `EntryAccountNumber` | entry account number |
| `EntryAmount`, `EntryAmountBase` | amount and GEL equivalent |
| `EntryAmountDebit`, `EntryAmountDebitBase`, `EntryAmountCredit`, `EntryAmountCreditBase` | debit and credit, with GEL equivalents |
| `EntryComment` | content of the transaction |
| `DocumentKey` | the document's unique number in the bank, typed decimal |
| `DocumentProductGroup` | transaction type |
| `DocumentValueDate`, `DocumentReceiveDate`, `AuthDate` | value date, receive date, authorisation date |
| `DocumentNomination` | purpose, max 250 |
| `DocumentInformation` | additional info |
| `DocumentTreasuryCode` | treasury code |
| `DocumentSourceAmount`, `DocumentSourceCurrency`, `DocumentDestinationAmount`, `DocumentDestinationCurrency`, `DocumentRate` | conversion data |
| `DocumentPayerName`, `DocumentPayerInn` | third-party payer of a budget payment |
| `SenderDetails`, `BeneficiaryDetails` | `Name`, `Inn`, `AccountNumber`, `BankCode`, `BankName` |
| `DocComment` | joined from several attributes, e.g. "Automatic payment, 22/12/2021, JSC ..., GE75BG...GEL JSC "Bank of Georgia" BAGAGE22" |

V1 records also have `EntryDepartment`, `EntryAccountPoint`, `DocumentBranch`,
`DocumentDepartment`, `DocumentActualDate`, `DocumentExpiryDate`, `DocumentRateLimit`,
`DocumentRegistrationRate`, `DocumentSenderInstitution`, `DocumentIntermediaryInstitution`,
`DocumentBeneficiaryInstitution`, `DocumentPayee`, `DocumentCorrespondentAccountNumber`,
`DocumentCorrespondentBankCode`, `DocumentCorrespondentBankName`. V2 adds `AuthDate` and
`TotalCount`.

### Legacy V1 (L1-L3)

`GET api/statement/{accountNumber}/{currency}/{startDate}/{endDate}` (first 1000 records),
`GET api/statement/{accountNumber}/{currency}/{id}/{page}`,
`GET api/statement/summary/{accountNumber}/{currency}/{id}`. The V1 menu link "Statement
generation" opens the Statement category page; the page itself is only at `statement/statement.md`.

**Module**

- [`fetch_all_records`](services/bog_service.py#L296): N1, then N2 from page 2 while fewer records
  than `count` have arrived ([line 388](services/bog_service.py#L388)), at most 200 pages:
  [F7](#f7-statement-paging-uses-count).
- Lines ([wizard/bog_statement_import_wizard.py:92](wizard/bog_statement_import_wizard.py#L92)):
  amount = credit - debit; counterparty = sender for money in, beneficiary for money out; date =
  first 10 characters of `entryDate` (the Tbilisi date); `ref` = `entryDocumentNumber`, else
  `entryId`; `unique_import_id` = `bogbank-<journal>-<entryId>`; `documentKey` and
  `entryDocumentNumber` confirm sent payments
  (gec_bank `account_bank_statement_line.py`, `_gec_bank_auto_match`; keys `gec_bank_reference`, `bog_document_no`):
  [F8](#f8-decimal-keys).
- The daily cron imports yesterday to today ([models/bog_connection.py:122](models/bog_connection.py#L122));
  the 2-hour snapshot takes the last daily `Balance` as closing balance
  ([models/bog_statement.py:54](models/bog_statement.py#L54)).

---

## 11. Balance, rates, deposits, money request, file upload

### Balance (A1)

`GET api/accounts/{accountNumber}/{currency}`, optional query `initStatementBalance=true` ->
`AvailableBalance`, `CurrentBalance`, and with the flag `StatementBalance` (previous statement
balance). Postman: the available balance accounts for blocked operations, the current balance does
not.

### Rates (R1-R5), 60 per minute per method

| # | Path | Answer |
|---|---|---|
| R1 | `rates/nbg/{currency}` | bare decimal: National Bank rate to GEL |
| R2 | `rates/nbg/{currency}/{startDate}/{endDate}` | array of `Date`, `Rate`, `Currency`, one per date |
| R3 | `rates/commercial/{currency}` | `Sell` (GEL to currency), `Buy` (currency to GEL), BOG commercial rate |
| R4 | `rates/commercial/{sellCurrency}/{buyCurrency}` | bare decimal: BOG commercial cross rate |
| R5 | `v2/rates/{currency}` | `nbgRate`, `standardBuyRate`, `standardSellRate`, `digitalBuyRate`, `digitalSellRate`; the digital rate is the client's special rate when one exists |

### Deposits (P1, P2)

- P1 `GET api/deposits/agreements`, active deposits: `name`, `accountNo`, `balance`, `rate`,
  `agreeNo`, `maturityDate`, `startDate`, `interestAccrued`, `ccy`, `depositType`,
  `nextWithdrawalDate`, `interestWithPeriodType`, `accrualBalance`, `agreements[]` (`irr`, `rate`,
  `balance` as a text range).
- P2 `GET api/deposits/available-amount`: `ccy`, `totalAvailableAmount` per currency.

### Money request (M1)

`POST api/moneyrequest/create` asks someone to pay into your account; the recipient confirms.

| Field | | Rule |
|---|---|---|
| `AccountNumber` | R | your IBAN; the example has no currency: `GE11BG1111111111111111` |
| `Currency`, `Amount`, `Description` | R | |
| `IsPhysical` | R | `true` individual, `false` legal entity |
| `PhoneNumber`, `Pin` | | individual: exactly one of the two |
| `RecipientIdentifier` | | legal entity: required; `PhoneNumber` and `Pin` empty |

Success: `201 Created`, empty body. Postman: `400` validation error or user not found, `403` no
access to the account, `404` account not found.

### File upload (F1)

`POST api/files/upload`, `multipart/form-data`, field `file` -> a bare JSON string, the
`externalFileHash`, which goes into `AttachmentIds`. Allowed extensions: docx, docm, dotx, dotm,
docb, xls, xlsb, xlsm, xlsx, jpg, jpeg, png, ppt, gif, txt, pdf, zip, rar, tar, gzip, ico, dat, csv,
xml, enc, svg. Another extension or no file: `400` "File extension is not allowed". Postman: `401`
bad token, `403` no upload permission. No size limit is published. Result code 669 ("Please, Upload
Invoice or Contract") is where an attachment becomes mandatory.

**Module** - the same extension list is checked before sending
([services/bog_service.py:51](services/bog_service.py#L51)); the files are uploaded again at every
send (a swapped or removed file reaches the bank) and the hashes are stored on the payment.

---

## 12. Pages outside the menu

Three pages exist (raw Markdown and HTML) but no menu entry links to them. They give parameters
only: no description, no response, nothing on who may call them.

| # | Call | Body |
|---|---|---|
| U1 | `POST api/otp/request` | `ObjectKey` (integer, R), `ObjectType` (R; `ObjectType.Payment`, the example sends `0`) |
| U2 | `POST api/sign/document` | `Otp` (string, R), `ObjectKey` (integer, R) |
| U3 | `POST api/BalanceSheet` | `StartDate`, `EndDate`, `BalanceSheetEntries[]`: `AccountNumber`, `AccountDescription`, `OpeningDebit`, `OpeningCredit`, `DebitTurnover`, `CreditTunover` (sic), `NetTurnover`, `ClosingDebit`, `ClosingCredit`, `OpeningQuantityDebit`, `OpeningQuantityCredit`, `QuantityDebit`, `QuantityCredit`, `QuantityNetTurnover`, `ValueCalculated` (boolean), `IdentityCode`, `QuantityFinalDebit`, `QuantityFinalCredit`, all required |

- U3's page is in Georgian also on the English site: "საბალანსო უწყისის ატვირთვის მეთოდი", an
  upload of the company's trial balance (turnover sheet) to the bank.
- Read together, U1 and U2 look like signing a created document through the API with a one-time
  code: request an OTP for `ObjectKey` (presumably the `UniqueKey`), then sign with it. That is an
  inference; ask BOG ([Q2](#16-open-questions-for-bog)).

---

## 13. Statuses, result codes, error codes

### Document statuses

`Status` of S1/S2 and of each package line. Georgian wording from the Georgian page.

| Code | English page | Georgian page |
|---|---|---|
| `C` | Cancelled by Response | გაუქმებულია მომხმარებლის მიერ (cancelled by the customer) |
| `N` | Incomplete | დაუსრულებელი |
| `D` | Cancelled by Bank | გაუქმებულია ბანკის მიერ |
| `P` | Completed | შესრულებული (executed) |
| `A` | To be Signed | ხელმოსაწერი |
| `S` | Signed | ხელმოწერილი |
| `T` | In Progress | მუშავდება |
| `R` | Rejected | უარყოფილი |
| `Z` | Sign In Progress | ხელმოწერის პროცესში |

### Package statuses

`Status` of S3.

| Code | English page | Georgian page |
|---|---|---|
| `N` | Processing | დასამუშავებელი |
| `S` | Signed | ხელმოწერილი |
| `C` | Canceled by Response | გაუქმებულია მომხმარებლის მიერ (cancelled by the customer) |
| `P` | To be Signed | ხელმოსაწერი |
| `D` | File Duplicate | დუბლირებული ფაილი |
| `Z` | Sign in Progress | დოკუმენტი ხელმოწერის პროცესშია |
| `I` | Individual documents created | ინდივიდუალური დოკუმენტები შექმნილია |
| `A` | The bulk transfer is in process of Signature | მიმდინარეობს პაკეტური გადარიცხვის ხელმოწერა |
| `B` | Documents are being created | მიმდინარეობს დოკუმენტების შექმნა |
| `U` | Uploading file, checking | მიმდინარეობს ფაილის ატვირთვა, შემოწმება |
| `R` | (not on the English page) | წაშლილი (deleted) |

- The two tables reuse letters with other meanings: `P` is Completed for a document but To be
  Signed for a package; `D` is Cancelled by Bank against File Duplicate; `N` Incomplete against
  Processing; `A` To be Signed against signature in progress. One map for both would report an
  unsigned package as executed.
- The package table has no executed state. Whether a package was paid shows only in its lines'
  document statuses.

### Error codes

`RejectCode` of S1-S3.

| Code | Description |
|---|---|
| 12 | Wrong IBAN Format |
| 13 | Not Set Treasury code |
| 14 | Beneficiary Account Is Incorrect |
| 15 | Wrong destination |
| 16 | Fonts can not be read |
| 17 | Insufficient funds |
| 18 | Blocked Card |
| 19 | Expired card |
| 20 | Card error |
| 21 | The recipient account and Name Not Comparable |
| 22 | Canceled, please contact us for more information 2444444 |

### Result codes

`ResultCode` of the create calls and of S1-S3. The page has 163 rows; here one row per code and
description. "Given for" is the page's document type (`-` = none given); a code listed both with and
without a type is shown once, with the type. Only 0 is Success; seven codes are **Warn** (-998, -18,
-8, 333, 363, 444, 701), and no page says what Warn means. Code 702 (`CheckUniqueId` duplicate) is
not listed. C1 returns the bank's current list.

| Code | Type | Given for | Description (as published) |
|---|---|---|---|
| -999 | Error | Foreign | Error occured while executing operation |
| -998 | **Warn** | - | Rejected due to expiration |
| -99 | Error | Utility Payments | Payment failed, try again later |
| -82 | Error | - | Transfer to the entered account isn't possible. The account owner needs to update their personal information at the bank |
| -21 | Error | Foreign | document.result.code.foreign.transfer.incorrect.amount |
| -20 | Error | Foreign | document.result.code.foreign.transfer.incorrect.receiver.country |
| -19 | Error | Foreign | document.result.code.foreign.transfer.incorrect.receiver.status |
| -18 | **Warn** | Foreign | document.result.code.foreign.transfer.not.enough.balance.on.account |
| -17 | Error | Foreign | Benef Account Is Incorrect |
| -16 | Error | Foreign | Incorrect Commision Account |
| -15 | Error | Foreign | Incorrect Commision Parameters |
| -14 | Error | Utility Payments | გამგზავნის ანგარიში არასწორია (Georgian only: "sender account is incorrect") |
| -14 | Error | Foreign | Incorrect System Phase |
| -13 | Error | Foreign | document.result.code.foreign.transfer.template.not.found |
| -12 | Error | Foreign | Incorrect Currency |
| -11 | Error | Foreign | Incorrect Value Date |
| -10 | Error | Foreign | Additional Information format is invalid. Max number of symbols should be 210 |
| -9 | Error | Foreign | Transfer Description Format is Invalid. Valid Characters are a-z A-Z 0-9 /-?)., ' + : |
| -8 | **Warn** | Utility Payments | document.result.code.electronic.payment.https.error |
| -8 | Error | Foreign | Destination Account Is Incorrect |
| -7 | Error | Foreign | The receiver bank data is incorrect, try again |
| -6 | Error | Foreign | Intermediar Info Is Empty |
| -5 | Error | Foreign | Beneficiary Name Is not Valid |
| -4 | Error | Foreign | Sender Name Is Empty |
| -3 | Error | Foreign | Incorrect Sender Account |
| -2 | Error | Foreign | Transfer to this beneficiary account with the submitted parameters is impossible |
| -1 | Error | Foreign | Sender And Beneficiary Accounts Ccy Is Incorrect |
| 0 | **Success** | - | Document is Ready to Sign |
| 1 | Error | - | Document Not Found |
| 2 | Error | - | Doc Type Not Found |
| 4 | Error | Conversion | Incorrect Currency Rate For Specified Currencies |
| 28 | Error | - | CheckInn is used while transferring outside Bank of Georgia. Tis parameter is used only while transferring within Bank of Georgia |
| 29 | Error | - | Beneficiary account number and taxpayer number are incorrect |
| 30 | Error | - | Recipient's account number and/or bank code are blank |
| 31 | Error | - | Invalid sender or recipient Bank code |
| 32 | Error | - | Transaction is not possible |
| 33 | Error | Within Georgia | Sender ID not found |
| 33 | Error | - | Sender account is incorrect |
| 34 | Error | - | Incorrect Sender Account Currency |
| 35 | Error | - | Cannot perform transaction on the specified account |
| 36 | Error | - | Sender Number Taxpayer is Not Correct |
| 37 | Error | - | Beneficiary Account Is Empty |
| 38 | Error | - | Beneficiary Account Is Too Long |
| 39 | Error | - | Beneficiary Account Is Incorrect |
| 40 | Error | - | The Treasury code is incorrect |
| 41 | Error | - | Receiver tax id is not correct |
| 42 | Error | - | Beneficiary Name Is not Valid |
| 43 | Error | - | Recipient name should not exceed 160 symbols |
| 44 | Error | - | Beneficiary Account Is Incorrect |
| 45 | Error | - | Incorrect Beneficiary Account Currency |
| 46 | Error | - | Cannot perform transaction between specified accounts |
| 47 | Error | - | The document has expired |
| 48 | Error | - | Incorrect Value Date |
| 49 | Error | - | Incorrect Transfer Currency |
| 50 | Error | - | Incorrect Amount Format |
| 51 | Error | - | Incorrect Commis Amount Format |
| 52 | Error | - | Incorrect taxpayer ID |
| 53 | Error | - | Payer name must not exceed 160 symbols |
| 54 | Error | - | Nomination Is Empty |
| 55 | Error | - | Destination field should not exceed 250 symbols |
| 56 | Error | - | Additional information field should not exceed 250 symbols |
| 57 | Error | - | Validation General Exception |
| 58 | Error | - | Fee account is incorrect |
| 59 | Error | - | Payer name and payer INN are filled only when making a transfer to a State Treasury account on behalf of the third person |
| 60 | Error | - | Beneficiary taxpayer number is empty |
| 61 | Error | Within BoG, Within Georgia | The number of symbols in the identification code must not exceed 14 |
| 71 | Error | Foreign | Sender And Beneficiary Accounts Ccy Is Incorrect |
| 72 | Error | - | Transfer to this beneficiary account with the submitted parameters is impossible |
| 73 | Error | Foreign | Incorrect Sender Account |
| 74 | Error | Foreign | Sender Name Is Empty |
| 75 | Error | Foreign | Beneficiary Name Is not Valid |
| 76 | Error | Foreign | Intermediar Info Is Empty |
| 77 | Error | Foreign | The receiver bank data is incorrect, try again |
| 78 | Error | Foreign | Destination Account Is Incorrect |
| 79 | Error | Foreign | Transfer Description Format is Invalid. Valid Characters are a-z A-Z 0-9 /-?)., ' + : |
| 80 | Error | Foreign | Additional Information format is invalid. Max number of symbols should be 210 |
| 81 | Error | Foreign, Within BoG | Incorrect Value Date |
| 82 | Error | Foreign | Incorrect Currency |
| 83 | Error | Foreign, Between My Accounts | Insufficient funds |
| 84 | Error | Foreign | Incorrect System Phase |
| 85 | Error | Foreign | Incorrect Commision Parameters |
| 86 | Error | Foreign | Incorrect Commision Account |
| 87 | Error | Foreign | Benef Account Is Incorrect |
| 90 | Error | - | Recipient Name Long |
| 91 | Error | - | Description Long |
| 92 | Error | Foreign | Recipient's Country code is not valid |
| 96 | Error | Foreign | Transaction Type Description is not valid, please indicate correct code |
| 110 | Error | Conversion | Incorrect Amount Format |
| 111 | Error | Conversion | Incorrect Transfer Currency |
| 112 | Error | Conversion | Incorrect Sender Account |
| 113 | Error | Conversion | Beneficiary Account Is Incorrect |
| 114 | Error | Conversion | Sender And Beneficiary Accounts Is Same |
| 115 | Error | Conversion | Sender And Beneficiary Accounts Ccy Is Same |
| 116 | Error | Conversion | Sender And Beneficiary Client Is Different |
| 117 | Error | Conversion | Sender and beneficiary branches are different. Choose different accounts or contact the Bank. |
| 118 | Error | Conversion | Incorrect Document Parameters |
| 119 | Error | Conversion | Incorrect Remark Length |
| 120 | Error | Conversion | Incorrect Document Currency Rate |
| 121 | Error | Conversion | Incorrect Document Currency |
| 122 | Error | Conversion | Error occured while executing operation |
| 123 | Error | Conversion | Error occured while executing operation |
| 124 | Error | - | Sender account is invalid. Please correct and try again |
| 147 | Error | - | Wrong IBAN Format |
| 150 | Error | - | Required Field |
| 151 | Error | - | Field Value Must Be Numeric |
| 152 | Error | - | Field Format Does Not Match |
| 153 | Error | - | ID length should not exceed 11 symbols |
| 154 | Error | - | Field value not found |
| 155 | Error | - | Salary transfer is made only to the individual |
| 157 | Error | Foreign | document.bulk.result.code.pmi.recip.name.length |
| 158 | Error | Foreign | document.bulk.result.code.pmi.regreporting.required.field |
| 333 | **Warn** | - | Not Enough Working Balance |
| 363 | **Warn** | - | Document has Duplicate. |
| 444 | **Warn** | - | Not Enough Funds |
| 500 | Error | - | Internal Error |
| 666 | Error | - | error.message.documents.wrong.content.symbols |
| 669 | Error | - | Please, Upload Invoice or Contract |
| 670 | Error | - | Beneficiary Account Is Incorrect |
| 671 | Error | Within Georgia | Beneficiary Account Is Incorrect |
| 671 | Error | - | Incorrect Account Number |
| 673 | Error | Foreign | document.bulk.result.code.pmi.recipient.required.fields |
| 674 | Error | Foreign, Within BoG, Within Georgia | You are not allowed to transfer to this account |
| 675 | Error | - | document.result.code.source.account.invalid |
| 676 | Error | - | document.result.code.has.not.access.to.source.account |
| 677 | Error | Foreign, Within BoG, Within Georgia | document.result.code.nomination.is.mandatory |
| 678 | Error | Foreign, Within Georgia | document.result.code.dispatch.type.is.mandatory |
| 679 | Error | - | document.result.code.wrong.comission.account |
| 701 | **Warn** | - | Document inputs didn't pass validations |
| 999 | Error | - | Error occured while executing operation |
| 1001 | Error | - | You don't have right to transfer |
| 1002 | Error | - | The receiver bank data is incorrect, try again |
| 9999 | Error | - | document.result.code.unknown.error |

**Module** - `BOG_WARN_CODES` = 333, 363, 444, 701
([models/account_payment.py:23](models/account_payment.py#L23)); -998, -18 and -8 are treated as
failures. Readable texts for 21 codes ([models/account_payment.py:32](models/account_payment.py#L32));
674 there reads "from this account", the page says "to this account".

---

## 14. Where BOG's sources contradict each other

| # | Where | Contradiction | Read it as / module |
|---|---|---|---|
| 1 | Rate limits | pages: rates 60 per minute per method; Postman folder 3: "1 request per minute per method" | the pages; the module README follows Postman |
| 2 | Current day activities | Documents page: `api/documents/...`, PascalCase; Statement New page and the Introduction limit table: `api/v2/documents/...`, camelCase; Postman calls the unversioned path in both places | both exist; the module uses the unversioned path and reads both casings |
| 3 | Statement `Count` | V2 pages: `Count` "a number of records", `TotalCount` the total "regardless of paging"; Postman 6.4: "Count - total number of records", "If Count > 1000 use pagination" | take `TotalCount`, fall back to `Count`; the module does this ([F7](#f7-statement-paging-uses-count)) |
| 4 | N2 response | field list: `Id`, `Count`, `TotalCount`, `Records`; example and Postman: bare array | accept both; the module does |
| 5 | N4 summary | English page lists a parameter `id` typed date; the path, the Georgian page and Postman use `startDate`/`endDate` | dates; the module does |
| 6 | Package status | page: lines in `DocumentStatuses[]`, `BulkLineStatus` a string per line; Postman 5.3: "BulkLineStatus field contains status of individual lines" | the page; the module reads the page ([F3](#f3-package-lines-never-reach-the-payments)) |
| 7 | D1 `PayerInn` | tagged required; its own description, `PayerName` and code 59 say payer fields are only for Treasury payments on behalf of a third person; B1 tags it optional; Postman 4.1 and 5.1 leave it out | leave it out unless paying the Treasury for someone else ([F6](#f6-payerinn-on-every-domestic-document)) |
| 8 | D1 `Currency` | not in the JSON field list nor in Postman's 4.1 body; Postman's 4.1 text lists it as required; the XML example sends `GEL` | no page says it is rejected; the module sends it |
| 9 | `DispatchType` | tagged optional, described as "mandatory" for outbound transfers; code 678 "dispatch type is mandatory" is listed for Foreign although the foreign model has no such field; Postman v1.0.4 replaced it with `Charges` on 5.2 | send on domestic, never on foreign |
| 10 | Foreign purpose | the field is `PaymentDetail`; codes 677 "nomination is mandatory" (Foreign) and -9 / 79 call it by other names; Postman v1.0.4: `Nomination` on foreign "was silently dropped" | send `PaymentDetail` ([F5](#f5-foreign-documents-are-sent-in-the-domestic-shape)) |
| 11 | Foreign `BeneficiaryBankCode` | described as an "RTGS code" (Georgian clearing) on a SWIFT transfer, while the intermediary bank code is "SWIFT" | send the BIC (inference) |
| 12 | `CheckInn` | boolean on D1, B1, B2; "string" on D2; every example `true` | boolean |
| 13 | `Charges` | `OUR` "will pay all fees charged by the sending bank" restates `SHA`; in SWIFT, OUR means the sender pays all fees | ask BOG ([Q10](#16-open-questions-for-bog)) |
| 14 | Code exchange | desktop and web pages: `grant_type` "client_credentials"; Postman 1.3.2: `authorization_code`; web page: `scope` "a text code", its own example `scope=corp` | the module uses client credentials only |
| 15 | Status `C` | English: "Cancelled by Response"; Georgian: cancelled by the customer | the Georgian wording |
| 16 | Package statuses | the Georgian page has `R` (deleted), the English page does not | handle `R` |
| 17 | B2 description | "create one or more package documents in the national currency" on the foreign-currency page | foreign |
| 18 | Cross rate (R4) | `sellCurrency` described as the "to" currency, `buyCurrency` as "from"; the answer described as "an exchange rate by a National Bank" (copied from R1); description in Georgian on the English page | check the direction before use |
| 19 | NBG history (R2) | Postman folder 3: `rates/nbg/{currency}/hist`; the page and Postman 3.3: `/{startDate}/{endDate}` | dates |
| 20 | Key types | `UniqueKey` integer; statement `DocumentKey` and `EntryId` "decimal number" (example `1.0`); `RejectCode` integer in S1/S2, string in S3; `Match` decimal, integer in S3 | normalise keys to integer strings ([F8](#f8-decimal-keys)) |
| 21 | V1 menu | the V1 "Statement generation" link opens the category page; the page exists only as `statement/statement.md` | V1 is deprecated |
| 22 | Postman 6.3 | V1 summary URL uses `{id}`, its text `{startDate}/{endDate}` | V1 is deprecated |

---

## 15. What the pages change for this module

Ordered by money risk. Each item: what happens, where, the smallest fix. F1-F4, F7 and F8 are fixed, F9 in part; F5 and F6 wait for BOG's answers (section 16). Line references below date from the first review.

### F1. Statuses are letters

- S1 returns `"Status": "P"` (Completed). [`_bog_refresh_status`](models/account_payment.py#L558)
  lowercases it to `p`; no hint ([models/account_payment.py:62](models/account_payment.py#L62)) is
  a substring of one letter, so the payment stays Created and gets the note "unrecognised document
  status: P". With the hourly cron active that repeats for every open payment, 24 notes a day each.
  The same holds for every document and package letter
  ([models/account_batch_payment.py:16](models/account_batch_payment.py#L16)).
- If BOG returned the English description instead, "Incomplete" contains `complet`, and the payment
  would be marked Confirmed although nothing was executed.
- The tests feed `"Executed"` and `"Rejected"` ([tests/test_bog_payment.py:202](tests/test_bog_payment.py#L202)),
  words BOG does not use.
- Fix: exact maps from [section 13](#13-statuses-result-codes-error-codes), raw value and note kept
  for anything else.
  - Document: `A`, `Z` -> Created; `S`, `T` -> Sent / Signed; `P` -> Confirmed; `R`, `D`, `C` ->
    Failed; `N` -> unchanged with a note (meaning unclear).
  - Package, its own map: `U`, `B`, `I`, `P`, `A`, `Z`, `N` -> Created; `S` -> Sent / Signed; `C`,
    `R` -> Failed; `D` (File Duplicate) -> Failed, with a do-not-resend note like 363. The batch is
    Confirmed only when its lines are `P`.

### F2. Retries are not deduplicated without CheckUniqueId

- A send times out -> Unknown; Recover finds nothing ([F4](#f4-recovery-stores-the-entry-id-not-the-document-key));
  Reset to Pending ([models/account_payment.py:489](models/account_payment.py#L489), also for a
  send stuck in Sending for 15 minutes); Send again. The same `UniqueId` goes out, but without
  `CheckUniqueId` no page says BOG refuses it: if the first document exists, there are now two. The
  same applies to Create Anyway after a Warn code
  ([models/account_payment.py:470](models/account_payment.py#L470)), whose docstring says reusing
  `UniqueId` "is what makes this safe to repeat".
- Fix: add `"CheckUniqueId": true` to every document in
  [`_bog_build_document`](models/account_payment.py#L500), single and package. Treat `702` as
  "already at the bank" - state Unknown with a note to look it up, never Failed - and keep the raw
  response, because `702` is not in the table and no page says whether its answer carries the
  existing `UniqueKey`.

### F3. Package lines never reach the payments

Fixed: the module reads `DocumentStatuses` (`BulkLineStatus` as a fallback) and matches by `UniqueId`, else `DocumentNo`. The finding as first written:

- S3 returns `{"Status": "S", "DocumentStatuses": [{"UniqueId": "...", "UniqueKey": 101, "Status": "P"}]}`.
  [models/account_batch_payment.py:224](models/account_batch_payment.py#L224) reads `BulkLineStatus`
  at the top level, finds nothing, and no payment gets its `UniqueKey` or status. Matching by
  `DocumentNo` ([line 247](models/account_batch_payment.py#L247)) cannot work either: lines carry no
  `DocumentNo`.
- Fix: read `DocumentStatuses` (keep `BulkLineStatus` as a fallback), match by `UniqueId`, store
  `UniqueKey`, map each line's `Status` with the document map from F1.

### F4. Recovery stores the entry id, not the document key

- T1 returns `{"Id": 1, "DocKey": 2, "DocNo": "ODOO57"}`.
  [models/account_payment.py:681](models/account_payment.py#L681) saves `1` as the document key and
  then asks S1 for document 1: another document, or `404`. The page names `DocKey` as the document's
  ID. The test fixture has only `id` ([tests/test_bog_payment.py:224](tests/test_bog_payment.py#L224)).
- T1 lists bookings; no page says an unsigned document appears there, so "not found today" is the
  expected answer for a document that is only created.
- Fix: read `DocKey` / `docKey`. As the recovery route, a re-send with `CheckUniqueId` (F2) answers
  the real question - does the document exist - for 7 days, not only today.

### F5. Foreign documents are sent in the domestic shape

- A foreign payment with memo "Invoice 12" goes out with `Nomination: "Invoice 12"`,
  `DispatchType`, `PayerInn` and `IsSalary`, without `PaymentDetail` or `Charges`. Per Postman
  v1.0.4 the foreign model has no `Nomination`, so the purpose is dropped and the document has none,
  or fails with 677. Packages (B2) get the same shape.
- The foreign purpose accepts only `a-z A-Z 0-9 / - ? ) . , ' + :` (codes -9 / 79): a Georgian memo
  fails.
- Fix: a foreign builder - `PaymentDetail` (Latin, at most 136), `Charges`, `Currency`, beneficiary
  bank code or name, recipient address, city and countries, `PurposeCode` where needed; no
  `Nomination`, `DispatchType`, `PayerInn`, `IsSalary`. The module has no fields yet for charges,
  address or countries.

### F6. PayerInn on every domestic document

- An ordinary GEL payment to a supplier carries `PayerInn` = the company code
  ([models/account_payment.py:571](models/account_payment.py#L571)). Code 59 says payer name and INN
  are filled only for Treasury payments on behalf of a third person, so BOG may refuse every
  domestic document; Postman leaves the field out
  ([section 14](#14-where-bogs-sources-contradict-each-other) #7).
- Fix: send `PayerInn` / `PayerName` only for a Treasury payment for someone else. The module sends
  no Treasury payments, so: never. Confirm with BOG ([Q7](#16-open-questions-for-bog)).

### F7. Statement paging uses Count

Fixed: `fetch_all_records` reads `totalCount` and stops at it, else on a short page. The finding as first written:

- If `Count` is the size of the current page, as the V2 pages read: a period with 2,500 entries
  returns `count` 1000, `totalCount` 2500 and 1000 records;
  [services/bog_service.py:388](services/bog_service.py#L388) sees 1000 >= 1000 and stops. 1,500
  entries are never imported and nothing reports it. The test
  [`test_fetch_all_records_stops_when_count_reached`](tests/test_bog_service.py#L160) encodes the
  Postman reading.
- Fix: total = `totalCount` when present, else `count`; keep reading until an empty page or the
  total.

### F8. Decimal keys

- `documentKey` and `entryId` are typed decimal (example `1.0`). If BOG sends `987654.0`, the match
  key becomes `"987654.0"` ([wizard/bog_statement_import_wizard.py:138](wizard/bog_statement_import_wizard.py#L138))
  while the payment holds `"987654"` from `UniqueKey`, and nothing is auto-confirmed.
  `unique_import_id` ([line 137](wizard/bog_statement_import_wizard.py#L137)) would also change if
  BOG switched between `1` and `1.0`, and the same entry would import twice.
- Fix: normalise numeric keys to integer strings before use.

### F9. README and comments the pages correct

| README / code | Pages |
|---|---|
| "There is no test environment" (README), [models/bog_connection.py:18](models/bog_connection.py#L18) | a test environment exists, by request to the business banker; host not published |
| Section 2, "`Status` vocabulary is undocumented" | documented letters ([section 13](#13-statuses-result-codes-error-codes)) |
| Section 3, Warn codes mean "not created - create it anyway?" | no page says what Warn means |
| Section 4, no lookup by our own `UniqueId` | still true; `CheckUniqueId` is the documented duplicate guard |
| Section 5, `BulkLineStatus` mapped by `DocumentNo` | `DocumentStatuses[]` by `UniqueId` |
| Section 6, rates "1/minute per rates method", [services/bog_service.py:541](services/bog_service.py#L541) | 60 per minute per method |
| "Known unknowns" | [section 17](#17-readme-known-unknowns-answered) |

Smaller: `BeneficiaryInn` is sent as stored ([models/account_payment.py:569](models/account_payment.py#L569)),
while `PayerInn` loses a `GE` prefix. If partner VATs are stored as `GE...`, BOG gets a value that
is not an identification code (codes 41, 153). Status polling makes one S1 call per payment; S2
checks many keys in one call.

---

## 16. Open questions for BOG

Neither the 43 pages nor the collection answers these.

| # | Question | Why it matters | Module today |
|---|---|---|---|
| Q1 | Test environment: host, credentials, does money move? | testing without production | no environment switch |
| Q2 | Who signs an API-created document: a user in Business Online, or the app? Are `otp/request` and `sign/document` meant for clients, and with which flow? | when a document becomes a payment | state Created until a status says more |
| Q3 | Does `Status` come as the letter (`P`) or as text? Which values does `BulkLineStatus` take? | F1, F3 | substring guess |
| Q4 | Warn codes (333, 363, 444, 701, -998, -18, -8): is the document created? How is it confirmed? | Create Anyway | 333, 444, 701 read as not created; 363 and the rest as failed |
| Q5 | `CheckUniqueId` duplicate (702): does the answer carry the existing `UniqueKey`? | recovery | flag not sent |
| Q6 | N1: is `Count` the page size or the total? Does N1 include today's entries? | F7, daily sync | `Count` read as the total |
| Q7 | Domestic `PayerInn`: required, or refused with 59 outside Treasury payments? | every domestic payment | always sent |
| Q8 | Do unsigned documents appear in current day activities? Which call finds a document by `UniqueId` or `DocumentNo`? | recovery | searches T1 by `DocumentNo` |
| Q9 | Packages: maximum lines; does one bad line reject the package; is `BULK` dispatch allowed inside a package? | payroll | 500-line self-cap |
| Q10 | `Charges`: what does `OUR` cover, and what applies when `Charges` is omitted? | foreign fees | not sent |
| Q11 | Path dates (`YYYY-MM-DD`): Tbilisi local time? | entries near midnight | Tbilisi assumed |
| Q12 | Shape of the `400` error body | readable errors | raw text kept |

---

## 17. README "Known unknowns", answered

| README item | Answer |
|---|---|
| `expires_in` for client credentials | the client-credentials page lists no response fields; the desktop and web pages document `expires_in` in seconds, Postman 1.1.1 reads it from the client-credentials answer, the implicit example shows 300. Reading it with 300 s as fallback matches |
| `Status` values | documented: 9 document letters, 10 package letters (11 on the Georgian page) |
| `BulkLineStatus` shape | a string per line inside `DocumentStatuses[]`; its values are not listed |
| `todayactivities` path | both are documented: unversioned (Documents, PascalCase) and `v2` (Statement New, camelCase, named in the limit table); Postman uses the unversioned one |
| Bulk array size limit | still not documented |

---

## 18. Sources

All under `https://api.bog.ge/docs/en/bonline/`; add `.md` for the raw page (Georgian:
`https://api.bog.ge/docs/bonline/<slug>.md`). The category pages (Introduction, Authentication,
Documents, Statement, Statement New, Exchange rates, Exchange rates New, Deposits New, Money Request
New, File Upload New, Result codes) only list their children and have no `.md`. No page shows an
update date.

| Menu | Page | Slug |
|---|---|---|
| Introduction | Introduction | `introduction` |
| | Postman Collections (NEW!) | `introduction-token` |
| Authentication | Authentication | `auth/auth-introduction` |
| | For a desktop application | `auth/desktop-authentication` |
| | Authentification for a web application | `auth/web-authentication` |
| | Authentification using token | `auth/token-authentication` |
| Documents | Individual document in the national currency | `documents/domestic` |
| | Individual document in the foreign currency | `documents/foreign` |
| | Conversion | `documents/conversion` |
| | Package transfer in the national currency | `documents/bulk-domestic` |
| | Package transfer in the foreign currency | `documents/bulk-foreign` |
| | Individual document status | `documents/status` |
| | Individual document statuses | `documents/statuses` |
| | Package transfer status | `documents/bulk-status` |
| | Cancellation of a Package Transfer | `documents/bulk-delete` |
| | Cancellation of an individual document | `documents/document-delete` |
| | Document creation codes | `documents/document-codes` |
| | Current day activities | `documents/todayactivities` |
| Statement | Statement generation | `statement/statement` |
| | Statement global and daily balances | `statement/summary` |
| | Statement entries on the page | `statement/paging` |
| Statement New | Current day activities | `statement/todayactivities` |
| | Statement generation | `statement/statementV2` |
| | Statement with revaluation | `statement/statementV2Revaluation` |
| | Statement entries on the page | `statement/pagingV2` |
| | Statement global and daily balances | `statement/summaryV2` |
| Exchange rates | A currency rate of the National Bank for a given currency | `rates/nbg` |
| | National Bank's currency exchange rate history | `rates/nbg-hist` |
| | Bank's commercial currency exchange rate | `rates/commercial-currency` |
| | Cross Rate | `rates/commercial-sellCurrency-buyCurrency` |
| Exchange rates New | Currency rate details | `rates/rate-details` |
| (top level) | Available Balance | `accounts` |
| Deposits New | Deposits list | `deposits/agreements` |
| | Deposit amounts by currency | `deposits/available-amount` |
| Money Request New | Money request creation | `money-request/create` |
| File Upload New | File upload | `files/upload` |
| Result codes | Result Codes | `result/result-codes` |
| | Error Codes | `result/reject-codes` |
| | Document Statuses | `result/document-statuses` |
| | Bulk Transfer Statuses | `result/bulk-transfer-statuses` |
| not in the menu | OTP Request | `otp/request` |
| | Document Sign | `sign/document` |
| | საბალანსო უწყისის ატვირთვის მეთოდი (balance sheet upload) | `balance-sheet` |

Postman collection v1.0.4 (2026-09-26), 46 requests, identical in both languages:

- English: `https://api.bog.ge/docs/en/files/BOG_BusinessOnline_API_EN.postman_collection.json`
- Georgian: `https://api.bog.ge/docs/files/BOG_BusinessOnline_API_KA.postman_collection.json`

The menu comes from the site's sidebar data; to find new pages, compare the Introduction page's
menu with this table.
