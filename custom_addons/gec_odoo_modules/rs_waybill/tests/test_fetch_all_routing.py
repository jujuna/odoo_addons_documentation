"""Fetch All routing: get_waybills returns the login's outgoing waybills (no SELLER_TIN),
get_buyer_waybills the incoming. An internal transport waybill (seller = buyer = us) is synced once,
by the seller path, listed in Sent and Received."""

from ast import literal_eval
from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon

OWN_TIN = '400777001'
OTHER_OWN_TIN = '400777002'
EXTERNAL_TIN = '400777999'


@tagged('post_install', '-at_install')
class TestFetchAllRouting(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'vat': OWN_TIN})
        cls.other_company = cls.env['res.company'].create({
            'name': 'Routing Sister Co', 'vat': OTHER_OWN_TIN})

    def _route(self, sync_method, rows):
        """Run one Fetch All path on `rows`; return {direction: {company: [row ids]}}."""
        seen = {}

        def capture(wb_self, rows_, direction, overrides):
            seen.setdefault(direction, {})[wb_self.env.company] = [r['ID'] for r in rows_]
            return len(rows_), 0, 0

        Waybill = type(self.env['rs.waybill'])
        with patch.object(Waybill, '_fetch_waybills_chunked', return_value=rows), \
             patch.object(Waybill, '_process_rs_rows', capture):
            getattr(self.env['rs.waybill'].with_company(self.company), sync_method)()
        return seen

    def test_sent_waybills_without_seller_tin_are_synced(self):
        rows = [{'ID': '1', 'BUYER_TIN': EXTERNAL_TIN}]
        seen = self._route('_sync_seller_waybills_one', rows)
        self.assertEqual(seen.get('seller', {}).get(self.company), ['1'],
                         "a sent waybill must not be dropped because RS sends no SELLER_TIN")

    def test_internal_transport_goes_to_the_seller_path(self):
        rows = [{'ID': '2', 'BUYER_TIN': OWN_TIN}]
        seen = self._route('_sync_seller_waybills_one', rows)
        self.assertEqual(seen.get('seller', {}).get(self.company), ['2'])

    def test_sale_to_a_sister_company_is_left_to_its_buyer_path(self):
        rows = [{'ID': '3', 'BUYER_TIN': OTHER_OWN_TIN}]
        seen = self._route('_sync_seller_waybills_one', rows)
        self.assertNotIn('seller', seen)

    def test_rows_of_an_unknown_taxpayer_are_skipped_and_logged(self):
        self.company.write({'vat': '400777555'})
        rows = [{'ID': '4', 'SELLER_TIN': EXTERNAL_TIN, 'BUYER_TIN': '400777888'}]
        with self.assertLogs('odoo.addons.rs_waybill.models.rs_waybill_sync', 'WARNING') as logs:
            seen = self._route('_sync_seller_waybills_one', rows)
        self.assertFalse(seen)
        self.assertIn('match no company Tax ID', logs.output[0])

    def test_received_waybills_are_synced_and_internal_ones_left_to_seller(self):
        rows = [
            {'ID': '5', 'SELLER_TIN': EXTERNAL_TIN, 'BUYER_TIN': OWN_TIN},
            {'ID': '6', 'SELLER_TIN': OWN_TIN, 'BUYER_TIN': OWN_TIN},
            {'ID': '7', 'SELLER_TIN': EXTERNAL_TIN},
        ]
        seen = self._route('_sync_buyer_waybills_one', rows)
        self.assertEqual(seen.get('buyer', {}).get(self.company), ['5', '7'],
                         "row 7 has no BUYER_TIN and belongs to the company that fetched it")

    def test_internal_transport_is_listed_in_sent_and_received(self):
        waybill = self.make_waybill(waybill_type='1', seller_tin=OWN_TIN, buyer_tin=OWN_TIN,
                                    state='active')
        Waybill = self.env['rs.waybill'].with_company(self.company)
        for xmlid in ('rs_waybill.action_rs_waybill_given', 'rs_waybill.action_rs_waybill_received'):
            domain = literal_eval(self.env.ref(xmlid).domain)
            self.assertIn(waybill, Waybill.search(domain), "%s must list it" % xmlid)

    def _process(self, direction, rs_id):
        """Run the row engine on one row; the per-row commit is stubbed (the test cursor forbids
        it)."""
        Waybill = type(self.env['rs.waybill'])
        Service = type(self.env['rs.waybill.soap.service'])
        with patch.object(Service, '_get_client', return_value=(None, 'su', 'sp', None)), \
             patch.object(Service, 'get_full_waybill_with_client', return_value=({'ID': rs_id}, [])), \
             patch.object(Waybill, '_map_rs_waybill_vals', return_value={}), \
             patch.object(Waybill, '_goods_lines_changed', return_value=False), \
             patch.object(self.env.cr, 'commit', lambda: None):
            self.env['rs.waybill'].with_company(self.company)._process_rs_rows(
                [{'ID': rs_id}], direction, {})

    def test_seller_path_takes_over_a_waybill_stored_as_transporter(self):
        """Our own sale that we also carry can arrive first on the transporter feed (no SELLER_TIN);
        the seller path takes it over."""
        waybill = self.make_waybill(waybill_direction='transporter', rs_internal_id='555001',
                                    seller_tin=OWN_TIN, buyer_tin=EXTERNAL_TIN)
        self._process('seller', '555001')
        self.assertEqual(waybill.waybill_direction, 'seller')

    def test_transporter_path_never_takes_over_a_seller_waybill(self):
        waybill = self.make_waybill(rs_internal_id='555002', seller_tin=OWN_TIN,
                                    buyer_tin=EXTERNAL_TIN)
        self._process('transporter', '555002')
        self.assertEqual(waybill.waybill_direction, 'seller')

    def test_fetch_filters_by_creation_date_only(self):
        """Only the creation date is sent as a filter; RS applies every date filter, so the others
        stay empty."""
        Service = type(self.env['rs.waybill.soap.service'])
        sent = {}

        def capture(svc, client, history, su, sp, method_name, params=None, row_tag='Table'):
            sent[method_name] = params
            return []

        with patch.object(Service, '_get_client', return_value=(None, 'su', 'sp', None)), \
             patch.object(Service, '_call_datatable', capture):
            self.service.get_waybills('2026-09-22', '2026-09-25')
            self.service.get_buyer_waybills('2026-09-22', '2026-09-25')
        for method in ('get_waybills', 'get_buyer_waybills'):
            params = sent[method]
            self.assertEqual((params['create_date_s'], params['create_date_e']),
                             ('2026-09-22', '2026-09-25'), method)
            for name in ('begin_date', 'delivery_date', 'close_date'):
                self.assertIsNone(params[name + '_s'], '%s %s_s' % (method, name))
                self.assertIsNone(params[name + '_e'], '%s %s_e' % (method, name))
