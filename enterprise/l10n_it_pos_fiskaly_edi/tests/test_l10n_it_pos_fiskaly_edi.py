from odoo.addons.l10n_it_pos_fiskaly.tests.common import TestL10nItPosFiskalyCommon
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nItPosFiskalyEdi(TestL10nItPosFiskalyCommon):

    def test_codice_fiscale_is_the_tax_id_number(self):
        self.company.l10n_it_codice_fiscale = 'MRTMTT91D08F205J'
        self.assertEqual(self.company._l10n_it_fiskaly_tax_id_number(), 'MRTMTT91D08F205J')
