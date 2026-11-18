"""Computed display labels refresh when the data behind them changes, with no manual cache
invalidation.
"""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestPartnerTinLabel(RsWaybillCommon):
    """res.partner under show_partner_tin: the driver dropdown."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.driver = cls.env['res.partner'].create({
            'name': 'Giorgi Driver', 'vat': '01001000001', 'rs_is_driver': True})

    def _label(self):
        return self.driver.with_context(show_partner_tin=True).display_name

    def test_the_label_shows_tin_and_name(self):
        self.assertEqual(self._label(), '01001000001 — Giorgi Driver')

    def test_correcting_the_vat_refreshes_the_label(self):
        self.driver.vat = '02002000002'
        self.assertEqual(self._label(), '02002000002 — Giorgi Driver',
                         "the dropdown kept showing the old TIN")

    def test_clearing_the_vat_leaves_the_name(self):
        self.driver.vat = False
        self.assertEqual(self._label(), 'Giorgi Driver')

    def test_the_name_fallback_refreshes_too(self):
        partner = self.env['res.partner'].create({'name': 'No Tin Here'})
        labelled = partner.with_context(show_partner_tin=True)
        self.assertEqual(labelled.display_name, 'No Tin Here')
        partner.name = 'Renamed'
        self.assertEqual(labelled.display_name, 'Renamed')

    def test_without_the_context_the_standard_label_is_untouched(self):
        self.assertEqual(self.driver.display_name, 'Giorgi Driver')


@tagged('post_install', '-at_install')
class TestVehiclePlateLabel(RsWaybillCommon):
    """fleet.vehicle under rs_plate_only: the waybill's Car Plate dropdown."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.driver = cls.env['res.partner'].create({
            'name': 'Driver One', 'vat': '01001000009', 'rs_is_driver': True})
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'driver_id': cls.driver.id,
            'license_plate': 'AA-111-AA',
            'model_id': cls.env['fleet.vehicle']._ensure_rs_placeholder_model().id,
        })

    def _label(self):
        return self.vehicle.with_context(rs_plate_only=True).display_name

    def test_the_label_is_the_bare_plate(self):
        self.assertEqual(self._label(), 'AA-111-AA')

    def test_changing_the_plate_refreshes_the_label(self):
        self.vehicle.license_plate = 'bb-222-bb'
        self.assertEqual(self._label(), 'BB-222-BB')


@tagged('post_install', '-at_install')
class TestExternalRefLabel(RsWaybillCommon):
    """rs.product.external.ref — 'Seller: barcode → Product'."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seller = cls.env['res.partner'].create({
            'name': 'Seller One', 'vat': '400777000'})
        cls.ref = cls.env['rs.product.external.ref'].create({
            'product_id': cls.product.product_tmpl_id.id,
            'variant_id': cls.product.id,
            'seller_partner_id': cls.seller.id,
            'external_barcode': 'EXT-9',
        })

    def test_the_label_names_both_parties(self):
        self.assertIn('Seller One', self.ref.display_name)
        self.assertIn('EXT-9', self.ref.display_name)

    def test_renaming_the_seller_refreshes_the_label(self):
        """The label must follow the seller's name, not only a change of the link."""
        self.assertIn('Seller One', self.ref.display_name)
        self.seller.name = 'Seller Renamed'
        self.assertIn('Seller Renamed', self.ref.display_name,
                      "the mapping label kept the seller's old name")

    def test_renaming_the_product_refreshes_the_label(self):
        self.product.product_tmpl_id.name = 'Widget Renamed'
        self.assertIn('Widget Renamed', self.ref.display_name)

    def test_changing_the_barcode_refreshes_the_label(self):
        self.ref.external_barcode = 'EXT-10'
        self.assertIn('EXT-10', self.ref.display_name)
