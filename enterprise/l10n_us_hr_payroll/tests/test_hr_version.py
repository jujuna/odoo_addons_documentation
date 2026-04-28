# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests import TransactionCase, tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestHrVersion(TransactionCase):
    def test_default_hr_version_creation(self):
        """ Ensure no constraints trigger when creating a default contract template. """
        self.env.company.state_id = self.env.ref("base.state_us_5")
        self.env['hr.version'].create({'name': 'test'})
