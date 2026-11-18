# Sign with Georgian ID Card (QES) (`id_ge_sign`) — Developer guide

For a developer who knows Odoo 20 Sign but not this module. Business use and setup:
[README.md](README.md). Flow notes with core references:
[documentations/id_ge_sign.md](../../../documentations/id_ge_sign.md).

## 1. Purpose and facts

The module plugs the Georgian ID Card into Sign 20's external-signature flow, the one
`sign_itsme` uses. Core freezes the document, waits for a signature increment, appends it and
completes the request; the module replaces only the step where core would open a session at
Odoo's signature host, and launches the desktop card application instead. It never sets
`external_signature_session_token`, so core never calls that host.

| | |
|---|---|
| Depends | `sign` (roles, external-signature flow, completion). Python: `cryptography`, `asn1crypto` (both in Odoo's requirements) |
| New models | none |
| Extended models | `sign.item.role`, `sign.request`, `sign.request.item`, `res.config.settings`, `ir.config_parameter` |
| Controllers | `GeoeidController`, inherits core `Sign` controller |
| Hooks, crons | none |
| Neutralize | `data/neutralize.sql` clears every card session token |
| Assets | `static/src/**` in `web.assets_backend` and `sign.assets_public_sign` (the backend and the public signing page load `Document` from different bundles); `static/tests/**` in `web.assets_unit_tests` |

Data files, in manifest order: `data/ir_config_parameter.xml` (two settings defaults, then the
certificate fill), `report/sign_completion_report.xml` (completion mail and certificate of
completion), `views/res_config_settings_views.xml` (the settings block),
`views/sign_item_role_views.xml` (the Roles menu).

## 2. Architecture

```text
Signing page (dialog)        Odoo                          Card application
─────────────────────        ────                          ────────────────
Proceed to Signing ────────► core /sign/sign
                             freeze the PDF, new token
launch link ◄─────────────── geoeid-unitool://.../init/<token>
open the link ───────────────────────────────────────────► GET init, document
                                                           place block, PIN3
                             POST submit ◄──────────────── signed PDF
                             verify, store card data,
                             core appends and completes
poll status ───────────────► idle / launched / signed / failed
```

Signer line = `sign.request.item` (card session fields `geoeid_*`); frozen and signed PDFs =
core `sign.request.document` (`frozen_file`, `file`).

The browser only triggers the app. `init`, `document` and `submit` are plain HTTP calls from
the app, authorised by a 10-minute token; `status` and `cancel` are JSON-RPC calls from the
signing page, authorised by the signer's `access_token`.

## 3. File map

| File | Holds |
|---|---|
| `__init__.py` | imports `models`, `controllers` |
| `__manifest__.py` | manifest |
| `README.md` | user guide |
| `README_DEV.md` | this guide |
| `controllers/__init__.py` | import |
| `controllers/geoeid.py` | all card routes, the public-link override and the raw multipart re-parse |
| `data/geo_signing_ca.pem` | the state's GEO Signing CA G2 and GEO Signing CA certificates (id.ge), PEM |
| `data/ir_config_parameter.xml` | language default (noupdate); the certificate fill call |
| `data/neutralize.sql` | clears card session tokens in a neutralized copy |
| `dev/mock_universal_program.py` | fake card app; written for the old hash mode, does not match today's routes |
| `i18n/ka_GE.po` | Georgian translations |
| `models/__init__.py` | imports |
| `models/ir_config_parameter.py` | certificate fill and the PEM check on `id_ge_sign.trust_anchor` |
| `models/res_config_settings.py` | language setting |
| `models/sign_item_role.py` | the `geoeid` authentication and its core role hooks |
| `models/sign_request.py` | public-attempt key; mails to placeholder addresses skipped |
| `models/sign_request_item.py` | card session fields, signer ordering, launch, submit, fail, cancel, identity, placeholder, audit |
| `report/sign_completion_report.xml` | hides placeholder emails; adds "Georgian ID Card Signatures" to the certificate of completion |
| `static/src/components/sign_request/document_signable_geoeid.js` | routes card roles to the dialog; public links skip the name and email dialog |
| `static/src/components/sign_request/signable_PDF_iframe_geoeid.js` | fills the card signer's signature fields with a name image |
| `static/src/dialogs/geoeid_signer_dialog.js` | the signing dialog: launch, open the app, poll, cancel |
| `static/src/dialogs/geoeid_signer_dialog.xml` | its template |
| `static/tests/geoeid_signer_dialog.test.js` | Hoot tests of the dialog and the patches |
| `tests/__init__.py` | imports |
| `tests/common.py` | fixtures: card-shaped certificates, roles, requests, core `PdfSigner` playing the app |
| `tests/test_*.py` | one file per area, listed in section 10 |
| `tools/__init__.py` | imports |
| `tools/cms.py` | PAdES / CMS verification and signer identity |
| `tools/pdf_update.py` | what the returned PDF may add to the frozen one: one signature field, nothing else |
| `tools/protocol.py` | constants, the launch URL and the init JSON |
| `views/res_config_settings_views.xml` | "Sign with Georgian ID Card" block in Sign settings |
| `views/sign_item_role_views.xml` | **Sign > Configuration > Roles** list, for Sign managers |

## 4. Flows

### Request creation

1. `SignRequestItem.create`: for a request with a `geoeid` role, refuses a template with more
   than one document and sets the card signers' `mail_sent_order` after the last regular signer.
2. Core `sign.request` then numbers every signer strictly when any role
   `requires_external_signature`, so all signers sign one after another.

### Launch (signer presses Proceed to Signing)

1. `GeoeidSignerDialog.launch` calls core `/sign/sign/<request>/<token>` with the field values.
2. Core stores the values and calls `_sign_externally`, which calls our
   `_freeze_documents_for_external_signature` override (refuses more than one document, before
   freezing), then freezes the document (`frozen_file`, state `awaiting_signature`).
3. `_get_external_signature_url`: with no `id_ge_sign.trust_anchor` it returns only
   `{'message': ...}`, and core releases the frozen document with `_cancel_external_signature`.
   Otherwise it writes a new `geoeid_token`, `geoeid_token_expiry` (now + 10 minutes), state
   `launched`, clears `geoeid_error` and `geoeid_signed_digest`, and returns the
   `geoeid-unitool://` URL from `protocol.launch_url`. Called without documents (page load) it
   returns `{}`.
4. The dialog opens the URL through a hidden link and polls `status` every 3 seconds, at most
   200 times (the token lifetime).

### The app fetches the document

1. `init`: `_geoeid_find_by_token` (unknown or expired token → empty), then 404 unless
   `launched`; returns `protocol.build_init_document_json` (document mode, language from
   `_geoeid_settings`; the profile is always Baseline B), `Cache-Control: no-store`.
2. `document`: the exact `frozen_file` bytes, 404 unless `launched` with one awaiting document.

### Submit (the app uploads the signed PDF)

1. Route `submit`, `max_content_length` = core's 25 MiB + `_geoeid_signature_increment_limit` +
   64 KiB; 404 unless the item is `launched` or `signed`.
2. `_read_signed_file`: takes `signedFile`; when werkzeug found no file (the app's unquoted
   boundary contains `=`), re-parses the raw body with the boundary from the header.
3. `_geoeid_submit_document`, in this order:
   - locks the request, then the item, and re-reads them;
   - refuses a token that is not the item's or has expired;
   - an item already `signed` returns for the same sha256 and refuses other bytes;
   - refuses unless `launched`, item and request `sent`, validity not passed, one awaiting
     document;
   - size: longer than the frozen PDF, at most `id_ge_sign.max_signature_increment` (5 MiB) more;
   - `verify_pdf_signature(signed, anchors, expected_prefix=frozen)`, then refuses an untrusted
     result;
   - strips `PNOGE-` and runs `_geoeid_check_identity`;
   - inside a savepoint: writes the certificate fields, `signed`, `geoeid_signed_on` and the
     digest; `_geoeid_update_placeholder`; posts `_geoeid_audit_body` as the signer (their user
     when one exists, so the sign log names them); calls core `_apply_external_signatures`,
     which appends the increment and completes the request; raises unless the item is now
     `completed`, which rolls the savepoint back.
4. The route answers 409 with `Retry-After: 1` on `LockError`; on `CmsVerificationError`,
   `ValueError` or `UserError` it calls `_geoeid_fail` and answers 400 with the reason.

`_geoeid_fail` takes the locks with `try_lock_for_update` and returns quietly when another
transaction holds them or the item is no longer the same `launched` attempt. Otherwise: state
`failed`, token cleared, reason cut to 512 characters into `geoeid_error`, and an internal note
(`mail.mt_note`) authored by the signer's partner.

### Status and cancel (signing page)

- `status`: `{'state': geoeid_state}` only, `failed` for an unknown signer. The reason never
  goes to the browser; the dialog shows a fixed sentence.
- `cancel` → `_geoeid_cancel`: for `launched` or `failed`, core `_cancel_external_signature`
  (frozen document released), state `idle`, token and error cleared. The dialog also calls it
  on unmount.

### Signer change

`write`: when `partner_id` changes on an item that had a partner, every non-idle card session
of the old signer is cancelled with `_geoeid_cancel` after core's `write`. Core allows the
change only on a sent item whose role has `change_authorized`, and rotates `access_token` only
when the invitation was mailed; without this cancel the old signer's app could still submit for
up to 10 minutes. The old signer's stored field values stay, as in core itsme.

### Public link

1. Front end `_signDocuments` patch: for an unknown public user on a card role, calls
   `/sign/geoeid/public` with a browser UUID `attempt_id` kept across retries, then continues
   as a known signer. Core `/sign/send_public` (`make_public_user`) is overridden to take the
   same path for a shared request with a single card role.
2. `public_user` refuses unless: valid UUID, `shared` request, matching token (constant-time),
   one item, no partner, `geoeid` role, validity not passed.
3. It looks up `geoeid_public_attempt` = sha256(session id) + shared request id + attempt id. A
   match is reused only while `sent` or `signed`, active, under 10 minutes old and valid;
   otherwise it creates an archived partner "Georgian ID Card signer" with a unique
   `@id-card.invalid` email and copies the shared request as its creator (`no_sign_mail`,
   state `sent`).
4. After a trusted submit, `_geoeid_update_placeholder` renames the partner, writes the
   personal number to `vat`, and unarchives it unless another active partner (same or no
   company) has that number with or without `GE`.

### Mails to placeholder addresses

`_send_signature_access_message`, `_send_completed_documents_message`, `_send_refused_message`
skip `@id-card.invalid` addresses, and `_get_final_recipients` drops them. The QWeb inherits hide
the address in the completion mail and the sign log.

### Certificates (`id_ge_sign.trust_anchor`)

- `_geoeid_fill_trust_anchor` reads `data/geo_signing_ca.pem` and saves it **only when the key
  is empty**, so an administrator's value survives every upgrade and an emptied key is refilled.
- `_check_geoeid_trust_anchor` refuses a non-empty value with no PEM certificate.
- `tools/cms._check_trust` is single-level: the card certificate's issuer must equal an
  anchor's subject and verify with its key. The anchor must hold the issuing CA, not a root.

## 5. Verification (`tools/cms.py`)

`verify_pdf_signature` accepts the returned PDF only when:

- it starts with the exact frozen bytes;
- the last `/ByteRange` covers the whole file, with only whitespace after it;
- the CMS has one signer, signed attributes, content type *data* and a `messageDigest` equal to
  the hash of the signed bytes;
- the signature verifies with the certificate key (RSA PKCS#1 v1.5 only);
- the certificate is valid now and its key usage has nonRepudiation (the card's signing certificate; its login
  certificate has digitalSignature only and is refused);
- it chains to an anchor (`trusted`); the model refuses anything else.

The identity is the subject's common name and `serialNumber` (`PNOGE-` + 11 digits). Not
checked: revocation (OCSP/CRL) and timestamps.

A valid signature proves who signed the bytes, not what the bytes say: the file comes from the
signer's PC. So `_geoeid_submit_document` then calls `check_signature_update`
(`tools/pdf_update.py`), which accepts the returned PDF only when:

- every update after the frozen bytes is plain objects plus one cross-reference that lists exactly
  them, generation 0, no free entry, `/Prev` pointing at the table before it. Readers disagree on
  a broken table (one shows the old object, another the new one), so such a file is refused
  before anything is compared;
- every object the update writes reads cleanly in the library's strict mode, and the trailer names
  one `/Root`: a repeated key or a stream that does not end at its `/Length` is read one way by
  PyPDF2 and another by pdf.js and Poppler;
- read from both files, the document is the same: the whole object graph from the catalog, except
  `/AcroForm` and `/OutputIntents` on the catalog and `/Annots` on a page;
- the form gained exactly one field, a signature widget holding only the keys in `FIELD_KEYS`
  (no action), and each page's annotations are the old ones plus, at most, that field;
- the visible block is at most `id_ge_sign.max_signature_area_percent` of its page (default
  `protocol.GEOEID_MAX_SIGNATURE_AREA_PERCENT`, 2; a real card block measured 0.73).

Core `PdfSigner` output passes too (two updates in a row; cross-reference streams on templates
that use them), because the tests and an earlier company signature rely on it.

## 6. Data

| Record | noupdate | On upgrade |
|---|---|---|
| `geoeid_language` (`id_ge_sign.language` = `ka`) | yes | left alone |
| `<function _geoeid_fill_trust_anchor>` | no, at the file root | runs on every install and upgrade; fills an empty key only |

The function sits outside the `noupdate` block on purpose: a data `<function>` inside a
noupdate block runs only at install. `data/geo_signing_ca.pem` must ship with the code;
`file_open` raises without it and aborts the install or upgrade.

`id_ge_sign.max_signature_increment` has no record and no screen; the default is in
`tools/protocol.py`.

## 7. Guards and invariants

| Guard | Where | Why |
|---|---|---|
| Never set `external_signature_session_token` | whole module | core calls Odoo's signature host whenever it is set |
| Card data written before `_apply_external_signatures`, inside one savepoint, postcondition `completed` | `_geoeid_submit_document` | core completes the request (certificate of completion, mails) inside that call |
| Lock order: request, then item | submit, cancel, fail | the same order everywhere avoids deadlocks |
| `_geoeid_fail` never raises and never overwrites another attempt | `_geoeid_fail` | it runs inside the route's error handler |
| The token is not burned on success; the expiry ends it | `_geoeid_find_by_token`, submit check | an identical re-upload (same digest) must still be acknowledged |
| `init` and `document` only while `launched` | controller | the frozen PDF is not served again after signing |
| No anchor → no launch; untrusted → refused | `_get_external_signature_url`, `_geoeid_submit_document` | every completed card signature has a verified chain |
| Identity compared only for a commercial partner with an 11-digit `vat` | `_geoeid_check_identity` | a contact person inherits the company's `vat` |
| Placeholder unarchived only without an active duplicate | `_geoeid_update_placeholder` | one visible contact per person |
| Defaults in `_geoeid_settings` equal the settings fields' defaults | `_geoeid_settings` | the settings screen and the flow must agree |

## 8. Security

No new model, so no `ir.access.csv` rows.

| Field or element | Restricted to |
|---|---|
| `geoeid_token`, `geoeid_signed_digest` (`sign.request.item`) | `base.group_system` |
| `geoeid_public_attempt` (`sign.request`) | `base.group_system` |
| Menu **Sign > Configuration > Roles** | `sign.group_sign_manager` |

| Route | Auth | Authorised by |
|---|---|---|
| `/sign/geoeid/cancel/<request>/<token>`, `/status/...` | public, JSON-RPC | the signer's `access_token` |
| `/sign/geoeid/public/<request>/<token>` | public, JSON-RPC | the shared request's `access_token` + the checks in section 4 |
| `/sign/geoeid/init/<token>`, `/document/...`, `/submit/...` | public, HTTP, no CSRF | the 10-minute card token |

`sudo()` uses, each safe because the token or core has already authorised the caller:
`_signer_item`, `_geoeid_find_by_token` and `public_user` (token lookup from a public route);
`public_user` partner create and request copy (as the shared request's creator); `write` (core
has just allowed the signer change); `_geoeid_update_placeholder` (placeholder email only);
the signer's user lookup in submit (to complete as that user); `_geoeid_settings` and
`_geoeid_signature_increment_limit` (system parameters); `o.sudo()` in the completion report.

## 9. Integration

No other custom module depends on `id_ge_sign` or reads its fields.

| Touches | What to keep in mind |
|---|---|
| Contacts' `vat` | Read as the personal number; written on public-link placeholders. Other modules (rs.ge, signify, `gec_localization`) read the same field |
| `documents_hr_sign` | Files a signed HR document only inside core `/sign/sign`; a card signer completes in `submit`, so nothing is filed (core itsme has the same gap) |
| `hr_contract_salary` | Completes the offer from the core sign route, which a card signer never reaches |
| Contact merge | Rewrites `sign.log` partners, which are part of the hashed log; never merge placeholders |

## 10. Tests

From the odoo20 root:

```bash
data_venv/bin/python .claude/skills/odoo-dev/scripts/test_run.py id_ge_sign
```

The tests patch `_qes_host_call` to raise, so any call to Odoo's signature host fails a test.

| File | Covers |
|---|---|
| `test_sign_item_role.py` | external-signature flag, provider name, no IAP service |
| `test_request_create.py` | one-document rule, card signers after regular ones, strict order |
| `test_launch.py` | launch URL, freeze, new token per launch, out of turn, no certificate saved |
| `test_submit.py` | completion, stored identity, chatter, certificate of completion, resubmit, limits, rollback, trust |
| `test_identity.py` | personal number against Tax ID: own, prefixed, company, contact person, empty |
| `test_placeholder.py` | rename, Tax ID, unarchive, duplicates by company and prefix |
| `test_cancel_fail_token.py` | cancel, fail, token lookup, settings, audit text, signer change, refusal note, PEM check |
| `test_sign_request.py` | no mails to placeholder addresses |
| `test_token_access.py` | technical fields hidden from Sign users |
| `test_cms.py` | `tools/cms.py` checks and `tools/protocol.py` |
| `test_pdf_update.py` | `tools/pdf_update.py`: accepted signatures, changed content, broken tables, block size |
| `test_controllers.py` | every route, the app's multipart boundary, 404 / 409 / 413, public attempts |
| `static/tests/geoeid_signer_dialog.test.js` | dialog launch, polling, errors, cancel, `getAuthDialog`, the name image |

Rollback tests call submit in a plain `try`: `TransactionCase.assertRaises` opens its own
savepoint and would hide the module's.

## 11. Extending safely

- Override the core hooks (`_get_external_signature_url`,
  `_freeze_documents_for_external_signature`, the role hooks) with `super()`; do not re-implement
  core's freeze, append or finalize.
- Keep the savepoint and the `completed` postcondition around `_apply_external_signatures`; a
  write after that call runs on a completed request.
- Keep `_read_signed_file`'s raw re-parse: the real app's boundary breaks werkzeug.
- A new refusal in submit raises `CmsVerificationError` so the route records it through
  `_geoeid_fail`.
- Never trust the uploaded PDF beyond what `verify_pdf_signature` proves; the file comes from
  the signer's computer.
- New user texts need their `ka_GE` entry in `i18n/ka_GE.po`.

## 12. Known limitations

| Limitation | Consequence |
|---|---|
| The signer places the visible block | Up to 2 % of a page can be covered where the signer chooses; hash mode (Odoo builds the bytes) is the full fix |
| Cross-reference stream updates are checked through the PDF library's read | Less strict than the row-by-row check of classic tables; only templates that already use streams can get one |
| No revocation, timestamp or LT/LTA | The record says "revocation not checked" |
| Single-level trust check | The anchor must hold the issuing CA; a new id.ge CA must be added by hand |
| Two card signers never run with real cards | A DocMDP lock by the app would make readers flag the first signature |
| Abandoned public attempts | A `sent` request and an archived partner remain unless the shared link has a validity date |
| `dev/mock_universal_program.py` | Still hash mode; it does not work with today's routes |
| The real-card flow is not proven on Odoo 20 | Run one real signature on a test database with a public https address before go-live |

## 13. Upgrading an existing database

No manual step. `-u id_ge_sign` fills `id_ge_sign.trust_anchor` when it is empty. A leftover
`id_ge_sign.require_trusted_chain` row is read by nothing and can be deleted.
