from odoo import fields, models

# Logs of paths containing this are the money audit trail and are never vacuumed.
GC_PROTECTED_FRAGMENT = 'transfers'


class TbcApiLog(models.Model):
    _name = 'tbc.api.log'
    _description = 'TBC Bank API Log'
    _inherit = ['gec.bank.api.log.mixin']

    connection_id = fields.Many2one('tbc.connection', string='Connection', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='connection_id.company_id', store=True, index=True)

    def _gec_bank_log_vacuum_domain(self):
        return [('endpoint', 'not like', GC_PROTECTED_FRAGMENT)]
