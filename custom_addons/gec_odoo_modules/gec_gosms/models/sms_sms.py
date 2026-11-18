from collections import defaultdict

from odoo import api, fields, models


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    record_company_id = fields.Many2one('res.company', 'Company', ondelete='set null')
    gosms_urgent = fields.Boolean("Deliver Even if Blocked", copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['record_company_id'] = vals.get('record_company_id') or self.env.company.id
        return super().create(vals_list)

    def _split_by_api(self):
        sms_by_company = defaultdict(lambda: self.env['sms.sms'])
        todo_via_super = self.browse()
        for sms in self:
            sms_by_company[sms._get_sms_company()] += sms
        for company, company_sms in sms_by_company.items():
            if company.gosms_sms_enabled:
                sms_api = company._get_sms_api_class()(self.env)
                sms_api._set_company(company)
                yield sms_api, company_sms
            else:
                todo_via_super += company_sms
        if todo_via_super:
            yield from super(SmsSms, todo_via_super)._split_by_api()

    def _get_sms_company(self):
        return self.mail_message_id.record_company_id or self.record_company_id or super()._get_sms_company()

    def _get_send_batch_size(self):
        # the cron calls this on an empty recordset: look at every company, sudo because the cron is not limited to its own
        companies = self._get_sms_company() if self else self.env['res.company'].sudo().search([('gosms_sms_enabled', '=', True)], limit=1)
        if any(companies.mapped('gosms_sms_enabled')):
            return self.env['ir.config_parameter'].sudo().get_int('gec_gosms.session.batch.size') or 10
        return super()._get_send_batch_size()

    def _handle_call_result_hook(self, results):
        """The core hook reads every result, not only its records: a GoSMS "no credit" result must not open the Odoo credit notice."""
        other_sms = self - self.filtered(lambda sms: sms._get_sms_company().gosms_sms_enabled)
        other_uuids = set(other_sms.mapped('uuid'))
        super(SmsSms, other_sms)._handle_call_result_hook([result for result in results if result['uuid'] in other_uuids])
