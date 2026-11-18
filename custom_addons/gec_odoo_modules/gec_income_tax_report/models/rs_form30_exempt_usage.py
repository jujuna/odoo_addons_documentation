from odoo import fields, models


class RsForm30ExemptUsage(models.Model):
    _name = 'rs.form30.exempt.usage'
    _description = 'Form 30 International Agreement Exemption Usage'
    _order = 'date desc, id desc'

    partner_id = fields.Many2one('res.partner', string='Recipient', required=True, ondelete='cascade', index=True)
    line_id = fields.Many2one('rs.form30.line', string='Declaration Line', required=True, ondelete='cascade', index=True)
    declaration_id = fields.Many2one(related='line_id.declaration_id', store=True)
    company_id = fields.Many2one(related='line_id.company_id', store=True)
    date = fields.Date(string='Payment Date', related='line_id.date', store=True)
    amount = fields.Float(string='Exempted Here')
    balance_before = fields.Float(string='Before')
    balance_after = fields.Float(string='After')
