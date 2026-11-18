from odoo import api, models
from odoo.fields import Domain


class AccountLockException(models.Model):
    _inherit = 'account.lock_exception'

    @api.model_create_multi
    def create(self, vals_list):
        exceptions = super().create(vals_list)

        if exceptions_impacting_snapshots := exceptions.filtered(lambda x: x.lock_date_field in ('tax_lock_date', 'fiscalyear_lock_date')):
            exceptions_impacting_snapshots._garbage_collect_report_snapshots_for_lock_exception()

        exceptions._create_report_snapshot_triggers_at_end_datetime()

        return exceptions

    def write(self, vals):
        rslt = super().write(vals)

        if any(lock_date_field in vals.get('lock_date_field', {}) for lock_date_field in ('tax_lock_date', 'fiscalyear_lock_date')):
            self._garbage_collect_report_snapshots_for_lock_exception()

        if 'end_datetime' in vals:
            self._create_report_snapshot_triggers_at_end_datetime()

        return rslt

    def _garbage_collect_report_snapshots_for_lock_exception(self):
        self.env['account.report.snapshot']._acquire_snapshot_lock()

        generic_tax_report = self.env.ref('account.generic_tax_report')
        snapshot_deletion_domains = []
        for lock_exception in self:
            # For simplicity, we consider all branches are impacted, and need garbage collection of their snapshots, even if they have a more
            # restrictive lock date themselves.
            impacted_branches = self.env['res.company'].sudo().search([('id', 'child_of', lock_exception.company_id.id)])

            exception_violation_domain = [('company_id', 'in', impacted_branches.ids)]
            if lock_exception.lock_date:
                exception_violation_domain.append(('date', '>', lock_exception.lock_date))

            if lock_exception.lock_date_field == 'tax_lock_date':
                exception_violation_domain.append(('report_id.root_report_id', '=', generic_tax_report.id))

            snapshot_deletion_domains.append(exception_violation_domain)

        self.env['account.report.snapshot'].sudo().search(Domain.OR(snapshot_deletion_domains)).unlink()

    def _create_report_snapshot_triggers_at_end_datetime(self):
        for end_datetime in set(self.filtered(lambda x: x.lock_date_field in ('tax_lock_date', 'fiscalyear_lock_date')).mapped('end_datetime')):
            if end_datetime:
                self.env.ref('account_reports.ir_cron_create_snapshots')._trigger(at=end_datetime)
