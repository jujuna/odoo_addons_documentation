from collections import Counter, defaultdict

from odoo import models, fields, _
from odoo.exceptions import UserError
from odoo.tools import float_compare
from odoo.addons.rs_waybill.models.rs_waybill import (
    WAYBILL_TYPE, TRANSPORT_TYPE, WAYBILL_STATUS, STATE,
)

# RS-sourced fields shown in the popup and checked for drift (from _map_rs_waybill_vals).
MIRROR_FIELDS = [
    'state', 'waybill_status', 'is_confirmed',
    'rs_waybill_number', 'waybill_type', 'category', 'is_medicine',
    'activation_date', 'transport_start_date', 'delivery_date', 'close_date',
    'seller_tin', 'seller_name', 'start_address',
    'buyer_tin', 'buyer_name', 'end_address',
    'transport_type', 'other_transport', 'transporter_tin', 'transporter_name',
    'transport_cost', 'transport_cost_payer',
    'driver_name', 'driver_tin', 'car_number',
    'reception_info', 'receiver_info', 'comment',
]


class RsWaybill(models.Model):
    _inherit = 'rs.waybill'

    def action_open_live_rs_view(self):
        """ Fetch the waybill's current state from RS.GE and show it in a popup,
        highlighting fields that differ from Odoo. """
        self.ensure_one()
        if not self.rs_internal_id:
            raise UserError(_("This waybill has no RS.GE ID yet."))
        snapshot = self.env['rs.waybill.live'].create({'waybill_id': self.id})
        snapshot._fetch_and_fill()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Live RS.GE View'),
            'res_model': 'rs.waybill.live',
            'res_id': snapshot.id,
            'view_mode': 'form',
            'target': 'new',
        }


class RsWaybillLive(models.TransientModel):
    _name = 'rs.waybill.live'
    _description = 'Live RS.GE Waybill Snapshot'

    waybill_id = fields.Many2one('rs.waybill', required=True, ondelete='cascade')
    fetched_at = fields.Datetime(readonly=True)
    summary = fields.Char(readonly=True)
    has_drift = fields.Boolean(readonly=True)
    drift_field_names = fields.Char(readonly=True)

    rs_internal_id = fields.Integer(string='Internal ID', readonly=True)
    rs_waybill_number = fields.Char(string='Waybill Number', readonly=True)
    state = fields.Selection(STATE, readonly=True)
    waybill_status = fields.Selection(WAYBILL_STATUS, string='RS Status', readonly=True)
    is_confirmed = fields.Selection([('0', 'Unconfirmed'), ('1', 'Confirmed'), ('2', 'Rejected'), ('-1', 'Refused')],
                                    readonly=True)
    waybill_type = fields.Selection(WAYBILL_TYPE, readonly=True)
    category = fields.Selection([('0', 'Normal'), ('1', 'Wood')], readonly=True)
    is_medicine = fields.Selection([('0', 'Normal'), ('1', 'Medicine')], readonly=True)
    activation_date = fields.Datetime(readonly=True)
    transport_start_date = fields.Datetime(string='Transport Start Date', readonly=True)
    delivery_date = fields.Datetime(readonly=True)
    # RS CLOSE_DATE — set on any close, delivery completion included (not a cancellation).
    close_date = fields.Datetime(readonly=True)
    seller_name = fields.Char(string='Seller Name', readonly=True)
    seller_tin = fields.Char(string='Seller Tin', readonly=True)
    start_address = fields.Char(string='Start Address', readonly=True)
    buyer_name = fields.Char(string='Buyer Name', readonly=True)
    buyer_tin = fields.Char(string='Buyer Tin', readonly=True)
    end_address = fields.Char(string='End Address', readonly=True)
    transport_type = fields.Selection(TRANSPORT_TYPE, readonly=True)
    other_transport = fields.Char(string='Other Transport', readonly=True)
    transporter_name = fields.Char(string='Transporter Name', readonly=True)
    transporter_tin = fields.Char(string='Transporter Tin', readonly=True)
    transport_cost = fields.Float(string='Transport Cost', readonly=True)
    transport_cost_payer = fields.Selection([('1', 'Buyer'), ('2', 'Seller')], readonly=True)
    driver_name = fields.Char(string='Driver Name', readonly=True)
    driver_tin = fields.Char(string='Driver Tin', readonly=True)
    car_number = fields.Char(string='Car Number', readonly=True)
    reception_info = fields.Char(string='Handed Over By', readonly=True)
    receiver_info = fields.Char(string='Received By', readonly=True)
    comment = fields.Text(string='Notes', readonly=True)
    full_amount = fields.Float(string='Goods Total', readonly=True)
    line_ids = fields.One2many('rs.waybill.live.line', 'live_id', string='Goods', readonly=True)


    def _fetch_and_fill(self):
        self.ensure_one()
        wb = self.waybill_id
        header, goods = wb._rs_service().get_full_waybill(wb.rs_internal_id)
        if not header:
            raise UserError(_("Could not fetch this waybill from RS.GE."))
        rs_vals = wb._map_rs_waybill_vals(header)

        def differs(field, rs_value):
            odoo_value = wb[field]
            try:
                if not odoo_value and not rs_value:
                    return False
                if hasattr(odoo_value, 'strftime') and isinstance(rs_value, str):
                    return odoo_value.strftime('%Y-%m-%d %H:%M:%S') != rs_value
                if isinstance(odoo_value, float) and isinstance(rs_value, (int, float)):
                    return float_compare(odoo_value, rs_value, precision_digits=4) != 0
                return odoo_value != rs_value
            except Exception:
                return True

        snap = {f: rs_vals.get(f) for f in MIRROR_FIELDS if f in rs_vals}
        drift = [f for f in MIRROR_FIELDS if f in rs_vals and differs(f, rs_vals[f])]

        # Match goods by (barcode, name) plus an occurrence number: a waybill may carry the same product twice.
        existing = defaultdict(list)
        for line in wb.line_ids:
            existing[(line.bar_code or '', line.name or '')].append(line)
        matched = defaultdict(int)
        rs_keys, line_cmds, goods_total = Counter(), [(5, 0, 0)], 0.0
        for item in goods:
            bar_code = (item.get('BAR_CODE') or '').strip()
            name = (item.get('W_NAME') or '').strip() or 'Unknown'
            key = (bar_code, name)
            rs_keys[key] += 1
            qty = float(item.get('QUANTITY') or 0)
            price = float(item.get('PRICE') or 0)
            goods_total += qty * price
            candidates = existing.get(key, [])
            index = matched[key]
            match = candidates[index] if index < len(candidates) else None
            matched[key] += 1
            if not match:
                status = 'only_rs'
            elif (float_compare(match.quantity, qty, precision_digits=4) != 0
                    or float_compare(match.unit_price, price, precision_digits=4) != 0):
                status = 'changed'
            else:
                status = 'same'
            line_cmds.append((0, 0, {
                'name': name, 'bar_code': bar_code, 'unit_name': item.get('UNIT_TXT') or '',
                'quantity': qty, 'unit_price': price, 'amount': qty * price,
                'vat_type': item.get('VAT_TYPE') or '0', 'status': status,
            }))
        for key, lines in existing.items():
            for line in lines[rs_keys.get(key, 0):]:
                line_cmds.append((0, 0, {
                    'name': line.name, 'bar_code': line.bar_code, 'unit_name': line.unit_name,
                    'quantity': line.quantity, 'unit_price': line.unit_price,
                    'amount': line.amount, 'vat_type': line.vat_type, 'status': 'only_odoo',
                }))
        goods_drift = any(c[2].get('status') != 'same' for c in line_cmds if c[0] == 0)

        n = len(drift) + (1 if goods_drift else 0)
        self.write({
            **snap,
            'rs_internal_id': wb.rs_internal_id,
            'full_amount': goods_total,
            'fetched_at': fields.Datetime.now(),
            'drift_field_names': ','.join(drift),
            'has_drift': bool(n),
            'summary': _("Differences found — highlighted below") if n else _("In sync with RS.GE"),
            'line_ids': line_cmds,
        })


class RsWaybillLiveLine(models.TransientModel):
    _name = 'rs.waybill.live.line'
    _description = 'Live RS.GE Waybill Goods Line'

    live_id = fields.Many2one('rs.waybill.live', required=True, ondelete='cascade')
    name = fields.Char(readonly=True)
    bar_code = fields.Char(string='Code', readonly=True)
    unit_name = fields.Char(string='Unit', readonly=True)
    quantity = fields.Float(readonly=True)
    unit_price = fields.Float(string='Unit Price', readonly=True)
    amount = fields.Float(string='Total', readonly=True)
    vat_type = fields.Selection([('0', 'Standard'), ('1', 'Zero'), ('2', 'Exempt')], readonly=True)
    status = fields.Selection([
        ('same', 'In sync'), ('changed', 'Changed'),
        ('only_rs', 'Only on RS'), ('only_odoo', 'Only in Odoo')], readonly=True)
