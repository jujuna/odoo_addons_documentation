"""Save, Send and Send to Transporter cannot run twice on RS.GE: the first click locks the waybill, a second one is
told to wait and sends nothing; one that waited finds the work done. Print keeps one PDF per waybill.
"""

from unittest.mock import patch

from odoo.exceptions import LockError, UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestSaveLock(RsWaybillCommon):

    def test_second_save_waits_and_sends_nothing(self):
        waybill = self.make_waybill(state='draft')
        self.add_line(waybill)
        service = type(self.env['rs.waybill.soap.service'])

        with patch.object(type(waybill), 'lock_for_update', side_effect=LockError("locked")), \
                patch.object(service, 'save_waybill', return_value={'id': 1, 'waybill_number': ''}) as save, \
                patch.object(self.env.cr, 'commit'), \
                self.assertRaisesRegex(UserError, 'already being sent'):
            waybill.action_save_to_rs()

        save.assert_not_called()

    def test_second_send_waits_and_sends_nothing(self):
        waybill = self.make_waybill(state='draft', rs_internal_id=970001)
        self.add_line(waybill)
        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(type(waybill), 'lock_for_update', side_effect=LockError("locked")), \
                patch.object(service, 'send_waybill') as send, \
                self.assertRaisesRegex(UserError, 'already being sent'):
            waybill.action_send_rs_waybill()
        send.assert_not_called()

    def test_a_send_that_waited_finds_it_active(self):
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=970002)
        with patch.object(type(self.env['rs.waybill.soap.service']), 'send_waybill') as send:
            waybill.action_send_rs_waybill()
        send.assert_not_called()

    def test_second_send_to_transporter_waits_and_creates_nothing(self):
        waybill = self.make_waybill(state='draft', transport_type='7')
        self.add_line(waybill)
        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(type(waybill), 'lock_for_update', side_effect=LockError("locked")), \
                patch.object(service, 'save_waybill') as save, \
                self.assertRaisesRegex(UserError, 'already being sent'):
            waybill.action_send_carrier_waybill()
        save.assert_not_called()

    def test_printing_twice_keeps_one_pdf(self):
        waybill = self.make_waybill(state='active', rs_internal_id=970003, rs_waybill_number='0970003')
        service = type(self.env['rs.waybill.soap.service'])
        for content in (b'%PDF-1 first', b'%PDF-1 second'):
            with patch.object(service, 'get_print_pdf', return_value=content):
                waybill.action_print_pdf()
        pdfs = self.env['ir.attachment'].search([('res_model', '=', 'rs.waybill'), ('res_id', '=', waybill.id)])
        self.assertEqual(len(pdfs), 1)
        self.assertEqual(bytes(pdfs.raw), b'%PDF-1 second', "refreshed with what RS.GE prints now")
