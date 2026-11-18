from odoo import api, models, fields, _
from odoo.exceptions import UserError

# What RS.GE keeps in a template besides the buyer and addresses (see _build_waybill_xml). Trip-specific values (dates,
# number, status, linked documents) are not part of a template.
TEMPLATE_HEADER_FIELDS = [
    'waybill_type', 'transport_type', 'category', 'is_medicine',
    'buyer_id', 'buyer_tin', 'buyer_name', 'citizen', 'start_address', 'end_address',
    'seller_tin', 'seller_name', 'transporter_tin', 'transporter_name', 'other_transport',
    'driver_partner_id', 'driver_tin', 'driver_name', 'driver_is_foreigner', 'vehicle_id', 'car_number',
    'transport_cost', 'transport_cost_payer', 'reception_info', 'receiver_info', 'comment',
]


def _template_line_commands(lines):
    """ Goods lines for a template or a waybill made from one: what is declared, never the link to a delivery,
        an order or an RS.GE line. A template only holds them; stock moves when a waybill from it is saved. """
    return [(0, 0, {
        'sequence': line.sequence,
        'product_id': line.product_id.id,
        'name': line.name,
        'bar_code': line.bar_code,
        'uom_id': line.uom_id.id,
        'unit_name': line.unit_name,
        'rs_unit_code': line.rs_unit_code,
        'quantity': line.quantity,
        'unit_price': line.unit_price,
        'vat_type': line.vat_type,
    }) for line in lines.filtered(lambda l: l.rs_line_status != 'remove')]


class TemplateSaveWizard(models.TransientModel):
    _name = 'rs.waybill.template.save.wizard'
    _description = 'Save Waybill as Template'


    waybill_id = fields.Many2one('rs.waybill', required=True)
    name = fields.Char(string='Template Name', required=True)


    def action_save(self):
        self.ensure_one()
        service = self.waybill_id._rs_service()
        waybill = self.waybill_id
        tid = service.save_waybill_template(waybill, self.name)
        # The same content RS.GE now holds (it was built from this waybill): a waybill made from the template at
        # once carries the goods, driver and car. The template belongs to the waybill's company, not the switcher's.
        company = waybill.company_id or self.env.company
        self.env['rs.waybill'].with_company(company).create({
            **{name: waybill._fields[name].convert_to_write(waybill[name], waybill) for name in TEMPLATE_HEADER_FIELDS},
            'company_id': company.id,
            'is_template': True,
            'rs_template_id': tid,
            'template_name': self.name,
            'waybill_direction': 'seller',
            'line_ids': _template_line_commands(waybill.line_ids),
        })
        return {'type': 'ir.actions.act_window_close'}


class TemplatePickerWizard(models.TransientModel):
    _name = 'rs.waybill.template.picker.wizard'
    _description = 'Picker Waybill Template'

    template_id = fields.Many2one('rs.waybill',string='Template',required=True, domain=[('is_template','=',True)])

    def action_load(self):
        self.ensure_one()
        new = self.template_id.copy({
            # One2many lines are never copied by copy(): without this the new waybill would have no goods.
            'line_ids': _template_line_commands(self.template_id.line_ids),
            'is_template': False,
            'template_name': False,
            'rs_template_id': self.template_id.rs_template_id,
            'rs_internal_id': 0,
            'rs_waybill_number': False,
            'state': 'draft',
            'waybill_status': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rs.waybill',
            'res_id': new.id,
            'view_mode': 'form',
            'target': 'current',
        }