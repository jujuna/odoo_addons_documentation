# rs.ge E-Invoice — Down Payments / Advances

How `rs_einvoice` and `rs_base_methods` (both in `custom_addons/gec_odoo_modules`) handle prepayment/advance VAT invoices and their settlement against the final delivery invoice on rs.ge.

> **Re-verified 2026-09-22** against the canonical `gec_odoo_modules` copy on Odoo 20. Paths and line refs were repointed (the file was written against the now-dead `gec_rs_invoice` / `rs_base` copies), and one claim was withdrawn — see *Mode selection* below.

> Down payments are **two layers**, not one: (1) issuing the advance VAT invoice, and (2) settling it when the goods are delivered. Settlement has **two mutually exclusive modes** with opposite VAT semantics on rs.ge. The mode is picked automatically at invoice creation — Native when the advance qualifies, Net otherwise.

---

## Layer 1 — The advance (prepayment) invoice

An advance invoice is filed on rs.ge through a different endpoint: `save_invoice_a` instead of `save_invoice`.

- The selector is the boolean `rs_einv_is_advance` ([account_move.py:138](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L138)). `_rs_pick_save_variant` maps it to the `'advance'` variant ([account_move.py:2000](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L2000)), and `save_invoice` routes `'advance'` → `save_invoice_a` ([rs_soap_service.py:259](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L259)).
- **Auto-detection at create** ([account_move.py:1305](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1305)): a customer invoice whose product lines are *all* `is_downpayment` is flagged `rs_einv_is_advance = True`. A credit note reversing an advance inherits the flag.
- `_rs_is_downpayment_invoice` ([account_move.py:1507](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1507)) = "every product line is a down-payment line". This is what distinguishes a *pure advance* (or its reversal) from a final invoice that merely carries offset rows.

### The down-payment offset credit note is kept off rs.ge
A standalone offset credit note (an `out_refund`, no `reversed_entry_id`, all DP lines) is force-skipped at create with reason `down_payment` ([account_move.py:1313](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1313)), and a constraint *forbids* un-ticking Skip on it ([account_move.py:1109](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1109)). Rationale in code: the advance VAT was already filed via the advance invoice, so the internal offset is Odoo-accounting-only.

---

## Layer 2 — Settlement of the advance on the final invoice

Field `rs_einv_advance_settlement_mode` ([account_move.py:142](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L142)), default `net`:

| Mode | What goes to rs.ge | VAT semantics |
|---|---|---|
| `net` | Delivery lines **reduced** by the advance, so rs.ge sees the net taxable amount only | The advance VAT never appears again on the final invoice |
| `native_attach` | **Full** delivery lines; the prior advance(s) are attached via rs.ge v3.0.5 advance API | rs.ge itself subtracts the attached advance VAT |

Both modes require the invoice to be **mixed** — regular delivery lines *and* negative `is_downpayment` offset rows (`_rs_has_downpayment_offset_lines`, [account_move.py:1525](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1525)). A pure advance is Layer 1, not settlement.

### Mode A — Net offset (default)
`_rs_lines_to_payload` ([account_move_sync.py:430](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L430)) spreads the total offset gross across the regular lines proportionally, scales each line's VAT by the same ratio, and pushes the residual cents onto the last line so the net total/VAT reconcile exactly.

Restrictions (both raise `UserError`):
- Net total after deduction must be **> 0** — offset cannot equal or exceed delivery ([account_move_sync.py:470](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L470)).
- Offset VAT must **not exceed** delivery VAT — net mode cannot reverse surplus advance VAT; the user is told to issue an advance correction or switch to native mode ([account_move_sync.py:477](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L477)).

### Mode B — Native rs.ge attach
The engine is `_rs_sync_native_advance_settlements` ([account_move_seller.py:490](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L490)), called automatically after every line sync on create/update/send ([account_move_seller.py:152](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L152), [:825](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L825), [:948](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L948)). It never raises; on failure it sets `rs_einv_advance_sync_state` to `partial`/`error` and **blocks Send-to-buyer** ([account_move_seller.py:951](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L951)).

How Odoo finds *which* rs.ge advance to attach: `_rs_expected_advance_settlements` ([account_move_seller.py:211](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L211)) walks each negative offset line → `sale_line_ids` → prior `invoice_lines` → the posted, same-company, same-partner advance invoice with `rs_einv_is_advance`. If the link is missing or ambiguous it raises and tells the user to use Net mode instead (no label-parsing fallback).

SOAP ops used ([rs_soap_service.py:470](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L470)+): `get_attachable_advance_invoices`, `get_attached_advance_invoices`, `attach_advance_invoice`, `update_advance_invoice`, `detach_advance_invoices`. Each attach/update is recorded in the audit model `rs.einvoice.advance.settlement` ([rs_einvoice_models.py:76](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_models.py#L76)).

Eligibility, checked at validate-time ([account_move.py:1018](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1018)) and in the engine via `_rs_check_native_advance_eligibility` ([account_move_seller.py:328](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L328)):
- Customer invoice only; not on the advance itself; must have both delivery and offset lines. When the offset lines are removed later, the invoice is simply sent in Net mode; Odoo refuses only if an advance is already attached on rs.ge.
- Each advance must be **buyer-confirmed** on rs.ge (`RS_ACCEPTED`).
- Each advance must be dated a **strictly earlier month** than the final invoice. Same-month is refused by rs.ge (it is covered by the final invoice itself) — use Net mode or a later date.
- Over-settle guard: attached advance VAT ≤ full delivery VAT ([account_move_seller.py:490](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L490)).
- Stray guard: if rs.ge has advances attached that Odoo doesn't expect (carried over from a corrected original, or attached on the portal), it raises — rs.ge refuses detaching a confirmed advance mid-correction ([account_move_seller.py:527](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L527)).
- `MIN_DRG_AMOUNT` floor: cannot drop settled VAT below the amount already consumed ([account_move_seller.py:565](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L565)).

### Mode is locked once filed
`write` guard ([account_move.py:1373](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1373)): the settlement mode can only change while Draft (status `0`). Native → Net is additionally blocked if any advance is already attached (status `200`) — detach or Delete on RS first.

---

## Mode selection — automatic, and the same on every path

`rs_einv_advance_settlement_mode` **defaults to `net`**, but `create()` immediately upgrades it to
`native_attach` when the invoice qualifies ([account_move.py:1316-1320](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1316)):
a customer invoice, not itself an advance, carrying down-payment offset lines, and passing
`_rs_native_advance_eligible()` ([account_move_seller.py:366](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L366)).

That helper is the whole decision. It returns False — leaving the invoice on Net — when:

- the advance cannot be traced from the offset line back to a posted advance invoice
  (`_rs_expected_advance_settlements` raises or finds nothing);
- **any advance is dated in the same month as, or later than, the final invoice**
  (`(adv.year, adv.month) >= (final.year, final.month)`), because rs.ge refuses a same-month attach;
- an advance is not buyer-confirmed on rs.ge (it re-checks the live status first).

An explicit `rs_einv_advance_settlement_mode` in the create values is respected and never overridden.

### The waybill wizard no longer forces Native — claim withdrawn 2026-09-22
An earlier version of this file said `rs.invoice.from.waybill.wizard` sets
`rs_einv_advance_settlement_mode = 'native_attach'`, and warned that the same economic invoice filed
different payloads depending on whether it was built by hand or by the wizard. **That is no longer
true**: `native_attach` does not appear anywhere in `rs_base_methods`. The wizard now only appends the
standard Odoo deduction (section + negated DP lines via core builders) and lets the create-time
auto-detection decide, exactly like a manual invoice — its own docstring says so
([rs_invoice_from_waybill_wizard.py:485-488](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L485)).
The waybill→SO-line matcher still excludes `is_downpayment` lines so a DP line is never treated as a
deliverable ([rs_invoice_from_waybill_wizard_line.py:83](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard_line.py#L83)).

## Corrections & reissue around advances

- **Advances can't be replaced** via Cancel-&-Reissue or Correct-&-Reissue ([rs_replace_orchestrator.py:87](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_replace_orchestrator.py#L87)). Reverse them with Add Credit Note (full-cancellation reason), then issue the new final invoice separately.
- `_rs_assert_advance_correctable` ([account_move_seller.py:458](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L458)) blocks correcting an advance that is **fully settled** (`AMOUNT_LEFT ≤ 0`) or whose corrected VAT would fall **below the already-settled amount**. rs.ge refuses both and returns no error text, so it fails fast before creating the correction draft ([rs_replace_orchestrator.py:211](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_replace_orchestrator.py#L211)).
- Correcting a *final* invoice that has advances attached: must keep Native mode + the offset lines so Odoo reconciles the carry-over, otherwise it raises ([account_move_seller.py:710](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L710)).

---

## Security / visibility

- `rs.einvoice.advance.settlement`: `account.group_account_invoice` gets `cru` — **no delete** — plus a company restriction row, both now in the single Odoo 20 file ([ir.access.csv:4-5](../custom_addons/gec_odoo_modules/rs_einvoice/security/ir.access.csv#L4)). `ir.model.access.csv` and `rs_einvoice_company_rules.xml` were merged into it on 2026-09-22.
- The Advance Settlement selector only shows for customer invoices that have offset lines; the audit tables and the "advance settlement is not clean" warning banner are in [account_move_views.xml](../custom_addons/gec_odoo_modules/rs_einvoice/views/account_move_views.xml).
- Read-only live viewer of attached advances: `_build_advances` ([rs_einvoice_view_wizard.py:138](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_view_wizard.py#L138)).

---

## VAT compliance — which mode is correct

Both modes produce the **correct VAT total**, but they are not equal in *form*:

- An advance creates a VAT event on receipt (Tax Code Art. 163 — tax point = date advance received). The final period's taxable base is the full supply minus the advance already taxed (GRS situational guide **N11125**).
- From **1 September 2025**, an electronic VAT invoice (Form III-05²) must **reference the advance invoice (field 9) and show the advance VAT offset against the final invoice** (MoF Order #996, Art. 53). This explicit reference-and-offset is what **Native attach** does; **Net** files no reference to the advance (the offset CN is force-skipped and native sync doesn't run).

Consequence: **Native is the compliance-aligned default post-1-Sep-2025.** Net is a totals-correct fallback that omits the formal linkage — acceptable mainly when Native is structurally impossible (same VAT period as the supply, advance not buyer-confirmed, or no SO link). Risk of Net where an earlier-period advance exists is a **formal invoicing defect (YELLOW)** — VAT total is right, so an Art. 275 understatement fine is unlikely; exposure is the Art. 291 catch-all and a GRS reissue request. (Field-9 exact behavior to be confirmed against the live Form III-05² spec.)

**Live check (2026-06-22, test DB `gec_modules2`):** A net-mode final (rs.ge ეა-86 / `354867487`) read back from rs.ge showed the **net** amount 189.74 (VAT 28.94) with an **empty attached-advance list** — confirming net mode files the reduced amount and creates no advance reference. Its paired advance (ავ-72 / `354867408`, VAT 14.26, buyer-confirmed) + the final summed to the full-deal VAT 43.20 — no double-count. Separately, an older same-month native_attach invoice (`352142885`) was found on rs.ge with the **full** amount and **no** advance attached → advance VAT double-counted; this is the dangerous native silent-fail mode when the attach can't happen (same-month), from before the eligibility guard existed. A cross-month test (S00078: advance ავ-72 / `354868924` dated May, buyer-confirmed; final ეა-86 / `354868977` dated June) was read back from rs.ge: **`get_attachable_advance_invoices` lists the May advance as attachable to the June period** — i.e. Native attach *would* succeed. It didn't attach only because the final was sent in **net** mode and the mode locks once on rs.ge (status ≠ draft). So Native is empirically viable for cross-month; the recurring blocker is purely the **net default + send-lock**, not the rs.ge mechanism. Same-month deposits net within one VAT period (GRS guide N11125), so Net is correct there; field-9 only matters cross-month. **End-to-end verified (2026-06-22, S00084):** advance ავ-72 / `354874466` (May, buyer-confirmed) → final ეა-86 / `354874493` (June) auto-picked `native_attach`, attach returned rs_status 200, and rs.ge shows the final at its **full** amount (106.20, VAT 16.20) with the **advance attached** (VAT 3.24) — the field-9 reference present, no double-count.

**Implemented fix (2026-06-22):** finals now auto-resolve their settlement mode at creation — `_rs_native_advance_eligible()` ([account_move_seller.py](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py)) returns true when every down-payment offset is backed by a confirmed, strictly-earlier-month advance (refreshing the advance's rs.ge status on demand if locally stale); `create()` sets `native_attach` when eligible and the caller didn't choose a mode, else leaves Net. The waybill wizard no longer hard-codes `native_attach` — both entry points share this one rule.

## Restriction summary

| # | Restriction | Where |
|---|---|---|
| 1 | All-DP customer invoice auto-flagged as advance (`save_invoice_a`) | [account_move.py:1305](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1305) |
| 2 | Standalone DP offset CN force-skipped; Skip cannot be un-ticked | [account_move.py:1109](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1109), [:1292](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1313) |
| 3 | Net: net total after deduction must be > 0 | [account_move_sync.py:470](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L470) |
| 4 | Net: offset VAT cannot exceed delivery VAT | [account_move_sync.py:477](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L477) |
| 5 | Native: customer invoice only, not the advance, needs delivery+offset lines | [account_move.py:1018](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1018) |
| 6 | Native: advance must be buyer-confirmed and strictly earlier-month | [account_move_seller.py:328](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L328) |
| 7 | Native: advance must be resolvable (1 unambiguous SO-linked advance with rs.ge ID) | [account_move_seller.py:211](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L211) |
| 8 | Native: no over-settle; no stray rs.ge advances; respect MIN_DRG floor | [account_move_seller.py:490](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L490), [:527](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L527), [:565](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L565) |
| 9 | Native sync failure blocks Send-to-buyer | [account_move_seller.py:951](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L951) |
| 10 | Settlement mode locked after filing; Native→Net blocked once attached | [account_move.py:1373](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1373) |
| 11 | Advances cannot be Cancel/Correct-&-Reissued | [rs_replace_orchestrator.py:87](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_replace_orchestrator.py#L87) |
| 12 | Fully-settled / below-settled advance correction blocked | [account_move_seller.py:458](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L458) |
| 13 | Mode auto-picked at create: Native if eligible, else Net (same rule for manual and waybill-wizard invoices) | [account_move.py:1316](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1316), [account_move_seller.py:366](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L366) |
