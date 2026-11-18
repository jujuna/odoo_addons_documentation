from odoo import api, fields, models, Command

from ..models.account_move import MONTHS_GE, RS_STATUS, _rs_clean_number, rs_to_float


class RsEinvoiceViewWizard(models.TransientModel):
    _name = 'rs.einvoice.view.wizard'
    _description = 'rs.ge Live Invoice Data (read-only)'

    move_id = fields.Many2one('account.move', readonly=True)
    rs_invoice_id = fields.Char(readonly=True)
    rs_status = fields.Selection(RS_STATUS, readonly=True)
    created_label = fields.Char(readonly=True)
    operation_month = fields.Selection(MONTHS_GE, readonly=True)
    operation_year = fields.Char(readonly=True)
    invoice_number = fields.Char(readonly=True)
    declaration_number = fields.Char(readonly=True)
    seller_tin = fields.Char(readonly=True)
    seller_name = fields.Char(readonly=True)
    buyer_tin = fields.Char(readonly=True)
    buyer_name = fields.Char(readonly=True)
    total_vat_charge = fields.Float(digits=(16, 2), readonly=True)
    total_vat_reduce = fields.Float(digits=(16, 2), readonly=True)
    goods_line_ids = fields.One2many('rs.einvoice.view.line', 'wizard_id', domain=[('kind', '=', 'goods')], readonly=True)
    waybill_line_ids = fields.One2many('rs.einvoice.view.line', 'wizard_id', domain=[('kind', '=', 'waybill')], readonly=True)
    advance_line_ids = fields.One2many('rs.einvoice.view.line', 'wizard_id', domain=[('kind', '=', 'advance')], readonly=True)

    @api.model
    def _build_from_move(self, move):
        move.ensure_one()
        service = move._rs_get_service()
        inv_id = move._rs_inv_id_int
        head = service.get_invoice(inv_id)

        status = str(getattr(head, 'status', '') or '')
        op_dt = getattr(head, 'operation_dt', None)
        reg_dt = getattr(head, 'reg_dt', None)
        seq_s = getattr(head, 'seq_num_s', '') or ''
        seq_b = getattr(head, 'seq_num_b', '') or ''
        seller_un = getattr(head, 'seller_un_id', 0) or 0
        buyer_un = getattr(head, 'buyer_un_id', 0) or 0

        seller = self._safe_party(service, seller_un)
        buyer = self._safe_party(service, buyer_un)

        goods_cmds, total_vat = self._build_goods(move, service, inv_id)
        adv_cmds, total_adv_vat = self._build_advances(move, service, inv_id)
        wb_cmds = self._build_waybills(move, service, inv_id)

        series = (getattr(head, 'f_series', '') or '').strip()
        number = _rs_clean_number(getattr(head, 'f_number', ''))
        invoice_number = ('%s %s' % (series, number)).strip() if number else series
        declaration = _rs_clean_number(seq_b if move.rs_einv_is_buyer_side else seq_s)

        net = round(total_vat - total_adv_vat, 2)
        return self.create({
            'move_id': move.id,
            'rs_invoice_id': move.rs_einv_id or '',
            'rs_status': status or False,
            'created_label': self._date_str(reg_dt),
            'operation_month': str(op_dt.month) if op_dt else False,
            'operation_year': str(op_dt.year) if op_dt else False,
            'invoice_number': invoice_number,
            'declaration_number': declaration,
            'seller_tin': seller['tin'],
            'seller_name': seller['name'],
            'buyer_tin': buyer['tin'],
            'buyer_name': buyer['name'],
            'total_vat_charge': net if net >= 0 else 0.0,
            'total_vat_reduce': -net if net < 0 else 0.0,
            'goods_line_ids': goods_cmds,
            'waybill_line_ids': wb_cmds,
            'advance_line_ids': adv_cmds,
        })

    @staticmethod
    def _date_str(value):
        if not value:
            return ''
        if hasattr(value, 'strftime'):
            return value.strftime('%d-%m-%Y %H:%M')
        text = str(value)
        return text.split('T')[0] if 'T' in text else text

    @staticmethod
    def _safe_party(service, un_id):
        if not un_id or int(un_id) <= 0:
            return {'tin': '', 'name': ''}
        try:
            return service.get_party_from_un_id(un_id)
        except Exception:
            return {'tin': str(un_id), 'name': ''}

    def _build_goods(self, move, service, inv_id):
        rows = service.get_invoice_desc(inv_id) or []
        cmds = []
        total_vat = 0.0
        seq = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            seq += 1
            vat_raw = rs_to_float(row.get('drg_amount'))
            if vat_raw > 0:
                taxation = 'ჩვეულებრივი'
                vat = vat_raw
                total_vat += vat_raw
            elif vat_raw == 0:
                taxation = 'ნულოვანი'
                vat = 0.0
            else:
                taxation = 'დაუბეგრავი'
                vat = 0.0
            cmds.append(Command.create({
                'kind': 'goods',
                'sequence': seq,
                'name': row.get('goods') or '',
                'unit': row.get('g_unit') or '',
                'quantity': rs_to_float(row.get('g_number')),
                'full_amount': rs_to_float(row.get('full_amount')),
                'taxation': taxation,
                'vat_amount': vat,
                'excise_amount': rs_to_float(row.get('aqcizi_amount')),
            }))
        return cmds, round(total_vat, 2)

    def _build_advances(self, move, service, inv_id):
        try:
            rows = service.get_attached_advance_invoices(inv_id) or []
        except Exception:
            return [], 0.0
        cmds = []
        total = 0.0
        seq = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            seq += 1
            vat = rs_to_float(row.get('drg_amount'))
            total += vat
            cmds.append(Command.create({
                'kind': 'advance',
                'sequence': seq,
                'adv_series': row.get('f_series') or '',
                'adv_date': self._date_str(row.get('operation_dt')),
                'adv_vat': vat,
            }))
        return cmds, round(total, 2)

    def _build_waybills(self, move, service, inv_id):
        try:
            rows = service.get_invoice_waybills(inv_id) or []
        except Exception:
            return []
        cmds = []
        seq = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            seq += 1
            cmds.append(Command.create({
                'kind': 'waybill',
                'sequence': seq,
                'wb_number': row.get('overhead_no') or '',
                'wb_date': self._date_str(row.get('overhead_dt')),
            }))
        return cmds


class RsEinvoiceViewLine(models.TransientModel):
    _name = 'rs.einvoice.view.line'
    _description = 'rs.ge Live Invoice Line (read-only)'
    _order = 'kind, sequence, id'

    wizard_id = fields.Many2one('rs.einvoice.view.wizard', required=True, ondelete='cascade')
    kind = fields.Selection([('goods', 'Goods'), ('waybill', 'Waybill'), ('advance', 'Advance')], required=True)
    sequence = fields.Integer(default=0)

    name = fields.Char(readonly=True)
    unit = fields.Char(readonly=True)
    quantity = fields.Float(digits=(16, 4), readonly=True)
    full_amount = fields.Float(digits=(16, 2), readonly=True)
    taxation = fields.Char(readonly=True)
    vat_amount = fields.Float(digits=(16, 2), readonly=True)
    excise_amount = fields.Float(digits=(16, 2), readonly=True)

    wb_number = fields.Char(readonly=True)
    wb_date = fields.Char(readonly=True)

    adv_series = fields.Char(readonly=True)
    adv_date = fields.Char(readonly=True)
    adv_vat = fields.Float(digits=(16, 2), readonly=True)
