from datetime import datetime
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged

from odoo.addons.rs_einvoice.models import rs_einvoice_cron

from . import stub_responses
from .common import RsEinvoiceCommon


@tagged('post_install', '-at_install')
class TestCron(RsEinvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company = cls.setup_other_company()['company']
        cls.vendor = cls.env['res.partner'].create({'name': 'Supplier LLC', 'vat': '404404404'})

    def _sent(self, move, rs_id):
        move.action_post()
        move.write({'rs_einv_id': rs_id, 'rs_einv_status': '2'})
        return move

    def test_status_cron_serves_a_company_when_another_has_no_responsible_user(self):
        foreign = self.env['account.move'].with_company(self.other_company).create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'company_id': self.other_company.id,
            'invoice_line_ids': [Command.create({'name': 'Service', 'price_unit': 10})],
        })
        self._sent(foreign, '700999')
        self._sent(self._invoice(invoice_date='2026-09-20'), '700123')
        self.env.flush_all()
        self.env.cr.execute("UPDATE account_move SET write_date = now() - interval '1 day' WHERE id = %s", [foreign.id])
        foreign.invalidate_recordset(['write_date'])
        cron = self.env['rs.einvoice.cron']
        passes = [(self.company, self.env.user)]
        with self._patch_rsge(chek=stub_responses.chek(), get_invoice=stub_responses.get_invoice(status=2)) as rsge:
            with patch.object(type(cron), '_rs_company_passes', return_value=passes):
                refreshed = cron._cron_refresh_status(False, batch_size=1)
        self.assertEqual(refreshed, 1)
        self.assertEqual(rsge.calls.count('get_invoice'), 1)

    def _sync_as(self, company, rs_id):
        """(created, partner lookup mock) of one buyer-sync pass of ``company`` over rs.ge's one new bill ``rs_id``."""
        row = {
            'id': rs_id, 'status': 1, 'saident_no_s': '404404404', 'buyer_un_id': 731937, 'k_type': 0,
            'operation_dt': '2026-09-20T00:00:00',
        }
        service = type(self.env['rs.soap.service'])
        ambiguous = (self.env['res.partner'], self.vendor)
        with (
            patch.object(service, '_check_auth'),
            patch.object(service, '_rs_company_un_id', return_value=731937),
            patch.object(service, 'get_user_invoices', return_value=[row]),
            patch.object(rs_einvoice_cron, '_rs_find_partner_by_tin', return_value=ambiguous) as find_partner,
        ):
            created = self.env['rs.einvoice.cron'].with_company(company)._sync_one_user(datetime(2026, 9, 19), datetime(2026, 9, 21))
        return created, find_partner

    def test_buyer_sync_skips_a_bill_the_company_of_the_same_tax_id_holds(self):
        branch = self.env['res.company'].create({'name': 'Branch', 'parent_id': self.company.id, 'vat': self.company.vat})
        self.env.user.company_ids = [Command.link(branch.id)]
        self.env['account.journal'].create({'name': 'Branch Bills', 'code': 'BBL', 'type': 'purchase', 'company_id': branch.id})
        self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
            'invoice_date': '2026-09-20',
            'rs_einv_id': '555300',
            'rs_einv_status': '1',
        })
        created, find_partner = self._sync_as(branch, 555300)
        self.assertEqual(created, 0)
        find_partner.assert_not_called()
        find_partner = self._sync_as(branch, 555301)[1]
        find_partner.assert_called_once()
