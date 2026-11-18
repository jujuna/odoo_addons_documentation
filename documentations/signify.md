# Signify E-Signature

> **Module:** `signify` | **Path:** [`custom_addons/gec_odoo_modules/signify/`](../custom_addons/gec_odoo_modules/signify/)
> Status: built 2026-10-29, on gec20_prod1 since 2026-10-31; review fixes of 2026-11-06 (see [`dev_notes/plans/signify_review_20261106.md`](../dev_notes/plans/signify_review_20261106.md)); per-user OAuth connection replaced the company login on 2026-11-10 (uncommitted, see [`dev_notes/plans/signify_oauth_plan_20261110.md`](../dev_notes/plans/signify_oauth_plan_20261110.md)); Documents bridge: [`signify_documents.md`](signify_documents.md).
> Design: [`dev_notes/plans/signify_module_design.md`](../dev_notes/plans/signify_module_design.md); API: [`dev_notes/reference/signify/signify_api_v2_reference.md`](../dev_notes/reference/signify/signify_api_v2_reference.md).

## What It Does & Why It Exists

Signify is a Georgian e-signature service. It sends a document to people and collects their signatures by email,
SMS or a direct link. Signers can click to sign, confirm with an SMS code, sign with a Georgian ID card or
company stamp, pass a remote video ID check, or sign on a signature pad. This module lets an Odoo user send a PDF or
Word file for signing, and see who has signed. When everyone has signed, the signed file and Signify's evidence
report come back into Odoo. A document can be linked to any Odoo record that has a chatter (a contract on a
partner, an offer on a sale order, an agreement on an employee). The signed copy then lands on that record too.
Signify runs the whole signing workflow. Odoo only sends the document and tracks it.
Every user works with their own Signify account: each user connects it once (OAuth), and a document is sent, tracked
and recalled with the account of the user who sent it.

---

## The Big Picture — How It Works

```
Settings (partner Client ID/Secret) --> each user: Connect Signify Account (OAuth)
Draft --(Send)--> Sent --(Signify, polled every 15 min or Refresh)--> Signed --> signed files + evidence report
                    |                                             \--> Rejected (reason posted)
                    \--(Recall)--> Recalled             Signify may also report Recalled or Deleted
```

1. Once per user and company: **Signify > Configuration > Signify Accounts > Connect Signify Account** (see
   [Connection](#the-signify-connection-per-user-oauth)). Without it the user can prepare drafts, but Send stops.
2. The user creates a document: Signify > Documents > New with an uploaded file, or **Send with Signify** in the
   viewer of a PDF in any chatter (the draft opens with that file and that record already linked). They optionally link it to a record
   ("Linked To"), then add the recipients in order.
3. **Send** uploads the file, gives Signify the recipients and their methods, and invites them, all with the
   Signify account of the user who clicked. The document becomes **Sent** and keeps that account in **Sent With**.
4. Signify emails or texts the recipients, or the user opens a recipient's signing page from Odoo (Link
   recipients).
5. A scheduled action asks Signify for the status of every open document every 15 minutes, each with the account
   it was sent with. **Refresh Status** asks at once. Recipient lines show Waiting, To Act, Done or Rejected.
6. When the document is **Signed**, the signed files are saved on the document. The signed document is also
   copied to the linked record with a note in its chatter. The evidence report is fetched as soon as Signify has
   generated it, and it stays on the Signify document only.

Odoo is polled rather than called back because prod1 is not reachable from the internet. A webhook is planned as P3
for installations that are.

### Key Decision Points
- **Which Signify account sends:** the account of the user who clicks Send, in the document's company. The user needs a
  Signify plan with API access (Business Pro or Enterprise). The document keeps that account for status, recall, signing
  links and the cron, whoever opens it later.
- **Connecting another Signify account:** it archives the user's current one for that company. The archived account
  keeps serving the documents sent with it.
- **Order** (`workflow_type`): *In Order* sends recipients one after another, by the line order; *All at Once* invites everyone together.
- **Role** per line: Signer, Approver, CC (receives the signed copy) or Automatic Signer (our company seal or
  Georgian qualified signature, applied by Signify).
- **Delivery** per line: Email, SMS, or Link. A Link recipient gets no message; the user opens the page from
  Odoo, for example on the office PC with the signature pad.
- **Method** per line: Basic, SMS Code, Qualified (Georgian ID card, Georgian company stamp, EU), Signature Pad,
  Remote ID.
- **Signature Keyword**: a word printed in the file, such as "Director". Signify places the signature field
  there. Without it, Signify rejects the send with its own message, and nothing is sent.

---

## When to Use It (and When Not To)

### This module is for:
- Contracts and agreements that need a legally strong Georgian signature: ID card, company stamp, or remote video ID.
- Signers outside the company who sign on their phone by SMS code.
- Signing in the office on a Signify signature pad.

### Use something else when:
- The signature only needs to be drawn in Odoo, and the fields are placed on the page with a mouse: use Odoo
  **Sign** (installed, unused on prod1).
- You need the Georgian ID card inside Odoo Sign: `id_ge_sign` does that on Odoo 19, but it does not load on 20.

---

## Real-World Scenarios

### Scenario 1: Service contract to a customer, SMS code
**Situation:** a sales manager has a PDF contract for customer "Alfa LLC". The contract has the word "Client"
under the signature line.
**What they do:**
1. Signify > Documents > New, then upload the PDF, and set Linked To = the Alfa LLC contact.
2. Add a recipient line: the customer's director as Signer, Delivery SMS, Method SMS Code, keyword "Client".
3. Click **Send**.
**What happens:** the director receives an SMS, opens the document, and signs with a one-time code. Within 15
minutes, the document shows Signed. The signed PDF appears on the Alfa LLC contact, with a chatter note. The
evidence report is on the Signify document.

### Scenario 2: Two-party agreement with Georgian ID card and our seal
**Situation:** an agreement must be signed by a private person with an ID card, then sealed by our company.
**What they do:**
1. Line 1: the person as Signer, Method Qualified, Georgian ID Card, keyword "Party B".
2. Line 2: our company as Automatic Signer, Company Seal, keyword "Party A".
3. Order: In Order.
**What happens:** Signify sends the ID-card step to the person, using the Personal Number of the recipient line
(filled from the contact's Tax ID when that is 11 digits). After the person signs, Signify applies the seal. If the
line has no Personal Number, none is sent, and Signify refuses the ID-card step with its own message.

### Scenario 3: Contract already in a sale order's chatter
**What they do:** open the PDF in the sale order's chatter, click **Send with Signify** in the viewer header, add
the recipients in the draft that opens, Send.
**What happens:** the draft has the PDF and "Linked To" = the sale order; the signed copy comes back to that sale
order. The button shows only for Signify users and only for PDFs: Odoo's viewer does not open Word files, so a
DOC/DOCX goes through Signify > Documents > New.

### Scenario 4: Customer signs at the front desk on the pad
**What they do:** a line with Delivery Link and Method Signature Pad, then Send. Then click the open-page icon on
that recipient line.
**What happens:** the Signify page opens in a new tab on the PC with the pad, and the customer signs there.
Anyone who opens a Link + Basic page signs as that recipient, so use Link only when the signer is in front of the
screen.

---

## How Things Work Under the Hood

### The Signify connection (per-user OAuth)

Signify's API takes an OAuth bearer token, not a company login. Each user therefore has a `signify.connection`
([`signify_connection.py`](../custom_addons/gec_odoo_modules/signify/models/signify_connection.py)): their Signify account
for one company, with its tokens. The tokens are visible to Settings administrators only.

- **Setup (once per database):** the Client ID and Client Secret that Signify gives to the Odoo partner go in Settings
  (see Configuration). The callback URL is built from the system parameter `web.base.url` (not from a company's website
  domain). Signify must whitelist it for every Odoo host, so it must not change: freeze it with `web.base.url.freeze`.
- **Connect:** the button opens `/signify/oauth/start`
  ([`controllers/main.py:19`](../custom_addons/gec_odoo_modules/signify/controllers/main.py#L19)) for the active
  company. Odoo sends the browser to Signify's authorize page with a PKCE challenge (S256) and a random `state`. The
  `state`, the PKCE verifier, the company and the callback URL wait in the user's session: one pending attempt per browser session,
  a new Connect replaces it.
- **Callback:** `/signify/oauth/callback`
  ([`:44`](../custom_addons/gec_odoo_modules/signify/controllers/main.py#L44)) takes the session entry out (a user outside the Signify
  group gets a 404; no entry or a different state, for example an expired attempt or another Odoo address, gets a plain "start again" message),
  exchanges the code for tokens with the Client Secret, the verifier and the callback URL saved at the start, reads the account id and email from `/userinfo`, and saves the connection
  ([`_signify_connect()`](../custom_addons/gec_odoo_modules/signify/models/signify_connection.py#L44)). A refused
  connection (for example Cancel) shows Signify's own text.
- **One active account per user and company** (unique index on `active`). Connecting the same Signify account again
  refreshes its row. Connecting a different one archives the old row first. The old account is not revoked: its
  tokens stay, so the documents already sent with it keep syncing and can be recalled.
- **Send:** `action_send` takes the clicking user's active connection for the document's company and stores it on
  the document as **Sent With** (`connection_id`). Status, Refresh, Recall, the signing link and the cron all use
  that stored connection, never the current user's. A colleague can open and refresh the document, and Signify sees
  the sender's account.
- **Token refresh**
  ([`_get_access_token()`](../custom_addons/gec_odoo_modules/signify/models/signify_connection.py#L84)): the access
  token lasts about 30 minutes and is renewed a minute early, or after a 401. The renewal runs in its **own cursor**
  under a row lock and is committed at once. Reason: Signify does not document whether a refresh token can be used
  twice. If the renewal lived in the request's transaction, a rollback (a failed Send, a retried request) would lose
  the new token while Signify had already retired the old one. The lock makes two workers wait for one refresh. When
  the refresh response has no new refresh token, the old one is kept.
- **Expired grant:** when Signify answers `invalid_grant` (revoked, password changed, refresh token expired) the
  stored tokens are cleared and the message names the account and its owner and says the owner must connect it again. Pressing Connect with the same
  Signify account restores the row, and its documents sync again. The cron skips an account that cannot connect and
  goes on with the others.
- **Disconnect:** a user disconnects their own account only (a Settings administrator, any). It is refused while a
  document sent with it is Sent, or Signed without its evidence report. Otherwise Odoo revokes the refresh token at
  Signify (a failed revoke is only logged), clears the tokens and archives the row.
- **Documents sent before OAuth** have no account. They are not updated any more: Refresh, Recall and the signing
  link say to connect an account, and the cron logs a warning and skips them. They keep the state they had. (On
  prod1 and gec20_signify_test there were none when OAuth replaced the login.)
- **Access:** Signify users read the connections of their companies, without the token fields; only Settings
  administrators write them. A user's own actions (connect, disconnect) go through checked methods that write with
  `sudo()` ([`security/ir.access.csv`](../custom_addons/gec_odoo_modules/signify/security/ir.access.csv)).
- **Neutralize** ([`data/neutralize.sql`](../custom_addons/gec_odoo_modules/signify/data/neutralize.sql)): a copied
  database loses the Client ID and Secret and every stored token, so a test copy cannot act on Signify with the live
  accounts.

### Core Logic
- **action_send()** ([`signify_document.py:108`](../custom_addons/gec_odoo_modules/signify/models/signify_document.py#L108)):
  - The order matters. Odoo re-runs a request after a database conflict, so nothing irreversible may happen
    before the last step:
    1. create the Signify draft;
    2. set the recipients with `shareAutomatically: false`;
    3. write every Odoo change and run `cr.flush()`, which also writes the "Draft -> Sent" tracking message;
    4. **`share-document` as the very last statement.**
  - An error in steps 2-3 deletes the Signify draft, then shows the error. `share-document` has its own `try`: a
    timeout or connection failure there (`SignifyTransportError`) does **not** delete the draft, because Signify may
    have shared it. The user gets "Signify did not confirm the share of ...: check the Signify portal before sending
    it again.", and Odoo stays in Draft. Any other error on share deletes the draft.
  - The record is locked (`try_lock_for_update`), so a double click cannot send twice.
- **SignifyAPI** ([`tools/signify_api.py:66`](../custom_addons/gec_odoo_modules/signify/tools/signify_api.py#L66)):
  - Is built from one connection and sends its bearer token. It is created once per click, or once per account in a
    cron run.
  - Reads Signify's `status` before the HTTP code, because Signify answers HTTP 400 with a JSON reason.
  - On HTTP 401 it asks the connection for a new token once and repeats the call.
  - A timeout or connection failure raises `SignifyTransportError`, so the caller can tell "no answer" from a refusal.
  - Never logs the file, the token or the secret.
- **_cron_signify_sync() / _signify_sync()** ([`signify_document.py:191`](../custom_addons/gec_odoo_modules/signify/models/signify_document.py#L191), [`:206`](../custom_addons/gec_odoo_modules/signify/models/signify_document.py#L206)):
  - Groups the open documents by their connection and syncs each group with that account, in the account's company.
    An account that cannot connect (expired grant, no connection) is logged and skipped. **Refresh Status** does the
    same grouping for the selected documents and shows the error.
  - Asks for statuses in batches of 500.
  - A batch Signify refuses is asked again one document at a time. "Document not found" marks that document
    Deleted.
  - In the cron, the status and signed-files step and the evidence step of a document are two separate savepoints,
    and each document is committed on its own. One bad document, or a failed evidence download, cannot undo the run
    or the Signed state and the signed files; the evidence is retried at the next run. The loop stops when the cron
    has no time left. In Refresh, errors are shown to the user.
- **_signify_apply_status()** ([`:245`](../custom_addons/gec_odoo_modules/signify/models/signify_document.py#L245)):
  - Maps Signify's status names to Odoo's by case: `FINISHED` <-> `finished`.
  - A status Odoo does not know is logged and skipped, never written. A `DRAFT` answer is ignored the same way, so
    Send cannot reopen on a document Signify still holds.
  - On Rejected, it posts the recipient's reason when Signify sends one.
  - On Signed, it downloads the files ([`:276`](../custom_addons/gec_odoo_modules/signify/models/signify_document.py#L276)); the sync then fetches the evidence ([`:299`](../custom_addons/gec_odoo_modules/signify/models/signify_document.py#L299)) in its own step.
  - The copy on the linked record is built from the downloaded data. When Signify returns no signed document file,
    no copy is made and no note is posted there.
- **action_new_from_attachment()** ([`signify_document.py:177`](../custom_addons/gec_odoo_modules/signify/models/signify_document.py#L177)):
  - The chatter button's server side ([`static/src/file_viewer/`](../custom_addons/gec_odoo_modules/signify/static/src/file_viewer/)).
  - It reads the attachment **as the user** with an explicit `check_access('read')`, so a file the user cannot
    open cannot be copied into a Signify draft (Odoo's AccessError). Sign's own button has no explicit check here.
  - It links the draft only when the file's model is a valid "Linked To" target and the record still exists; a file
    whose record is gone gives an unlinked draft.
  - The draft takes the linked record's company (`_mail_get_companies`), not the active company.
- **_signify_payload()** ([`signify_recipient.py:76`](../custom_addons/gec_odoo_modules/signify/models/signify_recipient.py#L76)):
  - Builds one recipient for Signify. The phone is sent in E.164 format; `personalId` is the line's Personal Number,
    the tax code comes from the company's Tax ID.
  - Approvers and CCs get no signature field.
- **action_open_signing_page()** ([`signify_recipient.py:124`](../custom_addons/gec_odoo_modules/signify/models/signify_recipient.py#L124)):
  the server refuses recipients whose Contact Type is not Link ("Only link recipients have a signing page."). It asks
  Signify for the link with the document's account.

### Important Fields (only the ones that matter)
- `state`: Draft, Sent, Signed, Rejected, Recalled, Deleted. These are Signify's own document statuses.
- `personal_id` (Personal Number) on the recipient: what is sent as `personalId` for Georgian ID card and remote ID.
  Computed from the contact's Tax ID when that is 11 digits, and editable. It lives on the line because core syncs
  the Tax ID of a company's contact person with the company.
- `connection_id` (Sent With) on the document: the account that sent it. It is set by Send only, users cannot edit it,
  and an account with documents cannot be deleted. A document without it cannot be synced.
- `signify_ref` on the document and on each recipient: the Signify ids that the sync and the signing link use.
- `signed_attachment_ids`: if empty on a Signed document, the next sync downloads the files.
- `evidence_attachment_id`: if empty on a Signed document, the document stays in the cron's list until the
  report arrives.

---

## Configuration & Settings

- **Client ID / Client Secret / Redirect URL** (Settings > General Settings > Integrations > Signify,
  [`res_config_settings.py`](../custom_addons/gec_odoo_modules/signify/models/res_config_settings.py)):
  - The Client ID and Secret identify the Odoo installation (the partner app) to Signify. They are stored as the
    system parameters `signify.client_id` and `signify.client_secret`: **one pair for the whole database, not per
    company**. The settings screen is for Settings administrators.
  - The Redirect URL is the callback (`<web.base.url>/signify/oauth/callback`). Give it to Signify to whitelist, for
    every Odoo host that will connect. It always comes from the system parameter `web.base.url`, even if a company has a website domain. Set `web.base.url.freeze` so core does not rewrite the base URL.
  - Without the Client ID and Secret, Connect and token renewal stop with "Signify is not set up".
  - The user who connects needs a Signify Business Pro or Enterprise plan (Signify's requirement for API access).
- **Signify Accounts** (Signify > Configuration > Signify Accounts): the list of connections. It opens on "My
  Accounts". **Connect Signify Account** starts the flow; **Disconnect** appears on connected rows.
- **Groups** (Settings > Users, privilege "Signify"):
  - **User** sees and sends their own documents, and edits or deletes them only while they are drafts.
  - **Administrator** sees and edits every document of their companies.
  - Rows: [`security/ir.access.csv`](../custom_addons/gec_odoo_modules/signify/security/ir.access.csv).
- **Scheduled action** "Signify: Sync Document Status": every 15 minutes, runs as OdooBot.

---

## Dependencies

| Requires | Why |
|---|---|
| `mail` | Chatter, tracking and notes on the document and on the linked record |
| `base_setup` | The Integrations block in General Settings |
| `phone_validation` | Formats the contact's phone as an international number for SMS |

| Works With (optional) | What It Adds |
|---|---|
| Any app with a chatter | Its records can be "Linked To" and receive the signed copy |
| Documents app | [`signify_documents`](signify_documents.md) files signed files and evidence reports in a per-company Documents folder and lets "Send with Signify" be pinned on Documents folders |

---

## Gotchas & Non-Obvious Behavior

- **Personal number:**
  - For ID-card and remote-ID signing, the recipient line's Personal Number is sent. It fills from the contact's Tax
    ID when that holds 11 digits, and can be edited.
  - A contact person of a company inherits the company's 9-digit code, so no personal number is sent until the line's
    Personal Number is filled in.
  - Never type a personal number into the Tax ID of a company's contact person: core syncs it with the company, so it
    would overwrite the company's TIN for the company and all its contacts.
  - On prod1, 1 of 20 employee work contacts had a Tax ID (2026-10-29).
- **Status is not instant:** without a webhook, Odoo learns about a signature at the next 15-minute run or on
  Refresh.
- **Only the signed document goes to the linked record:**
  - Files a signer attached in Signify, and the evidence report, stay on the Signify document.
  - The note on the linked record names the files but does not attach them, so a posted file cannot become that
    record's main attachment and start OCR.
- **Sync fields cannot be set by users:** `state`, the Signify ids and the downloaded files are refused in
  create and write for everyone except the module itself. Defaults (`default_*` in the context or a personal
  default) are overridden on create. Otherwise, a user could point a draft at a colleague's Signify document and
  let the cron download that contract.
- **Linked To must be readable:** a user cannot link a record they cannot read, on create or on write. The check
  runs on the saved value ([`:87`](../custom_addons/gec_odoo_modules/signify/models/signify_document.py#L87)), so a default cannot slip a link in. A link to a
  record that does not exist is stored empty by core's Reference field.
- **Not linkable:** Discuss channels, Signify documents and abstract models. A PDF from a channel or DM gives an
  unlinked draft, so notes and signed contracts never land in a channel that every member can see. The button is
  hidden on a Signify document's own files.
- **Known risk:** if the server dies in the second between Signify sharing the document and Odoo's commit,
  Signify has sent invitations while Odoo still shows Draft. A second Send would create a second document. A timeout
  on the share call leaves the same state on purpose, so the user must check the Signify portal before sending again.
- **A Sent document cannot be deleted:** "Recall a sent document before deleting it."
- **Another Signify account is fine:** connecting a different account archives the old one but does not lose its
  documents, because each document keeps its own connection. Do not disconnect an account whose documents are in
  progress: Odoo refuses it until they are signed and their evidence has arrived (or recalled).
- **Connect again after expiry:** an account whose Signify grant ended (revoked, password changed) shows as not
  connected. Its documents stop syncing until the same user connects the same Signify account again. A different
  Signify account does not take them over.
- **Callback host:** Signify rejects a callback URL that is not whitelisted. A new Odoo address, or a changed base
  URL, needs Signify to whitelist it first. Odoo's refresh request does not send the URL, so only new connections need it.
- **Test copies:** the neutralize script clears the Client ID, Secret and all tokens. A copy that should talk to
  Signify needs them filled in again and its users connected again.
- **Everyone in the Signify group sees the account emails** of their companies (no tokens), not only their own.
- **Georgian:** [`i18n/ka_GE.po`](../custom_addons/gec_odoo_modules/signify/i18n/ka_GE.po), 127 of 127 strings (fields, views, errors,
  the chatter button). 62 reuse the exact wording of our reviewed `gec_i18n` packs; after a string change, export the
  `.pot` again (`odoo-bin i18n export -d <db> signify`) and translate the new lines.
- **Open questions for Signify** (design section 11): a test sandbox, keyword placement details, file size, whether
  approvers need a field, whether email may be left out for SMS recipients, and deleting shared documents.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`../dev_notes/plans/signify_module_design.md`](../dev_notes/plans/signify_module_design.md): design v2, decisions U1-U9, bug-hunt and verification.
- [`../dev_notes/plans/signify_oauth_plan_20261110.md`](../dev_notes/plans/signify_oauth_plan_20261110.md): per-user OAuth, decisions D1-D4, provider facts, open questions for Signify.
