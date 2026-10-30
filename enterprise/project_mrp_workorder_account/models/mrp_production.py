# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _update_date_finished_analytic_lines(self):
        super()._update_date_finished_analytic_lines()
        for production in self:
            analytic_date = fields.Date.context_today(production, timestamp=production.date_finished)
            production.workorder_ids.employee_analytic_account_line_ids.sudo().write({'date': analytic_date})

    def write(self, vals):
        distribution_per_project = {p: p.sudo()._get_analytic_distribution() for p in self.project_id}
        res = super().write(vals)
        if 'project_id' in vals:
            for production in self:
                if production.state == 'draft':
                    continue
                for wo in production.workorder_ids:
                    wo._update_productivity_analytic(distribution_per_project.get(production.project_id, {}))
        return res
