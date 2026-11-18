from odoo import fields, models

# The upload endpoints move money; their rows are the audit trail and are never vacuumed.
GC_PROTECTED_FRAGMENT = 'main/upload'


class BasisbankApiLog(models.Model):
    _name = 'basisbank.api.log'
    _description = 'Basis Bank API Log'
    _inherit = ['gec.bank.api.log.mixin']

    connection_id = fields.Many2one('basisbank.connection', string='Connection', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='connection_id.company_id', store=True, index=True)
    error_code = fields.Integer(string='Error Code')

    def _gec_bank_log_vacuum_domain(self):
        return [('endpoint', 'not like', GC_PROTECTED_FRAGMENT)]
