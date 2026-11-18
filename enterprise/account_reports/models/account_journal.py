from odoo import api, fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    is_tax_return_journal = fields.Boolean(
        compute='_compute_is_tax_return_journal',
    )

    @api.depends('company_id')
    def _compute_is_tax_return_journal(self):
        for journal in self:
            journal.is_tax_return_journal = journal == journal.company_id.account_tax_return_journal_id

    @api.model_create_multi
    def create(self, vals_list):
        journals = super().create(vals_list)

        # Creating a journal might invalidate snapshots if journal groups are in use (the default group might need it, it will have to be in the options)
        if self.env['account.journal.group'].search([], limit=1):
            self.env.ref('account_reports.ir_cron_create_snapshots')._trigger()

        return journals

    def write(self, vals):
        rslt = super().write(vals)

        if 'journal_group_id' in vals:
            # Might change the content of the default journal group ; snapshots need refresh
            self.env.ref('account_reports.ir_cron_create_snapshots')._trigger()

        return rslt
