"""Live RS View drift detection: the popup tints only real differences."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestLiveViewDrift(RsWaybillCommon):

    def _live_snapshot(self, waybill, header, goods):
        Service = type(self.env['rs.waybill.soap.service'])
        snapshot = self.env['rs.waybill.live'].create({'waybill_id': waybill.id})
        with patch.object(Service, 'get_full_waybill', return_value=(header, goods)):
            snapshot._fetch_and_fill()
        return snapshot

    def _header(self, **overrides):
        vals = {'STATUS': '1', 'SELLER_TIN': '400111000'}
        vals.update(overrides)
        return vals

    def test_float_rounding_is_not_drift(self):
        """transport_cost 100.0 vs 100.00000000001 from RS is not a change."""
        waybill = self.make_waybill(rs_internal_id=960001, transport_cost=100.0)
        snapshot = self._live_snapshot(
            waybill, self._header(TRANSPORT_COAST='100.00000000001'), [])
        self.assertNotIn('transport_cost', snapshot.drift_field_names or '')

    def test_a_real_cost_change_is_still_drift(self):
        waybill = self.make_waybill(rs_internal_id=960002, transport_cost=100.0)
        snapshot = self._live_snapshot(
            waybill, self._header(TRANSPORT_COAST='250.0'), [])
        self.assertIn('transport_cost', snapshot.drift_field_names or '')

    def test_duplicate_goods_rows_are_compared_individually(self):
        """The same product twice (split quantities or prices) is compared row by row."""
        waybill = self.make_waybill(rs_internal_id=960003)
        self.add_line(waybill, quantity=10.0, unit_price=5.0, bar_code='X1', name='Widget')
        self.add_line(waybill, quantity=20.0, unit_price=5.0, bar_code='X1', name='Widget')

        snapshot = self._live_snapshot(waybill, self._header(), [
            {'BAR_CODE': 'X1', 'W_NAME': 'Widget', 'QUANTITY': '10', 'PRICE': '5'},
            {'BAR_CODE': 'X1', 'W_NAME': 'Widget', 'QUANTITY': '99', 'PRICE': '5'},
        ])

        statuses = sorted(snapshot.line_ids.mapped('status'))
        self.assertEqual(len(snapshot.line_ids), 2)
        self.assertIn('changed', statuses, "the changed duplicate row was not detected")
        self.assertTrue(snapshot.has_drift)

    def test_identical_duplicate_rows_report_no_drift(self):
        waybill = self.make_waybill(rs_internal_id=960004)
        self.add_line(waybill, quantity=10.0, unit_price=5.0, bar_code='X1', name='Widget')
        self.add_line(waybill, quantity=10.0, unit_price=5.0, bar_code='X1', name='Widget')

        snapshot = self._live_snapshot(waybill, self._header(), [
            {'BAR_CODE': 'X1', 'W_NAME': 'Widget', 'QUANTITY': '10', 'PRICE': '5'},
            {'BAR_CODE': 'X1', 'W_NAME': 'Widget', 'QUANTITY': '10', 'PRICE': '5'},
        ])

        self.assertEqual(snapshot.line_ids.mapped('status'), ['same', 'same'])

    def test_a_row_odoo_holds_twice_and_rs_only_once(self):
        """The surplus copy must surface as only_odoo, not silently match."""
        waybill = self.make_waybill(rs_internal_id=960005)
        self.add_line(waybill, quantity=10.0, unit_price=5.0, bar_code='X1', name='Widget')
        self.add_line(waybill, quantity=10.0, unit_price=5.0, bar_code='X1', name='Widget')

        snapshot = self._live_snapshot(waybill, self._header(), [
            {'BAR_CODE': 'X1', 'W_NAME': 'Widget', 'QUANTITY': '10', 'PRICE': '5'},
        ])

        self.assertEqual(sorted(snapshot.line_ids.mapped('status')),
                         ['only_odoo', 'same'])

    def test_a_row_only_rs_has(self):
        waybill = self.make_waybill(rs_internal_id=960006)
        snapshot = self._live_snapshot(waybill, self._header(), [
            {'BAR_CODE': 'X9', 'W_NAME': 'Surprise', 'QUANTITY': '1', 'PRICE': '1'},
        ])
        self.assertEqual(snapshot.line_ids.mapped('status'), ['only_rs'])

    def test_quantity_rounding_is_not_a_changed_line(self):
        waybill = self.make_waybill(rs_internal_id=960007)
        self.add_line(waybill, quantity=10.0, unit_price=5.0, bar_code='X1', name='Widget')

        snapshot = self._live_snapshot(waybill, self._header(), [
            {'BAR_CODE': 'X1', 'W_NAME': 'Widget',
             'QUANTITY': '10.000000001', 'PRICE': '5.000000001'},
        ])

        self.assertEqual(snapshot.line_ids.mapped('status'), ['same'])


@tagged('post_install', '-at_install')
class TestExternalRefLastSeen(RsWaybillCommon):
    """last_seen_date means "this mapping resolved something", not "somebody looked at it"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seller = cls.env['res.partner'].create({
            'name': 'Seen Seller', 'vat': '400121212'})

    def test_a_resolving_mapping_is_stamped(self):
        ref = self.env['rs.product.external.ref'].create({
            'product_id': self.product.product_tmpl_id.id,
            'variant_id': self.product.id,
            'seller_partner_id': self.seller.id,
            'external_barcode': 'SEEN-1',
        })
        found = self.env['rs.waybill']._resolve_product('SEEN-1', self.seller)
        self.assertEqual(found, self.product)
        self.assertTrue(ref.last_seen_date)

    def test_a_mapping_that_resolves_to_nothing_is_not_stamped(self):
        """A multi-variant template with no variant chosen resolves to nothing and is not stamped as
        recently used."""
        template = self.env['product.template'].create({
            'name': 'Multi Variant', 'type': 'consu'})
        attribute = self.env['product.attribute'].create({'name': 'Size'})
        values = self.env['product.attribute.value'].create([
            {'name': 'S', 'attribute_id': attribute.id},
            {'name': 'L', 'attribute_id': attribute.id},
        ])
        self.env['product.template.attribute.line'].create({
            'product_tmpl_id': template.id,
            'attribute_id': attribute.id,
            'value_ids': [(6, 0, values.ids)],
        })
        self.assertGreater(len(template.product_variant_ids), 1)

        ref = self.env['rs.product.external.ref'].create({
            'product_id': template.id,
            'variant_id': template.product_variant_ids[0].id,
            'seller_partner_id': self.seller.id,
            'external_barcode': 'SEEN-2',
        })
        ref.invalidate_recordset()
        self.env.cr.execute(
            "UPDATE rs_product_external_ref SET variant_id = NULL WHERE id = %s", (ref.id,))
        ref.invalidate_recordset(['variant_id'])

        found = self.env['rs.waybill']._resolve_product('SEEN-2', self.seller)

        self.assertFalse(found)
        self.assertFalse(ref.last_seen_date,
                         "a mapping that resolved to nothing was marked as in use")
