"""RS.GE's answers to our carrier actions (Activate, Save) are checked, so Odoo never shows active
or saved when RS.GE refused.
"""

from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestTransporterReplies(RsWaybillCommon):

    def _rs_answers(self, **calls):
        client = SimpleNamespace(service=SimpleNamespace(**{k: (lambda v: lambda **kw: v)(v)
                                                             for k, v in calls.items()}))
        service = type(self.env['rs.waybill.soap.service'])
        return patch.object(service, '_get_client', return_value=(client, 'su', 'sp', None))

    def _service(self):
        return self.env['rs.waybill.soap.service']

    def test_activate_success_returns_the_number(self):
        with self._rs_answers(send_waybill_transporter=SimpleNamespace(
                send_waybill_transporterResult=1, waybill_number='0123456')):
            self.assertEqual(self._service().send_transporter_waybill(1, False), '0123456')

    def test_activate_refusal_is_shown(self):
        with self._rs_answers(send_waybill_transporter=SimpleNamespace(
                send_waybill_transporterResult=-1, waybill_number=None)), \
                self.assertRaises(UserError):
            self._service().send_transporter_waybill(1, False)

    def test_activate_unexpected_answer_is_not_taken_as_a_number(self):
        with self._rs_answers(send_waybill_transporter='<weird/>'), self.assertRaises(UserError):
            self._service().send_transporter_waybill(1, False)

    def test_activate_failure_leaves_the_waybill_not_active(self):
        waybill = self.make_waybill(waybill_direction='transporter', state='draft',
                                    waybill_status='8', rs_internal_id=992001)
        with self._rs_answers(send_waybill_transporter='<weird/>'), \
                patch.object(type(waybill), '_validate_transporter_driver_fields'), \
                self.assertRaises(UserError):
            waybill.action_active_transporter()
        self.assertEqual(waybill.state, 'draft')

    def test_save_refusal_is_shown(self):
        with self._rs_answers(save_waybill_transporter=-1), self.assertRaises(UserError):
            self._service().save_transporter_waybill(1, 'AA-001-AA', '01001000001')

    def test_save_success_passes(self):
        with self._rs_answers(save_waybill_transporter=1):
            self._service().save_transporter_waybill(1, 'AA-001-AA', '01001000001')
