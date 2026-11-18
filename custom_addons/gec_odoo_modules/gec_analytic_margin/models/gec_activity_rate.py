from odoo import api, models, fields, _


class GecActivityRate(models.Model):
    """What one unit of an activity cost in one period, written by every allocation run.

    Deleted with its run, so history never disagrees with the lines it describes."""
    _name = 'gec.activity.rate'
    _description = 'Activity Rate History'
    _order = 'date_from desc, activity_id'
    _rec_name = 'activity_id'

    activity_id = fields.Many2one(
        'gec.activity', required=True, ondelete='cascade', index=True,
    )
    rule_id = fields.Many2one('gec.allocation.rule', ondelete='set null')
    run_id = fields.Many2one(
        'gec.allocation.run', required=True, ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(related='run_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')

    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)

    rate_mode = fields.Selection(
        [('actual', 'Actual'), ('standard', 'Standard')],
        required=True,
    )
    driver_label = fields.Char(string='Unit')
    rate = fields.Float(
        string='Cost per Unit', digits=(16, 4),
        help="What one unit of this activity cost in this period.",
    )
    quantity = fields.Float(
        string='Quantity Measured',
        help="Driver units counted in the period — hours, tickets, deployments.",
    )
    practical_capacity = fields.Float(
        help="Capacity the activity was assumed to have, if one was set.",
    )
    capacity_used = fields.Float(
        string='Capacity Used (%)',
        help="Measured quantity as a percentage of practical capacity. Below "
             "100% means idle capacity was held back from cost objects.",
    )
    pool_amount = fields.Monetary(
        string='Pool', help="Source cost available to this rule in the period.",
    )
    charged_amount = fields.Monetary(
        string='Charged', help="What was actually moved onto cost objects.",
    )
    variance_amount = fields.Monetary(
        string='Not Charged',
        help="Pool less what was charged out. With a standard rate this is the "
             "absorption variance; with a practical capacity it is the cost of "
             "unused capacity. Either way it stays on the source rather than "
             "being pushed onto products.",
    )
    # Split unabsorbed cost into over-spending vs unused capacity: they call for opposite responses.
    volume_variance = fields.Monetary(
        string='Idle Capacity',
        help="The part of Not Charged caused by running below practical "
             "capacity: unused units times the rate. Blank when no practical "
             "capacity is set, because without one there is no volume to miss.",
    )
    spending_variance = fields.Monetary(
        string='Rate Variance',
        help="The part of Not Charged caused by the pool differing from what "
             "the rate assumed. With an actual rate this is always zero by "
             "construction — the rate is derived from the pool. With a standard "
             "rate it is what the activity over- or underspent.",
    )
    unused_quantity = fields.Float(
        string='Idle Units',
        help="Practical capacity less the quantity measured.",
    )

    @api.model
    def _split_variance(self, pool, charged, rate, capacity):
        """Split (pool - charged) into volume and spending; practical capacity stands in for budgeted volume.
        volume = -(capacity - quantity) x rate; spending = pool + capacity x rate;
        costs negative; no capacity: all spending."""
        variance = pool - charged
        if not capacity:
            return 0.0, variance
        spending = pool + capacity * rate
        return variance - spending, spending

    def action_open_run(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Allocation Run"),
            'res_model': 'gec.allocation.run',
            'res_id': self.run_id.id,
            'view_mode': 'form',
        }
