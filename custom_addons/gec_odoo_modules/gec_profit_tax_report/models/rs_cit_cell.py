from odoo import fields, models


class RsCitCell(models.Model):
    """One row of the profit tax declaration, as the rs.ge form lays it out."""
    _name = 'rs.cit.cell'
    _description = 'rs.ge Profit Tax Declaration Row'
    _order = 'sequence, id'

    code = fields.Char(required=True, help="Row number on the form, e.g. 16.1.1.")
    name = fields.Char(required=True, help="Row text exactly as the rs.ge form prints it.")
    part = fields.Selection([('3', 'Part III'), ('4', 'Part IV')], required=True, default='3')
    sequence = fields.Integer(default=10)
    parent_id = fields.Many2one('rs.cit.cell', ondelete='restrict', help="The row this one is a part of.")
    kind = fields.Selection([('auto', 'From Accounting'),
                             ('calc', 'Formula'),
                             ('manual', 'Typed In'),], required=True,
                            help="From Accounting: read from posted journal items of the month. "
                                 "Formula: calculated from other rows. Typed In: entered by the accountant.")
    measure = fields.Selection([('balance', 'Debit - Credit'),
                                ('debit', 'Debits Only'),
                                ('market', 'Market Price Difference'),
                                ('register', 'Taxed Items Recovered')], required=True, default='balance',
                               help="How journal items of the month count on a row read from accounting. "
                                    "Debits Only: payments such as dividends, advances or loans given, so the "
                                    "accrual or the later settlement on the same account does not cancel them out. "
                                    "Market Price Difference: invoice lines with a market value, compared with "
                                    "their amount (lines 16.3 and 16.4). Taxed Items Recovered: money back on amounts taxed "
                                    "earlier on lines 18.1.1, 18.1.3, 18.1.4, 18.2 and 18.3 (lines 27.1 and 27.2). "
                                    "No account can feed these two kinds of rows.")

    columns = fields.Selection([('both', 'Columns 2 and 3'), ('col2', 'Column 2 Only'), ('col3', 'Column 3 Only')],
                               required=True, default='both',
                               help="Amount columns the rs.ge form shows for this row.")

    _code_uniq = models.Constraint('UNIQUE(code)', 'Row code must be unique.')
