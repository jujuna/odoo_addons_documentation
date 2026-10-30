from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestPurchaseIntrastat(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.purchase_user = cls.env['res.users'].create({
            'name': 'Purchase User Test',
            'login': 'purchase_user_test',
            'email': 'purchase_user_test@example.com',
            'group_ids': [Command.set([cls.env.ref('purchase.group_purchase_user').id])],
        })

        cls.intrastat_code = cls.env['account.intrastat.code'].sudo().search([], limit=1)
        cls.product_a.intrastat_code_id = cls.intrastat_code

    def test_purchase_user_can_print_rfq_with_intrastat_product(self):
        po = self.env['purchase.order'].with_user(self.purchase_user).create({
            'partner_id': self.partner_a.id,
            'order_line': [Command.create({
                'product_id': self.product_a.id,
                'product_qty': 5.0,
                'price_unit': 100.0,
            })],
        })
        # This must NOT raise an AccessError.
        report = self.env['ir.actions.report'].with_user(self.purchase_user).with_context(force_report_rendering=True)
        with self.allow_pdf_render():
            report = report._render_qweb_pdf('purchase.report_purchasequotation', res_ids=po.ids)
        self.assertTrue(report)
