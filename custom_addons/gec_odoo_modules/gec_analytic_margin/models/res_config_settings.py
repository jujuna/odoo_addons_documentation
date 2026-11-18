from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    group_gec_abc = fields.Boolean(
        string='Activity-Based Costing',
        implied_group='gec_analytic_margin.group_gec_abc',
        help="Spread shared costs — a development team, a support desk, an "
             "overhead pool — onto the products and business lines that "
             "actually consumed them, using measured drivers instead of typed "
             "percentages.\n\n"
             "Adds the costing menus and an Activity field on analytic "
             "distribution models. Switching it off hides them again; nothing "
             "already allocated is lost.",
    )

    # The scheduled action is inert until one of these is set, so it is opt-in.
    gec_allocation_cron_mode = fields.Selection(
        related='company_id.gec_allocation_cron_mode', readonly=False,
    )
    gec_pl_mode = fields.Selection(
        related='company_id.gec_pl_mode', readonly=False,
    )
    gec_allocation_cron_basis = fields.Selection(
        related='company_id.gec_allocation_cron_basis', readonly=False,
    )
    gec_allocation_cron_delay_days = fields.Integer(
        related='company_id.gec_allocation_cron_delay_days', readonly=False,
    )
