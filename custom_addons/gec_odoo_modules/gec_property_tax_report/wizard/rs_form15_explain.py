from odoo import api, fields, models

LINE_MODELS = {
    'part3': 'rs.form15.part3.line',
    'part4': 'rs.form15.part4.line',
}


class RsForm15Explain(models.TransientModel):
    """Why one declaration row holds its numbers, rendered from `line._explain()`."""
    _name = 'rs.form15.explain'
    _description = 'rs.ge Form 15 Row Explanation'

    declaration_id = fields.Many2one('rs.form15.declaration', required=True, readonly=True)
    line_part = fields.Selection(
        [('part3', 'Part III'), ('part4', 'Part IV')], required=True, readonly=True)
    line_ref = fields.Integer(required=True, readonly=True)
    content = fields.Html(compute='_compute_content', sanitize=False, readonly=True)

    def _line(self):
        self.ensure_one()
        return self.env[LINE_MODELS[self.line_part]].browse(self.line_ref).exists()

    @api.depends('line_ref', 'line_part')
    def _compute_content(self):
        for wizard in self:
            line = wizard._line()
            if not line:
                wizard.content = False
                continue
            wizard.content = self.env['ir.qweb']._render(
                'gec_property_tax_report.row_explanation',
                {
                    'declaration': wizard.declaration_id,
                    'part': wizard.line_part,
                    'currency': wizard.declaration_id.currency_id,
                    **line._explain(),
                },
            )
