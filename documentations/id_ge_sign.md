# Sign with Georgian ID Card (QES) (`id_ge_sign`)

> **Module:** `id_ge_sign` 20.0.3.2.0 | **Path:** [`custom_addons/gec_odoo_modules/id_ge_sign/`](../custom_addons/gec_odoo_modules/id_ge_sign/)
> Verified against Odoo 20 source on 2026-10-31 (port onto the Sign 20 external-signature flow; installed and probed on a scratch database, not yet on `gec20_prod1`).

---

## What It Does & Why It Exists

Stock Odoo Sign produces a *simple electronic signature*: a drawn or typed mark with an audit trail, but no certificate and no cryptographic binding. For documents where Georgian law expects a signature equal to a handwritten one (labour contracts, commercial agreements), that is not enough.

This module lets a signer sign an Odoo Sign document with their **Georgian ID Card**, embedded in the PDF as a PAdES signature. It adds "Georgian ID Card" to the **Authentication** field of a Sign role ([sign_item_role.py:7](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_item_role.py#L7)), so templates, roles, the signer list and the portal stay standard.

The signing itself happens in the desktop **Georgian ID Card Universal Program** (the `geoeid-unitool://` app from id.ge), launched from the browser. Odoo hands the app the PDF, the app lets the signer place a visible block, signs with the card and uploads the PDF back. Odoo verifies the embedded signature and records the cardholder's identity from the certificate.

**Every signature must chain to the trust anchor** (the state's GEO Signing CA certificates, shipped with the module and saved in `id_ge_sign.trust_anchor`, see Configuration). Without the anchor, card signing does not start at all; a certificate from any other issuer is refused. Revocation is not checked, so the record says "chain verified, revocation not checked", never "qualified".

---

## The Big Picture — How It Works

The module plugs into Sign 20's own flow for signers who sign the PDF themselves (the flow `sign_itsme` uses for *Qualified Signature via itsme®*): the role sets `requires_external_signature` ([sign_item_role.py:12](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_item_role.py#L12); core [sign_item_role.py:44](../enterprise/sign/models/sign_item_role.py#L44)). Core then freezes the document, waits for a signature increment, appends it and finalizes without re-stamping. The module only replaces the step where core would send the signer to Odoo's signature service: it launches the desktop app instead ([sign_request_item.py:65](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L65)).

```
Signer fills fields, clicks "Proceed to Signing"   (role Authentication = Georgian ID Card)
        |
        v
GeoeidSignerDialog --> core POST /sign/sign/<req>/<token>
        |               core: store values, freeze the working copy (frozen_file, state awaiting_signature)
        |               id_ge_sign: new 10-minute token, return geoeid-unitool://.../init/<token>
        v
Dialog opens the link  -->  Universal Program (desktop)
        |                     GET  /sign/geoeid/init/<token>      -> JSON {dataType:"document", dataUrl, submitUrl, ...}
        |  (dialog polls)     GET  /sign/geoeid/document/<token>  -> the frozen PDF
        v                     card signs, POST /sign/geoeid/submit/<token> -> signed PDF (multipart "signedFile")
Dialog polls /sign/geoeid/status          |
        |                       id_ge_sign: verify (must start with the frozen bytes), identity check,
        |                       store certificate data; core: append the increment, complete the signer,
        v                       complete the request (certificate of completion, mails)
"Thank you" page
```

No call goes to Odoo's QES host: core contacts it only when `external_signature_session_token` is set ([sign_request_item.py:940](../enterprise/sign/models/sign_request_item.py#L940), [:983](../enterprise/sign/models/sign_request_item.py#L983), [:1011](../enterprise/sign/models/sign_request_item.py#L1011)) or inside the method this module overrides, and the module never sets that token.

### Key Decision Points
- **Role Authentication = `geoeid`** turns a Sign role into a card-signing role. Everything keys off it.
- **Trust anchor saved?** Without it the signer gets "Signing with the Georgian ID Card is not set up yet. Please contact the sender of this document." when they click to sign, before the app opens: `_get_external_signature_url` returns a message instead of a URL and core releases the frozen document ([sign_request_item.py:904-911](../enterprise/sign/models/sign_request_item.py#L904)). With it, a certificate that does not chain to it is refused at submit, after the PIN. Since 2026-11-12 there is no switch: the old *Require trusted certificate chain* setting is gone, and an `id_ge_sign.require_trusted_chain` row left in a database is read by nothing.
- **Signer contact has an 11-digit personal number in Tax ID?** Then the card's number must match it ([sign_request_item.py:156](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L156)). Only a contact that is its own commercial entity (no parent company) is compared, and only when its Tax ID, without a country prefix, is exactly 11 digits. A contact person of a company carries the company's Tax ID (`vat` is a synced commercial field, [res_partner.py:744](../odoo/addons/base/models/res_partner.py#L744)), so it is not compared; neither is a Tax ID of another shape (for example a company code), and an empty Tax ID accepts any card.

---

## When to Use It (and When Not To)

### This module is for:
- Georgian employees or counterparties signing on a **desktop** with a card reader and the Universal Program installed.
- Requests with one card signer, optionally after ordinary Odoo Sign signers.

### Use something else when:
- **Mobile signers**: the `geoeid-unitool://` scheme has no mobile build.
- **Several PDFs in one request**: refused when the request is created ([sign_request_item.py:49](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L49)).
- **Salary-package templates** (`hr_contract_salary`): that module completes the offer from the core sign route, which a card signer never reaches; do not put a card role on those templates.
- **Long-term archive (LT/LTA)**: needs timestamp and revocation services; out of scope.

---

## Real-World Scenarios

### Scenario 1: An employee signs a contract sent by HR
**Situation:** HR sends a contract to employee Giorgi, whose contact has Tax ID `01001000001`.
**What he does:** Opens the link; his signature field is auto-filled; clicks **Proceed to Signing**; the app opens; he places the block and enters the PIN.
**What happens:** Odoo checks that the card's personal number is `01001000001`, appends the signature, completes the request. The certificate of completion has a "Georgian ID Card Signatures" table with the name, personal number, serial, expiry and whether the chain was verified ([sign_completion_report.xml:27](../custom_addons/gec_odoo_modules/id_ge_sign/report/sign_completion_report.xml#L27)). A card with another number is refused (the app gets 400 with the reason): no certificate data and no `signed` state are written, but a `launched` attempt is set to `failed`, its token is cleared, the error text (first 512 characters) is stored in `geoeid_error`, and an internal note "The Georgian ID Card signature of … was refused: <reason>" is posted on the request (`_geoeid_fail`). The signer's dialog shows one fixed sentence, never the reason: "The ID card signature was not accepted. Try again with your own ID card, or ask the sender for a new link."

**Who is named.** The chatter line names the card holder (certificate common name). When that name differs from the invited contact's name (any difference, also Latin vs Georgian spelling), the line adds "on the link sent to <contact>". The completion certificate's *Signatory* column shows the card holder's name too.

### Scenario 2: Anonymous public link
**Situation:** A self-service link for someone who is not yet a contact.
**What they do:** Open the link and sign with the card. No name or email is asked.
**What happens:** Odoo creates an **archived** placeholder contact with a unique `@id-card.invalid` email ([geoeid.py:87](../custom_addons/gec_odoo_modules/id_ge_sign/controllers/geoeid.py#L87)) and turns the link into a sent request. A retry of the same document in the same browser session gets the same request, not a new placeholder (see the endpoints). After signing, the placeholder is renamed to the cardholder's name ([sign_request_item.py:164](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L164)). It also gets the personal number as Tax ID (every completed signature has a trusted chain), and it becomes visible only if no active contact already has that number. So the same person signing ten times gives **one** visible contact; the archived placeholders keep each signing's history.

### Scenario 3: A regular signer, then a card signer
**Situation:** A manager approves with an ordinary signature, then the counterparty signs with the card.
**What happens:** Card signers are moved after the regular ones at creation, and core then numbers every signer strictly ([sign_request.py:896](../enterprise/sign/models/sign_request.py#L896)), so the card signer is invited after the manager signs. The frozen document already carries the manager's values.

---

## How Things Work Under the Hood

### The endpoints ([`controllers/geoeid.py`](../custom_addons/gec_odoo_modules/id_ge_sign/controllers/geoeid.py))

The launch goes through core `/sign/sign` ([main.py:675](../enterprise/sign/controllers/main.py#L675)), which calls `_sign_externally` for external roles. The module adds:

| Endpoint | Caller | Purpose |
|---|---|---|
| `POST /sign/geoeid/cancel/<req>/<token>` | signing page | puts a launched or failed attempt back to idle and releases the frozen document ([geoeid.py:35](../custom_addons/gec_odoo_modules/id_ge_sign/controllers/geoeid.py#L35)) |
| `POST /sign/geoeid/status/<req>/<token>` | signing page (polling) | reports `idle / launched / signed / failed` only, without the refusal reason (the desktop app still gets it in the submit answer) |
| `POST /sign/geoeid/public/<req>/<token>` | signing page (public link only) | creates the archived placeholder signer; only for a shared request with exactly one card role and no partner. Core `/sign/send_public` is overridden ([geoeid.py:51](../custom_addons/gec_odoo_modules/id_ge_sign/controllers/geoeid.py#L51)) so such a link takes this path; other links go to core unchanged |
| `GET /sign/geoeid/init/<token>` | desktop app | returns the document-mode JSON |
| `GET /sign/geoeid/document/<token>` | desktop app | serves the frozen PDF of the pending signer ([geoeid.py:119](../custom_addons/gec_odoo_modules/id_ge_sign/controllers/geoeid.py#L119)) |
| `POST /sign/geoeid/submit/<token>` | desktop app | receives the signed PDF, verifies and completes; 413 over the size limit, 409 with `Retry-After: 1` on a concurrent submit, 400 on a rejected signature ([geoeid.py:137](../custom_addons/gec_odoo_modules/id_ge_sign/controllers/geoeid.py#L137)) |

`init`, `document` and `submit` are plain HTTP scoped by a token valid 10 minutes from the launch ([sign_request_item.py:14](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L14)), new on every launch. It is **not burned on success**: `geoeid_token` is not cleared, but it stops working 10 minutes after the launch, because every lookup and the submit check reject an expired token ([sign_request_item.py:223](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L223), [:96](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L96)). `init` and `document` return 404 unless the signer is `launched`, so the frozen PDF cannot be read again after signing, and both send `Cache-Control: no-store`. `submit` accepts `launched` or `signed`: the same PDF again (same sha256, kept in `geoeid_signed_digest`) returns success and changes nothing; other bytes get 400 and change nothing. A rejected signature or a cancel clears the token; a new launch mints a new one and clears the digest. The token field is readable by administrators only, like core's `access_token`.

**Public link attempts.** The browser sends a UUID `attempt_id`, kept across retries of the same document. A retry with the same `attempt_id` in the same session returns the same request, but only while it is still sent or signed, active, newer than 10 minutes and within its validity.

**Submit limits.** The route accepts at most core's 25 MiB + `id_ge_sign.max_signature_increment` + 64 KiB of multipart overhead (413 above that). The returned PDF must be longer than the frozen one (it must carry a new signature) and at most `max_signature_increment` larger.

### Model logic ([`models/sign_request_item.py`](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py))

- **`_get_external_signature_url()`** ([:65](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L65)) — one of two core overrides in the flow; the other is `_freeze_documents_for_external_signature()` ([:83](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L83); core [sign_request_item.py:791](../enterprise/sign/models/sign_request_item.py#L791)), which refuses a template with more than one document before freezing, with the same message as `create()`. Core calls this one after freezing ([sign_request_item.py:896-901](../enterprise/sign/models/sign_request_item.py#L896)); for a card role it mints a new token and returns the `geoeid-unitool://` URL, or, with no trust anchor saved, only the "not set up yet" message (core then releases the frozen document). Called without documents (page load, backend "Sign" button) it returns nothing, so there is no redirect.
- **`write()`** — when core accepts a signer change (only for a sent item whose role allows it, [sign_request_item.py:118-170](../enterprise/sign/models/sign_request_item.py#L118)), an open card session of the old signer is cancelled with `_geoeid_cancel()`: token cleared, state idle, frozen document released. Core itself rotates only `access_token`, and only when the invitation was mailed, so without this the old signer's desktop app could still submit for 10 minutes. The old signer's filled values (drawn signature, texts) stay on the item, as in core itsme.
- **`_geoeid_submit_document()`** ([:88](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L88)) — in this order: lock; check the token; an already `signed` signer returns for the same PDF digest and refuses another; refuse unless the session is live, the request is sent and valid and exactly one document is frozen; size checks (longer than the frozen PDF, at most the allowed increment); verify the PDF against the frozen bytes; trust and identity checks; then, inside a savepoint, write the certificate data and `signed`, update a placeholder contact, post the audit message and call core `_apply_external_signatures` ([sign_request_item.py:820](../enterprise/sign/models/sign_request_item.py#L820)). Core appends the increment and completes the request inside that call (certificate of completion, mails), which is why our data is written first. If the signer is not completed afterwards, the savepoint undoes everything and the attempt is marked failed.
- **`_geoeid_check_identity()`** ([:156](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L156)) — compares the card's personal number (the ETSI prefix `PNOGE-` removed, [protocol.py:7](../custom_addons/gec_odoo_modules/id_ge_sign/tools/protocol.py#L7)) with the signer's Tax ID, only for a contact that is its own commercial entity and holds 11 digits.
- **`_geoeid_update_placeholder()`** ([:164](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L164)) — public-link contacts only (see Scenario 2).
- **`create()`** ([:40](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L40)) — one document per request with a card signer; card signers after the regular ones.

### Role hooks ([`models/sign_item_role.py`](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_item_role.py))

- `requires_external_signature` is true for the card role (copy of `sign_itsme`).
- `_get_iap_service_name` returns nothing for the card role: no IAP credits are used or shown.
- `_get_external_signature_provider_name` returns "Georgian ID Card" for the card role, so core's invitation mail says "This is a qualified signature request. You will need to authenticate yourself using Georgian ID Card" ([mail_templates.xml:22](../enterprise/sign/data/mail_templates.xml#L22)). That is core's text about the card; our own verdict in the chatter and the completion certificate says "chain verified, revocation not checked".

### Verification ([`tools/cms.py`](../custom_addons/gec_odoo_modules/id_ge_sign/tools/cms.py))

`verify_pdf_signature()` ([cms.py:47](../custom_addons/gec_odoo_modules/id_ge_sign/tools/cms.py#L47)) accepts the returned PDF only when:

- it starts with the exact frozen bytes, so it is an incremental update of them;
- the **last** `/ByteRange` covers the whole file, with nothing unsigned after it except whitespace;
- the CMS has exactly one signer, signed attributes, content type *data* and a `messageDigest` equal to the digest of the signed bytes;
- the signature verifies with the certificate key; only RSA PKCS#1 v1.5 is accepted;
- the certificate is valid at submit time and its key usage allows signing;
- the certificate's issuer equals an anchor's subject and the anchor's key verifies it (PKCS#1 v1.5). That makes it trusted, and the model refuses anything else. The check is single-level, not full path building, so the anchor must hold the certificate that **directly** issued the card (the PSDA issuing intermediate), not only the root. Key usage accepts digitalSignature or nonRepudiation; revocation is not checked.

The identity comes from the certificate subject: common name and `serialNumber` (`PNOGE-` + the 11-digit personal number).

### Completed document

Core produces it: `_finalize_documents` keeps the appended file as is, with no log-hash stamp, when a signer signs externally and no company seal is set ([sign_request_document.py:163-192](../enterprise/sign/models/sign_request_document.py#L163)). With a company signing certificate, core adds its own seal as a further incremental update.

### Front-end ([`static/src/`](../custom_addons/gec_odoo_modules/id_ge_sign/static/src/))

- **`document_signable_geoeid.js`** — routes `geoeid` roles to `GeoeidSignerDialog` and, on public links, skips the name/email dialog by calling `/sign/geoeid/public`.
- **`signable_PDF_iframe_geoeid.js`** — auto-fills the card signer's signature fields with a name image (a placement guide for the card's block).
- **`geoeid_signer_dialog.js`** — calls core `/sign/sign`, opens the app link, polls the status. Refusals at launch (for example core's "The signers before you have not signed yet." or our "not set up yet") are shown as they come, in the signer's language; a refused signature shows one fixed sentence, because the stored reason is technical and was written in the desktop app's request language.

### Important fields (`sign.request.item`)
- `geoeid_state` — `idle`, `launched`, `signed` or `failed`; the dialog polls it.
- `geoeid_cert_common_name`, `geoeid_cert_personal_number` (11 digits), `geoeid_cert_serial`, `geoeid_cert_not_after` — the cardholder identity captured at submit.
- `geoeid_cert_trusted` — true only when the certificate chained to the anchor; always true for signatures completed since 2026-11-12 (older ones may be false, the report then says "Chain not verified").
- `geoeid_error` — the last refusal reason, technical English, cut to 512 characters; shown in no view and not in the status answer the signer's browser polls; the same text is posted as an internal note on the request, authored by the signer.
- `geoeid_signed_digest` — sha256 of the accepted PDF; lets an identical re-upload succeed. Administrators only, readonly, not copied.
- `geoeid_public_attempt` (on `sign.request`) — the string `<sha256 of the session id>:<shared request id>:<attempt_id>` (the browser's UUID; only the session id is hashed, [geoeid.py:73](../custom_addons/gec_odoo_modules/id_ge_sign/controllers/geoeid.py#L73)); finds the request of a retry. Administrators only, readonly, not copied.

The frozen and signed PDFs live on core's `sign.request.document` (`frozen_file`, `file`).

---

## Configuration & Settings

**Turning it on for a role:** **Sign > Configuration > Roles** (added by the module for Sign managers, [sign_item_role_views.xml:21](../custom_addons/gec_odoo_modules/id_ge_sign/views/sign_item_role_views.xml#L21)); set **Authentication** to "Georgian ID Card".

**Sign settings, "Sign with Georgian ID Card"** ([res_config_settings.py:7](../custom_addons/gec_odoo_modules/id_ge_sign/models/res_config_settings.py#L7)), read in [sign_request_item.py:226](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L226):

- **Signature profile** (`id_ge_sign.signature_profile`, default `B`) — sent to the app. `BT` asks the app for a timestamp, which Odoo does not check.
- **Application language** (`id_ge_sign.language`, default `ka`).
**System parameter** `id_ge_sign.trust_anchor` — PEM text of the certificates that directly issue card signing certificates (several PEM blocks in one value are read). The module ships the state's two, "GEO Signing CA G2" (valid to 2031-05-24) and "GEO Signing CA" (valid to 2032-01-01), in [data/geo_signing_ca.pem](../custom_addons/gec_odoo_modules/id_ge_sign/data/geo_signing_ca.pem), downloaded from [id.ge General Purpose PKI](https://id.ge/en/tsp/generalpki/) with their SHA-256 fingerprints checked. On install and on every upgrade they are saved in the key **only when it is empty** ([ir_config_parameter.py:12](../custom_addons/gec_odoo_modules/id_ge_sign/models/ir_config_parameter.py#L12), called from a non-noupdate `<function>` in [data/ir_config_parameter.xml](../custom_addons/gec_odoo_modules/id_ge_sign/data/ir_config_parameter.xml), the way core `ir.config_parameter.init` fills its own defaults): an admin's value is never overwritten, and an emptied key is filled again at the next upgrade. So no database needs a hand paste; when the agency publishes a newer CA, add its PEM after the others in this key. Root certificates alone do not work (the check is one level). Before go-live, prove it with one real card on a test database, because the trust check has never run against a real card. A non-empty value without a valid PEM certificate is refused on save ([ir_config_parameter.py:18](../custom_addons/gec_odoo_modules/id_ge_sign/models/ir_config_parameter.py#L18): "Set valid PEM certificates for Georgian ID signing.").

**Other system parameter** (no settings screen, no data record, default in code):

- `id_ge_sign.max_signature_increment` — default 5 MiB ([protocol.py:9](../custom_addons/gec_odoo_modules/id_ge_sign/tools/protocol.py#L9)): the largest allowed difference between the returned PDF and the frozen PDF.

**Signer identity:** the contact's **Tax ID**. Put an individual's 11-digit personal number there (the same field rs.ge, signify and `gec_localization` use) and only their own card is accepted.

---

## Dependencies

| Requires | Why |
|---|---|
| `sign` (Enterprise) | Roles, the external-signature flow, completion |

| Python | Why |
|---|---|
| `cryptography`, `asn1crypto` | Parse and verify the embedded PAdES signature; both are in Odoo's requirements |

No new models, so no `ir.access.csv`. Fields are added to `sign.request.item` and `sign.request`.

---

## Gotchas & Non-Obvious Behavior

- **Strict signing order.** Any request with a card signer makes every signer sign one after another, including regular signers who signed in parallel before ([sign_request.py:896](../enterprise/sign/models/sign_request.py#L896), [sign_request_item.py:377](../enterprise/sign/models/sign_request_item.py#L377)). The send wizard shows the order as mandatory.
- **"Sign Now" with more than one role is refused** for templates with a card role ([sign_template.py:610](../enterprise/sign/models/sign_template.py#L610)); documents over 25 MB are refused ([sign_request.py:906](../enterprise/sign/models/sign_request.py#L906)).
- **Two card signers: test with real cards first.** The second card signer's values are stamped as an incremental annotation after the first card signature. The first signature stays cryptographically valid (proven on a scratch database), but if the Universal Program locks the document (DocMDP), PDF readers will flag it. Not verified with real cards.
- **One visible block per card signer, placed by hand.** The init message cannot carry a position.
- **The card stamps the certificate identity, not the Odoo name.** The Odoo name image stays as a placement guide.
- **Certificate validity is checked at submit time.**
- **Public-link contacts have a synthetic email.** Completion, refusal and signature-access mails to `@id-card.invalid` are skipped ([sign_request.py:14](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request.py#L14), [:25](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request.py#L25), [sign_request_item.py:240](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request_item.py#L240)), `_get_final_recipients` ([:11](../custom_addons/gec_odoo_modules/id_ge_sign/models/sign_request.py#L11)) drops them for the completion certificate ([sign_log_reports.xml:163](../enterprise/sign/report/sign_log_reports.xml#L163)), and the address is hidden in the completion mail and the sign log ([sign_completion_report.xml:4](../custom_addons/gec_odoo_modules/id_ge_sign/report/sign_completion_report.xml#L4)). An activated placeholder keeps that email.
- **Do not merge placeholder contacts.** The contact merge rewrites `sign.log` partners, which are part of the hashed log, and the request then shows an integrity warning ([sign_log.py:14](../enterprise/sign/models/sign_log.py#L14)).
- **`documents_sign` access.** [Likely] the access grant in `sign.request.item._sign()` does not run for card signers, as for core QES. The completed file is still attached.
- **HR contracts signed by card are not filed in the employee's Documents folder.** `documents_hr_sign` files only inside core's `/sign/sign` route ([main.py:12-47](../enterprise/documents_hr_sign/controllers/main.py#L12)); a card signer completes in `/sign/geoeid/submit`. Core itsme has the same gap. A bridge module is planned only if HR will sign by card (go-live plan D5).
- **Open go-live blocker: the returned PDF's update is not inspected.** The signed PDF comes from the signer's PC; Odoo checks the prefix, the size and the signature, not what the incremental update changes, so an altered update can replace page content (proven offline, go-live plan item 1). The fix waits for one real-card run (hash mode vs inspecting the update).
- **Out of scope:** LT/LTA profiles, the PSDA document timestamp and server-side OCSP/CRL checks.

---

## Desktop App Facts the Design Rests On

Checked against the installed app (`/Applications/Georgian ID Card.app`) on 2026-09-24:

- **The init message has no position and no certificate-read step.** The app's `JsonMessage` class (`web-signer.jar`) has exactly: `dataType`, `dataHex`, `dataUrl`, `hash`, `signAlg`, `submitUrl`, `description`, `docType`, `language`, `keyId`, `signatureProfile`, `padesUsage`.
- **Document mode** downloads the PDF, opens a placement dialog, draws the app's own visible block, signs and uploads the PDF as an incremental update of the bytes it received (a real card on v19 always passed the prefix check).
- **The upload uses an unparseable multipart boundary** (for example `boundary====1780578020325===`). `_read_signed_file()` re-parses the raw body with the header boundary ([geoeid.py:157](../custom_addons/gec_odoo_modules/id_ge_sign/controllers/geoeid.py#L157)).

---

## Testing Without a Card

A self-signed certificate whose subject carries `serialNumber=PNOGE-<11 digits>`, set on a throwaway company's **Signing certificate**, lets core `PdfSigner` play the card app: it appends an incremental `ETSI.CAdES.detached` signature that `verify_pdf_signature()` accepts. The module's tests are built on this ([tests/common.py](../custom_addons/gec_odoo_modules/id_ge_sign/tests/common.py)) and patch `_qes_host_call` to raise, so any call to Odoo's QES host fails a test.

| Suite | Covers | Run |
|---|---|---|
| Python ([`tests/`](../custom_addons/gec_odoo_modules/id_ge_sign/tests/)) | role hooks, request creation, launch, submit (incl. rollback on a failed completion), identity, placeholders, cancel / fail / token, completion mail, token access, `tools/cms.py` and `tools/protocol.py`, all HTTP routes incl. the app's unquoted multipart boundary | `odoo-bin -c odoo.conf -d <db> -u id_ge_sign --test-tags /id_ge_sign --stop-after-init` |
| Hoot, 25 tests ([`static/tests/geoeid_signer_dialog.test.js`](../custom_addons/gec_odoo_modules/id_ge_sign/static/tests/geoeid_signer_dialog.test.js)) | the signing dialog (launch, polling, server and network errors, cancel), `getAuthDialog`, the name image | after `-u id_ge_sign`: `--test-enable --test-tags "/id_ge_sign:WebSuite.test_unit_desktop"` |

`TransactionCase.assertRaises` runs its block in its own savepoint, so a test of the module's rollback must call the submit in a plain `try` (as the controller does), not inside `assertRaises`. Not covered: the signature prefill in `postRender` (it needs a mounted signing page). [`dev/mock_universal_program.py`](../custom_addons/gec_odoo_modules/id_ge_sign/dev/mock_universal_program.py) is an older hash-mode mock and no longer matches the routes.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- Module READMEs: [`README.md`](../custom_addons/gec_odoo_modules/id_ge_sign/README.md) (user guide) and [`README_DEV.md`](../custom_addons/gec_odoo_modules/id_ge_sign/README_DEV.md) (developer guide)
- Port plan: [`dev_notes/plans/id_ge_sign_v20_port_plan_20261031.md`](../dev_notes/plans/id_ge_sign_v20_port_plan_20261031.md)
