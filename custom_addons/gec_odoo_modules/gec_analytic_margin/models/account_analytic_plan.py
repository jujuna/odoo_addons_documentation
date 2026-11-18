from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class AccountAnalyticPlan(models.Model):
    """Mark which business question a plan answers (product, department) for the margin statement.

    Unset by default: a reading without a plan behind it is not offered."""
    _inherit = 'account.analytic.plan'

    gec_section_key = fields.Selection(
        [('product', 'Products'), ('department', 'Departments')],
        string='Margin Statement Reading',
        help="Offer this plan as its own reading of the Analytic Margin "
             "Statement.\n\n"
             "Set Products on the plan whose accounts are your product or "
             "service lines, and the statement gains a By Products view — one "
             "P&L per product line, allocated overhead included, because the "
             "accounts are analytic accounts like any other.\n\n"
             "Leave it empty and the plan still appears, inside By Analytic "
             "Plans with the rest.",
    )

    # No "inherit from project" setting: Odoo already copies plan columns from a project
    # to its timesheets; only items posted before the project's tag was set stay untagged.
    gec_items_behind_count = fields.Integer(
        string='Items Missing This Tag', compute='_compute_gec_items_behind',
        help="Analytic items logged on a project that names an account in this "
             "plan, but which carry none themselves — posted before the project "
             "was filled in.",
    )

    def _compute_gec_items_behind(self):
        Line = self.env['account.analytic.line']
        for plan in self:
            plan.gec_items_behind_count = (
                Line._gec_items_behind_project_tag(plan) if plan.id else 0
            )

    def action_gec_fill_from_projects(self):
        """Give posted items the tag their project already names.

        A button, not automatic: it rewrites history, so closed periods may stop matching their allocation run."""
        self.ensure_one()
        filled = self.env['account.analytic.line']._gec_backfill_project_tags(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if filled else 'warning',
                'message': _(
                    "%(count)s analytic item(s) now carry their project's "
                    "%(plan)s. Recompute any allocation run covering them — "
                    "what those periods measure has changed.",
                    count=filled, plan=self.display_name,
                ) if filled else _(
                    "Nothing to fill. Either no project names a %(plan)s, or "
                    "every item logged on one already carries it.",
                    plan=self.display_name,
                ),
                'sticky': bool(filled),
            },
        }

    @api.constrains('gec_section_key')
    def _check_gec_section_key_is_unique(self):
        for plan in self.filtered('gec_section_key'):
            other = self.search([
                ('gec_section_key', '=', plan.gec_section_key),
                ('id', '!=', plan.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    "Plan %(other)s is already the %(key)s reading of the "
                    "margin statement. One reading, one plan — otherwise the "
                    "report would have to guess which of them you meant.",
                    other=other.display_name, key=plan.gec_section_key,
                ))
