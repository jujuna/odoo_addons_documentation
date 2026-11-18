from odoo import api, models


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    @api.model
    def _gec_archive_rule_copies(self):
        """Data hook: archive the per-structure copies that predate the shared rule set. They are noupdate, so an upgrade
        never rewrites them (that would collide with the shared rules); their xmlids stay for the payslip lines on them."""
        data = self.env['ir.model.data'].search([('module', '=', 'geo_payroll'), ('model', '=', self._name), ('name', '=like', 'rule_geo_%')])
        copies = self.browse(data.filtered(lambda d: d.name.split('_')[2] in ('hourly', 'daily', 'unit')).mapped('res_id'))
        copies.filtered('active').action_archive()
