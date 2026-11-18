from odoo import api, fields, models

PARTS = [
    ('sale', 'Issued (B I)'),
    ('purchase', 'Received (B II)'),
    ('spec_sale', 'Issued Petroleum (tab 13)'),
    ('spec_purchase', 'Received Petroleum (tab 14)'),
]


class GecVatInvoiceLine(models.Model):
    _name = 'gec.vat.invoice.line'
    _inherit = 'gec.vat.declaration.row'
    _description = 'VAT Declaration Annex B I / B II / Tab 13 / 14 Row'
    _order = 'declaration_id, id'

    declaration_id = fields.Many2one('gec.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    part = fields.Selection(PARTS, required=True, default='sale')
    move_id = fields.Many2one('account.move', string='Odoo Invoice', ondelete='cascade', index=True, readonly=True,
        help="Set on rows built by Generate; a row without it was typed, e.g. for a paper invoice.")
    series = fields.Char()
    number = fields.Char()
    operation_month = fields.Date(help="Month of the taxable operation; the first day stands for the month.")
    partner_tin = fields.Char(string='Partner Tax ID', help="The buyer's Tax ID on annex B I, the supplier's on annex B II.")
    amount = fields.Float(string='VAT', help="VAT of the invoice, or the increase of a correction: payable on B I, creditable on B II.")
    reduce_amount = fields.Float(string='VAT Reduced', help="The decrease of a correction.")
    korect_series = fields.Char(string='Corrected Series')
    korect_number = fields.Char(string='Corrected Number')
    korect_date = fields.Date(string='Corrected Date')
    operation_date = fields.Date()
    station_from = fields.Char(string='Departure Station')
    station_to = fields.Char(string='Destination Station')
    product_code = fields.Char(string='RS Product Code')
    quantity_l = fields.Float(string='Litres', digits=(16, 3))
    quantity_kg = fields.Float(string='Kilograms', digits=(16, 3))


class GecVatAdvanceLine(models.Model):
    _name = 'gec.vat.advance.line'
    _inherit = 'gec.vat.declaration.row'
    _description = 'VAT Declaration Annex B I / B II Advance Offset'
    _order = 'declaration_id, id'

    declaration_id = fields.Many2one('gec.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    part = fields.Selection(PARTS, required=True, default='sale')
    settlement_id = fields.Many2one('rs.einvoice.advance.settlement', string='rs.ge Settlement', ondelete='cascade', readonly=True)
    delivery_series = fields.Char()
    delivery_number = fields.Char()
    advance_series = fields.Char()
    advance_number = fields.Char()
    amount = fields.Float(string='VAT')


class GecVatCustomsLine(models.Model):
    _name = 'gec.vat.customs.line'
    _inherit = 'gec.vat.declaration.row'
    _description = 'VAT Declaration Annex B III Row'
    _order = 'declaration_id, id'

    declaration_id = fields.Many2one('gec.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    assessment_number = fields.Char()
    customs_code = fields.Char()
    assessment_date = fields.Date()
    amount = fields.Float(string='VAT')
    pdf_type = fields.Selection([('customs', 'Customs declaration'), ('form4', 'Form 4')], string='Type', readonly=True)
    attachment_id = fields.Many2one('ir.attachment', string='Customs Declaration PDF', readonly=True, ondelete='set null')


class GecVatRefLine(models.Model):
    _name = 'gec.vat.ref.line'
    _inherit = 'gec.vat.declaration.row'
    _description = 'VAT Declaration Annex B IV / B V / B VIII / B IX Row'
    _order = 'declaration_id, id'

    declaration_id = fields.Many2one('gec.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    grid = fields.Selection([('b4', 'B IV'), ('b5', 'B V'), ('b8', 'B VIII'), ('b9', 'B IX')], string='Annex', required=True, default='b4')
    ref_number = fields.Char(string='Document Number',
        help="The acquisition document number on B IV, the declaration number on B V, B VIII and B IX.")
    ref_date = fields.Date(string='Purchase Date')
    period = fields.Date(compute='_compute_period', store=True, readonly=False,
        help="Reporting month on annexes B V, B VIII and B IX; the first day stands for the month.")
    partner_tin = fields.Char(string='Partner Tax ID', help="The seller's Tax ID on annex B IV, the supplier's on annex B V.")
    partner_name = fields.Char()
    owner_tin = fields.Char(string='Owner Tax ID')
    owner_name = fields.Char()
    amount = fields.Float(string='VAT')

    @api.depends('ref_number')
    def _compute_period(self):
        """ბ VIII / ბ IX: month of the Odoo declaration (ბ IX: or reverse-charge calculation) with this portal number; else empty, to type.
        ბ IV / ბ V keep the month typed."""
        for row in self:
            if row.grid not in ('b8', 'b9'):
                row.period = row.period
                continue
            source = self.env['gec.vat.declaration']
            if row.ref_number:
                domain = [('company_id', '=', row.declaration_id.company_id.id), ('portal_number', '=', row.ref_number)]
                source = source.search(domain, limit=1)
                if not source and row.grid == 'b9':
                    source = self.env['gec.vat.rc.declaration'].search(domain, limit=1)
            row.period = source.date_from
