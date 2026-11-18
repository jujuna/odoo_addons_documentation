from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class GecActivityPlanWizard(models.TransientModel):
    """Turn last period's actuals, scaled by a factor, into the plan for a new period."""
    _name = 'gec.activity.plan.wizard'
    _description = 'Plan Consumption from Actuals'

    activity_id = fields.Many2one('gec.activity', required=True)
    driver_label = fields.Char(related='activity_id.driver_label', string='Unit')

    source_date_from = fields.Date(
        string='Measure From', required=True,
        default=lambda self: fields.Date.context_today(self).replace(
            month=1, day=1,
        ),
    )
    source_date_to = fields.Date(
        string='Measure To', required=True,
        default=lambda self: fields.Date.context_today(self),
    )
    target_date_from = fields.Date(string='Plan From', required=True)
    target_date_to = fields.Date(string='Plan To', required=True)
    factor = fields.Float(
        string='Factor (%)', default=100.0, required=True,
        help="Applied to every measured quantity. 110 plans for ten percent "
             "more than last period, 90 for a planned efficiency gain.",
    )
    overwrite = fields.Boolean(
        string='Replace Existing Plans', default=True,
        help="A cost object that already has a plan for the target period is "
             "updated. Untick to leave hand-edited plans alone.",
    )

    @api.onchange('source_date_from', 'source_date_to')
    def _onchange_source_period(self):
        """Default the target to the period straight after the source."""
        if not (self.source_date_from and self.source_date_to):
            return
        length = self.source_date_to - self.source_date_from
        self.target_date_from = self.source_date_to + timedelta(days=1)
        self.target_date_to = self.target_date_from + length

    def action_generate(self):
        self.ensure_one()
        quantities = self.activity_id.get_quantities(
            self.source_date_from, self.source_date_to,
        )
        if not quantities:
            raise UserError(_(
                "%(name)s measured nothing between %(start)s and %(end)s, so "
                "there is nothing to plan from.\n\n"
                "Pick a period with data, or enter the plan by hand.",
                name=self.activity_id.name,
                start=self.source_date_from, end=self.source_date_to,
            ))

        Plan = self.env['gec.activity.plan']
        existing = {
            plan.analytic_account_id.id: plan
            for plan in Plan.search([
                ('activity_id', '=', self.activity_id.id),
                ('date_from', '=', self.target_date_from),
                ('date_to', '=', self.target_date_to),
            ])
        }

        created = Plan
        vals_list = []
        for account_id, quantity in quantities.items():
            planned = quantity * self.factor / 100.0
            if account_id in existing:
                if self.overwrite:
                    existing[account_id].planned_quantity = planned
                    created |= existing[account_id]
                continue
            vals_list.append({
                'activity_id': self.activity_id.id,
                'analytic_account_id': account_id,
                'date_from': self.target_date_from,
                'date_to': self.target_date_to,
                'planned_quantity': planned,
            })
        created |= Plan.create(vals_list)

        return {
            'type': 'ir.actions.act_window',
            'name': _("Planned Consumption"),
            'res_model': 'gec.activity.plan',
            'view_mode': 'list,pivot,form',
            'domain': [('id', 'in', created.ids)],
        }
