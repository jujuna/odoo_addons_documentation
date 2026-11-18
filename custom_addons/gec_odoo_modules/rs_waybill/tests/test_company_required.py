"""Every waybill has a company, and only that company's users see it."""

from psycopg2 import IntegrityError

from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestCompanyRequired(RsWaybillCommon):

    def test_a_waybill_without_company_is_refused(self):
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.make_waybill(company_id=False)
            self.env.flush_all()

    def test_no_company_is_not_visible_to_everyone(self):
        for model in ('rs.waybill', 'rs.waybill.line'):
            with self.subTest(model=model):
                rules = self.env['ir.access'].sudo().search(
                    [('model_id.model', '=', model), ('domain', '!=', False)])
                self.assertTrue(rules)
                self.assertFalse(any("'=', False" in rule.domain for rule in rules))
