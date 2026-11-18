from odoo import api, fields, models

from .rs_form30_declaration import _number, _refuse_in_file_rows
from .rs_form30_warning import _localize_warning

# Portal import order, not the on-screen order.
HEADERS = ['განაცემის მიმღების საიდენტიფიკაციო/ პირადი ნომერი', 'განაცემის მიმღების სახელი', 'განაცემის მიმღების გვარი', 'მომსახურების სახე',
    'განაცემის ოდენობა (თანხა)', 'მისამართი ', 'პირის რეზიდენტობა (ქვეყანა) ']


class RsForm30ServiceLine(models.Model):
    _name = 'rs.form30.service.line'
    _description = 'rs.ge Form 30 Untaxed Service Payment Line'
    _order = 'last_name, id'

    declaration_id = fields.Many2one('rs.form30.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    partner_id = fields.Many2one('res.partner', string='Recipient', ondelete='set null')
    withholding_line_id = fields.Many2one('account.payment.withholding.line', string='Withholding Line', ondelete='set null')
    payment_id = fields.Many2one('account.payment', related='withholding_line_id.payment_id', string='Payment')
    move_id = fields.Many2one('account.move', string='Journal Entry', ondelete='set null', index='btree_not_null', readonly=True,
        help="The journal entry this row declares; can belong to a branch of the declaration's company (payments are reconciled within one root "
        "company).")
    date = fields.Date(string='Payment Date')
    settlement_payment_ids = fields.Many2many('account.payment', 'rs_form30_service_payment_rel', 'line_id', 'payment_id', string='Payments',
        readonly=True, copy=False,
        help="The payments whose cash this row declares; can belong to a branch of the declaration's company (payments are reconciled within one "
        "root company).")
    settlement_statement_line_ids = fields.Many2many('account.bank.statement.line', 'rs_form30_service_statement_rel', 'line_id', 'statement_line_id',
        string='Bank Transactions', readonly=True, copy=False,
        help="The bank transactions whose cash this row declares; can belong to a branch of the declaration's company (payments are reconciled "
        "within one root company).")
    settlement_move_ids = fields.Many2many('account.move', 'rs_form30_service_move_rel', 'line_id', 'move_id', string='Offset Entries',
        readonly=True, copy=False, help="The offset entries whose settlement this row declares; can belong to a branch of the declaration's company.")
    identification = fields.Char(string='ID Number')
    first_name = fields.Char(string='First Name')
    last_name = fields.Char(string='Last Name')
    address = fields.Char()
    country_id = fields.Many2one('res.country', string='Residency', ondelete='restrict')
    service_type_id = fields.Many2one('rs.form30.service.type', string='Service Type', ondelete='restrict')
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    warning = fields.Char()
    warning_display = fields.Char(compute='_compute_warning_display')
    issue_level = fields.Selection([('note', 'Note'), ('warning', 'Warning'), ('blocker', 'Blocker')], string='Issue', readonly=True)
    in_file = fields.Boolean(string='In File', readonly=True, copy=False, help="This row went into the last exported file of its declaration.")
    exported_on = fields.Date(string='Exported On', readonly=True, copy=False)

    @api.depends('warning')
    @api.depends_context('lang')
    def _compute_warning_display(self):
        for line in self:
            line.warning_display = _localize_warning(line.env, line.warning)

    def write(self, vals):
        _refuse_in_file_rows(self)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_file(self):
        _refuse_in_file_rows(self)

    @api.model
    def _rs_form30_headers(self):
        return HEADERS

    def _export_values(self):
        self.ensure_one()
        return [self.identification or '', self.first_name or '', self.last_name or '', self.service_type_id.code or '', _number(self.amount),
            self.address or '', self.country_id.rs_form30_code or '']
