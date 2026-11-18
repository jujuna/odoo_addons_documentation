from collections import Counter, defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_compare


class RsWaybillAdjustmentWizard(models.TransientModel):
    _name = 'rs.waybill.adjustment.wizard'
    _description = 'View Waybill Adjustment History'

    waybill_id = fields.Many2one('rs.waybill', required=True, readonly=True)
    line_ids = fields.One2many('rs.waybill.adjustment.line', 'wizard_id', string='Adjustments')


class RsWaybillAdjustmentLine(models.TransientModel):
    _name = 'rs.waybill.adjustment.line'
    _description = 'View Waybill Snapshot entry'
    _order = 'date desc'

    wizard_id = fields.Many2one('rs.waybill.adjustment.wizard', required=True, ondelete='cascade')
    archival_id = fields.Integer(string='Archival ID', readonly=True)
    date = fields.Datetime(string='Edit Date', readonly=True)
    user_name = fields.Char(string='Edited By', readonly=True)

    def action_view_snapshot(self):
        """ Fetch the full historical snapshot from RS and display it. """
        self.ensure_one()
        service = self.wizard_id.waybill_id._rs_service()
        header, goods = service.get_adjusted_waybill(self.archival_id)
        if not header:
            raise UserError(_("Could not fetch snapshot for archival ID %s") % self.archival_id)

        def _norm_dt(s):
            # RS sends Georgian local time; Odoo Datetime fields are UTC.
            return service.rs_local_to_utc(s) or False

        wb = self.wizard_id.waybill_id
        live_header, live_goods = (service.get_full_waybill(wb.rs_internal_id)
                                   if wb and wb.rs_internal_id else (None, []))
        line_vals = [(0, 0, vals) for vals in self._snapshot_line_vals(goods, live_goods if live_header else None)]

        snapshot = self.env['rs.waybill.adjustment.snapshot'].create({
            'archival_id': self.archival_id,
            'date': self.date,
            'user_name': self.user_name,
            'waybill_id': self.wizard_id.waybill_id.id,
            'waybill_number': header.get('WAYBILL_NUMBER', ''),
            'waybill_type': header.get('TYPE') or False,
            'waybill_status': header.get('STATUS') or False,
            'transport_type': header.get('TRANS_ID') or False,
            'category': header.get('CATEGORY') or False,
            'seller_tin': header.get('SELLER_TIN', ''),
            'seller_name': header.get('SELLER_NAME', ''),
            'start_address': header.get('START_ADDRESS', ''),
            'buyer_tin': header.get('BUYER_TIN', ''),
            'buyer_name': header.get('BUYER_NAME', ''),
            'end_address': header.get('END_ADDRESS', ''),
            'citizen': header.get('CHEK_BUYER_TIN') == '1',
            'other_transport': header.get('TRANS_TXT', ''),
            'transporter_tin': header.get('TRANSPORTER_TIN', ''),
            'transporter_name': header.get('TRANSPORTER_NAME', ''),
            'driver_tin': header.get('DRIVER_TIN', ''),
            'driver_name': header.get('DRIVER_NAME', ''),
            'driver_is_foreigner': header.get('CHEK_DRIVER_TIN') == '0',
            'car_number': header.get('CAR_NUMBER', ''),
            'transport_cost': float(header.get('TRANSPORT_COAST') or 0),
            'transport_cost_payer': header.get('TRAN_COST_PAYER') or False,
            'transport_start_date': _norm_dt(header.get('BEGIN_DATE')),
            'delivery_date': _norm_dt(header.get('DELIVERY_DATE')),
            'activation_date': _norm_dt(header.get('ACTIVATE_DATE')),
            'is_confirmed': header.get('IS_CONFIRMED') or False,
            'reception_info': header.get('RECEPTION_INFO', ''),
            'receiver_info': header.get('RECEIVER_INFO', ''),
            'comment': header.get('COMMENT', ''),
            'full_amount': float(header.get('FULL_AMOUNT') or 0),
            'line_ids': line_vals,
        })
        drift = []
        if live_header:
            def _norm(key, v):
                v = (v or '').strip()
                if key in ('BEGIN_DATE', 'DELIVERY_DATE', 'ACTIVATE_DATE', 'CLOSE_DATE'):
                    v = v.replace('T', ' ').split('.', 1)[0]
                return v
            compare = [
                ('TYPE', 'waybill_type'), ('STATUS', 'waybill_status'),
                ('TRANS_ID', 'transport_type'), ('CATEGORY', 'category'),
                ('SELLER_TIN', 'seller_tin'), ('SELLER_NAME', 'seller_name'),
                ('START_ADDRESS', 'start_address'), ('BUYER_TIN', 'buyer_tin'),
                ('BUYER_NAME', 'buyer_name'), ('END_ADDRESS', 'end_address'),
                ('TRANS_TXT', 'other_transport'), ('TRANSPORTER_TIN', 'transporter_tin'),
                ('TRANSPORTER_NAME', 'transporter_name'), ('DRIVER_TIN', 'driver_tin'),
                ('DRIVER_NAME', 'driver_name'), ('CAR_NUMBER', 'car_number'),
                ('TRAN_COST_PAYER', 'transport_cost_payer'),
                ('BEGIN_DATE', 'transport_start_date'), ('DELIVERY_DATE', 'delivery_date'),
                ('ACTIVATE_DATE', 'activation_date'), ('IS_CONFIRMED', 'is_confirmed'),
                ('RECEPTION_INFO', 'reception_info'), ('RECEIVER_INFO', 'receiver_info'),
                ('COMMENT', 'comment'),
            ]
            for rs_key, field in compare:
                if _norm(rs_key, header.get(rs_key)) != _norm(rs_key, live_header.get(rs_key)):
                    drift.append(field)
            if float_compare(float(header.get('TRANSPORT_COAST') or 0),
                             float(live_header.get('TRANSPORT_COAST') or 0), precision_digits=4):
                drift.append('transport_cost')
        snapshot.drift_field_names = ','.join(drift)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rs.waybill.adjustment.snapshot',
            'res_id': snapshot.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def _snapshot_line_vals(self, goods, live_goods):
        """ The old version's goods, each marked against RS.GE's current goods; goods added since come last.
            live_goods None (current version not fetched): no marks. Matched by (code, name) and occurrence. """
        def key(item):
            return (item.get('BAR_CODE') or '').strip(), (item.get('W_NAME') or '').strip()

        def vals(item, status=False):
            return {
                'name': item.get('W_NAME', ''),
                'bar_code': item.get('BAR_CODE', ''),
                'unit_name': item.get('UNIT_TXT', '') or '',
                'quantity': float(item.get('QUANTITY') or 0),
                'unit_price': float(item.get('PRICE') or 0),
                'amount': float(item.get('AMOUNT') or 0),
                'vat_type': item.get('VAT_TYPE') or '0',
                'status': status,
            }

        if live_goods is None:
            return [vals(item) for item in goods]
        current = defaultdict(list)
        for item in live_goods:
            current[key(item)].append(item)
        used, result = Counter(), []
        for item in goods:
            k = key(item)
            match = current[k][used[k]] if used[k] < len(current[k]) else None
            used[k] += 1
            if not match:
                status = 'removed'
            elif any(float_compare(float(item.get(f) or 0), float(match.get(f) or 0), precision_digits=4)
                     for f in ('QUANTITY', 'PRICE')):
                status = 'changed'
            else:
                status = 'same'
            result.append(vals(item, status))
        for k, items in current.items():
            result += [vals(item, 'added') for item in items[used[k]:]]
        return result


class RsWaybillAdjustmentSnapshot(models.TransientModel):
    _name = 'rs.waybill.adjustment.snapshot'
    _description = 'Read-only Historical Snapshot'

    archival_id = fields.Integer(string='Archival ID', readonly=True)
    date = fields.Datetime(string='Edit Date', readonly=True)
    user_name = fields.Char(string='Edited By', readonly=True)
    waybill_id = fields.Many2one('rs.waybill', readonly=True)
    drift_field_names = fields.Char(readonly=True)  # CSV of fields changed vs the current waybill

    waybill_number = fields.Char(string='Waybill Number', readonly=True)
    waybill_type = fields.Selection([('1', 'Internal Transport'), ('2', 'With Transport'),
                                     ('3', 'Without Transport'), ('4', 'Distribution'),
                                     ('5', 'Return'), ('6', 'Sub Waybill')],
                                    string='Waybill Type', readonly=True)
    waybill_status = fields.Selection([('0', 'Saved'), ('1', 'Active'), ('2', 'Completed'),
                                       ('8', 'Sent To Transporter'),
                                       ('-1', 'Deleted'), ('-2', 'Cancelled')],
                                      string='Status', readonly=True)
    transport_type = fields.Selection([('1', 'Auto'), ('2', 'Railway'), ('3', 'Air'),
                                       ('4', 'Other'), ('6', 'Auto-Foreign country'),
                                       ('7', 'Carrier'), ('8', 'Moped/Motorcycle')],
                                      string='Transport Type', readonly=True)
    category = fields.Selection([('0', 'Normal'), ('1', 'Wood')], string='Category', readonly=True)

    seller_tin = fields.Char(readonly=True)
    seller_name = fields.Char(readonly=True)
    start_address = fields.Char(readonly=True)

    buyer_tin = fields.Char(readonly=True)
    buyer_name = fields.Char(readonly=True)
    end_address = fields.Char(readonly=True)
    citizen = fields.Boolean(readonly=True)

    other_transport = fields.Char(readonly=True)
    transporter_tin = fields.Char(readonly=True)
    transporter_name = fields.Char(readonly=True)
    driver_tin = fields.Char(readonly=True)
    driver_name = fields.Char(readonly=True)
    driver_is_foreigner = fields.Boolean(readonly=True)
    car_number = fields.Char(readonly=True)
    transport_cost = fields.Float(readonly=True)
    transport_cost_payer = fields.Selection([('1', 'Buyer'), ('2', 'Seller')], readonly=True)
    transport_start_date = fields.Datetime(readonly=True)
    delivery_date = fields.Datetime(readonly=True)
    activation_date = fields.Datetime(readonly=True)

    is_confirmed = fields.Selection([('0', 'Unconfirmed'), ('1', 'Confirmed'),('2', 'Rejected'), ('-1', 'Refused')], readonly=True)

    reception_info = fields.Char(readonly=True)
    receiver_info = fields.Char(readonly=True)
    comment = fields.Text(readonly=True)
    full_amount = fields.Float(readonly=True)

    line_ids = fields.One2many('rs.waybill.adjustment.snapshot.line', 'snapshot_id', string='Goods')


class RsWaybillAdjustmentSnapshotLine(models.TransientModel):
    _name = 'rs.waybill.adjustment.snapshot.line'
    _description = 'Snapshot Goods Line'
    _order = 'sequence, id'

    snapshot_id = fields.Many2one('rs.waybill.adjustment.snapshot', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Name', readonly=True)
    bar_code = fields.Char(string='Bar Code', readonly=True)
    unit_name = fields.Char(string='Unit', readonly=True)
    quantity = fields.Float(readonly=True)
    unit_price = fields.Float(readonly=True)
    amount = fields.Float(readonly=True)
    vat_type = fields.Selection([('0', 'Standard'), ('1', 'Zero'), ('2', 'Exempt')], readonly=True)
    # Against RS.GE's current version; empty when that could not be fetched.
    status = fields.Selection([
        ('same', 'Unchanged'), ('changed', 'Changed'),
        ('removed', 'Removed later'), ('added', 'Added later')], readonly=True)
