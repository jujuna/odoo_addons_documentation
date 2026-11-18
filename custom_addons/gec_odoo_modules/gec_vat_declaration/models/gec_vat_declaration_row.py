from odoo import api, models


class GecVatDeclarationRow(models.AbstractModel):
    _name = 'gec.vat.declaration.row'
    _description = 'VAT Declaration Row'

    @api.model_create_multi
    def create(self, vals_list):
        rows = super().create(vals_list)
        rows.declaration_id._check_draft()
        return rows

    def write(self, vals):
        self.declaration_id._check_draft()
        if vals.get('declaration_id'):
            self.declaration_id.browse(vals['declaration_id'])._check_draft()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_filed(self):
        self.declaration_id._check_draft()
