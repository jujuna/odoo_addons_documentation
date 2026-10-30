from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestBlackboxUnlink(CommonPosTest):
    """Deleting a 'pos.blackbox.be' used by a pos.config with a POS ID must be refused"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.blackbox_be = cls.env['pos.blackbox.be'].create({
            'fdm_id': 'VCB01002601',
            'local_ip': '0.0.0.0',
        })

    def _link_blackbox_to_registered_config(self):
        self.pos_config_eur.write({
            'l10n_be_blackbox_be_id': self.blackbox_be.id,
            'l10n_be_pos_id': 'CPOS0031234567',
        })

    def test_unlink_unused_blackbox(self):
        self.blackbox_be.unlink()
        self.assertFalse(self.blackbox_be.exists())

    def test_unlink_blackbox_used_by_config(self):
        self._link_blackbox_to_registered_config()
        with self.assertRaises(UserError):
            self.blackbox_be.unlink()
        self.assertTrue(self.blackbox_be.exists())

    def test_unlink_blackbox_used_by_archived_config(self):
        self._link_blackbox_to_registered_config()
        self.pos_config_eur.active = False
        with self.assertRaises(UserError):
            self.blackbox_be.unlink()
        self.assertTrue(self.blackbox_be.exists())

    def test_unlink_blackbox_used_by_neutralized_config(self):
        self._link_blackbox_to_registered_config()
        # neutralize.sql resets the POS ID of configs linked to a blackbox
        self.pos_config_eur.l10n_be_pos_id = ''
        self.blackbox_be.unlink()
        self.assertFalse(self.blackbox_be.exists())
        self.assertFalse(self.pos_config_eur.l10n_be_blackbox_be_id)
