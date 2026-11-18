"""RS.GE calls on a waybill that was never saved there are refused (rs_internal_id is False)."""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestRsIdGuard(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.waybill = self.make_waybill()
        self.assertFalse(self.waybill.rs_internal_id)

    def _assert_refused(self, method, *args, **kwargs):
        """The call is refused with the standard message and never reaches the SOAP layer."""
        Service = type(self.env['rs.waybill.soap.service'])
        with patch.object(Service, '_get_client') as get_client:
            with self.assertRaises(UserError) as e:
                getattr(self.waybill, method)(*args, **kwargs)
        self.assertIn('save the waybill to RS.GE first', e.exception.args[0])
        get_client.assert_not_called()

    def test_refuse_is_guarded(self):
        self._assert_refused('action_refuse_waybill')

    def test_delete_is_guarded(self):
        self._assert_refused('action_delete_waybill')

    def test_reject_is_guarded(self):
        self._assert_refused('action_reject_waybill')

    def test_save_transporter_is_guarded(self):
        self._assert_refused('action_save_transporter')

    def test_activate_transporter_is_guarded(self):
        self._assert_refused('action_active_transporter')

    def test_close_transporter_is_guarded(self):
        self._assert_refused('action_close_transporter')

    def test_print_pdf_is_guarded(self):
        self._assert_refused('action_print_pdf')

    def test_delete_does_not_unlink_an_unsaved_waybill(self):
        """Delete must not reach RS with id 0, and the record must stay for the operator to fix."""
        with self.assertRaises(UserError):
            self.waybill.action_delete_waybill()
        self.assertTrue(self.waybill.exists())

    def test_the_guard_lets_a_saved_waybill_through(self):
        """It gates on the id only, nothing else about the waybill's state."""
        self.waybill.rs_internal_id = 990001
        self.waybill._require_rs_id()
