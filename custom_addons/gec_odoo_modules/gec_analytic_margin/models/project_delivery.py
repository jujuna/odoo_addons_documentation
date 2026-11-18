import math
from datetime import timedelta

from odoo import api, fields, models


class ProjectProject(models.Model):
    """Delivery dates: go-live dates are typed (only the project manager knows them);
    the finish date is forecast from remaining hours and recent pace."""
    _inherit = 'project.project'

    # Pace window: long enough to smooth a holiday week, short enough to see a team moved off.
    BURN_WEEKS = 8

    gec_template_id = fields.Many2one(
        'project.project', string='Built From Template', copy=False, index='btree_not_null',
        domain=[('is_template', '=', True)],
        help="The project template this project was created from. Filled in when a project is "
             "created from a template; set it by hand for projects created before.",
    )
    gec_golive_planned = fields.Date(
        string='Planned Go-Live', copy=False,
        help="The date the customer is due to start using the system, as contracted.",
    )
    gec_golive_actual = fields.Date(
        string='Actual Go-Live', copy=False,
        help="The date the customer actually started using it. Empty while the project is not live.",
    )
    gec_burn_rate = fields.Float(
        string='Hours per Week', compute='_compute_gec_end_forecast', digits=(16, 1),
        help="Hours logged on the project per week over the last eight weeks.",
    )
    gec_end_forecast = fields.Date(
        string='Forecast End Date', compute='_compute_gec_end_forecast',
        help="Today plus the hours still to go at the pace of the last eight weeks. "
             "Empty when nothing is left to do or nobody worked on it lately.",
    )
    gec_end_delay_days = fields.Integer(
        string='Days Late', compute='_compute_gec_end_forecast',
        help="Forecast end date minus the project's planned end date. Negative: ahead of plan.",
    )

    @api.depends('allocated_hours', 'date')
    def _compute_gec_end_forecast(self):
        today = fields.Date.context_today(self)
        since = today - timedelta(weeks=self.BURN_WEEKS)
        hours = dict(self.env['account.analytic.line'].sudo()._read_group(
            [('project_id', 'in', self.ids), ('employee_id', '!=', False),
             ('date', '>', since), ('date', '<=', today)],
            ['project_id'], ['unit_amount:sum'],
        )) if self.ids else {}
        for project in self:
            burn = (hours.get(project, 0.0) or 0.0) / self.BURN_WEEKS
            to_go = max((project.allocated_hours or 0.0) - (project.effective_hours or 0.0), 0.0)
            end = today + timedelta(days=math.ceil(to_go / burn * 7)) if burn and to_go else False
            project.gec_burn_rate = burn
            project.gec_end_forecast = end
            project.gec_end_delay_days = (end - project.date).days if end and project.date else 0

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        if self.env.context.get('copy_from_template'):
            for project, vals in zip(self, vals_list):
                if project.is_template:
                    vals['gec_template_id'] = project.id
        return vals_list
