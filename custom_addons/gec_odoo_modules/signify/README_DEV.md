# Signify E-Signature (`signify`) — Developer guide

For a developer who has to change this module. Business view and user steps: [README.md](README.md). Module doc:
[documentations/signify.md](../../../documentations/signify.md). Signify API facts (local notes, not in git):
`dev_notes/reference/signify/signify_api_v2_reference.md`; design and review record:
`dev_notes/plans/signify_module_design.md`.

## 1. Purpose and facts

A standalone connector to the Signify API V2. Odoo sends a file and the recipients, then follows the status by
polling; Signify runs the whole signing workflow. Each Odoo user connects their own Signify account with OAuth 2.0
(section 3a). Odoo Sign is not used or extended.

| Item | Value |
|---|---|
| Depends | `base_setup` (Integrations block of General Settings), `mail` (chatter, tracking, the file viewer the button patches), `phone_validation` (`_phone_format` for E.164 numbers); Python `requests` |
| New models | `signify.document` (one file sent for signing), `signify.recipient` (one line of it), `signify.connection` (one Signify account of a user in a company, with its tokens) |
| Extended models | `res.config.settings` (Client ID and Secret as `ir.config_parameter`, the redirect URL to whitelist, the company's reminder fields), `res.company` (`signify_reminder_frequency`, `signify_reminder_max_count`) |
| Extended client code | `FileViewer` from `@web/core/file_viewer/file_viewer` (prototype patch + template extension) |
| Cron | **Signify: Sync Document Status**, every 15 minutes, as `base.user_root`, `noupdate` |
| Controllers, hooks | `/signify/oauth/start` and `/signify/oauth/callback` (section 3a); no hooks |
| Data, in manifest order | groups and privilege, cron, document views, settings view, connection views, menus, `ir.access.csv` (last) |

## 2. Architecture

```text
  ┌──────────────┐ send, sync ┌────────────┐   HTTPS   ┌───────────┐
  │ Document     │ ─────────► │ API client │ ────────► │ Signify   │
  │ + recipients │ ◄───────── │            │ ◄──────── │ API V2    │
  └──────────────┘  statuses  └────────────┘   JSON    └───────────┘
     │        ▲
     │ notes, │ "Send with Signify"
     │ copy   │ creates a draft
     ▼        │
  ┌──────────────┐
  │ Linked record│  (its chatter file viewer)
  └──────────────┘
```

Document = `signify.document`, recipients = `signify.recipient`, API client = `SignifyAPI` in
`tools/signify_api.py`, linked record = the `reference_doc` Reference field. Every Signify call goes through
`SignifyAPI`; the models never call `requests` themselves. The linked record only receives chatter notes and
attachments; nothing reads back from it.

## 3. File map

| File | Holds |
|---|---|
| `__init__.py` | imports `controllers`, `models` and `tools` |
| `__manifest__.py` | depends, data order, `web.assets_backend` and `web.assets_unit_tests` globs |
| `models/__init__.py` | model imports |
| `models/res_company.py` | reminder settings per company: `signify_reminder_frequency` (Signify's `RemindersFrequencyType` lower-cased, required, default `everyday`), `signify_reminder_max_count` (default 3) |
| `models/res_config_settings.py` | Client ID and Secret with `config_parameter=` (`signify.client_id`, `signify.client_secret`), `signify_redirect_url`, the two reminder fields related to `company_id` |
| `models/signify_connection.py` | the account: fields, unique rules, connect action, code exchange, token refresh, disconnect |
| `controllers/main.py` | `/signify/oauth/start` (PKCE, state in the session, redirect to Signify), `/signify/oauth/callback` |
| `models/signify_document.py` | the document: fields, create/write/delete guards, send, refresh, recall, create-from-attachment, cron sync, downloads |
| `models/signify_recipient.py` | the recipient line: fields, guards, payload part, sync values, signing page |
| `tools/__init__.py` | package marker |
| `tools/signify_api.py` | `SignifyAPI` (token of a connection, POST, envelope check), `oauth_client_credentials` (the one place that says "Signify is not set up"), `oauth_call` (token, userinfo, revoke), `_send` (error mapping), `SignifyError`, `SignifyTransportError`, constants (URLs, scope, routes, timeouts, signature size, batch size) |
| `security/signify_security.xml` | privilege **Signify**, groups **User** and **Administrator** (root and admin added) |
| `security/ir.access.csv` | access rows, see section 9 |
| `data/ir_cron_data.xml` | the sync cron (`noupdate`) |
| `views/signify_document_views.xml` | list, form, search, window action |
| `views/res_config_settings_views.xml` | the **Signify** setting inside the `integration` block of `base_setup.res_config_settings_view_form` |
| `views/signify_connection_views.xml` | list with **Connect Signify Account** and **Disconnect**, search, window action |
| `views/signify_templates.xml` | `signify_oauth_error`: the page the OAuth routes render on an error (message and **Back to Signify Accounts**), shape of `google_gmail.google_gmail_oauth_error` |
| `views/signify_menus.xml` | root menu **Signify**, **Documents**, **Configuration > Signify Accounts** |
| `static/description/icon.png` | app icon |
| `static/src/file_viewer/file_viewer.js` | `FileViewer` patch: group check, `canSendWithSignify` getter, click handler |
| `static/src/file_viewer/file_viewer.xml` | the **Send with Signify** header button before the core Download button |
| `static/tests/file_viewer.test.js` | Hoot tests of the button |
| `tests/__init__.py` | test imports |
| `tests/common.py` | `SignifyCommon`: companies, users with a connection each, partners, the HTTP router that patches `requests.request` (`oauth/token` names the OAuth endpoints) |
| `tests/test_signify_api.py` | the API client: token reuse, 401 refresh, envelope and error mapping, timeouts, no secrets in logs |
| `tests/test_signify_connection.py` | token refresh (expiry, rotation, `invalid_grant`, lock), disconnect rules, unique rules |
| `tests/test_signify_oauth.py` | the two routes: PKCE redirect, state checks, connect, archive of the old account, errors (`HttpCase`) |
| `tests/test_signify_payload.py` | `set-document-details` and `create-document` bodies for every role and method |
| `tests/test_signify_send.py` | the send order, cleanup on every failure point, lock, state and access guards |
| `tests/test_signify_sync.py` | status mapping, downloads, evidence, rejection, batching, per-account runs, savepoints, commit only in the cron |
| `tests/test_signify_access.py` | access rows, protected fields, defaults, linked-record check, multi-company, recall, signing page |
| `tests/test_signify_from_attachment.py` | the chatter button's server method: access, linking rules, end to end |
| `i18n/signify.pot` | translation template |
| `i18n/ka_GE.po` | Georgian |
| `README.md`, `README_DEV.md` | the two guides |

## 3a. OAuth: connecting an account

Partner credentials are database-wide `ir.config_parameter` rows (`signify.client_id`, `signify.client_secret`), set in
**Settings**; the same screen shows the redirect URL that Signify must whitelist.
The URL is `oauth_redirect_uri(env)` (`tools/signify_api.py`): `web.base.url` + `CALLBACK_ROUTE`, read from the system parameter, not `get_base_url()` (the website module
returns a company's website domain there, so the authorize leg, the token leg and the Settings URL would differ).
Scope `ALL openid email`; Authorization Code with PKCE (S256); Signify's token endpoint takes the client credentials as HTTP Basic.

1. **Signify Accounts > Connect Signify Account** (`signify.connection.action_connect`, Signify users only; a `UserError` from
   `oauth_client_credentials` when the Client ID or Secret is missing, so the user never leaves Odoo for that) opens
   `/signify/oauth/start?company_id=<active company>`.
2. `/signify/oauth/start` (auth `user`): the user must be a Signify user and the company one of their own, else 404. It stores
   `{state, verifier, company_id, redirect_uri}` in `request.session['signify_oauth']` (one pending attempt per browser session; a new start replaces it;
   a top-level key, because only `__setitem__` marks the session dirty) and redirects to Signify's `authorize` URL with the S256 challenge.
3. `/signify/oauth/callback`: pops the session entry (so an attempt works once), checks the group (404), then the state with `consteq`: no entry (expired, other tab, or another
   host, so another session) or a different state gives the error page (400) "start again from Signify Accounts". Then the company
   (404), an `error` from Signify (error page, 400), otherwise calls
   `signify.connection._signify_connect(company, code, verifier, redirect_uri)` with the `redirect_uri` stored at the start (never recomputed) as the logged-in user and redirects to the list.
4. `_signify_connect`: `token` call (code + verifier), `userinfo` call (`sub`, `email`), then under `sudo()` (users cannot write
   connections) it archives the user's other active connection of that company (tokens kept: their documents still sync) and
   writes or creates the one for this `sub`. Reconnecting an archived account reactivates it with new tokens.

`signify.connection`: unique `(user, company, sub)` and a unique index on `(user, company) WHERE active`, so each user has one
current account per company. `access_token`, `refresh_token` and `expiry` are `groups="base.group_system"`; `connected` is
`bool(refresh_token)`. A document keeps the connection it was sent with (`connection_id`, in `SYNC_FIELDS`), so status, recall and
signing links use that account even after the user connects another one.

**Token** (`_get_access_token(stale=None)`, pattern of `pos_platform_order_wolt/models/platform_order_wolt_token.py`): a token is valid
when it exists, differs from `stale` and expires in more than a minute. Otherwise the refresh runs in its own cursor
(`registry.cursor()`) under `lock_for_update` (up to 40 tries of 0.5 s, longer than the 15 s HTTP timeout), re-checks validity (another worker may
have refreshed), calls `token` with `grant_type=refresh_token`, writes, commits on leaving the `with`, and puts the values in the caller's
cache. A response without `refresh_token` keeps the old one. `invalid_grant` clears the tokens in that cursor, which commits, and then raises
"The Signify account <email> of <user> has expired: <user> must connect it again ..." (names the owner, because a manager or the cron can hit
another user's connection); a transport error during the refresh becomes a plain `UserError`, so `action_send` does not read it as an unknown
share outcome. A token answer without `expires_in` gets 1800 seconds.

**Disconnect** (`action_disconnect`): own connection only (settings administrators: any); refused while a document sent with it is
`shared`, or `finished` without its evidence report (checked with `sudo()`, every user's documents); revokes the refresh token at Signify
(a failure is only logged), clears the tokens and archives.

## 4. Send (`action_send`)

The order is the point: Odoo re-runs a request after a serialization failure (`odoo/http/retrying.py`), so nothing
irreversible may happen before the Odoo writes are safely flushed.

1. `ensure_one`, `check_access('write')` (owners can write only drafts), `try_lock_for_update(allow_referencing=True)`
   (empty → "being sent already"), state must be `draft`. Then the line checks, each on the first offending line:
   a signer without Signature Keyword; a signer or approver on `contact_type` `link` with `auth_type` `basic`
   (Signify records no identity for it); a line needing SMS (`contact_type` `mobile`, or signer/approver on
   `sms_otp`) whose partner has no `phone`.
2. `connection` = the active `signify.connection` of the **current user** in the document's company; `client = SignifyAPI(connection.sudo())`
   (no connection: a `RedirectWarning` with the button **Open Signify Accounts**, raised in `action_send` before any call; `SignifyAPI.__init__`
   keeps its plain `UserError` for Refresh, Recall, the signing page and the cron, which catch `UserError` and where connecting does not help). The connection is stored on the document in the same `sudo()` write.
3. `create-document` with the name, the extension from `file_name` and `file.to_base64()`, on `FILE_TIMEOUT`.
4. Inside one `try` (the details step):
   - `set-document-details` with `_signify_details_payload` (`shareAutomatically: false`, section 8);
   - every recipient must come back with its `recipientCode`, or `UserError`;
   - `sudo()` writes `signify_ref`, `state='shared'` and the recipients' ids and statuses;
   - a note on the linked record (`_linked_thread`);
   - `self.env.cr.flush()`: flushes the ORM **and runs the precommit hooks** (the state tracking message), unlike
     `flush_all()`.
5. `except Exception`: `_signify_discard_draft` (`delete-document` with `omitTrash: True`, its own failure is only
   logged), then re-raise, so Signify keeps nothing nobody was invited to.
6. `share-document`, the last statement, in its own `try`, on `FILE_TIMEOUT`:
   - `SignifyTransportError` (timeout, connection failure: the request may have reached Signify) does **not** delete
     the draft: `UserError` "Signify did not confirm the share of <name> (<reason>): check the Signify portal before
     sending it again."; the transaction rolls back and Odoo stays in draft;
   - any other error calls `_signify_discard_draft` and re-raises.

Accepted risk: the process dying between a successful `share-document` and the commit leaves a live document at
Signify with Odoo in draft.

## 5. Create from a chatter file

1. `file_viewer.js`: `onWillStart` caches `user.hasGroup("signify.group_signify_user")`. The getter
   `canSendWithSignify` requires that group, `state.file.isPdf`, a `thread`, and a thread model other than
   `signify.document`. It is a getter so it follows `activateFile` when the user pages through files. Requiring
   `thread` keeps it off non-chatter file objects (html_editor, the documents app).
2. Click: `orm.call("signify.document", "action_new_from_attachment", [file.id])`, then `close()`, then `doAction`.
3. `action_new_from_attachment`: `check_access('read')` on the attachment **as the user** (never `sudo`), so core's
   attachment rule decides. `reference_doc` is set only when the attachment's model is in
   `_selection_target_model()` and its record still exists; then `company_id` is the record's company
   (`_mail_get_companies`), else the active one. It creates the draft through the normal `create` (all guards
   apply) and returns the form action.

`_selection_target_model` lists non-abstract mail-thread models except `signify.document` and `discuss.channel` (a
channel link would post notes and attach signed contracts where every member sees them).

## 6. Status sync

Entry points: the cron `_cron_signify_sync`, and **Refresh Status** (`action_refresh`).

1. `_cron_signify_sync`: documents with `signify_ref` that are still in progress at Signify (`_signify_in_progress_domain`: `shared`, or
   `finished` without an evidence report; `action_disconnect` uses the same domain);
   grouped by `connection_id`; per connection `SignifyAPI(connection)` inside `try` (a connection that must be renewed, or a
   document without one, skips that group once, with a warning) and `_signify_sync(client, cron=True)` under `with_company`.
2. `action_refresh`: `check_access('read')`, then the same `_signify_sync` with `sudo()` on documents that have a
   `signify_ref`, per connection, errors raised to the user.
3. `_signify_sync`: `get-documents-status` per `STATUS_BATCH_SIZE` ids. A batch that fails with `SignifyError` is
   asked again one id at a time. A single id answered `DOCUMENT_NOT_FOUND` counts as `DELETED`; another single
   failure is logged in the cron and raised on Refresh. Per document, `_signify_apply_status` and, when the document is
   `finished` without an evidence report, `_signify_fetch_evidence` each go through `_signify_step`: in the cron each
   in its own savepoint with the error logged, so a failed evidence download keeps the Signed state and the signed
   files; on Refresh the error propagates. After each document the cron calls `ir.cron._commit_progress(1)`; when
   it reports no time left, `_signify_sync` returns False and `_cron_signify_sync` stops the whole run, the other
   accounts included (only in the cron: outside a cron `_commit_progress` commits).
4. `_signify_apply_status`: maps `documentStatus` and recipient `status` by lower-casing; an unknown value is logged
   and skipped, never written; so is `DRAFT`, which would reopen Send on a document Signify still holds. Newly
   `rejected`: a note on the document and the linked record. `finished`:
   - `_signify_fetch_signed_files` (only on the change to `finished`, never again when the files are deleted later;
     a failed download rolls the state write back, so the next run retries): attachments on the document, a
     note with them; copies of the `DOCUMENT` files to the linked record, built from the downloaded data, with
     `no_document=True`, and a note there **without** `attachment_ids` (a posted file can become the main attachment
     and start OCR); with no `DOCUMENT` file there is no copy and no note;
   - `_signify_fetch_evidence` runs after it from `_signify_sync`, in its own step (only while
     `evidence_attachment_id` is empty): `EVIDENCE_REPORT_NOT_YET_GENERATED` returns quietly and the next run asks
     again; the report stays on the document only.

## 7. Recall and the signing page

- `action_recall`: `check_access('read')`, state must be `shared`, `recall-document`, then `sudo()` sets
  `canceled`. If the Odoo write fails after Signify recalled, the next sync reads `CANCELED`.
- `signify.recipient.action_open_signing_page`: `contact_type` must be `link` ("Only link recipients have a signing
  page."), read check on the document, `generate-document-link` with both ids, returns an `ir.actions.act_url` to a
  new tab.

## 8. Payloads

`_signify_details_payload` (document) and `signify.recipient._signify_payload` (lines) build `set-document-details`.
Keys without a value are dropped; ids are sent as `int`; Selection values are Signify's names lower-cased, so the
mapping is `.upper()` / `.lower()`.

`additionalDetails` always carries `remindersFrequencyType` from the document's `company_id` and, unless it is
`never`, `remindersMaxCount`; `messageForRecipients` when the Message is set. `remindersInitialDelay` is not sent
(Signify's default: one interval).

| Recipient | Keys |
|---|---|
| every line | `recipientCode` (= the line id, used to match the answer), `name`, `email`, `mobileNumber` (E.164 via `_phone_format`, raw `phone` as fallback), `role`, `recipientContactType` |
| In Order workflow | `orderNumber` 1..n by `sequence` |
| signer | `possibleSignatureTypes: [auth_type]`; Qualified adds `qualifiedSignatureType` |
| approver | `possibleApprovalTypes: [auth_type]` |
| automatic signer | `autoSignType` |
| ID card, or remote ID (signer or approver) | `personalId` = the line's `personal_id`, when it has a value |
| company stamp | `taxCode` from the commercial partner's Tax ID |
| signer, automatic signer with a keyword | one `SIGNATURE` field: `autoPlacementText`, `SIGNATURE_WIDTH` × `SIGNATURE_HEIGHT` |

Approver and CC lines send no `fields`.

`personal_id` (stored, `readonly=False`, `precompute=True`) is computed from the partner's Tax ID when `split_vat(vat)`
gives 11 digits, and is editable on the line. It lives there because core syncs the Tax ID of a contact person with
the company: an 11-digit number typed there would overwrite the company's TIN for the company and all its contacts.

`auth_type` (stored, `readonly=False`, default `basic`) is computed by `_compute_auth_type` on `contact_type`: a
`link` line still on `basic` becomes `sms_otp`; every other value is kept (the core `service_tracking` pattern on
`product.template`). An explicit `auth_type` in `create`/`write` wins, a duplicate copies it, and an upgrade does not
recompute existing lines (the column already exists).

`SignifyAPI` takes the access token of its connection in `__init__` (`_get_access_token`); `call` POSTs to `BASE_URL + operation` with
`X-Language` `ka` or `en` from the env language and `Authorization: Bearer`, forces one refresh on HTTP 401 (`stale=` the rejected token), and `_parse` reads the JSON body **before** the HTTP code (Signify
answers 400 with a JSON reason). A non-`SUCCESS` body raises `SignifyError` carrying `status_code`; network errors
become `SignifyTransportError` (a `UserError`, mapped once in `_send`, which `oauth_call` shares). Only the operation and the status are logged, never the file, token
or secret.

## 9. Security

| Model | Group | Rights | Domain |
|---|---|---|---|
| `signify.document` | Administrator | crud | — |
| `signify.document` | User | c | — |
| `signify.document` | User | r | own: `create_uid = user` |
| `signify.document` | User | ud | own drafts |
| `signify.document` | (all) | crud | `company_id in company_ids` |
| `signify.recipient` | Administrator | crud | — |
| `signify.recipient` | User | r | lines of own documents |
| `signify.recipient` | User | cud | lines of own drafts |
| `signify.recipient` | (all) | crud | `company_id in company_ids` |
| `signify.connection` | User | r | — (token fields are system-only) |
| `signify.connection` | Settings | crud | — |
| `signify.connection` | (all) | crud | `company_id in company_ids` |

Rows of one group are OR'ed, rows without a group are AND'ed. The token fields of the connection carry
`groups="base.group_system"`; the client secret is an `ir.config_parameter`, readable by settings administrators only.

Each `sudo()`, and why it is safe:

| Where | Why |
|---|---|
| `_selection_target_model` | reads `ir.model` names only (as Sign does) |
| `action_send` writes | after `check_access('write')` and the lock; the sync fields are protected and must be written by the module |
| `action_refresh` | after `check_access('read')`; an owner cannot write a sent document, and the sync must write it |
| `action_recall` state write | after `check_access('read')` and a successful recall at Signify |
| `action_send`, `action_refresh`, `action_recall`, signing page: `SignifyAPI(connection.sudo())` | the token fields are system-only; used for a user who already passed the access check, never logged |
| `_signify_connect`, `action_disconnect` | users cannot write connections; the controller checked the user and company, `action_disconnect` checked the owner |
| `oauth_call` parameters | reads the client secret as `sudo()`; never logged |
| the cron | runs as `base.user_root`; it only writes what Signify reports for documents that already carry a Signify id |

## 10. Guards and invariants

- **Sync fields** (`SYNC_FIELDS` on both models: document state, Signify id, signed files, evidence; recipient id,
  status, action time) are refused in `create`/`write` unless `env.su`. In `create` they are also pinned to empty
  values, because defaults (a `default_<field>` context key or a personal `ir.default`) are merged after the
  override. Without this a user could point a draft at a colleague's Signify id and let the cron download that
  contract.
- **A recipient stays on its document**: `signify.recipient.write` refuses a change of `document_id` unless `env.su`.
  `write` checks the access rows against the old document only, so without it a user could move an own draft line
  onto a colleague's document. The form never sends `document_id` for an existing line.
- **Linked record readable**: `_check_reference_doc` runs on the saved records after `super().create()` and
  `super().write()`, in the caller's env, so defaults are covered. It is not an `@api.constrains`: v20 runs
  constraints on `self.sudo()`, where `has_access` is always true. A link to a missing id is stored empty by core's
  Reference field.
- **Nothing irreversible before the flush**: section 4.
- **A sent or signed document cannot be deleted**: `_unlink_except_shared_or_finished` (`@api.ondelete`,
  `at_uninstall=False`): "Recall a sent document before deleting it."; a Signed one is refused because its signed
  files and evidence report would be deleted with it. Draft, Rejected, Recalled and Deleted documents can be deleted.
- **Unknown Signify values are skipped**, never written (an unknown Selection value raises).
- **Recipients must be confirmed** by `recipientCode`, or the send stops and the draft is deleted.

## 11. Integration

- Reads `res.partner` name, email, phone and Tax ID (listed in the coupling map as a Tax ID reader). A change in
  how Tax ID holds the Georgian personal number changes the default of `personal_id`.
- The `FileViewer` extension sits next to Sign's and Documents' extensions of the same template. It anchors on the
  header Download button and does not carry `o-FileViewer-download`, so their xpaths never land on it.
- `signify_documents` (auto-installed with the Documents app) depends on `signify`: it adds `documents.mixin` to
  `signify.document` and calls `action_new_from_attachment`; it gives each company a Signify folder with the action
  pinned; the sender can open the filed file, it has no owner. Module doc:
  [documentations/signify_documents.md](../../../documentations/signify_documents.md).

## 12. Tests

All Signify HTTP is mocked; no test reaches Signify.

```bash
data_venv/bin/python odoo-bin -c odoo.conf -d <test_db> -u signify --test-enable --test-tags /signify --stop-after-init
```

The Hoot tests run through core's `WebSuite`, which `-u` does not load. After the update, run without `-u`:

```bash
data_venv/bin/python odoo-bin -c odoo.conf -d <test_db> --test-enable --test-tags /signify --stop-after-init
```

A run with no `[HOOT]` line in the log has not run the JS tests. What each file covers: section 3.

## 13. Extending safely

- Keep `share-document` the last statement of `action_send`, after `self.env.cr.flush()`; add new Odoo writes before
  the flush.
- Add a new sync field to `SYNC_FIELDS`, and write it only with `sudo()` after an explicit access check.
- Put access checks on a field in a post-`create`/`write` check, never in `@api.constrains`.
- Read anything coming from the client (attachment ids, record ids) as the user first; `sudo()` only after the check.
- New Signify statuses: add them to the Selection; until then they are skipped by design.
- Every Signify call goes through `SignifyAPI.call`, so errors, the token and logging stay in one place; OAuth calls go through `oauth_call`.
- Read tokens only through `_get_access_token`; never write them from the caller's cursor (the refresh is committed from its own).
- Post on the linked record without `attachment_ids`.

## 14. Known limitations

- Polling only: no webhook route, so status lags up to 15 minutes.
- Not proven against live Signify: whether `set-document-details` echoes `recipientCode` (if not, every send stops
  safely), whether approver and CC lines may omit `fields`, and how a status batch with one unknown id fails.
- A refresh that fails after a mid-run 401 makes the batch fall back to single ids, each failing.
- Not proven against live Signify: whether the refresh token rotates (both cases are handled), its lifetime, and the redirect URL whitelist of each Odoo host.
- **Send with Signify** can leave an extra draft on a double click or Esc during the call.
- Coexistence of the button with Sign's button is not covered by a test (Sign is not a dependency).
