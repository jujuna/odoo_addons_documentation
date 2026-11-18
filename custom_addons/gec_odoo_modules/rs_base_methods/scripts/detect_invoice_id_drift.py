# Read-only scan: list linked invoices whose rs_einv_id differs from the waybill's rs.ge INVOICE_ID.
# Run via:  odoo-bin shell -d <db> < this_file

admin = env.ref('base.user_admin')
wb_svc = env['rs.waybill.soap.service'].with_user(admin.id)


def _waybill_invoice_id(rs_internal):
    try:
        header, _goods = wb_svc.get_full_waybill(int(rs_internal))
    except Exception as e:
        return 'ERR:%s' % (repr(e)[:60])
    if not isinstance(header, dict):
        return None
    return header.get('INVOICE_ID')


links = env['rs.einvoice.waybill.link'].search([('move_id.rs_einv_id', '!=', False)])
seen = set()
drift = []
for link in links:
    move, waybill = link.move_id, link.waybill_id
    key = (move.id, waybill.id)
    if not waybill.rs_internal_id or key in seen:
        continue
    seen.add(key)
    rs_inv = _waybill_invoice_id(waybill.rs_internal_id)
    if str(rs_inv or '') != str(move.rs_einv_id or ''):
        drift.append((move.name, move.rs_einv_id, move.state, waybill.id, waybill.rs_internal_id, rs_inv))

print("Drifted records (move.rs_einv_id != waybill.INVOICE_ID): %d" % len(drift))
for name, rs_id, state, wb_id, wb_rs, rs_inv in drift:
    print("  move %s rs_einv_id=%s state=%s | waybill %s (rs %s) INVOICE_ID=%s" % (name, rs_id, state, wb_id, wb_rs, rs_inv))
print("DONE (read-only — nothing changed)")
