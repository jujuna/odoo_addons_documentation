# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user


class TestQualityReport(TransactionCase):

    def test_quality_worksheet_report_access(self):
        check = self.env['quality.check'].create({
            'team_id': self.env.ref('quality.quality_alert_team0').id,
            'test_type_id': self.env.ref('quality_control.test_type_passfail').id,
        })
        portal_user = new_test_user(self.env, login='portal_user', groups='base.group_portal')
        with self.assertRaises(AccessError):
            self.env['ir.actions.report'].with_user(portal_user)._render_qweb_html('quality_control.quality_worksheet', check.ids)
