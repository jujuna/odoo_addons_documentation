# Part of Odoo. See LICENSE file for full copyright and licensing details.

import odoo
from odoo.addons.l10n_be_pos_blackbox.tests.common import TestL10nBePosBlackboxCommon
from odoo.addons.point_of_sale.tests.test_order_receipt import TestPosOrderReceipt


@odoo.tests.tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nBePosBlackboxOrderReceipt(TestL10nBePosBlackboxCommon, TestPosOrderReceipt):

    def start_receipt_data_tour(self):
        self.start_tour(
            "/pos/ui/%d" % self.main_pos_config.id,
            'test_l10n_be_pos_blackbox_receipt_data',
            login="pos_admin",
        )

    def test_receipt_data(self):
        super().test_receipt_data()
