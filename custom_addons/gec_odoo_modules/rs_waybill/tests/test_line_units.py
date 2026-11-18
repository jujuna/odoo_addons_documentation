"""Each waybill line carries its own unit: a product sold as Pack of 12 goes to RS.GE as 2 შეკვრა at the pack
price, and stock moves 24 Units. Package units of any size share RS code 14, since RS.GE declares the kind of unit,
not its size.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestLineUnits(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        UoM = cls.env['uom.uom']
        cls.units = cls.env.ref('uom.product_uom_unit')
        cls.pack12 = UoM.create({'name': 'Pack of 12', 'relative_factor': 12,
                                 'relative_uom_id': cls.units.id, 'rs_unit_id': 14})
        cls.pack24 = UoM.create({'name': 'Pack of 24', 'relative_factor': 24,
                                 'relative_uom_id': cls.units.id, 'rs_unit_id': 14})
        cls.water = cls.env['product.product'].create({
            'name': 'Water 0.5L', 'is_storable': True, 'list_price': 2.5, 'taxes_id': [(5, 0, 0)],
            'barcode': 'W-05', 'uom_ids': [(6, 0, cls.pack12.ids)]})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Test Vendor LLC', 'vat': '404040404', 'supplier_rank': 1})

    def _sold(self, *lines):
        """A confirmed sales order of water with (quantity, unit, price) lines, its delivery reserved."""
        self.env['stock.quant']._update_available_quantity(self.water, self.warehouse.lot_stock_id, 500)
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.water.id, 'product_uom_qty': qty,
                                   'product_uom_id': unit.id, 'price_unit': price, 'tax_ids': [(5, 0, 0)]})
                           for qty, unit, price in lines],
        })
        order.with_context(skip_rs_auto_create=True).action_confirm()
        return order.picking_ids

    def _vendor_waybill(self, **line):
        vals = {'product_id': self.water.id, 'name': self.water.name, 'quantity': 2, 'unit_price': 30.0}
        vals.update(line)
        return self.env['rs.waybill'].with_context(rs_skip_resolve=True).create({
            'waybill_direction': 'buyer', 'waybill_type': '2', 'state': 'active',
            'seller_tin': self.vendor.vat, 'seller_name': self.vendor.name,
            'rs_internal_id': 990001, 'rs_waybill_number': '990001',
            'line_ids': [(0, 0, vals)],
        })

    # ── units ──

    def test_package_units_share_rs_code_14(self):
        self.assertEqual((self.pack12 | self.pack24).mapped('rs_unit_id'), [14, 14])
        self.assertEqual(self.env['uom.uom']._rs_uom_by_code()[14], self.env.ref('rs_waybill.uom_rs_bundle'),
                         "a shared code resolves to the unit this module shipped, not a user's package")

    def test_unit_without_code_is_sent_as_other_with_its_name(self):
        box = self.env['uom.uom'].create({'name': 'Crate', 'relative_factor': 6, 'relative_uom_id': self.units.id})
        self.assertEqual((box._rs_code(), box._rs_text()), (99, 'Crate'))

    # ── seller ──

    def test_sold_in_packs_goes_to_rs_in_packs(self):
        picking = self._sold((2, self.pack12, 30.0))
        move = picking.move_ids
        self.assertEqual((move.uom_id, move.product_uom_qty), (self.units, 24), "Odoo delivers in Units")
        vals = picking._rs_line_vals_from_move(move, 24, 1)
        self.assertEqual((vals['uom_id'], vals['quantity'], vals['unit_price'], vals['unit_name']),
                         (self.pack12.id, 2, 30.0, 'შეკვრა'))

        waybill = self.make_waybill(line_ids=[(0, 0, vals)])
        with patch.object(type(self.service), '_rs_company_un_id', return_value='12345'):
            xml = self.service._build_waybill_xml(waybill, None, 'su', 'sp')
        goods = xml.find('GOODS_LIST/GOODS')
        self.assertEqual([goods.findtext(tag) for tag in ('UNIT_ID', 'UNIT_TXT', 'QUANTITY', 'PRICE')],
                         ['14', 'შეკვრა', '2.0', '30.0'])

    def test_part_of_a_pack_is_declared_in_units(self):
        picking = self._sold((2, self.pack12, 30.0))
        vals = picking._rs_line_vals_from_move(picking.move_ids, 18, 1)
        self.assertEqual((vals['uom_id'], vals['quantity'], vals['unit_price'], vals['unit_name']),
                         (self.units.id, 18, 2.5, 'ცალი'), "never 1.5 შეკვრა")

    def test_draft_waybill_switches_to_packs_once_whole(self):
        picking = self._sold((2, self.pack12, 30.0))
        waybill = self.make_waybill(picking_id=picking.id)
        picking.waybill_id = waybill
        move = picking.move_ids
        waybill.line_ids = [(0, 0, picking._rs_line_vals_from_move(move, 18, 1))]

        picking._rs_sync_waybill_lines()  # all 24 reserved now
        self.assertEqual((waybill.line_ids.uom_id, waybill.line_ids.quantity, waybill.line_ids.unit_price),
                         (self.pack12, 2, 30.0))

    def test_validation_counts_packs_and_units_in_one_unit(self):
        picking = self._sold((2, self.pack12, 30.0), (5, self.units, 2.5))
        waybill = self.make_waybill(picking_id=picking.id)
        picking.waybill_id = waybill
        waybill.line_ids = picking._rs_build_waybill_lines()
        self.assertEqual(sorted(waybill.line_ids.mapped('uom_id.name')), ['Pack of 12', 'Units'])

        picking._rs_check_waybill_qty()  # 2 x 12 + 5 on both sides

        waybill.line_ids.filtered(lambda l: l.uom_id == self.pack12).quantity = 3
        with self.assertRaises(UserError):
            picking._rs_check_waybill_qty()

    def test_changing_only_the_unit_is_no_goods_change(self):
        waybill = self.make_waybill()
        line = self.add_line(waybill, quantity=2, unit_price=30, product_id=self.water.id, uom_id=self.pack12.id)
        waybill.edit_snapshot_json = waybill._build_line_snapshot()

        line.write({'uom_id': self.units.id, 'quantity': 24, 'unit_price': 2.5})
        self.assertEqual(waybill._compute_line_diff(waybill.edit_snapshot_json), [], "2 x Pack of 12 is 24 Units")

        line.quantity = 36
        [diff] = waybill._compute_line_diff(waybill.edit_snapshot_json)
        self.assertEqual((diff['type'], diff['qty_diff']), ('qty_up', 12), "diffs are in the product's unit")

    def test_snapshot_from_before_the_upgrade_reads_the_lines_unit(self):
        waybill = self.make_waybill()
        line = self.add_line(waybill, quantity=2, unit_price=30, product_id=self.water.id, uom_id=self.pack12.id)
        waybill.edit_snapshot_json = ('[{"line_id": %d, "product_id": %d, "quantity": 2, "unit_price": 30, '
                                      '"name": "x", "rs_good_id": "", "stock_move_id": null}]'
                                      % (line.id, self.water.id))
        self.assertEqual(waybill._compute_line_diff(waybill.edit_snapshot_json), [])

    # ── RS.GE -> Odoo ──

    def test_rs_unit_resolves_to_the_products_own_unit(self):
        Line = self.env['rs.waybill.line']
        self.assertEqual(Line._rs_match_uom(self.water, 14, 'შეკვრა'), (self.pack12, False))
        self.assertEqual(Line._rs_match_uom(self.water, 1, 'ცალი'), (self.units, False))
        self.assertEqual(Line._rs_match_uom(self.water, 2, 'კგ'), (self.units, True), "no kg unit on the product")
        self.assertEqual(Line._rs_match_uom(self.water, 0, ''), (self.units, False), "no code: nothing to check")

        self.water.uom_ids = self.pack12 | self.pack24
        self.assertEqual(Line._rs_match_uom(self.water, 14, 'შეკვრა'), (self.units, True),
                         "two package sizes: RS.GE does not say which")
        self.assertEqual(Line._rs_match_uom(self.water, 14, 'Pack of 24'), (self.pack24, False))

    def test_unit_change_on_rs_follows_but_an_unknown_code_is_learned_silently(self):
        waybill = self.make_waybill(state='active', rs_internal_id=990002)
        line = self.add_line(waybill, quantity=2, unit_price=30, product_id=self.water.id, uom_id=self.pack12.id,
                             name=self.water.name, bar_code='W-05', rs_good_id='5001', unit_name='შეკვრა')
        good = {'ID': '5001', 'BAR_CODE': 'W-05', 'W_NAME': self.water.name, 'QUANTITY': '2', 'PRICE': '30',
                'UNIT_ID': '14', 'UNIT_TXT': 'შეკვრა', 'VAT_TYPE': '0'}
        self.assertFalse(waybill._goods_lines_changed(waybill, [good]), "a line from before the upgrade")
        line.rs_unit_code = 14

        good.update(UNIT_ID='1', UNIT_TXT='ცალი', QUANTITY='24', PRICE='2.5')
        self.assertTrue(waybill._goods_lines_changed(waybill, [good]))
        waybill._sync_goods_lines([good])
        self.assertEqual((line.uom_id, line.quantity, line.rs_unit_code, line.uom_review),
                         (self.units, 24, 1, False))

    # ── buyer ──

    def test_vendor_packs_are_received_as_units(self):
        waybill = self._vendor_waybill(uom_id=self.pack12.id, rs_unit_code=14)
        self.assertEqual(waybill._rs_buyer_target(), {self.water: 24})

        waybill._rs_create_buyer_documents_if_missing()
        po_line = waybill.purchase_id.order_line
        self.assertEqual((po_line.uom_id, po_line.product_qty), (self.pack12, 2))

        waybill.is_confirmed = '1'
        waybill._cascade_validate_receipt()
        self.assertEqual(self.water.qty_available, 24)

    def test_unit_needing_review_blocks_documents_and_receive(self):
        self.water.uom_ids = self.pack12 | self.pack24
        waybill = self._vendor_waybill(uom_id=self.units.id, rs_unit_code=14, unit_name='შეკვრა',
                                       uom_review=True)
        self.assertEqual(waybill.unresolved_count, 1)
        self.assertFalse(waybill._rs_create_buyer_documents_if_missing(), "no PO in a guessed unit")
        with self.assertRaises(UserError):
            waybill.action_confirm_waybill()

        wizard = self.env['rs.waybill.mapping.wizard'].browse(waybill.action_open_mapping_wizard()['res_id'])
        self.assertEqual(wizard.line_ids.product_id, self.water)
        wizard.line_ids.uom_id = self.pack24
        wizard.action_apply()
        self.assertFalse(waybill.line_ids.uom_review)
        self.assertEqual(waybill._rs_buyer_target(), {self.water: 48})
