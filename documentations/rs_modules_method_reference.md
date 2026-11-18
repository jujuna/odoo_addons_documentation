# RS Modules — Method Reference (`rs_base` + `gec_rs_invoice`)

> Per-method reference for the two Georgian Revenue Service (rs.ge) integration modules.
> Goal: understand the **purpose** of each method — why it exists and what it solves — not just what it does.
> Covers **every** callable (307 total — methods, module-level functions, properties, staticmethods, and one shell script) across 23 source files. Each is tagged with **Liveness**, **Role**, and **Side effects**.
> Built by reading each file end-to-end and grepping the repo for call-sites/XML/cron wiring.

---

## How to read the tags

Each method carries three tags:

**Liveness** — is it actually reachable?
- **Active** — called from Python, wired to an XML button/action, a cron target, or an Odoo framework hook (`create`/`write`/`_compute_*`/`@api.constrains`/etc.). The reason is stated.
- **Dead-unused** — no caller, no XML reference, not a framework hook (verified by grep across `custom_addons` + `addons` + `enterprise`).
- **Deprecated** — superseded by a newer flow but kept for legacy data.
- **TODO-incomplete** — has a stub/hardcode/TODO that limits it.

**Role** — what kind of method it is: `Override` · `CRUD` · `Compute` · `Inverse` · `Onchange` · `Constraint` · `Action-button` · `Cron` · `SOAP-call` · `Helper` · `Default`.

**Side effects** — what it touches: `Reads-only` · `Writes-DB` · `Calls-rs.ge-API` · `Raises-to-user` · `Sends-mail` · `Returns-action`.

---

## The two modules and how they layer

| Module | Tech name | Role | Depends on |
|---|---|---|---|
| **RS E-Invoice (SOAP)** | `rs_einvoice` (dir `gec_rs_invoice`) | The core integration. SOAP client, seller/buyer invoice lifecycle, status sync, corrections, advance settlement, crons. | `accountant`, `stock` |
| **RS Base Methods** | `rs_base_methods` (dir `rs_base`) | Shared base. Per-user rs.ge credentials, the waybill↔invoice bridge, and the invoice-from-waybill wizard. | `rs_einvoice`, `rs_waybill`, `employee_registry_rs`, `sale_stock` |

**Key architectural fact:** the dependency points **`rs_base` → `rs_einvoice`**, not the other way. So:
- The SOAP service lives in `gec_rs_invoice`, but the **credentials** it needs live in `rs_base` (`res.users._get_rs_credentials`). To avoid a circular dependency, `rs_einvoice`'s SOAP service reaches the credentials via `getattr` and raises a friendly error if `rs_base` isn't installed.
- `rs_base` **extends** `gec_rs_invoice`'s `account.move` actions (`action_rs_create`, `action_rs_send`, `action_rs_edit`, `action_rs_delete`, `action_rs_refresh_status`, `action_rs_buyer_pull`, `_rs_create_invoice`, `_rs_auto_cancel_after_rs_cancellation`, `_rs_suggest_k_type_from_external`) via `super()` to inject waybill-link behaviour. When both modules are installed, the rs_base version runs and calls down into the gec version.

---

## rs.ge invoice status codes (the spine of the whole system)

Almost every method branches on the rs.ge status. This is the shared vocabulary:

| Code | Meaning | Who acts next |
|---|---|---|
| `0` | Draft on rs.ge (saved, not sent) | Seller (edit/send/delete) |
| `1` | Sent to buyer, awaiting accept | Buyer (accept/reject) |
| `2` | Confirmed by buyer | Seller (can now correct/cancel) |
| `3` | Corrected (a correction exists against it) | — |
| `4` | New correction draft | Seller (edit/send/delete) |
| `5` | Correction sent to buyer | Buyer (accept/reject) |
| `6` | Cancellation sent, awaiting buyer confirm | Buyer (confirm/reject) |
| `7` | Cancellation confirmed by buyer → invoice is dead | (auto-reversed locally) |
| `8` | Correction accepted by buyer → supersedes original | (original auto-cancelled) |
| `-1` | Deleted on rs.ge | — |

Two derived constants used throughout: `RS_ACCEPTED`/`RS_CONFIRMED` (statuses 2 and 8 — a settled, buyer-accepted state) and `RS_PENDING_BUYER` (1/5/6 — waiting on the buyer).

---

## The main flows (so the methods have a home)

1. **Seller lifecycle** — `action_rs_create` (save header on rs.ge) → `action_rs_edit` (push lines) → `action_rs_send` (to buyer) → buyer accepts (→2) or rejects (→ back to draft). Then optionally **correct** or **cancel**.
2. **Buyer lifecycle** — `action_rs_buyer_pull` (fetch a supplier invoice by its rs.ge ID) → `action_rs_buyer_accept` / `action_rs_buyer_reject` → `action_rs_import_supplier_correction` (cancel-and-reissue the local bill from the supplier's correction). The **buyer inbox wizard** lists/imports many at once.
3. **Two correction models** —
   - **Correct-and-Reissue**: files a real rs.ge *correction* (k_invoice) chained on the original; one buyer acceptance; original auto-cancelled only when accepted (status 8).
   - **Cancel-and-Reissue**: sends a real *cancellation* (→6→7) and clones a fresh draft; original auto-cancelled when the buyer confirms the cancel (status 7).
4. **Advance / down-payment settlement** — either **Native** (rs.ge's `attach_advance_invoice`, for confirmed advances from an earlier month) or **Net** (subtract the advance proportionally across lines, because rs.ge rejects negative lines).
5. **Waybill bridge** (`rs_base`) — link rs.ge transport waybills to invoices; create an invoice straight from waybills; block mutating a waybill that's attached to a live invoice.
6. **Background crons** — status refresh (buyer/seller), filing-deadline warnings (#996 Art.54), pending-action escalation, stuck-send/cancel detection, stranded-cancellation recovery, and log vacuum.

---

## Issues surfaced during the analysis

**Dead / unused code** (no caller anywhere in `custom_addons` + `addons` + `enterprise`):

| Method | File:line | Note |
|---|---|---|
| `buyer_confirm_cancellation` | [rs_soap_service.py:406](../custom_addons/gec_rs_invoice/rs_einvoice/models/rs_soap_service.py#L406) | Convenience wrapper; the 6→7 path is reached via `buyer_accept_invoice(target_status=7)` instead |
| `detach_advance_invoices` | [rs_soap_service.py:586](../custom_addons/gec_rs_invoice/rs_einvoice/models/rs_soap_service.py#L586) | Advance flow attaches/updates but never detaches |
| `_rs_row_lookup` (module fn) | [rs_soap_service.py:121](../custom_addons/gec_rs_invoice/rs_einvoice/models/rs_soap_service.py#L121) | Unused utility |
| `action_view_rs_invoices` | [rs_waybill.py:51](../custom_addons/rs_base/rs_base_methods/models/rs_waybill.py#L51) | Smart-button handler never wired to a view |
| `_waybill_direction` | [rs_invoice_from_waybill_wizard.py:80](../custom_addons/rs_base/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L80) | Reserved scaffolding for a future vendor-bill flow |
| `_order_line_model` | [rs_invoice_from_waybill_wizard.py:101](../custom_addons/rs_base/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L101) | Reserved scaffolding (line model hard-codes `sale.order.line`) |
| `_rs_rest_get_transaction_result` | [res_users.py:566](../custom_addons/rs_base/rs_base_methods/models/res_users.py#L566) | Exposed REST helper, no in-tree consumer yet |

**TODO / hardcode** worth tracking:
- `save_invoice_desc` and `_rs_get_purchase_vat_18` hardcode the **18% VAT rate** and set **excise = 0**; both carry TODOs to move the rate to a company setting and map excise from line taxes.

---

## Document map

- **Section A — rs.ge SOAP client layer** (everything else calls into this)
- **Section B — `gec_rs_invoice`: invoice lifecycle** (account_move core, seller, sync, buyer, corrections/replacements, wizards, supporting models, crons)
- **Section C — `rs_base`: credentials, waybill bridge, wizards, maintenance script**

---

# Section A — rs.ge SOAP client layer

This is the bottom of the stack: the Python wrappers around rs.ge's SOAP operations. Every seller/buyer/sync/waybill action ultimately calls a method here. There are two SOAP service files in `gec_rs_invoice` (the main client + a small view-only extension) and one in `rs_base` (the waybill-link operations) — the last is documented in Section C alongside the waybill bridge.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/rs_soap_service.py`

**File role:** SOAP client wrapper for the rs.ge e-invoice web service (`ntosservice.asmx`). It builds and caches a single `zeep` client, injects per-call credentials from `res.users._get_rs_credentials`, and exposes one Python method per rs.ge invoice SOAP operation (auth check, TIN/un_id lookups, invoice CRUD, status transitions, corrections, advance settlement, buyer-side discovery). Some endpoints whose responses zeep mis-parses (DataTable/`NewDataSet`) are hit with raw SOAP POST + lxml instead.

**Main flows it participates in:**
- Seller send: build header (`save_invoice`) → push lines (`save_invoice_desc`) → send (`send_invoice`/`send_correction`) — driven by `account_move_seller.py` + `account_move_sync.py`.
- Buyer accept/reject/confirm-cancel — driven by `account_move_buyer.py`.
- Correction chain: `create_correction` (k_invoice) → `get_makoreqtirebeli` to discover the active corrector.
- Advance settlement (v3.0.5): `get_attachable/attached_advance_invoices` → `attach_advance_invoice`/`update_advance_invoice`.
- Buyer inbox + incremental polling: `get_buyer_invoices`, `get_user_invoices` via `rs_buyer_inbox_wizard.py`.
- View wizards: line/waybill/advance display via `rs_einvoice_view_wizard.py`.

### Module-level helpers (not class methods)

These are free functions used by the class and by `rs_soap_service_view.py`.

#### `_new_safe_parser()` — line 21
- **Liveness:** Active. Called inside `get_invoice_desc` (line 456) and `_parse_datatable_rows` (line 635).
- **Role:** Helper.
- **Side effects:** Reads-only (builds an lxml parser).
- **Purpose:** Returns a hardened `etree.XMLParser` (no external entities, no DTD, no network) to defend against XXE injection when parsing raw rs.ge SOAP responses. Built fresh per parse because lxml parsers are not thread-safe.

#### `_to_rs_dt(value)` — line 47
- **Liveness:** Active. Used by `save_invoice` (271), `get_attachable_advance_invoices` (478).
- **Role:** Helper.
- **Side effects:** Reads-only.
- **Purpose:** Converts an Odoo `Date` to a `datetime` at Tbilisi noon so rs.ge (which interprets timestamps as Asia/Tbilisi, UTC+4) lands the operation on the intended calendar day and does not shift the VAT period across a midnight tz boundary.

#### `_retry_read(call, *args, **kwargs)` — line 67
- **Liveness:** Active. Wraps every idempotent READ (`get_un_id_from_tin`, `get_seller_un_id`, `get_invoice`, the raw-POST list endpoints, `get_makoreqtirebeli`, and the view-model reads).
- **Role:** Helper.
- **Side effects:** Calls-rs.ge-API (via the passed `call`); Raises-to-user after budget exhausted; sleeps between attempts.
- **Purpose:** Runs an idempotent SOAP read with exponential backoff (`SOAP_READ_RETRIES=3`, base 0.2s) on transient network errors. Writes are deliberately never routed through this — re-issuing a write could duplicate side effects on rs.ge.

#### `_zeep_fault_class()` — line 93
- **Liveness:** Active. Used in `except` clauses of all write wrappers (`save_invoice`, `save_invoice_desc`, `change_invoice_status`, `attach_advance_invoice`, `update_advance_invoice`, `detach_advance_invoices`).
- **Role:** Helper.
- **Side effects:** Reads-only.
- **Purpose:** Lazily imports `zeep.exceptions.Fault` and returns it (or an empty tuple if zeep is absent) so `except` clauses can catch SOAP faults without a hard import dependency at module load.

#### `_zeep_fault_message(exc)` — line 102
- **Liveness:** Active. Used wherever a caught `Fault` is turned into a `UserError`.
- **Role:** Helper.
- **Side effects:** Reads-only.
- **Purpose:** Extracts a human-readable message from a zeep `Fault` (its `.message`, else `str()`).

#### `_xml_escape(value)` — line 106
- **Liveness:** Active. Used by every raw-POST envelope builder here and in the view model.
- **Role:** Helper.
- **Side effects:** Reads-only.
- **Purpose:** XML-escapes a value before interpolation into a hand-crafted SOAP body. Critical for credentials: a password containing `&`, `<`, `>`, `"` would otherwise break the envelope and make every raw-POST call fail. (zeep escapes its own typed inputs, so this is only for the raw paths.)

#### `_rs_row_lookup(row, key, default=None)` — line 121
- **Liveness:** **Dead-unused.** grep across `custom_addons`, `addons`, `enterprise` finds no caller; not used inside this file or the view model. Flagged as a dead utility.
- **Role:** Helper.
- **Side effects:** Reads-only.
- **Purpose:** Intended to read a key from a dict/object rs.ge row tolerating case variants. No current consumer — downstream code parses rows via `_parse_datatable_rows` (lowercased keys) directly.

### class RsSoapService(models.AbstractModel)

`_name = 'rs.soap.service'` — an `AbstractModel`, so it is instantiated via `self.env['rs.soap.service']` by the account_move models and wizards.

#### `_get_credentials(self)` — line 138
- **Liveness:** Active. Called by nearly every wrapper in this file (and via inheritance by the view model).
- **Role:** Helper.
- **Side effects:** Reads-only (reads `res.users`); Raises-to-user.
- **Purpose:** Fetches `{su, sp, user_id}` by calling `res.users._get_rs_credentials` (provided by `rs_base_methods`). Because the manifest cannot declare that runtime dependency without a cycle, it detects the missing-provider case and the empty-`user_id` case explicitly, raising fix-it `UserError`s instead of a bare `AttributeError`. `user_id` here is the rs.ge `chek`-returned id, not the e-declaration personal number.

#### `_get_client(self)` — line 164
- **Liveness:** Active. Called by every zeep-based wrapper and by `_get_session`.
- **Role:** Helper.
- **Side effects:** Reads-only / network on first call (fetches WSDL); Raises-to-user if zeep is not installed.
- **Purpose:** Returns a module-level cached `zeep.Client` keyed on `WSDL_URL`. The ~50 KB WSDL is parsed once; subsequent calls reuse the same Client + Session + Transport (HTTP keep-alive). Credentials travel per call, so sharing the client is safe.

#### `_get_session(self)` — line 189
- **Liveness:** Active. Used by every raw-SOAP-POST method (`get_invoice_desc`, the advance list endpoints, `get_buyer_invoices`, `get_user_invoices`, and `get_invoice_waybills` in the view model).
- **Role:** Helper.
- **Side effects:** Reads-only.
- **Purpose:** Returns the cached zeep transport's `requests.Session` so the raw-POST endpoints reuse the same connection pool/keep-alive as the typed calls.

#### `_check_auth(self)` — line 197
- **Liveness:** Active. SOAP op `chek`. Callers: `account_move_seller.py` (lines 55, 834, 870, 962, 1151), `account_move_buyer.py` (45, 342, 514, 806, 947), `rs_buyer_inbox_wizard.py` (196, 665).
- **Role:** SOAP-call.
- **Side effects:** Calls-rs.ge-API; Raises-to-user on rejection.
- **Purpose:** Calls rs.ge `chek` (API §1) to validate `su`/`sp`/`user_id` before any real operation. Per the API doc, `chek` returns a bool and the canonical `user_id` to use in all other calls. This wrapper only asserts the bool and raises a guidance `UserError` if credentials are rejected — used as a pre-flight gate at the start of each user action.

#### `get_un_id_from_tin(self, tin)` — line 217
- **Liveness:** Active. SOAP op `get_un_id_from_tin`. Callers: `account_move.py` (1977), `account_move_buyer.py` (139, 163, 997), `account_move_seller.py` (104), and the verification helper at `account_move.py` (737-738).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried); Raises-to-user if not found.
- **Purpose:** Resolves a Georgian TIN to an rs.ge `un_id` (API §9). The wrapper normalizes the result shape (attribute vs int), and treats `0`/negative as "not registered", raising a `UserError` telling the user to verify the TIN. Used to resolve the buyer's un_id before `save_invoice`, and in seller/buyer-side party verification.

#### `get_seller_un_id(self)` — line 241
- **Liveness:** Active. SOAP op `get_un_id_from_user_id`. Callers: `account_move.py` (1976), `account_move_seller.py` (103, 525), `account_move_buyer.py` (978), `rs_buyer_inbox_wizard.py` (180, 673).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried).
- **Purpose:** Resolves the logged-in service user's own `un_id` from its `user_id` (API §9 `get_un_id_from_user_id`). Returns int, `0` when absent. Used as the seller's un_id for `save_invoice` and as the company un_id for buyer-inbox listing.

#### `save_invoice(self, inv_id, operation_date, seller_un_id, buyer_un_id, variant='regular', note='')` — line 259
- **Liveness:** Active. SOAP ops `save_invoice` / `save_invoice_a` / `save_invoice_n`. Callers: `account_move.py` (1979), `account_move_seller.py` (110).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API; Raises-to-user on SOAP fault.
- **Purpose:** Creates or updates an rs.ge invoice header (API §2). `inv_id=0` creates a new invoice; a non-zero id edits an existing one (including a corrector via its `k_id`). The `variant` selects the operation: `regular`→`save_invoice`, `advance`→`save_invoice_a` (compensation/advance invoice), `note`→`save_invoice_n` (adds a comment). Date is forced to Tbilisi noon to avoid VAT-period shift. One wrapper consolidates the three near-identical SOAP signatures.

#### `save_invoice_desc(self, inv_id, goods, g_unit, quantity, full_amount, vat_amount, desc_id=0)` — line 301
- **Liveness:** Active (with a **TODO**). SOAP op `save_invoice_desc`. Caller: `account_move_sync.py` (323).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API; Raises-to-user on SOAP fault.
- **Purpose:** Adds or updates one goods/service line on an invoice (API §4). `desc_id=0` inserts a new line. `full_amount` is amount incl. VAT+excise; `drg_amount` (mapped from `vat_amount`) carries the VAT with the API's special encoding (`>0` taxable, `0` zero-rated, `-1` exempt). Defaults `g_unit` to `'ერთეული'` because the API rejects an empty unit. **Excise (`aqcizi_amount`) is hardcoded to 0** — a TODO notes it is not yet mapped from line taxes.

#### `delete_invoice_desc(self, desc_id, inv_id)` — line 328
- **Liveness:** Active. SOAP op `delete_invoice_desc`. Caller: `account_move_sync.py` (381).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API.
- **Purpose:** Deletes a single goods line by its id (API §4). Used during line re-sync to clear stale lines (especially on a corrector header) before re-pushing fresh ones.

#### `change_invoice_status(self, inv_id, status)` — line 339
- **Liveness:** Active (internal hub). SOAP op `change_invoice_status`. No external caller calls it directly; it is the shared implementation behind `delete_invoice`, `send_invoice`, `send_correction`, and `cancel_invoice`, which are the externally-called wrappers.
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API; Raises-to-user on SOAP fault.
- **Purpose:** Seller-side status transition (API §5). Critically, per the API doc, `status` is the **target** status, not an action code (0→1 send original; 4→5 send corrector; →-1 delete; 2→6 cancel). The four thin wrappers below encode each correct target so callers can't pass the wrong code (e.g. sending a corrector with `status=1` silently fails on rs.ge).

#### `delete_invoice(self, inv_id)` — line 358
- **Liveness:** Active. Delegates to `change_invoice_status(inv_id, -1)`. Caller: `account_move_seller.py` (872).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API.
- **Purpose:** Deletes a draft/unsent invoice by moving it to status `-1` (API §5). Used when discarding an orphaned or superseded rs.ge draft.

#### `send_invoice(self, inv_id)` — line 361
- **Liveness:** Active. Delegates to `change_invoice_status(inv_id, 1)`. Caller: `account_move_seller.py` (989).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API.
- **Purpose:** Sends an original invoice to the buyer, status 0→1 (API §5). Named so callers don't have to remember the magic number.

#### `send_correction(self, k_id)` — line 365
- **Liveness:** Active. Delegates to `change_invoice_status(k_id, 5)`. Caller: `account_move_seller.py` (986).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API.
- **Purpose:** Sends a corrector (k-invoice) to the buyer, status 4→5 (API §5). Exists separately from `send_invoice` precisely because correctors require target `5`; passing `1` silently returns False on rs.ge.

#### `cancel_invoice(self, inv_id)` — line 370
- **Liveness:** Active. Delegates to `change_invoice_status(inv_id, 6)`. Caller: `account_move_seller.py` (1152).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API.
- **Purpose:** Seller request to cancel a buyer-confirmed invoice, status 2→6 (API §5). The buyer must then confirm (6→7).

#### `buyer_accept_invoice(self, inv_id, target_status)` — line 374
- **Liveness:** Active. SOAP op `acsept_invoice_status`. Caller: `account_move_buyer.py` (346). Also the implementation behind `buyer_confirm_cancellation`.
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API.
- **Purpose:** Buyer-side acceptance (API §5 `acsept_invoice_status`). `target_status` is the destination: 1→2 (accept original), 5→8 (accept correction), 6→7 (confirm cancellation). One wrapper covers all three buyer-accept transitions.

#### `buyer_reject_invoice(self, inv_id, reason)` — line 392
- **Liveness:** Active. SOAP op `ref_invoice_status`. Caller: `account_move_buyer.py` (808).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API.
- **Purpose:** Buyer-side rejection (API §5 `ref_invoice_status`). The `reason` is shown to the supplier on rs.ge.

#### `buyer_confirm_cancellation(self, inv_id)` — line 406
- **Liveness:** **Dead-unused.** Delegates to `buyer_accept_invoice(inv_id, target_status=7)`, but grep finds no caller. The 6→7 confirmation path is reached elsewhere (callers call `buyer_accept_invoice` with explicit `target_status`), leaving this convenience wrapper orphaned.
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API (if it were called).
- **Purpose:** Intended convenience: buyer confirms the seller's cancellation request (status 6→7, API §5).

#### `get_invoice(self, inv_id)` — line 410
- **Liveness:** Active. SOAP op `get_invoice`. Callers: `account_move_sync.py` (multiple), `account_move_buyer.py`, `account_move_seller.py` (1095) — used widely for status/header polling.
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried).
- **Purpose:** Fetches full invoice header info (API §3): series, number, operation/reg dates, seller/buyer un_id, status, declaration seq numbers, `k_id`, `k_type`, `dec_status`. Returns the raw zeep result object. Primary source for reconciling rs.ge state back into Odoo.

#### `get_invoice_desc(self, inv_id)` — line 421
- **Liveness:** Active. SOAP op `get_invoice_desc`. Callers: `account_move_sync.py` (276, 394, 680), `rs_einvoice_view_wizard.py` (106).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried); parses XML.
- **Purpose:** Fetches the goods/service line rows of an invoice (API §4). Uses a raw SOAP POST + lxml because zeep cannot parse this endpoint's DataTable. Returns a list of dicts with lowercased column keys.

#### `get_attachable_advance_invoices(self, seller_un_id, buyer_tin, operation_date)` — line 470
- **Liveness:** Active. SOAP op `get_attachable_advance_invoices` (v3.0.5). Caller: `account_move_seller.py` (529).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried); parses XML.
- **Purpose:** Lists advance invoices that rs.ge will allow to be settled against a delivery invoice for a given seller/buyer/operation-month (API §13). Only confirmed advances from strictly earlier tax months are returned. Raw SOAP POST + `_parse_datatable_rows`. Feeds the seller's advance auto-pick logic.

#### `get_attached_advance_invoices(self, invoice_id)` — line 509
- **Liveness:** Active. SOAP op `get_attached_advance_invoices` (v3.0.5). Callers: `account_move_seller.py` (435, 534), `rs_einvoice_view_wizard.py` (140).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried); parses XML.
- **Purpose:** Lists advances already attached/settled on a delivery invoice, with per-advance used/remaining VAT amounts and `IN_PREV_INVOICE`/`MIN_DRG_AMOUNT` correction markers (API §13). Used to read current settlement state before attach/update and for display.

#### `attach_advance_invoice(self, invoice_id, advance_invoice_id, advance_invoice_drg_amount, seller_un_id, buyer_tin)` — line 539
- **Liveness:** Active. SOAP op `attach_advance_invoice` (v3.0.5). Caller: `account_move_seller.py` (653).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API; Raises-to-user on SOAP fault.
- **Purpose:** Attaches/settles an advance invoice's VAT against a delivery invoice (API §13). Returns a `{Status, Message}` object (`Status=="200"` = success). Used by the seller advance-settlement flow when a new advance must be bound.

#### `update_advance_invoice(self, invoice_id, advance_invoice_id, advance_invoice_drg_amount)` — line 564
- **Liveness:** Active. SOAP op `update_advance_invoice` (v3.0.5). Caller: `account_move_seller.py` (620).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API; Raises-to-user on SOAP fault.
- **Purpose:** Adjusts the settled VAT amount of an already-attached advance (API §13). Allowed only on delivery-invoice statuses 0/1/4/5, and (on corrections) cannot drop below `MIN_DRG_AMOUNT`. Used to true-up an existing advance binding rather than detach/re-attach.

#### `detach_advance_invoices(self, invoice_id, advance_invoice_ids)` — line 586
- **Liveness:** **Dead-unused.** SOAP op `detach_advance_invoices` (v3.0.5). grep finds no caller. The advance flow currently attaches/updates but never detaches via this wrapper.
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API; Raises-to-user on SOAP fault (if called).
- **Purpose:** Intended to detach one or more advances from a delivery invoice (API §13), allowed only on statuses 0/1/4/5.

#### `_fmt_dt(dt)` (staticmethod) — line 625
- **Liveness:** Active. Used by `get_attachable_advance_invoices`, `get_buyer_invoices`, `get_user_invoices`.
- **Role:** Helper.
- **Side effects:** Reads-only.
- **Purpose:** Formats a `datetime` as `%Y-%m-%dT%H:%M:%S` for interpolation into raw SOAP envelopes; empty string for `None`.

#### `_parse_datatable_rows(xml_bytes)` (staticmethod) — line 631
- **Liveness:** Active. Used by all raw-POST list endpoints here and by `get_invoice_waybills` in the view model.
- **Role:** Helper.
- **Side effects:** Reads-only (parses XML with the safe parser).
- **Purpose:** Parses an rs.ge DataTable XML payload (`DocumentElement` children) into a list of dicts with lowercased tag keys — the shared shape every raw-POST endpoint returns to downstream code.

#### `get_buyer_invoices(self, un_id, s_dt, e_dt, op_s_dt=None, op_e_dt=None, invoice_no='', sa_ident_no='', desc='', doc_mos_nom='')` — line 645
- **Liveness:** Active. SOAP op `get_buyer_invoices`. Caller: `rs_buyer_inbox_wizard.py` (201).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried); parses XML.
- **Purpose:** Lists invoices where the calling un_id is the buyer, filterable by issue/operation date ranges and other criteria (API §7). Raw SOAP POST + lxml. Backs the buyer inbox's full-window fetch.

#### `get_user_invoices(self, un_id, last_update_s, last_update_e)` — line 694
- **Liveness:** Active. SOAP op `get_user_invoices` (v3.0.4). Caller: `rs_buyer_inbox_wizard.py` (681).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried); parses XML.
- **Purpose:** Incremental list of invoices changed within a last-update window (API §7). rs.ge caps the window to 3 days, so callers poll on a short cadence. Backs the buyer-inbox incremental sync.

#### `create_correction(self, original_inv_id, k_type=1)` — line 728
- **Liveness:** Active. SOAP op `k_invoice`. Caller: `account_move_seller.py` (757).
- **Role:** SOAP-call (write).
- **Side effects:** Calls-rs.ge-API.
- **Purpose:** Creates a correcting invoice (corrector / k-invoice) over a confirmed invoice (API §5 `k_invoice`); returns the new `k_id`. `k_type` selects the legal correction reason (1 cancel taxable op, 2 change op type, 3 price/compensation change, 4 goods returned). Per the API, second+ correctors must be created over the last confirmed corrector, not the original — the caller manages that base selection.

#### `get_makoreqtirebeli(self, inv_id)` — line 741
- **Liveness:** Active. SOAP op `get_makoreqtirebeli`. Caller: `account_move_sync.py` (141).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried).
- **Purpose:** Returns the active corrector's `k_id` for an invoice (API §5), normalized to int with `0` when none. This is the reliable source for supplier-correction discovery because the `k_id` field on `get_invoice` is unreliable. Used during sync to locate the live corrector record.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/rs_soap_service_view.py`

**File role:** Small auxiliary extension of the same `rs.soap.service` abstract model (via `_inherit`). It adds two read-only "view/lookup" SOAP wrappers — reverse party lookup by un_id and the waybills attached to an invoice — kept separate from the core CRUD/status file. Reuses the parent's client, credentials, session, retry, escaping, and DataTable parser.

**Main flows it participates in:**
- View wizard display: party name/TIN resolution and attached-waybill listing in `rs_einvoice_view_wizard.py`.

### class RsSoapServiceView(models.AbstractModel) — `_inherit = 'rs.soap.service'`

#### `get_party_from_un_id(self, un_id)` — line 16
- **Liveness:** Active. SOAP op `get_tin_from_un_id`. Caller: `rs_einvoice_view_wizard.py` (101).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried).
- **Purpose:** Reverse of `get_un_id_from_tin`: resolves an rs.ge `un_id` to `{tin, name}` (API §9 `get_tin_from_un_id`, which also returns the org name). Used to display the counterparty's identity in the view wizard.

#### `get_invoice_waybills(self, inv_id)` — line 33
- **Liveness:** Active. SOAP op `get_ntos_invoices_inv_nos`. Caller: `rs_einvoice_view_wizard.py` (163).
- **Role:** SOAP-call (read).
- **Side effects:** Calls-rs.ge-API (retried); parses XML.
- **Purpose:** Lists the waybills (overhead nos/dates) linked to an invoice (API §6 `get_ntos_invoices_inv_nos`). Raw SOAP POST + inherited `_parse_datatable_rows`. Used to show invoice→waybill linkage in the view wizard.

---

# Section B — `gec_rs_invoice`: the invoice lifecycle

This is the heart of the integration. It starts with `account_move.py` (the shared field declarations, computes, constraints, CRUD guards, and the large library of private helpers that every action reuses), then the seller actions, the status-sync engine, the buyer actions, the correction/replacement orchestration, the wizards, the supporting models, and the crons.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/account_move.py`

**File role:** The foundation layer of the `account.move` extension. It declares every rs.ge-related field on invoices/bills, plus the shared compute/constraint/onchange/CRUD-override logic and a large set of private helpers (validation, status math, locking, logging, auto-cancel mirroring, hashing for change-detection). The visible action buttons (`action_rs_create`, `action_rs_send`, etc.) live in sibling files; this file is what they all call into.

**Main flows it participates in:**
- Seller filing: preflight validation (`_rs_validate`), header push (`_rs_push_header_to_rs`), success detection, locking, and pending-action markers used by Create/Edit/Send/Cancel/Delete.
- Buyer side: party computation, TIN identity verification, auto-cancel mirroring when rs.ge voids a document.
- Correction / replacement orchestration: chaining base lookup, in-flight blocker detection, legacy-correction quarantine, neutralize-on-accept / reset-on-reject.
- Status sync: change-detection hashing, deadline cron (#996 Art.54), overdue banner compute, latest-record compute.
- Down-payment / advance settlement: detecting offset lines, native-attach eligibility, advance flags.
- Data integrity: CRUD guards (immutable fiscal fields once on rs.ge, ID overwrite protection, unlink protection) and SQL constraints.

### module-level functions

#### `_rs_status_label(code)` — line 95
- **Liveness:** Active — called in-file (12×) and across `account_move_sync.py`, `account_move_seller.py`, `rs_einvoice_view_wizard.py` (38 external refs).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Turns a raw rs.ge status code (e.g. `'2'`) into a readable English label (e.g. `Confirmed`) using the `RS_STATUS` map. Exists so logs and error popups show humans a meaning instead of a bare number; returns an em-dash for an empty code.

#### `_rs_clean_number(value)` — line 102
- **Liveness:** Active — used by `account_move_sync.py` and `rs_einvoice_view_wizard.py`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Normalizes a value from rs.ge into a clean string, treating placeholder junk (`''`, `-1`, `0`, `null`, `none`) as "no value". Solves the problem that rs.ge returns sentinel values for "not set" that should not be displayed as a real invoice number.

#### `rs_to_int(value, default=0)` — line 107
- **Liveness:** Active — used by `rs_buyer_inbox_wizard.py`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Safely converts an rs.ge field to an integer, returning a caller-chosen default instead of crashing on bad/missing input.

#### `rs_to_float(value, default=0.0)` — line 115
- **Liveness:** Active — used by `rs_buyer_inbox_wizard.py` and `account_move_seller.py`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Same as `rs_to_int` but for decimals (amounts). Returns the default on empty/garbage so amount parsing never throws.

### class AccountMove(models.Model) — `_inherit = 'account.move'`

#### `_compute_rs_operation_period(self)` — line 365
- **Liveness:** Active — `@api.depends('invoice_date')` compute for stored `rs_einv_operation_month`/`rs_einv_operation_year`.
- **Role:** Compute · **Side effects:** Writes-DB (stored compute)
- **Purpose:** Splits the invoice date into the Georgian VAT operation month and year, which rs.ge needs as separate values. Stored so they can be searched/grouped.

#### `_compute_rs_einv_parties(self)` — line 373
- **Liveness:** Active — `@api.depends(...)` compute for stored seller/buyer TIN/name and `rs_einv_is_buyer_side`.
- **Role:** Compute · **Side effects:** Writes-DB (stored compute)
- **Purpose:** Figures out who the seller and buyer are based on document direction — on a vendor bill the partner is the seller and our company is the buyer, vice versa for a customer invoice. Fills both parties' TIN/name and flags buyer-side, which drives whether the UI shows buyer or seller actions.

#### `_compute_rs_einv_has_downpayment_offsets(self)` — line 391
- **Liveness:** Active — `@api.depends(...)` compute.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Marks a customer invoice that mixes regular delivery lines with negative down-payment offset rows. Tells the UI and export logic this invoice needs special advance-settlement handling.

#### `_compute_latest(self)` — line 399
- **Liveness:** Active — `@api.depends(...)` compute for `rs_einv_latest_id`/`rs_einv_latest_status`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Finds the most recent live rs.ge record tied to this document — which may be a newer correction/replacement (status 8) or a legacy correction row, not the original. This is what Cancel-on-RS targets so it acts on the record rs.ge considers current.

#### `_compute_rs_einv_can_clear_cancelled_replacement(self)` — line 448
- **Liveness:** Active — `@api.depends(...)` compute.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** True only when this invoice's linked replacement got cancelled. Drives visibility of the "Clear Cancelled Replacement" button so the operator can unlink a dead replacement and start over.

#### `_compute_rs_einv_reversal_count(self)` — line 456
- **Liveness:** Active — `@api.depends('reversal_move_ids')` compute.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Counts credit notes/reversals against this invoice. Feeds the "Credit Notes" stat button.

#### `_compute_has_pending_changes(self)` — line 473
- **Liveness:** Active — `@api.depends(...)` compute.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Detects whether the invoice lines changed since the last successful sync by comparing a freshly computed hash with the stored fingerprint. Drives the "Update on RS" button. Legacy records with no stored hash show as pending.

#### `_compute_rs_einv_overdue(self)` — line 489
- **Liveness:** Active — `@api.depends(...)` compute for `rs_einv_overdue_days`/`rs_einv_overdue_state`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Counts days since the operation date for sales invoices still awaiting buyer confirmation and grades them green/yellow/red against the 30-day #996 Art.54 deadline. Powers the live deadline banner.

#### `init(self)` — line 524
- **Liveness:** Active — framework hook (runs on install/upgrade).
- **Role:** Override · **Side effects:** Writes-DB (DDL)
- **Purpose:** Creates a partial SQL index on posted sales invoices by date so the deadline cron's query stays fast as the table grows.

#### `_cron_rs_einv_check_deadlines(self)` — line 534
- **Liveness:** Active — cron target in `data/ir_cron.xml`.
- **Role:** Cron · **Side effects:** Reads-only on others / Writes-DB (logs) / Sends-mail (chatter)
- **Purpose:** Daily job that finds posted sales invoices past the 30-day rs.ge filing deadline and, once per day per invoice, writes an error log and posts a chatter warning to file immediately and avoid a penalty. A per-day marker prevents re-spamming.

#### `_rs_compute_line_hash(self)` — line 589
- **Liveness:** Active — called by `_compute_has_pending_changes` and `_rs_stamp_sync_hash`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Builds a short, order-independent SHA-256 fingerprint of the header + product-line state (description, UoM, qty, totals, taxes, DP flag) plus advance mode. The basis for detecting "unsynced changes".

#### `_rs_stamp_sync_hash(self)` — line 614
- **Liveness:** Active — called by `account_move_seller.py` after successful syncs (4×).
- **Role:** Helper · **Side effects:** Writes-DB
- **Purpose:** Records the current line hash after a successful push to rs.ge so the "pending changes" flag clears. Marks "Odoo and rs.ge now agree."

#### `_rs_log(self, message, level='info')` — line 619
- **Liveness:** Active — heavily used (17× in-file, 65 external refs).
- **Role:** Helper · **Side effects:** Writes-DB
- **Purpose:** Creates an `rs.einvoice.log` row attached to this move. The single channel for the per-document RS Logs audit trail on the form.

#### `_rs_product_lines(self)` — line 626
- **Liveness:** Active — used in-file (5×) and in buyer/seller files (7 refs).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns just the real product lines (filtering out section/note lines). Everything that talks to rs.ge or hashes lines starts here, because only product lines map to rs.ge invoice rows.

#### `_rs_notify(self, message, level='info', post_chatter=False, activity_xmlid=None, activity_summary=None, activity_note=None, activity_deadline=None)` — line 633
- **Liveness:** Active — used in-file and in sync/seller files (8 refs).
- **Role:** Helper · **Side effects:** Writes-DB / Sends-mail / can schedule activity
- **Purpose:** One call that always logs an RS event and optionally also posts to chatter and/or schedules a to-do. Lets callers raise visibility through multiple channels at once, swallowing side-channel failures so the main flow never breaks.

#### `_rs_field_label(record, field_name, fallback='—')` (staticmethod) — line 657
- **Liveness:** Active — used in-file (4×) in error messages.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Translates a selection field's current value into its display label. Used so errors say "state: Posted" rather than the raw stored value.

#### `_rs_doc_label(self)` — line 665
- **Liveness:** Active — used in-file (4×).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns "bill" for vendor documents, "invoice" otherwise, so user-facing messages read naturally for both sides.

#### `_rs_find_other_move_by_rs_id(self, rs_id, use_sudo=False)` — line 670
- **Liveness:** Active — called from `account_move_buyer.py` (3×).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Looks up a different account.move in the same company already carrying a given rs.ge invoice ID. Buyer flows use it to detect that an incoming record is already represented by another local document (avoiding duplicates).

#### `_rs_extract_status_triplet(result)` (staticmethod) — line 682
- **Liveness:** Active — called from sync/seller files (3×).
- **Role:** Helper / SOAP result parser · **Side effects:** Reads-only
- **Purpose:** Pulls the three fields that matter from a `get_invoice` response — status, fiscal series, fiscal number — into a clean tuple. Centralizes the attribute-reading.

#### `_rs_get_fx_rate(self, target_date=None)` — line 691
- **Liveness:** Active — called in-file and by `account_move_sync.py:572`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Finds the latest currency rate on or before a date for this invoice's currency. rs.ge wants GEL, so foreign-currency invoices must convert using the correct historical rate; preflight uses it to confirm a rate exists.

#### `_rs_assert_no_blocking_replacement(self, original, replacement, guidance)` — line 701
- **Liveness:** Active — called by `_post` and `_rs_check_cn_post_preconditions`.
- **Role:** Helper / guard · **Side effects:** Raises-to-user
- **Purpose:** Always raises — formats the right error when an original already has a replacement linked. If the replacement is cancelled it says to clear it first; otherwise it explains the existing one. Prevents a second replacement chain on an invoice that already has one.

#### `_rs_verify_tin_identity(self, seller_un_id, buyer_un_id, service, context_label='')` — line 719
- **Liveness:** Active — called from `account_move_buyer.py:558`.
- **Role:** Helper / SOAP-call (`get_un_id_from_tin`) · **Side effects:** Calls-rs.ge-API / Raises-to-user
- **Purpose:** On buyer-side import, double-checks that the rs.ge record's seller/buyer internal IDs match the partner and company on the local bill, by resolving each TIN to its un_id and comparing. Stops a supplier correction meant for someone else from being imported onto the wrong bill.

#### `_rs_schedule_manual_reversal_activity(self, reason='')` — line 759
- **Liveness:** Active — called in-file (3×) by auto-cancel/reset fallbacks.
- **Role:** Helper · **Side effects:** Writes-DB (activity)
- **Purpose:** Schedules a to-do when Odoo could not automatically cancel a document that rs.ge already voided (e.g. it's paid or in a locked period). Tells the operator how to unblock and align the books.

#### `_rs_auto_cancel_after_rs_cancellation(self, event_message=None)` — line 785
- **Liveness:** Active — called in-file and from sync/buyer-inbox; overridden in `rs_base`.
- **Role:** Helper · **Side effects:** Writes-DB / Sends-mail / can schedule activity
- **Purpose:** Mirrors an rs.ge voiding into Odoo by setting the local document to Cancelled (resetting to draft first if needed). Used whenever rs.ge has decided the document is dead (buyer confirmed our cancel → 7, supplier cancel confirmed, or original superseded by accepted correction → 8). If Odoo refuses (paid/locked), it falls back to logging + a manual-cancel to-do instead of crashing.

#### `_rs_neutralize_after_correction_accepted(self)` — line 851
- **Liveness:** Active — called from `account_move_sync.py` (2×).
- **Role:** Helper · **Side effects:** Writes-DB / Sends-mail (via auto-cancel)
- **Purpose:** When a Correct-and-Reissue replacement is accepted (status 8), cancels the now-superseded original so the books show only the corrected invoice. Idempotent — bails if the original isn't a posted sales invoice or already has reversals.

#### `_rs_reset_correction_to_draft_after_rejection(self)` — line 869
- **Liveness:** Active — called from `account_move_sync.py:88`.
- **Role:** Helper · **Side effects:** Writes-DB / can schedule activity
- **Purpose:** When the buyer rejects a correction (rs.ge drops it back to status 4), resets the local correction to draft so the user can fix lines and re-send on the same rs.ge record. Falls back to a to-do if the reset is blocked.

#### `_rs_schedule_cancel_pending_activity(self, target_id)` — line 892
- **Liveness:** Active — called from `account_move_seller.py:1167`.
- **Role:** Helper · **Side effects:** Writes-DB / Sends-mail / schedules activity
- **Purpose:** After Cancel-on-RS is sent, records the timestamp and posts a chatter note plus a 14-day to-do explaining the local accounting is NOT yet reversed — reversal only happens once the buyer confirms on rs.ge. Makes the "waiting on buyer" state visible and drives the stuck-cancel cron.

#### `_rs_schedule_line_sync_activity(self, target_id, failed_line, committed_writes, total_lines)` — line 908
- **Liveness:** Active — called from `account_move_sync.py` (2×).
- **Role:** Helper · **Side effects:** Writes-DB / Sends-mail / schedules activity
- **Purpose:** Surfaces a partial line sync — when Update-on-RS wrote some line slots then failed, leaving rs.ge holding a mix of old and new lines. Logs, chatters, and schedules a to-do to fix it and re-run Update on RS before sending to the buyer.

#### `_rs_validate(self)` — line 929
- **Liveness:** Active — called from `account_move_seller.py` before Create/Edit/Send (3×).
- **Role:** Helper / preflight · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** The big local preflight before any rs.ge call. Catches everything rs.ge would silently reject or truncate: wrong active company, Skip flag set, buyer-side document, not posted, missing/non-numeric/identical TINs, non-GEL company currency, impossible dates, no product lines, illegal negative lines, native-advance prerequisites, empty/over-long line names, missing FX rate, negative-rate taxes. Gives one clear local error instead of a cryptic SOAP failure.

#### `_check_rs_einv_id_format(self)` — line 1084
- **Liveness:** Active — `@api.constrains('rs_einv_id')`.
- **Role:** Constraint · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Refuses any rs.ge invoice ID that isn't a positive integer, so a malformed value can never reach the SOAP layer.

#### `_check_rs_skip_consistency(self)` — line 1099
- **Liveness:** Active — `@api.constrains('rs_einv_skip', 'rs_einv_id')`.
- **Role:** Constraint · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Stops a document being marked "Skip rs.ge" while it still has a live rs.ge ID. You must Cancel/Delete on RS first, else the record would be orphaned on rs.ge with no local tracking.

#### `_check_rs_skip_downpayment_offset_locked(self)` — line 1109
- **Liveness:** Active — `@api.constrains('rs_einv_skip', 'invoice_line_ids')`.
- **Role:** Constraint · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Forces freestanding down-payment offset credit notes to keep "Skip rs.ge" ticked. Their VAT was already filed via the advance invoice, so filing the offset CN would double-count.

#### `_check_rs_skip_vat_neutral_lines(self)` — line 1124
- **Liveness:** Active — `@api.constrains(...)`.
- **Role:** Constraint · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** For VAT-neutral skip reasons (bad debt, warranty, commercial gesture, intercompany mirror), enforces that the CN lines carry no tax and use expense (not income) accounts. These are economic expenses, not VAT reversals, so they must not touch the VAT chain or revenue accounts.

#### `_check_unique_pending_correction(self)` — line 1164
- **Liveness:** Active — `@api.constrains(...)`.
- **Role:** Constraint · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Rejects a second FILED correction (rs.ge ID set, status 4/5) against an original that already has one in flight, because rs.ge forbids overlapping corrections. Drafts are serialized upstream, so this is the last-line filing guard.

#### `_onchange_rs_einv_skip(self)` — line 1201
- **Liveness:** Active — `@api.onchange('rs_einv_skip')`.
- **Role:** Onchange · **Side effects:** Reads-only (UI warning + clears reason)
- **Purpose:** When the user unticks Skip, clears the skip reason and warns if un-skipping a VAT-neutral CN that carries no taxes (filing won't actually reduce VAT). Prevents a pointless rs.ge filing with no tax effect.

#### `_onchange_rs_einv_note_length(self)` — line 1231
- **Liveness:** Active — `@api.onchange('rs_einv_note')`.
- **Role:** Onchange · **Side effects:** Reads-only (UI warning)
- **Purpose:** Warns when the RS Note nears the 255-char limit, because Odoo's `size=255` would silently truncate longer text and data would be lost on the rs.ge PDF.

#### `_onchange_rs_einv_k_type_suggest(self)` — line 1247
- **Liveness:** Active — `@api.onchange('reversed_entry_id', 'invoice_line_ids', 'move_type')`.
- **Role:** Onchange · **Side effects:** Reads-only (sets field)
- **Purpose:** Auto-suggests a correction reason (k_type) on a credit note the first time, but never overwrites a value the user already set. Saves picking the obvious reason by hand.

#### `_onchange_rs_einv_k_type_mark_user_set(self)` — line 1256
- **Liveness:** Active — `@api.onchange('rs_einv_k_type')`.
- **Role:** Onchange · **Side effects:** Reads-only (sets flag)
- **Purpose:** Once the user picks a reason, flips the `..._user_set` flag so the auto-suggestion logic stops touching it. Protects a deliberate choice from being silently overwritten.

#### `_rs_suggest_k_type(self)` — line 1262
- **Liveness:** Active — called in-file (3×).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Best-effort guess of the correction reason from the CN's shape: full-amount match → "Full cancellation", else "Price/amount changed". Also consults the external hook (so stock/waybill modules can suggest "Goods Returned"). A sensible default the user can override.

#### `_rs_suggest_k_type_from_external(self)` — line 1286
- **Liveness:** Active — extension hook; called in-file and overridden via `super()` in `rs_base`'s `account_move.py:311`.
- **Role:** Helper (extension hook) · **Side effects:** Reads-only
- **Purpose:** A deliberately empty hook returning `None` here so other modules (stock/waybill) can override it to suggest "Goods Returned to Seller". Keeps this module independent of stock while allowing a richer suggestion when those modules are installed.

#### `create(self, vals_list)` — line 1291
- **Liveness:** Active — framework override (`@api.model_create_multi`).
- **Role:** Override / CRUD · **Side effects:** Writes-DB
- **Purpose:** After creating moves, sets sensible rs.ge defaults: suggests a CN reason, flags pure DP invoices as advances, propagates the advance flag from a reversed advance, auto-ticks Skip (reason `down_payment`) on freestanding DP offset CNs, and auto-selects native advance settlement when a final invoice has offset lines and is eligible. Front-loads the right config so the operator usually needn't set it.

#### `write(self, vals)` — line 1323
- **Liveness:** Active — framework override (CRUD).
- **Role:** Override / CRUD · **Side effects:** Writes-DB / Sends-mail / Raises-to-user
- **Purpose:** The main data-integrity gate on edits. Blocks clearing/changing the rs.ge invoice ID directly (must use Delete on RS / Resolve Orphan), locks fiscal fields (partner, currency, date, reversed entry) once the document is on rs.ge, blocks toggling Skip on a posted record, and restricts changing advance mode after filing. A context bypass (`rs_allow_post_send_edit`/`rs_allow_id_overwrite`) is allowed but logged to chatter and RS Logs. Prevents Odoo and rs.ge silently drifting apart.

#### `unlink(self)` — line 1492
- **Liveness:** Active — framework override (CRUD).
- **Role:** Override / CRUD · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Refuses to delete any move that still has a live rs.ge record (unless skipped). Deleting locally would leave an orphan on rs.ge nobody could find or cancel — the user must Delete on RS first.

#### `_rs_is_downpayment_invoice(self)` — line 1507
- **Liveness:** Active — called in-file (3×).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** True when every product line is a down-payment line — a pure advance invoice or a freestanding/reversing offset CN. Deliberately false for a final invoice that merely mixes offset rows with normal lines, so the two cases get different handling.

#### `_rs_has_downpayment_offset_lines(self)` — line 1525
- **Liveness:** Active — called in-file (5×) and in sync/seller files.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** True when a final invoice has BOTH regular delivery lines and at least one DP offset row. That mix is the signal that the advance must be subtracted from (net) or attached to (native) the rs.ge payload.

#### `_rs_uses_native_advance_attach(self)` — line 1538
- **Liveness:** Active — called from sync/seller/models files (5×).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** True when this final customer invoice is configured for rs.ge native advance-attach mode (mode = native, has offset lines, not itself an advance). Lets sync/seller code branch cleanly between net offsetting and native attachment.

#### `_post(self, soft=True)` — line 1547
- **Liveness:** Active — framework override (posting).
- **Role:** Override · **Side effects:** Writes-DB / Calls-rs.ge-API (via refresh) / Raises-to-user / Sends-mail
- **Purpose:** Hooks posting to enforce rs.ge rules and auto-maintain state. Blocks posting buyer-side documents still pending on rs.ge (forces "Accept on rs.ge"), checks replacement-cancel acceptance, re-suggests CN reasons, blocks duplicate reductions on a replaced original, refreshes the original's status and runs CN preconditions before posting, then after the real post auto-syncs edited lines for Sent-pending invoices. Centralizes "is this document allowed to post given its rs.ge state."

#### `_rs_auto_sync_pending_sent_edits(self)` — line 1625
- **Liveness:** Active — called in-file by `_post`.
- **Role:** Helper · **Side effects:** Writes-DB / Calls-rs.ge-API (via `action_rs_edit`) / Sends-mail
- **Purpose:** After re-posting a Sent-pending sales invoice with unsynced line changes, automatically pushes those changes to rs.ge so the operator needn't click Update on RS. A failure never blocks the post — it warns and leaves the pending flag set for a manual retry, inside a savepoint.

#### `_rs_check_cn_post_preconditions(self, refresh_original=True)` — line 1656
- **Liveness:** Active — called in-file by `_post`.
- **Role:** Helper · **Side effects:** Reads-only / Calls-rs.ge-API (optional refresh) / Raises-to-user
- **Purpose:** Validates that a credit note may be filed against its original: original must not have a blocking replacement, must be at status Confirmed/Corrected, and (when Corrected) have no other correction in flight and a locally linked accepted correction. Stops corrections rs.ge would reject or that would corrupt the chain.

#### `_rs_assert_can_be_reversed(self)` — line 1701
- **Liveness:** Active — called from `rs_correction_wizard.py:212`.
- **Role:** Helper / guard · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Blocks creating a credit note from an original unless it is Confirmed/Corrected and free of blocking replacements/in-flight corrections/active legacy corrections. The reverse-side gate (mirrors `_rs_check_cn_post_preconditions`) used by the correction wizard before a CN is even built.

#### `_rs_locked_on_rs(self)` — line 1738
- **Liveness:** Active — called by `_rs_raise_if_locked`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** True when this document — or any correction child — sits in a locked rs.ge state. Used to decide whether reset/cancel should be blocked because something is still live on rs.ge.

#### `_rs_raise_if_locked(self, action_label, allow_pending=False)` — line 1756
- **Liveness:** Active — called by `button_draft`/`button_cancel`.
- **Role:** Helper / guard · **Side effects:** Calls-rs.ge-API (refresh) / Writes-DB (log) / Raises-to-user
- **Purpose:** Before reset-to-draft or cancel, refreshes status and blocks if locked, cancelled-and-confirmed (7), or pending; an unreachable rs.ge also blocks (never let the two sides drift). `allow_pending=True` lets a Sent-pending invoice through since rs.ge keeps it editable until the buyer acts. Context `rs_skip_lock_check` skips the check for internal auto-cancel paths.

#### `button_draft(self)` — line 1804
- **Liveness:** Active — framework/UI override (Reset to Draft).
- **Role:** Override / Action-button · **Side effects:** Calls-rs.ge-API (via lock check) / Raises-to-user
- **Purpose:** Wraps standard Reset to Draft so it refuses on documents locked on rs.ge, and specifically forbids resetting the paired "replacement reversal" half of a Correct-and-Reissue (which must mirror its original).

#### `button_cancel(self)` — line 1817
- **Liveness:** Active — framework/UI override (Cancel).
- **Role:** Override / Action-button · **Side effects:** Calls-rs.ge-API (via lock check) / Raises-to-user
- **Purpose:** Wraps standard Cancel so a document still live on rs.ge can't be cancelled locally first — you must Cancel/Delete on RS. Prevents the books and rs.ge from disagreeing.

#### `_rs_get_service(self)` — line 1822
- **Liveness:** Active — used across the module / `rs_base` (19 refs).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns the shared `rs.soap.service` wrapper. A single indirection point so the SOAP entry can be swapped or mocked.

#### `_rs_inv_id_int` (property) — line 1826
- **Liveness:** Active — used in-file and in `rs_einvoice_waybill_link.py` (20 refs).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns the rs.ge invoice ID as an integer (0 if none). rs.ge SOAP methods want a numeric ID, so this saves every caller the cast/guard.

#### `_rs_get_correction_base_id(self)` — line 1829
- **Liveness:** Active — called from `account_move_seller.py:755`.
- **Role:** Helper / SOAP-call (`get_invoice`) · **Side effects:** Calls-rs.ge-API / Writes-DB (log) / Raises-to-user
- **Purpose:** Works out which rs.ge record ID a new correction must chain onto — the latest accepted replacement (status 8) if the chain advanced, else the original. Verifies that base is actually accepted on rs.ge before returning it, raising if rs.ge moved on (asks the user to run Check Status). Stops corrections chaining onto a stale base.

#### `_rs_find_pending_correction_blocker(self, exclude_move=None)` — line 1878
- **Liveness:** Active — called in-file and from seller/orchestrator (3×).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns the first in-flight correction (status 4/5/6) on this invoice's chain, or empty. Status 6 counts because a cancelled-but-unconfirmed correction leaves the chain indeterminate. Callers use it to refuse starting a new correction while one is unsettled.

#### `_rs_find_invoice_corrections_of(self, original, status=None, exclude_self=False)` — line 1896
- **Liveness:** Active — called in-file (3×).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns the posted Correct-and-Reissue correction invoices that replace a given original (optionally filtered by status), newest first. The shared query behind "what corrections exist for this invoice."

#### `_rs_find_legacy_corrections(self, status=None)` — line 1917
- **Liveness:** Active — called in-file and from `account_move_seller.py:1124`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns old-style `rs.einvoice.correction` rows from the deprecated Request-Edit flow. That flow no longer creates corrections, but legacy DBs may still hold these rows, so current flows look them up to quarantine them rather than treat them as ordinary credit notes.

#### `_rs_active_legacy_corrections(self)` — line 1937
- **Liveness:** Active — called by `_rs_raise_if_legacy_corrections_active`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Narrows `_rs_find_legacy_corrections` to those not deleted on rs.ge (status ≠ -1). The set that actually blocks new automated correction chains.

#### `_rs_raise_if_legacy_corrections_active(self, action_label)` — line 1943
- **Liveness:** Active — called in-file and from seller/orchestrator.
- **Role:** Helper / guard · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Refuses to start a new automated CN/correction chain when an active legacy correction (with no Odoo CN backing it) still exists on rs.ge. Forces the operator to clear the old-style correction first.

#### `_rs_assert_chain_has_local_confirmed_correction(self)` — line 1960
- **Liveness:** Active — called in-file and from `account_move_seller.py:733`.
- **Role:** Helper / guard · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** When rs.ge says an invoice is Corrected (status 3) but Odoo has no linked accepted correction, raises and tells the user to run Check Status. Prevents continuing a chain while the local picture lags rs.ge.

#### `_rs_push_header_to_rs(self, service, target_id, label=None)` — line 1973
- **Liveness:** Active — called from `account_move_seller.py` (3×).
- **Role:** SOAP-call (`save_invoice`/`save_invoice_a`/`save_invoice_n`) · **Side effects:** Calls-rs.ge-API / Writes-DB (log) / Raises-to-user
- **Purpose:** Pushes the invoice header (date, seller/buyer un_ids) via the correct `save_invoice` variant chosen from the move's flags. Resolves seller/buyer internal IDs first, raises with a log entry on failure. The single place the header save happens.

#### `_rs_pick_save_variant(self)` — line 2000
- **Liveness:** Active — called in-file and from seller.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Decides which save endpoint to use and what note to pass: `advance` for prepayment invoices, `note` (with text) when an RS Note is set, otherwise `regular`. Keeps the endpoint-selection rule in one spot.

#### `_rs_save_succeeded(result)` (staticmethod) — line 2008
- **Liveness:** Active — called in-file and from `account_move_sync.py:722`.
- **Role:** Helper / SOAP result parser · **Side effects:** Reads-only
- **Purpose:** Returns True if any of the three `save_invoice*` variants reported success. rs.ge uses a different result attribute per variant, so this checks all of them.

#### `_rs_send_succeeded(result)` (staticmethod) — line 2017
- **Liveness:** Active — called from `account_move_seller.py:992`.
- **Role:** Helper / SOAP result parser · **Side effects:** Reads-only
- **Purpose:** Returns True only when `change_invoice_status` truly succeeded. Plain truthiness would misread a zeep object whose result is False as success; this inspects the flag explicitly so a failed Send/Cancel isn't treated as done.

#### `_rs_target_is_correction(self, target_id)` — line 2035
- **Liveness:** Active — called from seller (2×).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Determines whether a given rs.ge ID points to a correction record (states 4/5/8) vs a plain invoice. Send uses it to decide whether it is sending a correction or an original, which changes the status code sent.

#### `_rs_mark_pending(self, action_code)` — line 2056
- **Liveness:** Active — called from seller (2×).
- **Role:** Helper · **Side effects:** Writes-DB (commits)
- **Purpose:** Stamps a "pending action" marker (create/correction/delete/send) + timestamp, then commits immediately, right before firing an rs.ge request. If the request hangs or the response is lost, the marker survives so Resolve Orphan can recover the record later.

#### `_rs_clear_pending(self)` — line 2063
- **Liveness:** Active — called from buyer/seller (5×).
- **Role:** Helper · **Side effects:** Writes-DB
- **Purpose:** Clears the pending-action marker once an rs.ge request completes (or is resolved). Counterpart to `_rs_mark_pending`.

#### `_rs_acquire_row_lock(self, action_label)` — line 2069
- **Liveness:** Active — called from buyer/seller/orchestrator (12×).
- **Role:** Helper · **Side effects:** Reads-only (DB row lock) / Raises-to-user
- **Purpose:** Takes a `SELECT ... FOR UPDATE NOWAIT` lock on the move so two rs.ge actions can't run on the same document at once. If already held it raises a friendly "another action is still running" error instead of blocking. Prevents concurrent double-filing.

#### `_rs_relock_after_commit(self)` — line 2091
- **Liveness:** Active — called from buyer/seller (6×).
- **Role:** Helper · **Side effects:** Reads-only (DB row lock)
- **Purpose:** After a mid-flow commit (e.g. the pending-marker commit), invalidates the cache and re-acquires a lock with SKIP LOCKED for the post-commit tail. Returns empty if the row is now busy or gone, so the caller can skip cleanly.

#### `_rs_round(amount, places=2)` (staticmethod) — line 2098
- **Liveness:** Active — called from `account_move_sync.py` (14×).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Rounds amounts using ROUND_HALF_UP (Decimal) for Georgian VAT compliance. Python's built-in `round()` uses banker's rounding which under-rounds X.5; GE tax rules expect half-up. Used for any value sent outbound or used in tax math.

#### `_rs_safe_refresh_status(self)` — line 2119
- **Liveness:** Active — called in-file and across module/`rs_base`/wizards (17×).
- **Role:** Helper / SOAP-call (via `action_rs_refresh_status`) · **Side effects:** Calls-rs.ge-API / Writes-DB (log) / Sends-mail / Raises-to-user (for credential/config errors)
- **Purpose:** Pulls the current rs.ge status while tolerating transient failures: returns True/False (False on a network blip) instead of crashing, but deliberately lets credential/configuration UserErrors bubble up so they stay visible. On a soft failure it logs and chatters a "retry manually" note. The safe wrapper everything uses before making a lock/state decision.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/account_move_seller.py`

**File role:** Seller-side mixin on `account.move`. Implements the create/update/send/cancel/delete lifecycle for invoices and corrections we issue, plus the entire "native rs.ge advance settlement" subsystem that attaches down-payment advance invoices to final invoices on rs.ge. Pure SOAP-orchestration layer: validates state, marks pending for orphan recovery, calls the SOAP wrapper, and routes returned statuses back onto the right Odoo record.

**Main flows it participates in:**
- **Send to RS** (`action_rs_create`) → fresh invoice (`_rs_create_invoice`) or a Correct-and-Reissue correction (`_rs_create_invoice_correction`).
- **Update on RS** (`action_rs_edit`).
- **Send to buyer** (`action_rs_send`).
- **Cancel on RS** (`action_rs_cancel` → `_rs_cancel_core`; core split so the Replace orchestrator can cancel atomically).
- **Delete on RS** (`action_rs_delete`).
- **Native advance settlement** — `_rs_expected_advance_settlements` resolves advance invoices behind negative DP lines via Sale links; `_rs_sync_native_advance_settlements` attaches/updates them on rs.ge.
- **Status routing** (`_rs_apply_status_update`).

### class AccountMove(models.Model) — `_inherit = 'account.move'`

#### `action_rs_create(self)` — line 21
- **Liveness:** Active — XML button `action_rs_create`; also `super()`-overridden in `rs_base_methods`.
- **Role:** Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API (via helpers) / Raises-to-user
- **Purpose:** The "Send to RS" entry point that decides what kind of rs.ge record to create. Acquires a lock, refuses if a prior request is still pending without an ID (duplicate guard), refuses Skip-marked/already-created docs, and validates. Branches: a replacement → `_rs_create_invoice_correction`; credit notes are hard-blocked with guidance to use the replacement flow; everything else → `_rs_create_invoice`. Centralizes the many preconditions and prevents duplicate/illegal submissions.

#### `_rs_create_invoice(self, service)` — line 102
- **Liveness:** Active — called at line 100; `super()` extension point in `rs_base_methods`.
- **Role:** SOAP-call / Helper · **Side effects:** Writes-DB / Calls-rs.ge-API / Raises-to-user / commits
- **Purpose:** Creates a brand-new invoice header on rs.ge. Resolves un_ids, picks the save variant, marks pending (for orphan recovery), then calls `save_invoice`. On success stamps `rs_einv_id`/status, clears pending, commits, re-locks the row, and continues with line sync, hash stamping, and native advance settlement. Split from the button so logic is reusable and the commit boundary is explicit.

#### `_rs_row_value(row, *keys)` (staticmethod) — line 152
- **Liveness:** Active — used throughout the file.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Tolerant accessor over a SOAP DataTable row: returns the first non-None value among several candidate key spellings (rs.ge returns inconsistent casing/aliases).

#### `_rs_to_int(value)` (staticmethod) — line 160
- **Liveness:** Active — used in-file.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Thin wrapper delegating to shared `rs_to_int`, exposed as a method so it's callable alongside `_rs_row_value`.

#### `_rs_to_float(value)` (staticmethod) — line 164
- **Liveness:** Active — used here and in `account_move_sync.py`/`rs_einvoice_view_wizard.py`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Wrapper delegating to shared `rs_to_float` for parsing rs.ge numeric strings. A cross-module utility.

#### `_rs_advance_response_status(cls, result)` (classmethod) — line 168
- **Liveness:** Active — used at 625, 660.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Extracts `(status, message)` from an advance attach/update response so the settlement sync can uniformly check for `'200'` success.

#### `_rs_advance_datatable_error(self, rows, label)` — line 174
- **Liveness:** Active — used at 535, 536.
- **Role:** Helper · **Side effects:** Raises-to-user
- **Purpose:** Scans an rs.ge DataTable for embedded `Error`/`ErrorMessage` cells and raises a labeled error if any are present. rs.ge sometimes returns HTTP-200 with an in-band error; this turns that silent failure into a clear message before the data is trusted.

#### `_rs_line_vat_abs_gel(self, line, rate_date=None)` — line 187
- **Liveness:** Active — used at 208, 234, 303.
- **Role:** Helper / Compute · **Side effects:** Reads-only
- **Purpose:** Returns the absolute VAT of a single line, converted to GEL and rounded to 2dp (VAT = `price_total - price_subtotal`). Conversion and abs() are needed because advance settlement works in GEL VAT amounts regardless of line sign.

#### `_rs_move_vat_abs_gel(self, move)` — line 194
- **Liveness:** Active — used at 278, 479.
- **Role:** Helper / Compute · **Side effects:** Reads-only
- **Purpose:** Sums absolute VAT in GEL across all product lines. Used to fingerprint an advance invoice by its VAT total when disambiguating which advance a DP offset line settles, and to compare corrected vs already-settled VAT.

#### `_rs_native_delivery_vat_total(self)` — line 203
- **Liveness:** Active — used at 511.
- **Role:** Helper / Compute · **Side effects:** Reads-only
- **Purpose:** Total VAT (GEL) of delivery lines only, excluding DP lines. The ceiling check in settlement sync so attached advance VAT can never exceed actual delivery VAT (over-settle guard).

#### `_rs_expected_advance_settlements(self, force=False)` — line 211
- **Liveness:** Active — used at 335, 372, 510.
- **Role:** Helper · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** The resolver behind native advance settlement: for each negative DP offset line it walks SO line → prior invoice lines to find the posted advance invoice, disambiguating by VAT match when several candidates exist. Returns per-advance settlement items or raises with precise guidance when links are missing/ambiguous/unsynced. Failure here is the signal to fall back to Net mode.

#### `_rs_build_advance_audit_vals(self, item, status, message, action)` — line 316
- **Liveness:** Active — used 4×.
- **Role:** Helper · **Side effects:** Reads-only (builds a dict)
- **Purpose:** Constructs the create vals for an `rs.einvoice.advance.settlement` audit row (final/advance link, VAT, status/message, action, timestamp). Keeps the audit-row shape consistent across the four call sites.

#### `_rs_check_native_advance_eligibility(self, final_date)` — line 328
- **Liveness:** Active — called from `account_move.py:1048`.
- **Role:** Helper / guard · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Fail-fast precondition before sending: each expected advance must be buyer-confirmed and dated in a strictly earlier month than the final (rs.ge never attaches same-month advances). Skips advances already settled (status 200). Raises with the exact reason so the user can switch to Net mode or re-date.

#### `_rs_native_advance_eligible(self)` — line 366
- **Liveness:** Active — called from `account_move.py:1319`.
- **Role:** Helper / Compute (boolean) · **Side effects:** Reads-only; may Call-rs.ge-API (refresh on unconfirmed advances)
- **Purpose:** Non-raising boolean ("can this final use native attachment?") used to auto-pick Native vs Net. Returns False for advances/non-out_invoices/no-offset-lines, swallows the resolver's error, and for unconfirmed advances attempts a refresh before deciding. The silent counterpart to `_rs_check_native_advance_eligibility` for UI defaulting.

#### `_rs_diagnose_unattachable(self, service, item, period_date)` — line 393
- **Liveness:** Active — used at 650.
- **Role:** Helper / SOAP-call (read) · **Side effects:** Reads-only / Calls-rs.ge-API (`get_invoice`)
- **Purpose:** Best-effort explanation of why rs.ge excluded an advance from the attachable list — checks live status, operation month, or concludes it's likely fully settled/under correction. Produces the human-readable `reason` in the "expected but not attachable" error so support can act without logging into rs.ge.

#### `_rs_advance_settlement_usage(self, service)` — line 425
- **Liveness:** Active — used at 463.
- **Role:** Helper / SOAP-call (read) · **Side effects:** Reads-only / Calls-rs.ge-API (`get_attached_advance_invoices`)
- **Purpose:** Queries rs.ge for how much of this advance is used/left across all finals that consumed it. Feeds the correctability check; exists because rs.ge tracks the remaining advance balance server-side and Odoo must read it live before allowing changes.

#### `_rs_assert_advance_correctable(self, service, replacement=None)` — line 458
- **Liveness:** Active — used at 734; also from `rs_replace_orchestrator.py:200`.
- **Role:** Helper / guard · **Side effects:** Reads-only / Calls-rs.ge-API (via usage) / Raises-to-user
- **Purpose:** Blocks corrections rs.ge will refuse: a fully-settled advance, or a correction that drops advance VAT below what finals already consumed. Raises with specifics. Protects from a guaranteed mid-correction rejection.

#### `_rs_sync_native_advance_settlements(self, service, target_id=None)` — line 490
- **Liveness:** Active — used at 150, 847, 968.
- **Role:** SOAP-call / Helper · **Side effects:** Writes-DB (audit rows/sync state/logs) / Calls-rs.ge-API (attach/update) / never raises (catches internally)
- **Purpose:** The core settlement engine. Reconciles Odoo's expected advances against rs.ge's attachable/attached lists, then attaches new advances or updates existing ones to match expected VAT, enforcing over-settle/under-floor/stray/status guards. Swallows all errors into `rs_einv_advance_sync_state` (`synced`/`partial`/`error`) plus a log, returning a bool — so a settlement failure degrades gracefully (e.g. blocking Send-to-buyer) rather than aborting the send.

#### `_rs_create_invoice_correction(self, service)` — line 694
- **Liveness:** Active — used at 59.
- **Role:** SOAP-call / Helper · **Side effects:** Writes-DB / Calls-rs.ge-API (`create_correction`, header/line push) / Raises-to-user / commits
- **Purpose:** Files a Correct-and-Reissue replacement as an rs.ge correction of `rs_einv_replaces_id`, pushing the replacement's own lines as the new state. Heavily guarded (original on rs.ge, buyer can't change, no legacy/pending correction in flight, chain has a local confirmed correction, advance correctable, carried-over advances force Native). On success stamps the correction ID/status, commits, re-locks, then pushes header + lines + hash. The mechanism for editing a buyer-confirmed invoice.

#### `action_rs_edit(self)` — line 807
- **Liveness:** Active — XML button `action_rs_edit`; called internally at `account_move.py:1639`; `super()`-overridden in `rs_base_methods`.
- **Role:** Action-button / Override-point · **Side effects:** Writes-DB / Calls-rs.ge-API / Raises-to-user
- **Purpose:** "Update on RS" — pushes current Odoo content to an editable rs.ge record. Requires an existing ID and posted state, refreshes status, and only proceeds when status is Draft/Sent/New-Correction (0/1/4), else tells the user to use a correction. Pushes header (conditionally), syncs lines, stamps the hash, syncs advances, and clears any stale rejection note.

#### `action_rs_delete(self)` — line 852
- **Liveness:** Active — XML button `action_rs_delete`; `super()`-overridden in `rs_base_methods`.
- **Role:** Action-button / Override-point · **Side effects:** Writes-DB / Calls-rs.ge-API (`delete_invoice`, `get_invoice`) / Raises-to-user
- **Purpose:** Deletes a Draft/New-Correction record from rs.ge. Refreshes status, refuses unless deletable, calls delete, then re-reads to confirm rs.ge reports -1 — if not, keeps the local pointer and raises (avoids orphaning a live record). On confirmed delete clears the local RS fields and reverts the corrected original/parent's status if the deletion was a correction.

#### `action_rs_send(self)` — line 934
- **Liveness:** Active — XML button `action_rs_send`; `super()`-overridden in `rs_base_methods`.
- **Role:** Action-button / Override-point · **Side effects:** Writes-DB / Calls-rs.ge-API (`send_invoice`/`send_correction`, `get_invoice`) / Raises-to-user / Returns-action / commits
- **Purpose:** "Send to buyer" — dispatches a Draft/New-Correction record. Validates state, pushes header/lines, then runs advance settlement; if settlement fails it returns a sticky danger notification and aborts before sending (so a half-settled invoice never reaches the buyer). Calls `send_correction`/`send_invoice`, stamps expected status (5 or 1) and timestamp, commits, then re-reads rs.ge to verify, and refreshes the corrected original when a correction was sent.

#### `action_rs_cancel(self)` — line 1079
- **Liveness:** Active — XML button `action_rs_cancel`.
- **Role:** Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API (via `_rs_cancel_core` + `get_invoice`) / Raises-to-user / commits
- **Purpose:** "Cancel on RS" — flips a confirmed/corrected record to Cancelled (Sent, status 6) for buyer confirmation. Locks, delegates validate+cancel to `_rs_cancel_core`, commits, then re-locks and verifies the real status, routing any divergence through `_rs_apply_status_update`. Thin wrapper so the cancel core can be reused by the Replace orchestrator with a shared transaction.

#### `_rs_cancel_core(self)` — line 1107
- **Liveness:** Active — used at 1083; also from `rs_replace_orchestrator.py:141`.
- **Role:** SOAP-call / Helper · **Side effects:** Writes-DB (status 6, schedules activity) / Calls-rs.ge-API (`cancel_invoice`) / Raises-to-user; does NOT commit (intentional)
- **Purpose:** Validates and performs the rs.ge cancellation, stamping local status 6, but leaves the commit to the caller so Cancel-and-Reissue can persist the cancel and reissue together. Guards against pending CN-driven and legacy corrections, requires an accepted status, schedules a "cancel pending" activity. Returns `(service, target_id_str)` for the caller's verification.

#### `_rs_apply_status_update(self, target_id_str, new_status, action_label='Update')` — line 1170
- **Liveness:** Active — used at 1105, 1166.
- **Role:** Helper · **Side effects:** Writes-DB (status) / posts chatter / may schedule a todo
- **Purpose:** Routes a freshly-read rs.ge status onto whichever Odoo record holds that RS ID — self, a CN-driven correction, or a legacy correction. If no record owns the ID it raises an error notification + todo warning of a desync. Exists because a cancel/correction can change a status on a record that isn't the one the button was pressed on (the correction child), so the status must follow the ID, not `self`.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/account_move_sync.py`

**File role:** Inheritance layer on `account.move` that keeps the local invoice in sync with its rs.ge counterpart: it polls the remote status, detects rejections/cancellations/corrections, reconciles them into Odoo (drafting, neutralizing, auto-cancelling), and pushes/pulls the line-item ("desc") data over SOAP. It also contains the GEL-conversion and payload-building logic that turns Odoo lines into the shape rs.ge expects (and back, for buyer-side bills).

**Main flows it participates in:**
- Status refresh/poll loop (`action_rs_refresh_status`) — buyer-rejection, cancellation-rejection, status-7 auto-cancel, status-8 correction-accepted neutralization, recursive child/parent refresh.
- Outbound line sync to rs.ge (`_rs_sync_lines` + payload builders), including down-payment net-settlement math.
- Inbound line pull for buyer-side bills (`_rs_refresh_pulled_lines`, snapshot + auto-import).
- SOAP result parsing helpers shared with seller/buyer flows.

### class AccountMove(models.Model) — `_inherit = 'account.move'`

#### `action_rs_refresh_status(self)` — line 19
- **Liveness:** Active — XML buttons; `super()`-called by `rs_base`; called from `account_move.py:2138` and recursively.
- **Role:** Action-button (SOAP-call orchestrator) · **Side effects:** Calls-rs.ge-API / Writes-DB / Sends-mail (chatter)
- **Purpose:** The central reconciliation routine. Fetches the live rs.ge invoice (`get_invoice`), updates series/number/sequence, then classifies the remote status against the stored one to detect three transitions humans care about: buyer rejection (status backward / `was_ref` flag / post-send drop to draft), buyer rejection of a cancellation (6 back to confirmed), and accepted cancellation (7). On rejection it posts a deduplicated warning and, for corrections, resets them to draft; on status 7 it auto-cancels and clears pending. It also pulls the supplier-correction ID for buyer-side bills, refreshes legacy and invoice-driven correction children, pulls buyer line snapshots, and recurses upward to the parent (guarded by an `excluded_ids` set against infinite loops). Exists because rs.ge is the source of truth and Odoo must mirror it without double-acting on the same event.

#### `_rs_sync_lines(self, service, target_id=None)` — line 270
- **Liveness:** Active — called from `account_move_seller.py` (4×).
- **Role:** SOAP-call (line push) Helper · **Side effects:** Calls-rs.ge-API (read+write+delete) / Writes-DB / Raises-to-user / schedules activity on partial failure
- **Purpose:** Pushes current Odoo lines onto the rs.ge document by reusing matching "desc" slots, overwriting changed ones, appending new ones, and deleting stale ones. Deliberately defensive: aborts before writing if any existing row lacks a usable ID (avoids writing the wrong slot), distinguishes "nothing written" from "partial write" on failure (different messages + a `partial` state + follow-up activity), and re-reads the final row count to catch silent mismatches. Non-transactional — a mid-sync failure can leave rs.ge holding a mix; the next sync cleans it up.

#### `_rs_get_lines_payload(self)` — line 425
- **Liveness:** Active — called by `_rs_sync_lines`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Thin wrapper returning the rs.ge payload list for this move's own lines, delegating to `_rs_lines_to_payload`.

#### `_rs_lines_to_payload(self, lines, rate_date=None)` — line 430
- **Liveness:** Active — called by `_rs_get_lines_payload`.
- **Role:** Helper (payload builder + business math) · **Side effects:** Reads-only / Raises-to-user (impossible net-settlement)
- **Purpose:** Converts Odoo lines into rs.ge line payloads. The non-trivial part is **down-payment net settlement**: when the invoice carries DP offset lines and is not in native mode, it spreads the offset (advance) gross and VAT proportionally across the regular lines so rs.ge receives the net taxable position (rs.ge rejects negatives). Guards degenerate cases (net ≤ 0, offset VAT > delivered VAT) with actionable errors, and rounds with a residual correction on the last line so totals stay exact. `rate_date` pins one FX day across a correction chain.

#### `_rs_line_to_payload(self, line, rate_date=None)` — line 529
- **Liveness:** Active — called 4× inside `_rs_lines_to_payload`.
- **Role:** Helper · **Side effects:** Reads-only / Raises-to-user (negative qty/amount on a regular invoice)
- **Purpose:** Maps one line to the rs.ge dict (`goods`, `g_unit`, `qty`, `full_amount`, `vat_amount`). Converts to GEL, forbids negative qty/amount on regular `out_invoice`/`in_invoice` (with guidance to split into a CN or mark Skip), and encodes VAT using rs.ge's convention: `-1` for untaxed, else the absolute GEL VAT. Defaults the unit to "ერთეული".

#### `_rs_amount_to_gel(self, amount, rate_date=None)` — line 564
- **Liveness:** Active — used here and from `account_move_seller.py`.
- **Role:** Helper (currency conversion) · **Side effects:** Reads-only / Raises-to-user (missing FX rate)
- **Purpose:** Converts a money amount into company currency (GEL). Short-circuits when already in company currency, else resolves the rate for `rate_date`/`invoice_date`/today via `_rs_get_fx_rate` and raises a clear "add a currency rate" error if none exists.

#### `_rs_line_matches_slot(self, payload, slot)` — line 587
- **Liveness:** Active — called by `_rs_sync_lines`.
- **Role:** Helper (comparison) · **Side effects:** Reads-only
- **Purpose:** Returns True when an existing rs.ge slot already equals the payload so the sync can skip a redundant `save_invoice_desc`. Compares normalized goods/unit text, qty at 4dp, amounts at 2dp. Makes re-syncs cheap and avoids churning slot IDs.

#### `_rs_get_purchase_vat_18(self)` — line 613
- **Liveness:** Active (with a **TODO**) — called here and from `account_move_buyer.py:252`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Looks up the company's 18% purchase VAT tax used when importing supplier lines into bills. **TODO: the 18% rate is hardcoded** and should move to a company setting if Georgia's rate changes.

#### `_rs_pulled_line_vals(self, snap, purchase_vat_18, existing_line=None)` — line 623
- **Liveness:** Active — called here and from `account_move_buyer.py`.
- **Role:** Helper (value builder) · **Side effects:** Reads-only
- **Purpose:** Builds the `account.move.line` vals from a pulled rs.ge snapshot. If `drg_amount > 0` and the 18% tax exists, treats `full_amount` as VAT-inclusive (price = base, applies tax); otherwise imports untaxed with price = gross. The optional `existing_line` preserves name/qty when updating.

#### `_rs_auto_import_pulled_to_bill_lines(self)` — line 642
- **Liveness:** Active — called from `account_move_buyer.py` (3×).
- **Role:** Helper (CRUD writer) · **Side effects:** Writes-DB (creates lines) / logs warnings
- **Purpose:** Materializes pulled rs.ge supplier-line snapshots into real bill lines in one `write`. Lines that needed the 18% VAT but couldn't find it are imported untaxed and logged by name so a user can fix the tax config. The convenience path that turns a downloaded supplier e-invoice into a posted-ready vendor bill.

#### `_rs_refresh_pulled_lines(self, service, raise_on_failure=False)` — line 674
- **Liveness:** Active — called here and from `account_move_buyer.py`.
- **Role:** SOAP-call (line pull) Helper · **Side effects:** Calls-rs.ge-API / Writes-DB (replaces snapshot lines) / Raises-to-user only when `raise_on_failure=True`
- **Purpose:** Pulls rs.ge line rows (`get_invoice_desc`) and stores them as read-only snapshots (type `rs_pulled`) for comparison. By default swallows fetch failures (logs a warning) so a routine refresh doesn't blow up; callers that must guarantee data before accepting a bill pass `raise_on_failure=True`. Replaces the old snapshot set atomically.

#### `_rs_line_snapshot_vals(self, row)` — line 710
- **Liveness:** Active — called by `_rs_refresh_pulled_lines`.
- **Role:** Helper (value builder) · **Side effects:** Reads-only
- **Purpose:** Single place that maps a raw rs.ge desc row into snapshot field values. Shared so the correction and pull paths build snapshots identically.

#### `_rs_extract_inv_id(self, result)` — line 721
- **Liveness:** Active — called from `account_move_seller.py:118`.
- **Role:** Helper (SOAP result parser) · **Side effects:** Reads-only
- **Purpose:** Pulls the new invoice ID (`invois_id`) out of a save result, returning it only when the save succeeded and the ID is positive. Centralizes the "did rs.ge really create it" check.

#### `_rs_extract_k_id(self, result)` — line 729
- **Liveness:** Active — called from `account_move_seller.py:758`.
- **Role:** Helper (SOAP result parser) · **Side effects:** Reads-only
- **Purpose:** Extracts the correction ID (`k_id`) from a result, returning it only when positive. Mirror of `_rs_extract_inv_id` for the correction-creation path.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/account_move_view_data.py`

**File role:** Tiny `account.move` layer exposing a single action-button: "view the current rs.ge data". No business logic itself — it builds a transient `rs.einvoice.view.wizard` from the move and opens it in a dialog.

### class AccountMove(models.Model) — `_inherit = 'account.move'`

#### `action_rs_view_current_data(self)` — line 10
- **Liveness:** Active — XML button in `account_move_view_data_views.xml`.
- **Role:** Action-button · **Side effects:** Raises-to-user (no rs.ge ID) / Returns-action (the rs.ge read happens inside `_build_from_move`)
- **Purpose:** Entry point for inspecting the live rs.ge state. Blocks early with a friendly error if the move has no `rs_einv_id`, else delegates to `rs.einvoice.view.wizard._build_from_move(self)` and opens it in a dialog. Gives a read-only "what does rs.ge say right now" view without touching the synced state.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/account_move_buyer.py`

**File role:** Buyer-side extension of `account.move`. Pulls incoming supplier invoices/corrections from rs.ge by their supplier-supplied ID, verifies seller/buyer identity against rs.ge TINs, lets the buyer accept or reject documents, imports supplier corrections by cancelling the old bill and reissuing a fresh draft (no credit note), and provides navigation/cleanup actions for replacement chains and orphaned/pending markers.

**Main flows it participates in:**
- **Pull + auto-import:** paste supplier rs.ge ID → `action_rs_buyer_pull` → identity/status checks → refresh pulled snapshot → auto-create bill lines.
- **Line re-sync:** `action_rs_buyer_reimport_lines` → merge (default) or force-replace draft lines.
- **Accept:** `action_rs_buyer_accept` → post → rs.ge accept → verify → auto-cancel when the accepted record was a supplier cancellation.
- **Reject:** `action_rs_buyer_reject` → `_rs_do_buyer_reject` → rs.ge reject → verify → auto-cancel once confirmed.
- **Supplier correction import (cancel-and-reissue):** `action_rs_import_supplier_correction` / `_rs_check_cancel_reissue_blockers` / `_rs_execute_cancel_and_reissue`.
- **Orphan / pending recovery:** `action_rs_resolve_orphan` / `_rs_do_resolve_orphan` / `action_rs_clear_pending`.
- **Replacement-chain navigation/cleanup.**

### class AccountMove(models.Model) — `_inherit = 'account.move'`

#### `action_rs_buyer_pull(self)` — line 25
- **Liveness:** Active — XML button; called by the buyer inbox wizard; `super()`-extended in `rs_base`.
- **Role:** Action-button + SOAP-call · **Side effects:** Calls-rs.ge-API / Writes-DB / Raises-to-user
- **Purpose:** Fetches metadata for the rs.ge invoice ID the supplier sent (pasted into `rs_einv_id`) and links it to this vendor bill. Runs a wall of safety checks first: buyer-side, not Skip, rs.ge status actionable (rejects drafts the supplier can still edit), corrections redirected to "Import Supplier Correction", and rs.ge seller/buyer un_ids must match the partner/company TINs so VAT is never booked against the wrong supplier. On success stores status/series/number, aligns `invoice_date` to the operation date when safe, seeds `k_type`, refreshes pulled lines, and auto-imports them if the draft is empty.

#### `action_rs_buyer_reimport_lines(self)` — line 219
- **Liveness:** Active — XML button.
- **Role:** Action-button + Helper-dispatcher · **Side effects:** Writes-DB / Raises-to-user
- **Purpose:** Re-syncs the draft's product lines with the latest rs.ge snapshot. By default merges (update matched, drop vanished, add new) via `_rs_merge_pulled_to_bill_lines`; with `rs_force_replace` in context it wipes and recreates. Guards buyer-side, draft state (Odoo forbids line edits on posted bills), and that pulled lines exist.

#### `_rs_pulled_match_key(text)` (staticmethod) — line 241
- **Liveness:** Active — used in `_rs_merge_pulled_to_bill_lines`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Produces a normalized (stripped, lowercased) key from a line description so a pulled snapshot row can be matched to an existing bill line by name during a merge.

#### `_rs_merge_pulled_to_bill_lines(self)` — line 246
- **Liveness:** Active — called by `action_rs_buyer_reimport_lines`.
- **Role:** Helper (line reconciliation) · **Side effects:** Writes-DB
- **Purpose:** Reconciles bill lines against the pulled snapshot keyed by name. Matched lines are updated while preserving operator metadata; lines no longer on rs.ge are removed and logged; snapshot rows with no match are added. The name-key merge exists so re-importing a supplier's correction doesn't blow away accountant edits on lines that still exist.

#### `action_rs_buyer_accept(self)` — line 300
- **Liveness:** Active — XML button.
- **Role:** Action-button + SOAP-call · **Side effects:** Calls-rs.ge-API / Writes-DB / Raises-to-user / commits / Sends-mail
- **Purpose:** Confirms an incoming pending invoice (1→2), correction (5→8), or supplier cancellation (6→7). Locks the row, refreshes status, posts the bill first if still draft (so VAT lands before acknowledgement), refreshes pulled lines for real accepts, then calls the accept API for the mapped target. After acknowledgement it commits and re-reads to verify the status moved. When the accepted record was a supplier cancellation (target 7), it auto-reverses the local bill; if that fails it stamps `rs_einv_reversal_pending_at` and escalates so the GL never silently diverges.

#### `_rs_check_cancel_reissue_blockers(self)` — line 417
- **Liveness:** Active — called by `_rs_execute_cancel_and_reissue` and the buyer inbox wizard.
- **Role:** Helper (validation) · **Side effects:** Reads-only
- **Purpose:** Returns a list of human-readable reasons the bill cannot be safely cancel-and-reissued (empty = safe). Refuses non-posted, non-`in_invoice`, paid/partially-paid (unreconcile first), bills with credit notes, bills on/before the lock date, and bills already pointing to a replacement. Shared by the executor and the preview wizard.

#### `_rs_execute_cancel_and_reissue(self, correction_rs_id)` — line 482
- **Liveness:** Active — called by `action_rs_import_supplier_correction` and the replace-preview wizard.
- **Role:** Helper (orchestration) + SOAP-call · **Side effects:** Calls-rs.ge-API / Writes-DB / Raises-to-user / Sends-mail
- **Purpose:** The core buyer-side cancel-and-reissue: verifies the rs.ge correction (numeric ID, status 5/8, `k_id` points back at this bill, TINs match), cancels the original bill, creates a new draft on a purchase journal dated to the correction's operation date, copies metadata, pulls and auto-imports the corrected lines, and cross-links original↔replacement (mode `fresh`) with chatter on both. If the correction is still pending (status 5) it warns and schedules a to-do to accept it. Replaces the original entirely rather than issuing a credit note, matching rs.ge's correction model.

#### `action_rs_import_supplier_correction(self)` — line 700
- **Liveness:** Active — XML button.
- **Role:** Action-button + SOAP-call + Returns-action · **Side effects:** Calls-rs.ge-API / Writes-DB / Raises-to-user / Returns-action
- **Purpose:** Entry point for importing a supplier's correction. Ensures buyer-side, finds the pending correction ID (refreshing once if absent), refuses if already linked to another move, and blocks foreign-currency bills (rs.ge correction amounts are GEL). Delegates to `_rs_execute_cancel_and_reissue`, clears the pending-correction marker, and opens the freshly created replacement bill.

#### `action_rs_buyer_reject(self)` — line 749
- **Liveness:** Active — XML button.
- **Role:** Action-button + SOAP-call (status refresh) + Returns-action · **Side effects:** Calls-rs.ge-API / Raises-to-user / Returns-action
- **Purpose:** Opens the rejection-reason wizard for a pending incoming document. Validates buyer-side, that an rs.ge ID is linked, refreshes status, and confirms it's still buyer-pending before returning the reject wizard. The actual rejection is performed later by `_rs_do_buyer_reject`.

#### `_rs_do_buyer_reject(self, reason)` — line 777
- **Liveness:** Active — called by the reject wizard.
- **Role:** Helper (wizard callback) + SOAP-call · **Side effects:** Calls-rs.ge-API / Writes-DB / Raises-to-user / commits / Sends-mail
- **Purpose:** Performs the actual rs.ge rejection once the wizard supplies a reason. Requires a non-empty reason, locks, re-checks rejectable, and refuses to reject a bill with reconciled payments (would drive AP negative). Calls the reject API, records the reason + provisional status, commits, then re-reads to verify the document left pending. Only when rs.ge confirms does it auto-cancel the local document; otherwise warns and leaves it for manual handling.

#### `action_rs_resolve_orphan(self)` — line 897
- **Liveness:** Active — XML button.
- **Role:** Action-button + Returns-action · **Side effects:** Writes-DB (clear-pending path) / Raises-to-user / Returns-action
- **Purpose:** Recovers from a timed-out request that may have left an unlinked ("orphan") rs.ge draft. If a pending marker exists and the document already has an rs.ge ID, it just clears the marker (the request actually succeeded). Otherwise opens the orphan-resolve wizard to supply the candidate ID to verify and link.

#### `_rs_do_resolve_orphan(self, candidate_id)` — line 923
- **Liveness:** Active — called by the orphan-resolve wizard.
- **Role:** Helper (wizard callback) + SOAP-call · **Side effects:** Calls-rs.ge-API / Writes-DB / Raises-to-user
- **Purpose:** Verifies a candidate orphan rs.ge ID before linking. Validates a positive integer not already linked elsewhere, reads the record, and confirms ownership by matching the rs.ge seller un_id to the company's own and the buyer un_id to the partner's TIN. Rejects vendor-side documents (this is the seller/customer-side orphan path; vendor records link through Pull). On clean verification writes ID/status/series/number and clears the pending marker.

#### `action_rs_clear_pending(self)` — line 1037
- **Liveness:** Active — XML button.
- **Role:** Action-button · **Side effects:** Writes-DB / Raises-to-user
- **Purpose:** Clears a pending marker without linking any record, for when the operator confirmed no rs.ge document was created. Locks the row and refuses to dismiss a marker younger than 5 minutes, because the original write could still be in flight and clearing early could let a retry create a duplicate. Logs the manual dismissal.

#### `action_rs_view_reversals(self)` — line 1066
- **Liveness:** Active — XML button.
- **Role:** Action-button + Returns-action · **Side effects:** Reads-only / Returns-action
- **Purpose:** Opens the reversal credit note(s) for this move — form for one, list for several. Navigation convenience, create disabled.

#### `action_rs_view_replacement(self)` — line 1085
- **Liveness:** Active — XML button.
- **Role:** Action-button + Returns-action · **Side effects:** Reads-only / Returns-action
- **Purpose:** Opens the replacement invoice (`rs_einv_replaced_by_id`) that supersedes this original; `False` if none. Lets the user jump down a cancel-and-reissue chain.

#### `action_rs_view_replaces(self)` — line 1099
- **Liveness:** Active — XML button.
- **Role:** Action-button + Returns-action · **Side effects:** Reads-only / Returns-action
- **Purpose:** Opens the original (`rs_einv_replaces_id`) that this replacement superseded; `False` if none. The inverse of `action_rs_view_replacement`.

#### `action_rs_clear_cancelled_replacement_link(self)` — line 1113
- **Liveness:** Active — XML button.
- **Role:** Action-button + Returns-action · **Side effects:** Writes-DB / Raises-to-user / Sends-mail / Returns-action (reload)
- **Purpose:** Unlinks a replacement chain, but only when the replacement was abandoned (state `cancel`). Refuses if the replacement still carries a live rs.ge ID so a real record is never orphaned. Clears the cross-links on both, logs/posts the change, and reloads. Frees an original to start a fresh cancel-and-reissue after a botched attempt.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/rs_replace_orchestrator.py`

**File role:** Orchestrates the two seller-side replacement flows on `account.move` — Cancel-and-Reissue (void the rs.ge invoice and clone a fresh draft) and Correct-and-Reissue (file a k_invoice correction chained on the original). Contains the shared preflight gate, a send-time guard, and the two flow entry points the correction wizard dispatches to. Relies on `_rs_cancel_core` and `_rs_assert_advance_correctable` (both in `account_move_seller.py`).

**Main flows it participates in:**
- Cancel-and-Reissue: preflight → refresh → `_rs_cancel_core` (real cancel) → clone fresh draft. Original auto-cancels locally on buyer confirm (status 7).
- Correct-and-Reissue: preflight → refresh → `_rs_assert_advance_correctable` → clone correction-mode draft. Original cancelled only on buyer acceptance (status 8).
- Send-time guard wired into the seller post/send path.
- Dispatched from the correction wizard.

### class AccountMove(models.Model)

#### `_rs_assert_replacement_cancel_accepted(self)` — line 12
- **Liveness:** Active — called in `account_move_seller.py:44`/`:939` and `account_move.py:1571`.
- **Role:** Helper (assertion guard in the post/send hook) · **Side effects:** Calls-rs.ge-API (via `original._rs_safe_refresh_status()`) / Raises-to-user
- **Purpose:** Blocks sending a Cancel-and-Reissue replacement until the original is cancelled on rs.ge AND the buyer confirmed it (status 7). Refreshes the original's status first. Without this, the replacement could go out while the cancellation is still pending, leaving two live invoices if the buyer rejects the cancel. Correction-mode replacements skip this — they are the correction.

#### `_rs_replace_preflight(self)` — line 46
- **Liveness:** Active — called by both flow methods (twice each, before and after a refresh).
- **Role:** Helper (precondition validator) · **Side effects:** Reads-only on local state / Raises-to-user
- **Purpose:** Single shared gate for either reissue flow. Enforces: seller-side `out_invoice`, posted, not Skip, already sent (`rs_einv_id` set), confirmed status (2 or 8), not an advance, not already replaced (distinct message when the prior replacement was cancelled). Also rejects legacy corrections and any in-flight blocker. Called twice in each flow — once before and once after a status refresh — so a stale local status can't slip a doomed reissue through.

#### `_rs_do_cancel_reissue(self)` — line 121
- **Liveness:** Active — dispatched from `rs_correction_wizard.py:265`.
- **Role:** Action (flow entry, via wizard) · **Side effects:** Writes-DB (creates replacement, sets links, commits) / Calls-rs.ge-API (`_rs_cancel_core`, refresh) / Raises-to-user / Returns-action
- **Purpose:** Runs Cancel-and-Reissue. Locks, preflights, refreshes, preflights again, then calls `_rs_cancel_core` to send a genuine cancellation (2/8 → 6 → 7) carrying no correction type — on rs.ge a cancellation and a k_invoice are distinct operations. Clones the original into a `fresh` replacement draft (today's dates, advance mode carried over), links them, commits, logs on both. The original is auto-cancelled locally only once the buyer confirms (status 7). Used when the invoice must be voided entirely (wrong buyer, duplicate, cancelled contract).

#### `_rs_do_correct_reissue(self, k_type=None)` — line 182
- **Liveness:** Active — dispatched from `rs_correction_wizard.py:263`.
- **Role:** Action (flow entry, via wizard) · **Side effects:** Writes-DB (creates correction-mode draft, sets links) / Calls-rs.ge-API (refresh, advance check) / Raises-to-user / Returns-action; no explicit commit
- **Purpose:** Runs Correct-and-Reissue. Locks, preflights, refreshes, preflights again, asserts the advance is correctable, validates `k_type` ∈ 1–4 (default '3'), and records whether the user set it. Clones the original into a `correction`-mode draft so the eventual send goes to rs.ge as a k_invoice correction chained on the original (one buyer acceptance). The original stays live while in flight and is cancelled only when accepted (status 8); on rejection it stays live and the draft can be edited and re-sent. Preferred over cancel-and-reissue for content errors.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/rs_replace_preview_wizard.py`

**File role:** A buyer-side batch preview/confirmation wizard for cancel-and-reissue driven by inbound rs.ge corrections. Shows one row per original-bill ⇄ rs.ge-correction pair and, on confirm, processes each row under its own savepoint so partial failures leave untouched bills unmodified. Per-bill work is delegated to `account_move_buyer._rs_execute_cancel_and_reissue`.

**Main flows it participates in:**
- Buyer-side Cancel-and-Reissue from rs.ge corrections: the buyer inbox wizard creates and opens this preview; the user reviews pairs and confirms.
- Result routing: opens one draft, a list of drafts, raises on all-fail, or shows a sticky partial-success notification then opens the succeeded drafts.

### class RsReplacePreview(models.TransientModel)

#### `_compute_line_count(self)` — line 30
- **Liveness:** Active — backs the `line_count` computed field rendered (invisible) in the form.
- **Role:** Compute (`@api.depends('line_ids')`) · **Side effects:** Reads-only
- **Purpose:** Computes `len(line_ids)` so the view/label can show the pair count without counting the one2many in the template.

#### `action_confirm(self)` — line 34
- **Liveness:** Active — XML `Confirm` button.
- **Role:** Action-button · **Side effects:** Writes-DB (via delegated method) / Calls-rs.ge-API / Raises-to-user (empty, or all-failed) / Returns-action / logs
- **Purpose:** Drives the batch. Refuses with no lines. Iterates each row (skipping rows missing the original or correction ID), running `_rs_execute_cancel_and_reissue` inside a per-row `cr.savepoint()` so one failing row rolls back only itself. Distinguishes `UserError` (recorded as-is) from unexpected exceptions (logged). Outcome routing: all-fail raises listing every reason; all-success opens the drafts; mixed returns a sticky warning listing failures with `next` opening the successful drafts. The savepoint-per-row design lets a large batch survive partial failures.

#### `_open_drafts_action(self, moves)` — line 131
- **Liveness:** Active — called within `action_confirm`.
- **Role:** Helper (action builder) · **Side effects:** Reads-only / Returns-action
- **Purpose:** Builds the window action landing the user on the resulting draft(s): close when empty, single form for one, else `list,form` filtered to the new drafts (create disabled). Centralizes the navigation for both the all-success and mixed paths.

> `RsReplacePreviewLine` (the per-pair row model) declares only fields — no methods.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/rs_correction_wizard.py`

**File role:** The transient wizards that drive the rs.ge correction flow. The primary class extends Odoo's standard Add Credit Note wizard (`account.move.reversal`) so the operator picks an rs.ge "treatment" (Odoo-only skip / cancel-and-reissue / correct-and-reissue) and a legal reason at credit-note creation time; the other two are small confirm-only wizards (orphan resolver, buyer rejection) that call back into `account.move`.

**Main flows it participates in:**
- Customer-side correction: choosing how a credit note interacts with rs.ge and routing the two reversal buttons.
- Orphan resolution: linking an rs.ge draft created by a timed-out call to its move.
- Buyer rejection: capturing a reason and sending it to the supplier.

### class AccountMoveReversal(models.TransientModel) — `_inherit = 'account.move.reversal'`

#### `default_get(self, fields_list)` — line 61
- **Liveness:** Active — framework hook (called when the wizard opens).
- **Role:** Override / Default · **Side effects:** Reads-only
- **Purpose:** Pre-selects a sensible RS Treatment. If exactly one selected move is a live, non-skipped customer invoice, defaults to `correct_reissue`; if any other live rs.ge move(s) are present, defaults to `skip`. Saves a manual choice and steers single-invoice corrections toward the preferred path.

#### `_compute_rs_einv_needs_k_type(self)` — line 77
- **Liveness:** Active — compute for `rs_einv_needs_k_type`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** True when at least one source move has a live (non-skipped) rs.ge record. The view uses it to decide whether the reason picker is shown/required.

#### `_compute_rs_einv_flow_preview(self)` — line 85
- **Liveness:** Active — compute for `rs_einv_flow_preview`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Builds a plain-language preview string of exactly what will happen on rs.ge for the chosen treatment. Each flow has materially different buyer-approval consequences, so the wizard spells out the outcome inline before the operator commits.

#### `_prepare_default_reversal(self, move)` — line 129
- **Liveness:** Active — override of standard `_prepare_default_reversal`.
- **Role:** Override / Helper · **Side effects:** Reads-only (returns vals)
- **Purpose:** When treatment is `skip`, stamps the new credit note as rs.ge-skipped and clears any k_type so the reversal is Odoo-only and never filed. For non-skip flows it leaves standard behavior untouched.

#### `refund_moves(self)` — line 146
- **Liveness:** Active — override; the "Reverse" button.
- **Role:** Override / Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API (status refresh) / Raises-to-user / Returns-action
- **Purpose:** Handles the plain "Reverse" button (exactly one credit note). Refuses reissue-shaped treatments (would silently discard the replacement invoice), blocks reversing a move that already has a replacement-flow link, requires a skip reason for skip flows, and — unless a context flag bypasses — refreshes each move's status and asserts it can legally be reversed before delegating to super. Guards against acting on a stale cached status.

#### `modify_moves(self)` — line 221
- **Liveness:** Active — override; the "Reverse and Create Invoice" button.
- **Role:** Override / Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API (downstream) / Raises-to-user / Returns-action
- **Purpose:** The only correct entry point for the two reissue-shaped flows (CN + new invoice). Rejects non-reissue treatments, enforces single-move/single-rs-invoice scope, refuses supplier-side documents. Routes: `correct_reissue` → `move._rs_do_correct_reissue(k_type=...)` (reason required); `replace` → `move._rs_do_cancel_reissue()`. Falls through to standard `modify_moves` if no rs.ge-tracked move is involved.

### class RsOrphanResolveWizard(models.TransientModel) — `_name = 'rs.einvoice.orphan.resolve.wizard'`

#### `action_confirm(self)` — line 285
- **Liveness:** Active — wizard button.
- **Role:** Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API (verification in callback) / Raises-to-user / Returns-action
- **Purpose:** Takes the rs.ge ID the operator pasted from the rs.ge web UI and calls `move._rs_do_resolve_orphan(candidate_id)` to verify party/direction and link the orphaned draft. Recovers from calls that timed out after rs.ge created the draft but before Odoo recorded its ID.

### class RsRejectWizard(models.TransientModel) — `_name = 'rs.einvoice.reject.wizard'`

#### `action_confirm(self)` — line 308
- **Liveness:** Active — wizard button.
- **Role:** Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API (`_rs_do_buyer_reject`) / Raises-to-user / Returns-action
- **Purpose:** Validates the rejection reason against a 480-char cap (rs.ge silently truncates longer text) and calls `move._rs_do_buyer_reject(reason)` to send the rejection. The length guard ensures the supplier gets a complete, actionable reason on the first attempt.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/rs_einvoice_view_wizard.py`

**File role:** The read-only "view current rs.ge data" wizard and its line model. Built on demand from a live rs.ge SOAP fetch (`_build_from_move`) so the operator can compare what rs.ge holds (header, goods, advances, waybills, VAT totals) against the Odoo invoice. All fields readonly.

### class RsEinvoiceViewWizard(models.TransientModel) — `_name = 'rs.einvoice.view.wizard'`

#### `_build_from_move(self, move)` — line 40
- **Liveness:** Active — called from `account_move_view_data.py:17`.
- **Role:** SOAP-call / CRUD (factory) · **Side effects:** Calls-rs.ge-API (multiple reads) / Writes-DB (creates the transient record)
- **Purpose:** The wizard's constructor-from-live-data. Fetches the rs.ge header, resolves seller/buyer parties, builds goods/advance/waybill line commands, then creates and returns a populated transient record. Computes net VAT (goods VAT minus attached-advance VAT) split into charge vs reduce totals, formats numbers, and picks the buyer- or seller-side sequence per direction. Shows rs.ge's authoritative current state, not Odoo's cached copy.

#### `_date_str(value)` (staticmethod) — line 88
- **Liveness:** Active — called by the build helpers.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Normalizes a date/datetime (or string) from rs.ge into a display string. Centralizes the inconsistent date shapes the SOAP layer returns.

#### `_safe_party(service, un_id)` (staticmethod) — line 97
- **Liveness:** Active — called twice by `_build_from_move`.
- **Role:** SOAP-call / Helper · **Side effects:** Calls-rs.ge-API (`get_party_from_un_id`), swallows exceptions
- **Purpose:** Resolves a party's TIN/name from an un_id, returning empty for a missing id and a stub if the lookup raises, so a failed party lookup never aborts the whole view.

#### `_build_goods(self, move, service, inv_id)` — line 105
- **Liveness:** Active — called by `_build_from_move`.
- **Role:** SOAP-call / Helper · **Side effects:** Calls-rs.ge-API (`get_invoice_desc`)
- **Purpose:** Fetches rs.ge goods rows and converts each into a `goods` view-line command, classifying taxation (standard/zero-rated/exempt) from the VAT amount and summing standard VAT. Returns the commands plus total VAT for the net-VAT calculation.

#### `_build_advances(self, move, service, inv_id)` — line 138
- **Liveness:** Active — called by `_build_from_move`.
- **Role:** SOAP-call / Helper · **Side effects:** Calls-rs.ge-API (`get_attached_advance_invoices`), swallows exceptions
- **Purpose:** Fetches attached advance invoices and builds `advance` view-line commands, returning commands plus total advance VAT (subtracted from goods VAT for the net figure). Returns empty on any SOAP error.

#### `_build_waybills(self, move, service, inv_id)` — line 161
- **Liveness:** Active — called by `_build_from_move`.
- **Role:** SOAP-call / Helper · **Side effects:** Calls-rs.ge-API (`get_invoice_waybills`), swallows exceptions
- **Purpose:** Fetches waybills linked to this rs.ge invoice and builds `waybill` view-line commands. Returns empty on any SOAP error. Lets the operator see rs.ge's waybill associations without leaving the form.

> `RsEinvoiceViewLine` declares only fields (the single line table backing the wizard's goods/waybill/advance views) — no methods.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/rs_einvoice_models.py`

**File role:** Supporting persistent models plus one `account.move.line` extension: the per-line sync-state computation shown in the line grid, the advance-settlement audit table, the per-document RS log, and the correction-history models. Two methods are the implementations behind the log/snapshot vacuum cron.

### class AccountMoveLine(models.Model) — `_inherit = 'account.move.line'`

#### `_compute_rs_sync_state(self)` — line 45
- **Liveness:** Active — compute for `rs_synced`/`rs_sync_state`, rendered in the line grid and the OWL widget.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Derives each product line's rs.ge sync state from the parent move's fields (skipped / not-sent / pending-edit / cancelled / superseded / confirmed / synced), including the native-advance-attach partial/error case for DP lines. Also sets `rs_synced` (True only for synced/confirmed). Drives per-line colour coding and badges so the operator sees at a glance which lines rs.ge still holds versus those edited after sync.

> `RsEinvoiceAdvanceSettlement` (audit of each advance-VAT attachment) and `RsEinvoiceCorrection` (correction-history header) declare only fields — no methods.

### class RsEinvoiceLog(models.Model) — `_name = 'rs.einvoice.log'`

#### `_cron_vacuum(self, retain_days=90, retain_errors_days=365)` — line 147
- **Liveness:** Active — invoked by the cron shim `_cron_vacuum_rs_logs` (target of the Vacuum Logs cron).
- **Role:** Cron (implementation) / CRUD · **Side effects:** Writes-DB (unlinks rows) / logs
- **Purpose:** Trims old RS log rows: INFO/WARNING older than `retain_days` (90) are deleted, ERROR kept longer (`retain_errors_days`, 365) to preserve audit context. Keeps the per-document log table bounded while protecting error history.

### class RsEinvoiceCorrectionLine(models.Model) — `_name = 'rs.einvoice.correction.line'`

#### `_compute_company_id(self)` — line 227
- **Liveness:** Active — compute for the stored `company_id`.
- **Role:** Compute · **Side effects:** Reads-only (stored compute)
- **Purpose:** Resolves the snapshot's company from either its parent correction's move (wizard flow) or its directly-linked move (buyer-pull flow). Stored and indexed so multi-company record rules and filtering work on snapshot rows regardless of parent.

#### `_cron_vacuum_snapshots(self, retain_pulled_days=180, retain_correction_days=730)` — line 240
- **Liveness:** Active — invoked by the cron shim `_cron_vacuum_rs_logs`.
- **Role:** Cron (implementation) / CRUD · **Side effects:** Writes-DB (unlinks rows) / logs
- **Purpose:** Trims old snapshots with two tiers: buyer-pulled cache rows (`rs_pulled`) dropped after 180 days (they're just cached copies of rs.ge source lines), while before/after correction audit snapshots are kept far longer (730). Keeps the snapshot table bounded without discarding the audit trail prematurely.

## `custom_addons/gec_rs_invoice/rs_einvoice/models/rs_buyer_inbox_wizard.py`

**File role:** Implements the buyer-side rs.ge inbox: a transient wizard (`rs.einvoice.inbox.wizard`) + its line model that lets an operator search rs.ge for incoming supplier invoices/corrections over a date range, review each, and bulk-import them as draft vendor bills via the standard Pull flow. It also hosts an `AbstractModel` (`rs.einvoice.cron`) carrying **every scheduled job** for the buyer-invoice integration — kept off `account.move` so `ir.cron` can target a dedicated model.

**Main flows it participates in:**
- **Manual buyer inbox:** open wizard → `action_search` (SOAP `get_buyer_invoices`) → `action_import_selected` → per-line `_do_import` → `action_rs_buyer_pull`; posted-original corrections route to the cancel-and-reissue preview.
- **Automated buyer sync (cron):** `_cron_sync_buyer_invoices` → `_sync_one_user` (SOAP `get_user_invoices`).
- **Status maintenance & safety crons:** refresh buyer/seller status, escalate stale pending actions, detect stuck sends/cancels, recover stranded status-7 reversals, vacuum logs.

### module-level functions

#### `_parse_dt_aware(raw)` — line 32
- **Liveness:** Active — called in `action_search`, `_sync_one_user`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Parses an rs.ge timestamp into a `datetime`, preserving timezone when present (normalizes trailing `Z`, tries `fromisoformat`/`strptime` fallbacks). Keeping tzinfo here lets callers choose naive-UTC vs local-calendar-day conversion, avoiding off-by-one calendar-day bugs.

#### `_to_naive_utc(dt)` — line 65
- **Liveness:** Active — called in `action_search`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Converts a tz-aware datetime to naive UTC (passes naive through) so it's safe to store in an Odoo `Datetime` field. Feeds `operation_dt`.

#### `_to_local_date(dt)` — line 74
- **Liveness:** Active — called in `action_search`, `_sync_one_user`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns the calendar date of the local wall-clock moment. Used to derive the supplier's local operation day (Tbilisi) as the imported bill's `invoice_date`, matching what rs.ge shows rather than a UTC-shifted day.

#### `_rs_row_get(row, key, default=None)` — line 96
- **Liveness:** Active — called 17× in-file.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Reads one logical field from a SOAP row by trying every known alias. Exists because rs.ge returns the same datum under inconsistent element names across endpoints, so callers can ask for a stable logical name like `seller_tin`.

#### `_rs_find_partner_by_tin(env, tin, company_id)` — line 105
- **Liveness:** Active — called in `action_search`, `_sync_one_user`.
- **Role:** Helper · **Side effects:** Reads-only (searches `res.partner` via sudo)
- **Purpose:** Resolves an rs.ge TIN to a single Odoo vendor, returning `(partner, ambiguous_partners)`. Prefers company-specific matches and accepts only when all candidates collapse to one commercial partner; if multiple distinct partners share the TIN it returns empty + the ambiguous set, forcing manual selection — because a TIN proves the legal entity but not which Odoo vendor record the bill should book against.

### class RsBuyerInboxWizard(models.TransientModel) — `rs.einvoice.inbox.wizard`

#### `_resolve_company_un_id(self, service)` — line 178
- **Liveness:** Active — called in `action_search`.
- **Role:** Helper · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Asks the SOAP service for the company's rs.ge un_id and raises a clear error pointing to credentials/Test-SOAP setup if it can't be resolved. A single friendly failure point before any expensive search.

#### `action_search(self)` — line 189
- **Liveness:** Active — XML button `action_search`.
- **Role:** Action-button (SOAP-call) · **Side effects:** Calls-rs.ge-API / Writes-DB (inbox lines) / Raises-to-user / Returns-action
- **Purpose:** The "Search" action. Validates the date range, authenticates, resolves the company un_id, then calls `get_buyer_invoices` over the chosen window (optionally filtered to action-required statuses). For each unique row it resolves the seller TIN to a vendor, checks whether a move with that `rs_einv_id` already exists, and builds a deduplicated set of inbox lines — pre-ticking not-yet-imported rows and flagging ambiguous-vendor rows. Re-opens the wizard so the operator sees the list.

#### `action_import_selected(self)` — line 284
- **Liveness:** Active — XML button `action_import_selected`.
- **Role:** Action-button · **Side effects:** Writes-DB (creates moves/preview wizard) / Calls-rs.ge-API (via `_do_import`) / Raises-to-user / Returns-action
- **Purpose:** The "Import Selected" action. Requires a purchase journal, then splits ticked rows: (1) corrections whose parent original bill is posted, cleared by the blocker check, and in status 5/8 → routed to the cancel-and-reissue preview; (2) everything else → imported directly via `_do_import`. Returns the preview wizard if any correction needs confirmation, else a notification listing per-row failures, else opens the created bill(s). Safely separates plain pulls from the destructive auto-cancel-and-reissue path, which must be previewed.

### class RsBuyerInboxLine(models.TransientModel) — `rs.einvoice.inbox.line`

#### `_do_import(self, Move, purchase_journal)` — line 469
- **Liveness:** Active — called by `action_import_selected`.
- **Role:** Helper (per-row import worker); SOAP-call · **Side effects:** Writes-DB (creates bill, sets chain links, chatter) / Calls-rs.ge-API (via `action_rs_buyer_pull`) / Raises-to-user is caught and returned as a note. Returns `(note, move_or_False)`.
- **Purpose:** Imports one inbox row into a draft vendor bill and runs Pull. Short-circuits already-imported/unmatched rows. For correction rows it requires the parent original in an acceptable state (cancelled → proceed; draft → refuse; posted → refuse with guidance). Creates an `in_invoice` inside a savepoint, sets `rs_einv_id`, calls Pull, and converts any error into a human-readable note rather than aborting the batch. For a fresh replacement of a cancelled original it wires the chain links (mode `fresh`) and posts a chatter link. Isolates one row's failure so the rest still import.

### class AccountMoveRsCron(models.AbstractModel) — `rs.einvoice.cron`

The cron entry-point host for buyer-invoice sync, on its own model so `ir.cron` can target it without touching `account.move`.

#### `_cron_sync_buyer_invoices(self, lookback_hours=72)` — line 623
- **Liveness:** Active — cron target in `data/ir_cron.xml`.
- **Role:** Cron · **Side effects:** Reads-only at this level (delegates writes) / logs
- **Purpose:** Top-level autosync. Clamps lookback to 1–72h (rs.ge's 3-day max), finds the single active RS-responsible user with credentials, and runs `_sync_one_user` in that user's env so credentials resolve. Logs and returns 0 (rather than raising) if misconfigured, so a bad config never wedges the scheduler.

#### `_sync_one_user(self, start_dt, end_dt)` — line 661
- **Liveness:** Active — called by `_cron_sync_buyer_invoices`.
- **Role:** Helper (per-user worker); SOAP-call · **Side effects:** Calls-rs.ge-API (`get_user_invoices`) / Writes-DB (creates drafts, Pull) / advisory transaction lock / logs
- **Purpose:** The actual buyer-sync worker. Auth-prechecks, resolves un_id, calls `get_user_invoices`, requires a purchase journal. Takes a per-company advisory lock so overlapping cron runs don't double-import. Filters to this buyer's un_id and importable statuses, skips draft/sent corrections and already-imported ids, resolves the seller TIN — skipping ambiguous/unmatched vendors with an info log (use the manual inbox for those). Surviving rows are created as `in_invoice` inside per-row savepoints and pulled, with per-row error isolation.

#### `_cron_escalate_pending_actions(self, age_hours=24)` — line 788
- **Liveness:** Active — cron target.
- **Role:** Cron · **Side effects:** Writes-DB (escalation stamp) / Sends-mail (chatter) / logs
- **Purpose:** Nudges moves with a pending-action marker older than `age_hours` by logging a warning and posting a chatter line to use "Resolve Orphan." Skips records already escalated within ~24h so the same stuck record isn't re-spammed. Stops an operator forgetting an orphaned draft left after a SOAP timeout.

#### `_cron_detect_stuck_sends(self, age_days=7)` — line 841
- **Liveness:** Active — cron target.
- **Role:** Cron · **Side effects:** Reads-only at this level (delegates) / Returns count
- **Purpose:** Flags seller-side documents stalled awaiting buyer action: status 1/5 (sent/correction-sent) and separately status 6 (cancel-sent, awaiting confirmation) past `age_days`, with tailored messages for each, run through `_escalate_stuck_moves`. The status-6 branch matters because the bill stays live in AR/VAT until the buyer confirms the cancellation.

#### `_escalate_stuck_moves(self, moves, re_escalate_cutoff, now, *, label, doc_label, build_messages, age_days)` — line 900
- **Liveness:** Active — called twice by `_cron_detect_stuck_sends`.
- **Role:** Helper (shared escalation engine) · **Side effects:** Writes-DB (escalation stamp) / Sends-mail / logs
- **Purpose:** Generic re-escalation loop shared by the stuck-send and stuck-cancel branches. For each move not escalated since `re_escalate_cutoff`, calls the caller-supplied `build_messages(move)`, writes the log warning, posts chatter, stamps the timestamp. Extracted to avoid duplicating the dedup/post logic across the two cases.

#### `_cron_refresh_status(self, is_buyer_side, batch_size=200)` — line 928
- **Liveness:** Active — called by the buyer/seller refresh entry points.
- **Role:** Cron worker (SOAP-call) · **Side effects:** Calls-rs.ge-API / Writes-DB (status, downstream reversals) / per-row locks / incremental commit / logs
- **Purpose:** Shared status-refresh worker, parameterized by side. Selects posted moves with an `rs_einv_id` in statuses 1/2/5/6/7/8 (not skipped), oldest-write first, capped at `batch_size`. Per move it takes `try_lock_for_update` and *skips* (never blocks) moves an operator is editing, re-reads under the lock, and calls `_rs_safe_refresh_status` in a savepoint. Exists because supplier-side actions flip rs.ge status silently; without it Odoo holds a stale value. Status 6 drives the 6→7 auto-reversal of local AP/AR+VAT; status 7 re-drives a reversal stranded by an interrupted accept/cancel tail (auto-cancel is idempotent). Commits per row so a long batch survives a worker restart.

#### `_cron_refresh_buyer_status(self, batch_size=200)` — line 1007
- **Liveness:** Active — cron target.
- **Role:** Cron · **Side effects:** Delegates to `_cron_refresh_status` (Calls-rs.ge-API / Writes-DB)
- **Purpose:** Thin entry point running `_cron_refresh_status(True, …)` for buyer-side bills. Gives `ir.cron` a zero-arg-style callable while sharing the worker.

#### `_cron_refresh_seller_status(self, batch_size=200)` — line 1011
- **Liveness:** Active — cron target.
- **Role:** Cron · **Side effects:** Delegates to `_cron_refresh_status`.
- **Purpose:** Mirror entry point running `_cron_refresh_status(False, …)` for seller-side invoices.

#### `_cron_rs_recover_stranded_cancellations(self, batch_size=200)` — line 1015
- **Liveness:** Active — cron target.
- **Role:** Cron · **Side effects:** Writes-DB (local cancel/reversal, pending flags) / per-row locks / incremental commit / logs. Makes NO rs.ge call.
- **Purpose:** Completes interrupted local reversals. Finds posted moves durably at status 7 (buyer-confirmed cancellation) that credit notes do not fully reverse (`payment_state != 'reversed'`) and with no pending-reversal flag, and re-drives `_rs_auto_cancel_after_rs_cancellation` purely locally — status 7 is already authoritative, so no SOAP is needed and it's safe even while refresh crons are off. A move it can't cancel (e.g. locked period) gets flagged and skipped next run, so it doesn't re-schedule a manual activity every cycle.

#### `_cron_vacuum_rs_logs(self)` — line 1081
- **Liveness:** Active — cron target ("RS E-Invoice: Vacuum Logs").
- **Role:** Cron (delegating shim) · **Side effects:** Writes-DB (deletes stale logs and snapshots via delegated models)
- **Purpose:** Thin shim so the vacuum cron can target this single model: delegates to `rs.einvoice.log._cron_vacuum` and `rs.einvoice.correction.line._cron_vacuum_snapshots`, summing their counts. Consolidates two cleanup jobs under one scheduled entry.

---

# Section C — `rs_base`: credentials, waybill bridge, wizards

`rs_base` is the shared base that sits **on top of** `gec_rs_invoice`. It holds the per-user rs.ge credentials, adds the waybill↔invoice bridge by extending the e-invoice actions via `super()`, and provides the invoice-from-waybill wizard.

## `custom_addons/rs_base/rs_base_methods/models/res_users.py`

**File role:** Per-user rs.ge credential store and the two authentication stacks. Holds the shared service username/password plus REST token/device-pairing fields, and provides both the stateless SOAP credential getter/test (ntosservice @ revenue.mof.ge) and the stateful REST bearer-token flow with optional SMS 2FA (eapi.rs.ge). Also exposes a generic authenticated REST call helper that downstream integrations reuse.

**Main flows it participates in:**
- SOAP auth: `_get_rs_credentials` feeds the e-invoice/waybill SOAP services; `action_rs_test_credentials` validates creds and fetches the SOAP user id.
- REST auth: `_rs_rest_authenticate` / `_get_rs_rest_token` produce a cached bearer token, with `_rs_rest_authenticate_step1` + `_rs_rest_complete_pin` covering the 2FA pairing path; `action_rs_test_rest_credentials` opens the PIN wizard.
- REST calls: `_rs_rest_authenticated_call` is the canonical authenticated POST with auto re-auth + transient backoff.
- Credential hygiene: `write` invalidates the cached token/device on cred change; constraints enforce a single RS-responsible user; sign-out clears the token cache.

### class ResUsers(models.Model) — `_inherit = 'res.users'`

#### `SELF_READABLE_FIELDS` (property) — line 94
- **Liveness:** Active — framework property override (Odoo reads it for self-service field access).
- **Role:** Override · **Side effects:** Reads-only
- **Purpose:** Extends the set of fields a non-admin may read on their own record to include the rs.ge credential/status fields. Without this, users couldn't see their own RS preferences. Token/device-code stay excluded (system-group only).

#### `SELF_WRITEABLE_FIELDS` (property) — line 101
- **Liveness:** Active — framework property override.
- **Role:** Override · **Side effects:** Reads-only
- **Purpose:** Lets a non-admin write their own `rs_username` and `rs_password` from Preferences. Only the two editable credentials are writable; tokens/ids/responsible flag stay admin-managed.

#### `write(self, vals)` — line 104
- **Liveness:** Active — `super()` override + ORM CRUD hook.
- **Role:** Override / CRUD · **Side effects:** Writes-DB
- **Purpose:** When the RS username/password changes, forcibly clears the cached REST token, expiry, SOAP user id, and the paired device code/date (using `setdefault` so an explicit value in the same write wins). Stale credentials must invalidate the cached token and device pairing, else the user keeps authenticating with the old identity.

#### `_check_single_rs_responsible(self)` — line 116
- **Liveness:** Active — `@api.constrains('rs_is_responsible', 'active')`.
- **Role:** Constraint · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Guarantees at most one active user carries the `rs_is_responsible` flag (the single owner crons run as). Prevents ambiguity over which user owns automated operations.

#### `_get_rs_credentials(self)` — line 135
- **Liveness:** Active — called by the SOAP services in sibling modules (`rs_soap_service.py` via `getattr`, `rs_waybill_soap_service.py`).
- **Role:** Helper · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Returns the SOAP credential dict (`su`, `sp`, `user_id`), raising a fix-it error pointing to Preferences if a credential is missing. The single source of truth both SOAP wrappers pull from — its presence is the signal that `rs_base_methods` is installed.

#### `action_rs_test_credentials(self)` — line 153
- **Liveness:** Active — XML button.
- **Role:** Action-button / SOAP-call · **Side effects:** Writes-DB / Calls-rs.ge-API / Raises-to-user / Returns-action
- **Purpose:** Validates SOAP credentials by calling `chek`; raises if zeep is missing, creds blank, endpoint unreachable, or auth fails. On success stores the returned `user_id` and returns a success notification with a soft reload. The "Test SOAP" button.

#### `_rs_rest_token_is_fresh(self)` — line 205
- **Liveness:** Active — called by `_rs_rest_authenticate`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** True only if a cached token exists and its expiry is more than the 60s refresh buffer in the future. Lets `_rs_rest_authenticate` skip a network round-trip while avoiding a token that would expire mid-request.

#### `_rs_rest_call(self, path, payload)` — line 213
- **Liveness:** Active — called by the two auth-step methods.
- **Role:** SOAP-call (REST) / Helper · **Side effects:** Calls-rs.ge-API / Raises-to-user
- **Purpose:** Shared low-level **unauthenticated** POST for the REST auth endpoints. Posts JSON, raises on transport/non-JSON/`STATUS.ID != 0`, returns the `DATA` dict. Centralizes the auth-endpoint plumbing.

#### `_rs_rest_authenticate_step1(self)` — line 238
- **Liveness:** Active — called by `_rs_rest_authenticate` and `action_rs_test_rest_credentials`.
- **Role:** SOAP-call (REST) / Helper · **Side effects:** Calls-rs.ge-API / Raises-to-user
- **Purpose:** First leg of REST auth: POSTs to `/Users/Authenticate` with username/password and the remembered `DEVICE_CODE`. Returns `('access', token, expires_in)` when auth completes outright, or `('pin', pin_token, masked_mobile)` when an SMS PIN is required. Separating step 1 lets the silent and interactive callers branch on the 2FA outcome.

#### `_rs_rest_complete_pin(self, pin_token, pin)` — line 264
- **Liveness:** Active — called by the PIN wizard.
- **Role:** SOAP-call (REST) / Helper · **Side effects:** Writes-DB / Calls-rs.ge-API / Raises-to-user
- **Purpose:** Second leg of 2FA: generates a fresh `DEVICE_CODE` GUID, POSTs it with the PIN to `/Users/AuthenticatePin`, and on success persists the access token + expiry + device code + paired timestamp. Storing the device code is what lets future logins skip the SMS step.

#### `_rs_rest_authenticate(self, force=False)` — line 290
- **Liveness:** Active — called by `_get_rs_rest_token`, `_rs_rest_authenticated_call`, and externally by `employee_registry_rs`.
- **Role:** SOAP-call (REST) / Helper · **Side effects:** Writes-DB / Calls-rs.ge-API / Raises-to-user
- **Purpose:** Returns a valid bearer token: reuses the fresh cached one unless `force`, else runs step 1. On `access` caches token+expiry; on `pin` (device not paired/revoked) clears any stale device code and raises a guidance error telling the user to use the interactive test button — a non-interactive caller (cron/API) can't enter an SMS PIN.

#### `_get_rs_rest_token(self, force=False)` — line 326
- **Liveness:** Active — called by `_rs_rest_authenticated_call` and externally by `employee_registry_rs`.
- **Role:** Helper · **Side effects:** Writes-DB / Calls-rs.ge-API / Raises-to-user
- **Purpose:** Thin public wrapper around `_rs_rest_authenticate` returning a fresh bearer token. The named entry point downstream modules call rather than reaching into the private method.

#### `action_rs_test_rest_credentials(self)` — line 331
- **Liveness:** Active — XML button.
- **Role:** Action-button / SOAP-call (REST) · **Side effects:** Writes-DB / Calls-rs.ge-API / Returns-action
- **Purpose:** Interactive REST auth entry. Runs step 1; on `access` caches the token and returns a success notification. On `pin` resets any rejected device code and opens the `rs.auth.pin.wizard` so the user can enter the SMS PIN and pair the device. The only path that can complete 2FA.

#### `_rs_rest_format_status_error(self, path, status_id, status_text)` — line 383
- **Liveness:** Active — called twice in `_rs_rest_authenticated_call`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Builds a user-facing error string from an rs.ge `STATUS`, appending a Georgian hint for universally-meaningful codes (-1, -2, -104, -105). Endpoint-specific codes stay raw because their meaning shifts per method.

#### `_rs_rest_authenticated_call(self, path, payload)` — line 397
- **Liveness:** Active — called by `_rs_rest_get_transaction_result`; the canonical baseline for downstream integrations.
- **Role:** SOAP-call (REST) / Helper · **Side effects:** Writes-DB (token rotation) / Calls-rs.ge-API / Raises-to-user
- **Purpose:** The general-purpose authenticated REST POST. Attaches `Authorization: bearer <token>`, and on HTTP 401 / STATUS -104/-105 forces a single re-auth and retries; on HTTP 5xx / STATUS -1 retries up to 3× with (1s,3s,8s) backoff; any other non-zero status raises immediately. Returns `DATA`. Never logs the auth header/password. New integrations get token rotation and transient-failure handling for free.

#### `_rs_rest_signout(self)` — line 510
- **Liveness:** Active — called by `action_rs_signout_rest`.
- **Role:** Helper / SOAP-call (REST) · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** POSTs `/Users/SignOut` with the cached token, then clears the local token cache. Idempotent and never raises — even on transport/401 errors — so a failed sign-out can't lock the user out of re-logging in. Keeps the device pairing intact so future auths still skip SMS.

#### `action_rs_signout_rest(self)` — line 544
- **Liveness:** Active — XML button.
- **Role:** Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API / Raises-to-user / Returns-action
- **Purpose:** Admin-only "Sign out from REST" button. Raises unless the user is in `base.group_system`, then runs `_rs_rest_signout` and returns a success notification with a soft reload. The group check exists because this can sign out *other* users' tokens.

#### `_rs_rest_get_transaction_result(self, transaction_id)` — line 566
- **Liveness:** **Dead-unused (in-tree).** Exposed idempotency helper for downstream modules; grep finds only its definition and constant — no in-repo consumer yet. Not dead from a removed caller; effectively unused pending a consumer.
- **Role:** SOAP-call (REST) / Helper · **Side effects:** Calls-rs.ge-API / Raises-to-user
- **Purpose:** Wraps `/Common/GetTransactionResult` to look up the outcome of a prior transaction (typically yielding `INVOICE_ID`). Raises on non-zero status — including rs.ge's -7 ("transaction in progress") which a caller may choose to retry. Provided so REST integrations can implement idempotent retries.

## `custom_addons/rs_base/rs_base_methods/models/account_move.py`

**File role:** rs_base's `account.move` extension. Layers waybill-link awareness on top of the e-invoice actions from `gec_rs_invoice`: carries One2many bridge rows (`rs.einvoice.waybill.link`), blocks sending an invoice whose waybill links aren't synced, and adds a "Goods Returned" k_type suggestion when a correction's original carried waybills. Every action method here is a thin `super()` wrapper that runs the e-invoice flow first, then injects waybill-link side effects.

**Main flows it participates in:**
- Seller invoice create/edit → after rs.ge accepts, push pending waybill links via SOAP.
- Send guard → refuse `action_rs_send` while any link is unsynced.
- Status refresh / delete → re-read or reset link sync state.
- Cancel-and-reissue → recreate the original's links on the replacement.
- Goods-returned correction → suggest k_type "4".
- Buyer (vendor bill) side → read rs.ge's attached waybills and create local link rows.

### class AccountMove(models.Model) — `_inherit = 'account.move'`

#### `_check_waybill_links_unique_active(self)` — line 37
- **Liveness:** Active — `@api.constrains` hook.
- **Role:** Constraint · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Enforces that a given rs.ge waybill is attached to at most one non-cancelled invoice. When an invoice is reactivated out of `cancel`, searches for other active invoices already holding the same waybills and raises listing the conflicts. Stops two live invoices claiming the same waybill on rs.ge.

#### `_compute_rs_einv_waybill_summary(self)` — line 65
- **Liveness:** Active — compute for `rs_einv_waybill_count`/`_has_links`/`_sync_state`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Rolls child link rows up into a per-invoice summary: count, has-links boolean, and a worst-case sync state (error > draft > synced > none). Drives the smart-button badge and state-dependent UI.

#### `_rs_sync_waybill_links(self, service)` — line 79
- **Liveness:** Active — called by `_rs_create_invoice` and `action_rs_edit`.
- **Role:** SOAP-call / Helper · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** Pushes each unsynced/dirty bridge row to rs.ge. For each link it deletes any stale remote row, calls `save_invoice_waybill_link`, then re-reads and **requires the just-saved waybill number to appear** before flipping the link to `synced`; otherwise marks `error` and forces re-sync. The verify-after-save loop exists because rs.ge's save can succeed silently while the link fails to attach.

#### `_rs_refresh_waybill_links(self, service)` — line 178
- **Liveness:** Active — called by `action_rs_refresh_status` and the carry-to-replacement helper.
- **Role:** SOAP-call / Helper · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** Re-reads remote waybill rows and reconciles: still-present `rs_remote_id`s stay synced; otherwise re-match by waybill number to an unclaimed remote row; previously-synced links no longer found are demoted to `draft` with their remote id cleared. Keeps local state honest after out-of-band changes.

#### `_rs_create_invoice(self, service)` — line 230
- **Liveness:** Active — `super()` override of `gec_rs_invoice._rs_create_invoice`.
- **Role:** Override · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** Runs the base create flow, then if the invoice now has an rs.ge id and waybill links, pushes them via `_rs_sync_waybill_links`. The hook that attaches waybills immediately after the invoice is created.

#### `action_rs_edit(self)` — line 236
- **Liveness:** Active — `super()` override of base `action_rs_edit`.
- **Role:** Override / Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API / Returns-action
- **Purpose:** After the base edit pushes invoice changes, re-syncs each record's waybill links so linkage edits propagate. Iterates the recordset (not `ensure_one`).

#### `action_rs_send(self)` — line 243
- **Liveness:** Active — `super()` override of base `action_rs_send`.
- **Role:** Override / Action-button · **Side effects:** Reads-only (guard) / Raises-to-user
- **Purpose:** Pre-send guard: refuses to send if any waybill link isn't `synced`, telling the user to click "Update on RS" first. Prevents an invoice being declared on rs.ge while its waybill attachments are pending. Only blocks; the send is delegated to `super()`.

#### `unlink(self)` — line 256
- **Liveness:** Active — `super()` override + ORM CRUD hook.
- **Role:** Override / CRUD · **Side effects:** Writes-DB
- **Purpose:** Deletes with `rs_skip_remote_detach=True` in context so the base unlink doesn't attempt a remote detach of waybill links during deletion. Avoids an unnecessary/failing rs.ge call when the record is going away anyway.

#### `action_rs_delete(self)` — line 259
- **Liveness:** Active — `super()` override of base `action_rs_delete`.
- **Role:** Override / Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** After the base deletes the invoice on rs.ge, resets each surviving link back to `draft` (remote id/timestamp/message cleared). Keeps links ready to re-attach if the invoice is recreated, since deleting the invoice on rs.ge also drops its remote links.

#### `action_rs_refresh_status(self)` — line 271
- **Liveness:** Active — `super()` override of base `action_rs_refresh_status`.
- **Role:** Override / Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** After the base refreshes the invoice status, re-reads and reconciles waybill links via `_rs_refresh_waybill_links` for each record with an rs.ge id and links. Keeps the waybill summary in step on every manual refresh.

#### `_rs_carry_waybill_links_to_replacement(self)` — line 278
- **Liveness:** Active — called by `_rs_auto_cancel_after_rs_cancellation`.
- **Role:** Helper · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** In a cancel-and-reissue flow, the replacement is a copy (and `copy=False` drops links), so this recreates the original's links on the replacement, skipping waybills it already has. Runs post-cancel so the unique-active constraint is satisfied. Refreshes the new links if the replacement already has an rs.ge id.

#### `_rs_auto_cancel_after_rs_cancellation(self, event_message=None)` — line 301
- **Liveness:** Active — `super()` override of base `_rs_auto_cancel_after_rs_cancellation`.
- **Role:** Override · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** After the base auto-cancels this invoice in response to an rs.ge cancellation, if the move is now `cancel` and has a reissue replacement, carries the waybill links over. Keeps waybill linkage attached across a cancel-and-reissue.

#### `_rs_suggest_k_type_from_external(self)` — line 309
- **Liveness:** Active — `super()` override of the base hook.
- **Role:** Override / Helper · **Side effects:** Reads-only
- **Purpose:** Adds a fallback to the base k_type suggestion. If the base returns nothing and the corrected original (reversed entry, replaced original, or self) had waybill links, suggests k_type `'4'` (Goods Returned). Lets the correction wizard pre-pick the right reason when goods are physically returned.

#### `action_open_rs_waybill_links(self)` — line 319
- **Liveness:** Active — XML smart button.
- **Role:** Action-button · **Side effects:** Returns-action
- **Purpose:** Opens this invoice's waybill links as a filtered list/form, with the current move pre-set. Lets the user inspect/manage the bridge rows from the invoice form.

#### `_rs_sync_buyer_waybill_links(self, service)` — line 335
- **Liveness:** Active — called by `action_rs_sync_buyer_waybills` and `action_rs_buyer_pull`.
- **Role:** SOAP-call / Helper · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** For a vendor bill, reads the waybills rs.ge has attached to the invoice and creates local link rows for matching buyer-direction `rs.waybill` records (by waybill number, optionally narrowed by seller TIN). Idempotent; missing local waybills are silently ignored (buyer-side waybill sync is a separate job). Lets a pulled vendor bill show which waybills the supplier attached.

#### `action_rs_sync_buyer_waybills(self)` — line 409
- **Liveness:** Active — XML button.
- **Role:** Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API / Raises-to-user
- **Purpose:** Manual "Sync Waybills" button on vendor bills. Validates it's a pulled vendor bill, then runs `_rs_sync_buyer_waybill_links`; logs a no-op if nothing new. The user-facing trigger for buyer-side waybill discovery.

#### `action_rs_buyer_pull(self)` — line 424
- **Liveness:** Active — `super()` override of base `action_rs_buyer_pull`.
- **Role:** Override / Action-button · **Side effects:** Writes-DB / Calls-rs.ge-API
- **Purpose:** After the base pulls vendor bills, automatically runs buyer waybill-link sync for each `in_invoice` that now has an rs.ge id. Folds waybill discovery into the standard pull so links appear without a separate click.

## `custom_addons/rs_base/rs_base_methods/models/rs_waybill.py`

**File role:** Extends the `rs.waybill` model (defined in `gec_rs_waybill`) to wire waybills into the e-invoice bridge. Adds the invoice-link relation, the invoice-lock state, mutation guards that block changing a waybill while it sits on a live invoice, and the multi-select entry point that opens the "Create RS Invoice from Waybills" wizard. Also kills the legacy waybill-service invoice path so all invoicing flows through `account.move`.

**Main flows it participates in:**
- Invoice-from-waybill: validate selected waybills → resolve buyer → open the wizard.
- Invoice lock: compute whether a waybill is held by a non-cancelled invoice; block refuse/edit/submit-edit/delete while locked.
- Smart-count of invoices attached to a waybill.
- Hard-disable of the old `action_save_invoice` flow.

### class RsWaybill(models.Model) — `_inherit = 'rs.waybill'`

#### `_compute_rs_invoice_count(self)` — line 27
- **Liveness:** Active — compute for `rs_invoice_count`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Counts the distinct invoices attached through `rs_invoice_link_ids.move_id`. Backs a smart-button display.

#### `_compute_is_locked_by_invoice(self)` — line 32
- **Liveness:** Active — compute for stored `is_locked_by_invoice`/`locked_by_move_id`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Determines whether the waybill is held by a live invoice: if the waybill isn't cancelled, takes the first linked non-cancelled `move_id` as the holder. The core of the mutation-lock — a true value means the waybill can't be re-used on another invoice, nor cancelled/edited/deleted.

#### `_compute_is_invoiced(self)` — line 44
- **Liveness:** Active — override of the base compute for `is_invoiced` (stored).
- **Role:** Override (Compute) · **Side effects:** Reads-only
- **Purpose:** Redefines "invoiced" for the new bridge: invoiced if linked to any non-cancelled `account.move`, OR (legacy) `rs_invoice_id` is set. Without this, the base compute wouldn't know about the link model, so bridged waybills would show as not invoiced.

#### `action_view_rs_invoices(self)` — line 51
- **Liveness:** **Dead-unused** — no caller and no `name="action_view_rs_invoices"` button anywhere; only the definition. A smart-button handler never hooked into a view.
- **Role:** Action-button (intended) · **Side effects:** Returns-action
- **Purpose:** Would open a list/form of the invoices attached to this waybill. Harmless but currently unreachable.

#### `_rs_assert_not_invoice_linked(self)` — line 67
- **Liveness:** Active — called by the four mutation actions below.
- **Role:** Helper (guard) · **Side effects:** Raises-to-user
- **Purpose:** The shared mutation guard. Filters `self` for `is_locked_by_invoice` waybills and, if any are locked, raises listing each and the holding invoice. Exists because rs.ge rejects mutating a waybill attached to a live invoice — the user must first detach by correcting the invoice.

#### `action_refuse_waybill(self)` — line 82
- **Liveness:** Active — overrides the base action; wired to view buttons and called from `stock_picking.py`.
- **Role:** Override (Action-button) · **Side effects:** Raises-to-user (on lock), else delegates
- **Purpose:** Guards the "refuse/cancel waybill" action: blocks it when invoice-linked, then defers to base. Prevents cancelling a waybill out from under a live invoice.

#### `action_edit_waybill(self)` — line 86
- **Liveness:** Active — overrides base; view button.
- **Role:** Override (Action-button) · **Side effects:** Raises-to-user (on lock), else delegates
- **Purpose:** Guards opening the waybill edit popup so a locked waybill can't be put into edit mode.

#### `action_submit_edit_to_rs(self)` — line 90
- **Liveness:** Active — overrides base (which does the `save_waybill` SOAP call); view button.
- **Role:** Override (Action-button) · **Side effects:** Raises-to-user (on lock), else delegates (Calls-rs.ge-API)
- **Purpose:** Guards the action that submits an edited waybill to rs.ge. Blocks for an invoice-linked waybill, since the remote edit would conflict with the attached invoice.

#### `action_delete_waybill(self)` — line 94
- **Liveness:** Active — overrides base; view button and called from `stock_picking.py`.
- **Role:** Override (Action-button) · **Side effects:** Raises-to-user (on lock), else delegates
- **Purpose:** Guards deletion: an invoice-linked waybill can't be deleted until detached.

#### `_validate_waybills_for_invoicing(self)` — line 102
- **Liveness:** Active — called by `action_open_invoice_from_waybill_wizard`.
- **Role:** Helper (validation) · **Side effects:** Raises-to-user
- **Purpose:** Pre-flight before opening the invoice wizard from a multi-selection. Rejects templates, non-seller-direction, not Active/Completed, not synced (`rs_internal_id`), missing waybill number/buyer TIN, already-locked, and legacy `rs_invoice_id` waybills (unless override context). Enforces single-company, single buyer-TIN, single sale-order grouping with detailed messages. Ensures the wizard only receives a clean, coherent batch.

#### `_resolve_waybill_partner(self)` — line 189
- **Liveness:** Active — called by `action_open_invoice_from_waybill_wizard`.
- **Role:** Helper · **Side effects:** Raises-to-user
- **Purpose:** Resolves the single buyer partner for the selected waybills. Prefers an explicit `buyer_id`; else searches partners by `company_registry`/`vat` equal to the buyer TIN, preferring a unique commercial partner. Raises if no match or ambiguous. Provides the wizard's `default_partner_id`.

#### `action_open_invoice_from_waybill_wizard(self)` — line 228
- **Liveness:** Active — invoked from the "Create RS Invoice" list-binding server action.
- **Role:** Action-button · **Side effects:** Raises-to-user (via validation) / Returns-action
- **Purpose:** The multi-select entry point. Validates the selection, resolves the buyer, then opens `rs.invoice.from.waybill.wizard` with the partner, selected waybills, and `default_is_standalone=True`. The supported way to invoice waybills through the bridge.

#### `action_save_invoice(self)` — line 244
- **Liveness:** Active (a deliberate **kill-switch**) — overrides the base method, which is still bound to a view button; when `rs_base_methods` is installed, pressing it hits this override.
- **Role:** Override (Action-button) · **Side effects:** Raises-to-user (always)
- **Purpose:** Hard-disables the legacy waybill-service invoice flow. The old action wrote `rs_invoice_id` directly and bypassed the `account.move` + e-invoice bridge, so this unconditionally raises and directs the user to the bridge-backed "Create RS Invoice" actions.

## `custom_addons/rs_base/rs_base_methods/models/rs_einvoice_waybill_link.py`

**File role:** Defines `rs.einvoice.waybill.link`, the join model connecting one `account.move` to one or more `rs.waybill` records, tracking the per-link remote sync state. Enforces the integrity rules around linkage: one waybill per active invoice, partner/direction/TIN consistency, concurrency locking, and the drift guards that prevent silently mutating/deleting a row whose remote rs.ge counterpart still exists. The data backbone of the mutation-lock that `rs_waybill.py` reads via `is_locked_by_invoice`.

### `_BigInteger(fields.Integer)` — line 30
- **Liveness:** Active — used as the field type of `rs_remote_id`.
- **Role:** Helper (custom field class) · **Side effects:** Reads-only (schema)
- **Purpose:** A `fields.Integer` subclass mapping to PostgreSQL bigint. rs.ge returns row IDs above the 32-bit signed range (~4.4 billion observed) which would overflow a plain Integer column.

### class RsEinvoiceWaybillLink(models.Model) — `rs.einvoice.waybill.link`

#### `create(self, vals_list)` — line 83
- **Liveness:** Active — `@api.model_create_multi`.
- **Role:** Override (CRUD) · **Side effects:** Writes-DB / Raises-to-user / row locks
- **Purpose:** Guards link creation. Unless in `rs_auto_sync` context, refuses links on vendor bills (owned by the Sync Waybills flow, not manual entry). Row-locks the target waybills (NOWAIT) before delegating to super, closing the race where two concurrent creates both pass the duplicate check.

#### `_lock_waybills(self, waybill_ids)` — line 98
- **Liveness:** Active — `@api.model`; called by `create` and `write`.
- **Role:** Helper (concurrency) · **Side effects:** Writes-DB (FOR UPDATE NOWAIT locks) / Raises-to-user
- **Purpose:** Acquires row-level locks on the `rs_waybill` rows so a concurrent create/write can't slip past the single-active-invoice check. NOWAIT fails fast with a friendly "another user is attaching this waybill" message instead of blocking.

#### `_check_waybill_not_on_another_invoice(self)` — line 119
- **Liveness:** Active — `@api.constrains('move_id', 'waybill_id')`.
- **Role:** Constraint · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Enforces that a waybill is attached to at most one non-cancelled invoice. Searches for other links of the same waybills on non-cancelled moves; if any belong to a different move, raises listing the conflicts. The DB-level half of the mutation-lock.

#### `_check_partner_and_type(self)` — line 151
- **Liveness:** Active — `@api.constrains('move_id', 'waybill_id')`.
- **Role:** Constraint · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** Enforces consistency between move and waybill. Customer invoices require seller-direction waybills (matched against the waybill's buyer TIN); vendor bills require buyer-direction waybills (against the seller TIN); other move types rejected. Also rejects attaching to a `rs_einv_skip` document, a direction mismatch, or a TIN mismatch. Prevents wiring a waybill to the wrong document or counterparty.

#### `_is_remote_protected(self)` — line 191
- **Liveness:** Active — called in `write` and `unlink`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** True when the link is fully synced to rs.ge (`sync_state == 'synced'`, `rs_remote_id` exists, move has an `rs_einv_id`). "Remote protected" rows have a real counterpart on rs.ge, so must not be silently mutated/deleted; gates the drift guards.

#### `_detach_remote(self)` — line 199
- **Liveness:** Active — called by `unlink`.
- **Role:** SOAP-call (wrapper) · **Side effects:** Calls-rs.ge-API / Raises-to-user / logs
- **Purpose:** Best-effort removal of the link's row on rs.ge before local deletion. Returns True if nothing to do; otherwise calls `delete_invoice_waybill_link` (underneath, rs.ge `delete_ntos_invoices_inv_nos`). On failure logs and re-raises so the user knows the remote detach failed.

#### `write(self, vals)` — line 224
- **Liveness:** Active — ORM write hook.
- **Role:** Override (CRUD) · **Side effects:** Writes-DB / Raises-to-user / may lock rows
- **Purpose:** Guards link edits. Unless in `rs_auto_sync`, blocks any manual write on a vendor-bill link. Enforces the drift guard: if any affected link is remote-protected and the write touches `waybill_id`/`move_id`, raises — you can't repoint a synced link without first detaching from rs.ge or cancelling the invoice. Row-locks the waybill before delegating if `waybill_id` is being set.

#### `unlink(self)` — line 242
- **Liveness:** Active — ORM unlink hook.
- **Role:** Override (CRUD) · **Side effects:** Writes-DB / Calls-rs.ge-API (via `_detach_remote`) / Raises-to-user
- **Purpose:** Guards link deletion. With `rs_skip_remote_detach` context deletes immediately (escape hatch for sync/correction internals). Otherwise blocks removing vendor-bill links manually, and blocks removing a link unless the move is a not-yet-sent correction draft (`rs_einv_replaces_id` set, `rs_einv_id` empty) — i.e. waybills can only be detached on a correction draft, not a live invoice. For remote-protected links calls `_detach_remote()` first. The deletion arm of the mutation-lock.

## `custom_addons/rs_base/rs_base_methods/models/rs_soap_service.py`

**File role:** Extends `rs.soap.service` with the three waybill-to-invoice link SOAP operations of rs.ge's `NtosService` (`ntos_invoices_inv_nos`): save, read, delete the waybill references attached to an e-invoice. Reuses transport/credentials/retry helpers from `rs_einvoice`'s SOAP service and adds robust DataTable/envelope parsing because rs.ge returns the read result in a non-standard `NewDataSet` shape that breaks zeep. (These ops are documented in `rs_invoice_api_docs.md` §6, not `waybill_api.md` — they belong to the e-invoice NtosService surface, linking existing waybills to existing invoices.)

### `_normalize_row(row)` (module-level) — line 21
- **Liveness:** Active — called by `_iter_datatable_rows`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Collapses one DataTable row (dict, zeep object, or subscriptable) into a dict with canonical lowercase keys (`id, inv_id, overhead_no, overhead_dt`). Guarantees downstream code sees one stable shape despite rs.ge/zeep casing inconsistency.

### `_iter_datatable_rows(result)` (module-level) — line 48
- **Liveness:** Active — called by `get_invoice_waybill_links`.
- **Role:** Helper (generator) · **Side effects:** Reads-only
- **Purpose:** Yields canonicalized row dicts from whatever zeep hands back for `get_ntos_invoices_inv_nos` (an object with `.rows`, a `.Tables[0]`/`.NewDataSet` wrapper, or a plain list). Absorbs the variability in how zeep exposes the embedded DataTable.

### class RsSoapService(models.AbstractModel) — `_inherit = 'rs.soap.service'`

#### `save_invoice_waybill_link(self, inv_id, overhead_no, overhead_dt)` — line 81
- **Liveness:** Active — called from `account_move.py:128`.
- **Role:** SOAP-call (wrapper) · **Side effects:** Calls-rs.ge-API / Raises-to-user / logs
- **Purpose:** Wraps rs.ge `save_ntos_invoices_inv_nos` (§6). Attaches a waybill reference (overhead number + date) to an existing invoice; returns bool. Per the API note, this only links — it does not auto-add the waybill's products to the invoice. Converts zeep faults into a readable error.

#### `get_invoice_waybill_links(self, inv_id)` — line 106
- **Liveness:** Active — called from `account_move.py:99,187,349`.
- **Role:** SOAP-call (wrapper) · **Side effects:** Calls-rs.ge-API / Raises-to-user (on fault) / logs
- **Purpose:** Wraps rs.ge `get_ntos_invoices_inv_nos` (§6). Returns the list of attached waybill references as dicts. Because rs.ge wraps the DataTable in a `NewDataSet` root zeep can't deserialize, it attaches a `HistoryPlugin` and, if the typed call raises a non-fault exception, falls back to parsing the raw envelope via `_parse_ntos_invoices_inv_nos_envelope`. Always removes the plugin in `finally`.

#### `_parse_ntos_invoices_inv_nos_envelope(envelope)` (staticmethod) — line 153
- **Liveness:** Active — called by `get_invoice_waybill_links`.
- **Role:** Helper (XML parser / SOAP fallback) · **Side effects:** Reads-only
- **Purpose:** Parses row dicts directly out of the raw SOAP envelope when zeep binding fails. Walks for every `DocumentElement`, treats each direct child as a row, lowercases each leaf tag into a key so the output matches the canonical names. The resilience layer for rs.ge's non-standard response.

#### `delete_invoice_waybill_link(self, remote_id, inv_id)` — line 194
- **Liveness:** Active — called from `rs_einvoice_waybill_link.py:208` (`_detach_remote`) and `account_move.py:121`.
- **Role:** SOAP-call (wrapper) · **Side effects:** Calls-rs.ge-API / Raises-to-user / logs
- **Purpose:** Wraps rs.ge `delete_ntos_invoices_inv_nos` (§6). Removes a waybill attachment row from an invoice by its rs.ge row id + invoice id; returns bool. The remote half of the link `unlink`/detach flow.

## `custom_addons/rs_base/rs_base_methods/models/sale_order.py`

**File role:** A small `sale.order` extension adding the sale-order-side entry point for invoicing delivered waybills through the bridge. Collects the order's invoiceable seller waybills and opens the same `rs.invoice.from.waybill.wizard`, pre-seeded with the order's partner and the order itself.

### class SaleOrder(models.Model) — `_inherit = 'sale.order'`

#### `_invoiceable_rs_waybills(self)` — line 10
- **Liveness:** Active — called by `action_open_rs_invoice_from_waybill_wizard`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Filters the order's related waybills down to those eligible for invoicing: seller-direction, not a template, status Active/Completed, synced, has a waybill number, not already locked by an invoice. Centralizes the eligibility rule so both button availability and wizard seeding agree.

#### `action_open_rs_invoice_from_waybill_wizard(self)` — line 21
- **Liveness:** Active — wired to a sale-order view button.
- **Role:** Action-button · **Side effects:** Raises-to-user / Returns-action
- **Purpose:** The SO-side entry point. Requires the order confirmed, at least one invoiceable seller waybill, and a partner VAT/Tax ID (needed for rs.ge); else raises a clear error. Opens `rs.invoice.from.waybill.wizard` seeded with `default_partner_id`, `default_seed_sale_order_id`, and `default_waybill_ids`.

## `custom_addons/rs_base/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py`

**File role:** Transient wizard that turns one or more rs.ge "seller" waybills into a single `account.move` (customer invoice). Maps each waybill good to an invoice line, resolves the partner/seller and matching sale-order context, builds the invoice values (reusing native Odoo SO/down-payment builders), and links the result back to every source waybill. Two entry modes: SO-seeded (from a sale order) and "standalone" (from the waybill list, aggregating lines and skipping SO-context preflight).

**Main flows it participates in:**
- Opened from a sale order or from the waybill list (standalone).
- User selects waybills → onchange rebuilds candidate lines → each line auto-matches an SO line → preflight validates → invoice created and linked.
- Down-payment settlement: reuses the seed/common SO's native DP deduction so rs.ge advance settlement and SO bookkeeping match a normal Regular invoice.

### class RsInvoiceFromWaybillWizard(models.TransientModel)

#### `_is_purchase(self)` — line 77
- **Liveness:** Active — called by every direction helper.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** True when `move_type == 'in_invoice'`. The single source of truth for the sale-vs-purchase branch, so internal helpers stay direction-agnostic for a future vendor-bill flow (only `out_invoice` is wired today).

#### `_waybill_direction(self)` — line 80
- **Liveness:** **Dead-unused** — no caller; reserved scaffolding for the future vendor-bill flow.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Would return `'buyer'`/`'seller'`. Currently the seller direction is hard-coded in the `waybill_ids` domain instead.

#### `_waybill_tin_field(self)` — line 83
- **Liveness:** Active — called by `_validate_preflight`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns the waybill field holding the counterparty TIN (`buyer_tin` for sales, `seller_tin` for purchases), so preflight can verify each waybill's TIN matches the partner regardless of direction.

#### `_journal_type(self)` — line 86
- **Liveness:** Active — called by `_validate_preflight`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns the expected journal type (`'sale'`/`'purchase'`) so preflight can reject a wrong-type journal.

#### `_product_default_taxes(self, product)` — line 89
- **Liveness:** Active — called from the line model's `_compute_unit_price`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Returns `product.taxes_id` (sales) or `supplier_taxes_id` (purchase). Lets an unmatched line default to the correct direction-appropriate taxes.

#### `_resolve_currency(self)` — line 93
- **Liveness:** Active — called by `_prepare_invoice_vals` when no seed SO exists.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Picks the invoice currency from the partner's pricelist (sales) or purchase currency, falling back to company currency. Only needed for the standalone/no-SO path.

#### `_order_line_model(self)` — line 101
- **Liveness:** **Dead-unused** — never called; reserved scaffolding (line model hard-codes `sale.order.line`).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Would return `'purchase.order.line'`/`'sale.order.line'` to let matching pick the right model per direction.

#### `_default_journal(self)` — line 108
- **Liveness:** Active — `default=` lambda for `journal_id`.
- **Role:** Default · **Side effects:** Reads-only
- **Purpose:** Picks the first journal of the correct type in the current company so the wizard opens with a sensible journal.

#### `default_get(self, fields_list)` — line 116
- **Liveness:** Active — framework override.
- **Role:** Override · **Side effects:** Reads-only
- **Purpose:** Seeds `is_standalone` from context and, when opened with `default_waybill_ids`, eagerly builds `line_ids` so the user sees candidate lines on first render rather than after an onchange.

#### `_build_line_commands(self, waybill_ids)` — line 133
- **Liveness:** Active — called by `default_get`.
- **Role:** Helper · **Side effects:** Reads-only (returns `Command.create` list)
- **Purpose:** Given waybill ids, returns one `Command.create` per waybill good that has a product, pre-filling product and quantity. Shared seed builder for the initial line set.

#### `_onchange_waybill_ids(self)` — line 152
- **Liveness:** Active — `@api.onchange('waybill_ids')`.
- **Role:** Onchange · **Side effects:** Reads-only (mutates in-memory lines)
- **Purpose:** Rebuilds `line_ids` when the user adds/removes a waybill, snapshotting user edits (qty, matched SO line, price, discount, taxes) keyed by (waybill, waybill-line) so they survive the rebuild. Critically returns early if the line set already matches the target — preventing the framework firing this onchange during initial load from wiping the `default_get`-seeded lines.

#### `_compute_common_sale_order(self)` — line 194
- **Liveness:** Active — `@api.depends('waybill_ids.sales_order_id')`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Sets `common_sale_order_id` when all waybills share exactly one SO (so it can be assigned to the invoice), and raises `has_mixed_sale_orders` when they span more than one.

#### `_compute_flags(self)` — line 201
- **Liveness:** Active — `@api.depends(...)`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Computes the three warning flags gating the confirmation checkboxes: any product line with no matched SO line (`has_unmatched`), any line over the SO line's remaining qty (`has_overdelivery`), any waybill with a legacy `rs_invoice_id` (`has_reused_waybill`).

#### `_validate_preflight(self)` — line 224
- **Liveness:** Active — called by `action_create_invoice`.
- **Role:** Constraint (validation helper) · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** The full gate before invoice creation. Verifies: partner VAT, lines exist, correct-type journal in current company, every waybill's TIN matches the partner, all waybills share one SO matching the seed, no legacy rs.ge invoice (unless override context), positive quantities, invoice date past the lock date, and — in SO-seeded mode — that unmatched/over-delivery confirmations are ticked. In standalone mode requires `_aggregate_invoice_lines` to net non-empty. Surfaces every blocking rule as one clear error.

#### `_prepare_line_vals(self, line)` — line 329
- **Liveness:** Active — called by `_prepare_invoice_vals` (non-standalone path).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Builds the `invoice_line_ids` dict for one wizard line. If a `sale.order.line` was matched it delegates to native `_prepare_invoice_line(quantity=...)` to inherit every standard field, then overrides price/discount/taxes/name only where the wizard line diverges. If unmatched, builds a minimal product/qty/price line. Keeps SO-linked lines fully native (so `qty_invoiced`/`invoice_status` update correctly) while still allowing standalone lines.

#### `_aggregate_invoice_lines(self)` — line 362
- **Liveness:** Active — called by `_validate_preflight` (non-empty check) and `_prepare_invoice_vals` (standalone path).
- **Role:** Helper · **Side effects:** Reads-only / Raises-to-user
- **Purpose:** The standalone-mode line builder. Groups wizard lines by (product, price, discount, uom, taxes, sale_line_id) and sums signed quantities — return waybills (`waybill_type == '5'`) contribute negative qty. Net-zero buckets dropped. `sale_line_id` is part of the key so lines tied to different SO lines stay separate; a single-SO-line bucket carries `sale_line_ids` so the SO sees the invoice. If any bucket nets negative (returns exceed deliveries) it raises and steers to a credit note, because a negative line can't be filed on rs.ge and would desync the SO.

#### `_prepare_invoice_vals(self)` — line 436
- **Liveness:** Active — called by `action_create_invoice`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Assembles the full `account.move` create dict. Chooses a seed SO (explicit seed → common SO → first distinct matched SO unless standalone) and starts from native `seed._prepare_invoice()` when available, else a minimal dict with resolved currency. Sets date, journal, merged narration, multi-SO `invoice_origin`, the invoice lines (aggregated in standalone, per-line otherwise), the `rs_einv_waybill_link_ids` back-links (source `'wizard'`, state `'draft'`), and appends native DP deduction commands when a single seed/common SO exists.

#### `_down_payment_deduction_commands(self, order)` — line 485
- **Liveness:** Active — called by `_prepare_invoice_vals`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Reproduces standard Odoo down-payment deduction (a DP section line plus negated DP lines with reversed tax data), reusing core builders. Exists so SO bookkeeping and rs.ge advance settlement behave exactly like a normally generated Regular invoice rather than a hand-built one.

#### `action_create_invoice(self)` — line 504
- **Liveness:** Active — XML button `action_create_invoice`.
- **Role:** Action-button · **Side effects:** Writes-DB / Raises-to-user (via preflight) / Returns-action
- **Purpose:** The wizard's submit. Runs preflight, builds vals, creates the `account.move`, then if there's a fiscal position re-maps product-line taxes through `fiscal_position_id.map_tax` (because lines were built before the fiscal position applied). Opens the new invoice in form view.

## `custom_addons/rs_base/rs_base_methods/wizards/rs_invoice_from_waybill_wizard_line.py`

**File role:** The line model for the invoice-from-waybill wizard — one row per waybill good. Each line auto-matches a `sale.order.line` for the same partner/product and derives its price, discount, taxes, remaining-to-invoice quantity, and a per-line warning from that match. All fields computed-but-editable so the operator can override.

### class RsInvoiceFromWaybillWizardLine(models.TransientModel)

#### `_compute_sale_line(self)` — line 57
- **Liveness:** Active — `@api.depends(...)` compute for `sale_line_id` (store, editable).
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Sets `sale_line_id` to the best-matching SO line. Calls `_rs_prefetch_sale_line_candidates` once for the whole recordset, then delegates per line to `_match_sale_line` — so matching does one search for the batch instead of one per line.

#### `_rs_prefetch_sale_line_candidates(self)` — line 62
- **Liveness:** Active — called by `_compute_sale_line`.
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** One `sale.order.line` search across all (partner, product) pairs, bucketed by (partner_id, product_id). Each bucket is what the per-line domain would return (confirmed orders, current company, `qty_to_invoice > 0`, real non-DP lines). A performance optimization avoiding per-line searches in the compute.

#### `_match_sale_line(self, candidate_pool=None)` — line 91
- **Liveness:** Active — called by `_compute_sale_line`; also supports a standalone path (own search if no pool).
- **Role:** Helper · **Side effects:** Reads-only
- **Purpose:** Resolves the single best SO line for one wizard line. Narrows candidates: prefer SO lines from the waybill's own sale order or the seed/common SO; if still ambiguous, prefer the SO whose pickings actually carry this waybill. Returns a match only when it can confidently narrow to one (else the lowest id), and returns `False` rather than guessing — because a naive match would silently pick the oldest matching SO line, possibly an unrelated past order.

#### `_compute_unit_price(self)` — line 149
- **Liveness:** Active — `@api.depends('sale_line_id', 'product_id')` compute for `unit_price`/`discount`/`tax_ids`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Derives price/discount/taxes. If matched, copies the SO line's. If only a product is set, defaults to list price, zero discount, and direction-appropriate default taxes. If neither, clears everything. Sensible editable defaults per line.

#### `_compute_warning(self)` — line 171
- **Liveness:** Active — `@api.depends(...)` compute for `warning`.
- **Role:** Compute · **Side effects:** Reads-only
- **Purpose:** Per-line UI warning: none if no product; an "unmatched — won't update qty_invoiced" note if no SO line matched; or an over-delivery note if qty exceeds the SO line's remaining. The row-level view of the wizard's `has_unmatched`/`has_overdelivery` flags.

## `custom_addons/rs_base/rs_base_methods/wizards/rs_auth_pin_wizard.py`

**File role:** A small transient wizard for rs.ge two-step (SMS PIN) authentication of the REST integration. Created by `res.users` code with a `pin_token`, the target user, and a masked phone number; collects the 4-digit SMS code and completes device pairing.

### class RsAuthPinWizard(models.TransientModel)

#### `action_confirm(self)` — line 30
- **Liveness:** Active — XML button `action_confirm`.
- **Role:** Action-button (REST-call) · **Side effects:** Calls-rs.ge-API / Writes-DB (token persisted by the called method) / Raises-to-user / Returns-action
- **Purpose:** Validates a PIN was entered, then calls `user_id._rs_rest_complete_pin(pin_token, pin)` to finish device pairing. On success returns a notification (RS will skip SMS for this device, with the token expiry) chained to a soft reload so the UI reflects the authenticated state.

## `custom_addons/rs_base/rs_base_methods/scripts/detect_invoice_id_drift.py`

**File role:** A standalone read-only maintenance script — NOT a model and NOT in `__manifest__.py`, so never loaded by the app. Run manually in an Odoo shell (`odoo-bin shell -d <db> < this_file`). Detects "INVOICE_ID drift": bridge-linked invoices whose stored Odoo `rs_einv_id` no longer matches the live rs.ge `INVOICE_ID` on the linked waybill. Reports only — changes nothing.

#### `_waybill_invoice_id(rs_internal)` — line 10
- **Liveness:** Active within the script (standalone tool, not wired into the app).
- **Role:** Script (helper) / SOAP-call · **Side effects:** Calls-rs.ge-API / Reads-only
- **Purpose:** Given a waybill's `rs_internal_id`, calls `wb_svc.get_full_waybill(...)` and returns the live rs.ge `INVOICE_ID` from the SOAP header. On any exception returns a short `'ERR:...'` string instead of raising, so one failed lookup doesn't abort the scan; returns `None` if the header isn't a dict.

#### Module-level body (lines 6–38) — no enclosing function
- **Liveness:** Active when piped into `odoo-bin shell`; manual/standalone.
- **Role:** Script · **Side effects:** Calls-rs.ge-API / Reads-only / prints
- **Purpose:** Resolves the admin user and a SOAP service, fetches all `rs.einvoice.waybill.link` records whose move has an `rs_einv_id`, de-duplicates by (move, waybill), and for each compares `move.rs_einv_id` against the live waybill `INVOICE_ID`. Mismatches are collected and printed, with a final "DONE (read-only — nothing changed)" line. Runs at import-time because the file is executed as shell input.

---

## Coverage

| Section | File | Callables |
|---|---|---:|
| A | `gec_rs_invoice` rs_soap_service.py (37) + rs_soap_service_view.py (2) | 39 |
| B | `gec_rs_invoice` account_move.py | 78 |
| B | `gec_rs_invoice` account_move_seller.py | 25 |
| B | `gec_rs_invoice` account_move_sync.py (14) + account_move_view_data.py (1) | 15 |
| B | `gec_rs_invoice` account_move_buyer.py | 17 |
| B | `gec_rs_invoice` rs_replace_orchestrator.py (4) + rs_replace_preview_wizard.py (3) | 7 |
| B | `gec_rs_invoice` rs_correction_wizard.py (8) + rs_einvoice_view_wizard.py (6) + rs_einvoice_models.py (4) | 18 |
| B | `gec_rs_invoice` rs_buyer_inbox_wizard.py | 19 |
| C | `rs_base` res_users.py | 18 |
| C | `rs_base` account_move.py (waybill bridge) | 17 |
| C | `rs_base` rs_waybill.py (13) + rs_einvoice_waybill_link.py (8) + rs_soap_service.py (4) + sale_order.py (2) | 27 |
| C | `rs_base` invoice-from-waybill wizard (19) + line (5) + PIN wizard (1) + drift script (2) | 27 |
| | **Total** | **307** |

> "Callables" counts methods plus module-level functions, properties, staticmethods, and the one shell-script body. Models that declare only fields (no callables) are noted inline and excluded: `RsEinvoiceViewLine`, `RsReplacePreviewLine`, `RsEinvoiceAdvanceSettlement`, `RsEinvoiceCorrection`.

*Built 2026-06-27 by reading every source file end-to-end and verifying call-sites/XML/cron wiring across `custom_addons`, `addons`, and `enterprise`.*

