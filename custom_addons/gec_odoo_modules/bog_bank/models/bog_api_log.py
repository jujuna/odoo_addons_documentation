from odoo import fields, models


class BogApiLog(models.Model):
    _name = 'bog.api.log'
    _description = 'Bank of Georgia API Log'
    _inherit = ['gec.bank.api.log.mixin']

    connection_id = fields.Many2one('bog.connection', string='Connection', required=True,
                                    ondelete='restrict', index=True)
    company_id = fields.Many2one(related='connection_id.company_id', store=True, index=True)
    # BOG reports business failures inside a 200 OK, so keep it apart from the HTTP status.
    result_code = fields.Integer(string='Result Code')
    # The reference BOG support asks for; returned on every response.
    correlation_id = fields.Char(string='Correlation ID', index=True)
    # Seconds from the Retry-After header of a 429.
    retry_after = fields.Integer(string='Retry After (s)')
    # Set on calls that create or delete a document; the endpoint prefix alone cannot tell them from polls.
    is_money_movement = fields.Boolean(string='Money Movement', index=True, default=False)

    def _gec_bank_log_vacuum_domain(self):
        return [('is_money_movement', '=', False)]
