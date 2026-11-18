from odoo import models, fields


class GecRevenueStream(models.Model):
    """What kind of revenue an amount is (license, maintenance, services).

    Apart from margin components on purpose: a stream changes no P&L figure, it only tells how much revenue recurs."""
    _name = 'gec.revenue.stream'
    _description = 'Revenue Stream'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    recurring = fields.Boolean(
        help="Revenue that renews without a new sale — annual maintenance, "
             "support, subscriptions. The benchmark's single best predictor of "
             "margin: a strong on-premises vendor earns 55–70% of revenue this "
             "way. Licenses and project work are one-off, however large.",
    )

    standard_product = fields.Boolean(
        string='Standard Product',
        help="Revenue from the product as it stands — licenses, maintenance, "
             "subscriptions — as opposed to work made for one customer. The "
             "benchmark reads a vendor's scalability off this share: 50–70% for a "
             "healthy one, 75–90% for a strong one.",
    )

    _code_uniq = models.Constraint('UNIQUE(code)', 'A revenue stream with this code already exists.')
