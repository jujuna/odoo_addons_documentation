from odoo import api, models, fields, _
from markupsafe import Markup
import json


class RsWaybillReturnDecisionWizard(models.TransientModel):
    """ Asks about goods lowered off a completed waybill or returned on a receipt: back in stock or scrapped,
        does the customer still want them? Never a physical return with a return waybill
        (adjusting + type 5 would count the goods twice on RS). """
    _name = 'rs.waybill.return.decision.wizard'
    _description = 'RS Waybill Correction Decision'

    waybill_id = fields.Many2one('rs.waybill', required=True, ondelete='cascade')
    line_ids = fields.One2many('rs.waybill.return.decision.line', 'wizard_id')
    # How many pending corrections this popup answers: ones a sync adds meanwhile stay.
    entry_count = fields.Integer()
    has_sale_lines = fields.Boolean(compute='_compute_has_sale_lines')
    # Goods that came back on a return receipt are physically here: only the order is asked.
    ask_where = fields.Boolean(compute='_compute_has_sale_lines')

    @api.depends('line_ids.sale_line_id', 'line_ids.returned')
    def _compute_has_sale_lines(self):
        for wizard in self:
            wizard.has_sale_lines = bool(wizard.line_ids.sale_line_id)
            wizard.ask_where = any(not line.returned for line in wizard.line_ids)


    def action_deliver_later(self):
        return self._apply('deliver')


    def action_reduce_order(self):
        return self._apply('reduce')


    def action_confirm(self):
        return self._apply(False)


    def _apply(self, order_decision):
        self.ensure_one()
        waybill = self.waybill_id
        notes = []
        for line in self.line_ids:
            if line.returned:
                notes.append(_("%(product)s: %(qty)s came back on a return")
                             % {'product': line.product_id.display_name, 'qty': line.qty})
            elif line.disposition == 'scrap':
                waybill._rs_scrap_correction(line.product_id, json.loads(line.chunks_json or '[]'))
                notes.append(_("%(product)s: %(qty)s scrapped (lost / damaged)")
                             % {'product': line.product_id.display_name, 'qty': line.qty})
            else:
                notes.append(_("%(product)s: %(qty)s back in stock")
                             % {'product': line.product_id.display_name, 'qty': line.qty})
        sale_lines = self.line_ids.sale_line_id
        if order_decision == 'deliver':
            waybill._rs_deliver_later(sale_lines)
        elif order_decision == 'reduce':
            lowered = {}
            for line in self.line_ids.filtered('sale_line_id'):
                sol = line.sale_line_id
                lowered[sol] = lowered.get(sol, 0.0) + line.product_id.uom_id._compute_quantity(
                    line.qty, sol.product_uom_id)
            waybill._rs_lower_sale_lines(lowered)
        remaining = waybill._rs_load_pending_corrections()[self.entry_count:]
        waybill.pending_return_json = json.dumps(remaining) if remaining else False
        decision = {'deliver': _("the customer still wants it: deliver later"),
                    'reduce': _("the order was reduced")}.get(order_decision)
        body = Markup(_("Lowered goods reconciled:<br/>%s")) % Markup('<br/>').join(notes)
        if decision:
            body += Markup('<br/>') + decision
        waybill.message_post(body=body)
        return {'type': 'ir.actions.act_window_close'}


class RsWaybillReturnDecisionLine(models.TransientModel):
    _name = 'rs.waybill.return.decision.line'
    _description = 'RS Waybill Correction Decision Line'

    wizard_id = fields.Many2one('rs.waybill.return.decision.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', readonly=True)
    qty = fields.Float(string='Quantity', readonly=True, digits='Product Unit')
    uom_id = fields.Many2one(related='product_id.uom_id', string='Unit')
    sale_line_id = fields.Many2one('sale.order.line', readonly=True)
    # [[location_id, lot_id, qty]]: where the lowering put the goods back.
    chunks_json = fields.Text()
    returned = fields.Boolean(readonly=True)
    disposition = fields.Selection([
        ('stock', 'Back in our warehouse'),
        ('scrap', 'Lost / damaged (scrap)'),
    ], string='Where is it?', required=True, default='stock')
