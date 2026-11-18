from odoo import _, api, models


class IrFilters(models.Model):
    _inherit = 'ir.filters'

    def _gec_check_favorites(self):
        rules = self.env['gec.access.profile']._current_rules()
        if rules.enabled and rules.has_flag('block_favorites'):
            raise self.env['gec.access.profile']._gec_refusal(
                _("Your access profile does not allow saving searches."), model=self._name)

    @api.model
    def create_filter(self, vals):
        self._gec_check_favorites()
        return super().create_filter(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if self._gec_client_reads_model() and not self.env.su:
            self._gec_check_favorites()
        return super().create(vals_list)

    def write(self, vals):
        if self._gec_client_reads_model() and not self.env.su:
            self._gec_check_favorites()
        return super().write(vals)
