# Part of Odoo. See LICENSE file for full copyright and licensing details.
import json
from datetime import timedelta
import requests
from contextlib import contextmanager
from unittest.mock import patch

from odoo import fields, Command
from odoo.tests import Form, TransactionCase, tagged
from ..models.dhl_request import DHLProvider


class TestDeliveryDHLCommon(TransactionCase):

    def setUp(self):
        super().setUp()

        self.iPadMini = self.env['product.product'].create({
            'name': 'iPad Mini',
            'weight': 0.01,
        })
        self.large_desk = self.env['product.product'].create({
            'name': 'Large Desk',
            'weight': 0.01,
        })
        self.uom_unit = self.env.ref('uom.product_uom_unit')

        self.incoterm = self.env['account.incoterms'].create({
            'name': 'Delivered At Place',
            'code': 'DAP',
        })
        self.env.company.write({
            'incoterm_id': self.incoterm.id,
        })

        self.your_company = self.env.ref('base.main_partner')
        self.your_company.write({
            'street': "Rue du Laid Burniat 5",
            'street2': "",
            'city': "Saint-Hubert",
            'zip': 6870,
            'state_id': False,
            'country_id': self.env.ref('base.be').id,
            'phone': '+1 555-555-5555',
        })
        self.uk_co = self.env['res.company'].create({
            'name': 'Fish n Chips Co',
            'street': 'Downing street 10',
            'street2': '',
            'city': 'London',
            'zip': 'SW1A 2AA',
            'state_id': False,
            'country_id': self.env.ref('base.uk').id,
            'phone': '+1 555-555-5555',
        })
        self.agrolait = self.env['res.partner'].create({
            'name': 'Agrolait',
            'phone': '(603)-996-3829',
            'street': "rue des Bourlottes, 9",
            'street2': "",
            'city': "Ramillies",
            'zip': 1367,
            'state_id': False,
            'country_id': self.env.ref('base.be').id,
        })
        self.delta_pc = self.env['res.partner'].create({
            'name': 'Delta PC',
            'phone': '(803)-873-6126',
            'street': "1515 Main Street",
            'street2': "",
            'city': "Columbia",
            'zip': 29201,
            'state_id': self.env.ref('base.state_us_41').id,
            'country_id': self.env.ref('base.us').id,
        })
        self.stock_location = self.env.ref('stock.stock_location_stock')
        self.customer_location = self.env.ref('stock.stock_location_customers')

        self.delivery_carrier_dhl_be_dom = self.env.ref('delivery_dhl_rest.delivery_carrier_dhl_be_dom', raise_if_not_found=False)
        if not self.delivery_carrier_dhl_be_dom:
            product_dhl = self.env['product.product'].create({
                "name": 'DHL BE',
                "default_code": 'Delivery_014',
                "type": 'service',
                "categ_id": self.env.ref('delivery.product_category_deliveries').id,
                "sale_ok": False,
                "purchase_ok": False,
                "list_price": 0.0,
                "invoice_policy": 'order',
            })
            self.delivery_carrier_dhl_be_dom = self.env['delivery.carrier'].create({
                "name": 'DHL BE',
                "product_id": product_dhl.id,
                "delivery_type": 'dhl_rest',
                "dhl_product_code": 'N',
                "dhl_api_key": 'apI8zX6vT2hQ9f',
                "dhl_api_secret": 'S^2eZ$1aL#2nF^0d',
                "dhl_account_number": '272699353',
                "dhl_default_package_type_id": self.env.ref('delivery_dhl_rest.dhl_packaging_BOX').id,
            })
        # Ask for delivery in 5 days, at noon.
        # This is to avoid errors where DHL return an error because it's not possible for them to deliver on time.
        self.delivery_date = fields.Datetime.today() + timedelta(hours=12) + timedelta(days=5)
        self.delivery_carrier_dhl_eu_intl = self.env.ref('delivery_dhl_rest.delivery_carrier_dhl_eu_intl', raise_if_not_found=False)
        if not self.delivery_carrier_dhl_eu_intl:
            product_dhl = self.env['product.product'].create({
                "name": 'DHL EU International',
                "default_code": 'Delivery_015',
                "type": 'service',
                "categ_id": self.env.ref('delivery.product_category_deliveries').id,
                "sale_ok": False,
                "purchase_ok": False,
                "list_price": 0.0,
                "invoice_policy": 'order',
            })
            self.delivery_carrier_dhl_eu_intl = self.env['delivery.carrier'].create({
                "name": 'DHL EU International',
                "product_id": product_dhl.id,
                "delivery_type": 'dhl_rest',
                "dhl_product_code": 'D',
                "dhl_api_key": 'apI8zX6vT2hQ9f',
                "dhl_api_secret": 'S^2eZ$1aL#2nF^0d',
                "dhl_account_number": '272699353',
                "dhl_default_package_type_id": self.env.ref('delivery_dhl_rest.dhl_packaging_BOX').id,
            })

    def wiz_put_in_pack(self, picking):
        """ Helper to use the 'stock.put.in.pack' wizard
        in order to call the 'action_put_in_pack' method.
        """
        wiz_action = picking.action_put_in_pack()
        self.assertEqual(wiz_action['res_model'], 'stock.put.in.pack', 'Wrong wizard returned')
        wiz = Form.from_action(self.env, wiz_action)
        wiz.package_type_id = picking.carrier_id.dhl_default_package_type_id
        wiz.save().action_put_in_pack()

    def dhl_basic_be_domestic_flow_with_insurance(self):

        def update_shipping_rate(sale_order, carrier):
            # I add free delivery cost in Sales order
            with _mock_request_call():
                delivery_wizard = Form(self.env['choose.delivery.carrier'].with_context({
                    'default_order_id': sale_order.id,
                    'default_carrier_id': carrier.id,
                }))
            choose_delivery_carrier = delivery_wizard.save()
            choose_delivery_carrier.update_price()
            choose_delivery_carrier.button_confirm()

        def validate_shipment(sale_order):
            picking = sale_order.picking_ids[0]
            self.assertEqual(picking.carrier_id, sale_order.carrier_id, "Carrier is not the same on Picking and on SO.")

            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            self.assertGreater(picking.shipping_weight, 0.0, "Picking weight should be positive.")

            picking.scheduled_date = self.delivery_date
            picking._action_done()
            self.assertTrue(picking.carrier_tracking_ref, "DHL did not return any tracking number")
            self.assertGreater(picking.carrier_price, 0.0, "DHL carrying price is probably incorrect")

        def cancel_shipment(sale_order):
            picking = sale_order.picking_ids[0]
            picking.cancel_shipment()
            self.assertFalse(picking.carrier_tracking_ref, "Carrier Tracking code has not been properly deleted")
            self.assertEqual(picking.carrier_price, 0.0, "Carrier price has not been properly deleted")

        SaleOrder = self.env['sale.order']

        delivery_carrier_dhl_be_dom_insured = self.delivery_carrier_dhl_be_dom.copy()
        delivery_carrier_dhl_be_dom_insured.shipping_insurance = 80

        sol_vals = {
            'product_id': self.iPadMini.id,
            'name': "[A1232] Large Cabinet",
            'product_uom_id': self.uom_unit.id,
            'product_uom_qty': 1.0,
        }

        so_vals = {
            'partner_id': self.agrolait.id,
            'order_line': [(0, None, sol_vals)],
            'date_order': self.delivery_date,
        }

        sale_order = SaleOrder.create(so_vals)
        insured_sale_order = SaleOrder.create(so_vals)

        update_shipping_rate(sale_order, self.delivery_carrier_dhl_be_dom)
        update_shipping_rate(insured_sale_order, delivery_carrier_dhl_be_dom_insured)

        delivery_cost = sum(line.price_total for line in sale_order.order_line if line.is_delivery)
        insured_delivery_cost = sum(line.price_total for line in insured_sale_order.order_line if line.is_delivery)
        self.assertGreater(delivery_cost, 0.0, "DHL delivery cost for this SO has not been correctly estimated.")
        self.assertGreater(insured_delivery_cost, 0.0, "DHL delivery cost for this SO has not been correctly estimated.")
        self.assertGreater(insured_delivery_cost, delivery_cost, "Insured delivery cost should be greater than uninsured delivery cost.")

        (sale_order | insured_sale_order).action_confirm()
        self.assertEqual(len(sale_order.picking_ids), 1, "The Sales Order did not generate a picking.")
        self.assertEqual(len(insured_sale_order.picking_ids), 1, "The Sales Order did not generate a picking.")

        validate_shipment(sale_order)
        validate_shipment(insured_sale_order)
        self.assertGreater(insured_sale_order.picking_ids[0].carrier_price, sale_order.picking_ids[0].carrier_price, "Insured delivery cost should be greater than uninsured delivery cost.")

        cancel_shipment(sale_order)
        cancel_shipment(insured_sale_order)

    def dhl_basic_international_flow(self):
        SaleOrder = self.env['sale.order']

        sol_vals = {
            'product_id': self.iPadMini.id,
            'name': "[A1232] Large Cabinet",
            'product_uom_id': self.uom_unit.id,
            'product_uom_qty': 1.0,
            'price_unit': self.iPadMini.lst_price
        }

        so_vals = {
            'partner_id': self.delta_pc.id,
            'carrier_id': self.delivery_carrier_dhl_eu_intl.id,
            'order_line': [(0, None, sol_vals)],
            'date_order': self.delivery_date,
        }

        sale_order = SaleOrder.create(so_vals)
        # I add free delivery cost in Sales order
        with _mock_request_call():
            delivery_wizard = Form(self.env['choose.delivery.carrier'].with_context({
                'default_order_id': sale_order.id,
                'default_carrier_id': self.delivery_carrier_dhl_eu_intl.id
            }))
        choose_delivery_carrier = delivery_wizard.save()
        choose_delivery_carrier.update_price()
        # doesn't work with the mocked request, because the productCode isn't the same...
        # self.assertGreater(sum(line.price_total for line in sale_order.order_line if line.is_delivery), 0.0, "DHL delivery cost for this SO has not been correctly estimated.")
        choose_delivery_carrier.button_confirm()

        sale_order.action_confirm()
        self.assertEqual(len(sale_order.picking_ids), 1, "The Sales Order did not generate a picking.")

        picking = sale_order.picking_ids[0]
        self.assertEqual(picking.carrier_id.id, sale_order.carrier_id.id, "Carrier is not the same on Picking and on SO.")

        picking.move_ids[0].quantity = 1.0
        picking.move_ids[0].picked = True
        self.assertGreater(picking.shipping_weight, 0.0, "Picking weight should be positive.")

        picking.scheduled_date = self.delivery_date
        picking._action_done()
        self.assertIsNot(picking.carrier_tracking_ref, False, "DHL did not return any tracking number")
        self.assertGreater(picking.carrier_price, 0.0, "DHL carrying price is probably incorrect")
        attachment_names = picking.message_ids.mapped("attachment_ids.name")
        self.assertIn(f"LabelShipping-DHL-{picking.carrier_tracking_ref}.PDF", attachment_names, "Label wasn't linked in the chatter")
        self.assertIn(f"CommercialInvoice-DHL-{picking.carrier_tracking_ref}.PDF", attachment_names, "Commercial invoice wasn't linked in the chatter")

        picking.cancel_shipment()
        self.assertFalse(picking.carrier_tracking_ref, "Carrier Tracking code has not been properly deleted")
        self.assertEqual(picking.carrier_price, 0.0, "Carrier price has not been properly deleted")

    def dhl_multipackage_international_flow(self):
        SaleOrder = self.env['sale.order']

        sol_1_vals = {
            'product_id': self.iPadMini.id,
            'name': "[A1232] Large Cabinet",
            'product_uom_id': self.uom_unit.id,
            'product_uom_qty': 1.0,
            'price_unit': self.iPadMini.lst_price
        }
        sol_2_vals = {
            'product_id': self.large_desk.id,
            'name': "[A1090] Large Desk",
            'product_uom_id': self.uom_unit.id,
            'product_uom_qty': 1.0,
            'price_unit': self.large_desk.lst_price
        }

        so_vals = {
            'partner_id': self.delta_pc.id,
            'carrier_id': self.delivery_carrier_dhl_eu_intl.id,
            'order_line': [(0, None, sol_1_vals), (0, None, sol_2_vals)],
            'date_order': self.delivery_date,
        }

        sale_order = SaleOrder.create(so_vals)
        # I add free delivery cost in Sales order
        with _mock_request_call():
            delivery_wizard = Form(self.env['choose.delivery.carrier'].with_context({
                'default_order_id': sale_order.id,
                'default_carrier_id': self.delivery_carrier_dhl_eu_intl.id
            }))
        choose_delivery_carrier = delivery_wizard.save()
        choose_delivery_carrier.update_price()
        choose_delivery_carrier.button_confirm()

        sale_order.action_confirm()
        self.assertEqual(len(sale_order.picking_ids), 1, "The Sales Order did not generate a picking.")

        picking = sale_order.picking_ids[0]
        self.assertEqual(picking.carrier_id.id, sale_order.carrier_id.id, "Carrier is not the same on Picking and on SO.")

        move0 = picking.move_ids[0]
        move0.quantity = 1.0
        move0.picked = True
        self.wiz_put_in_pack(picking)

        move1 = picking.move_ids[1]
        move1.quantity = 1.0
        move1.picked = True
        self.wiz_put_in_pack(picking)

        self.assertEqual(len(picking.move_line_ids.mapped('result_package_id')), 2, "2 Packages should have been created at this point")
        self.assertGreater(picking.shipping_weight, 0.0, "Picking weight should be positive.")

        picking.scheduled_date = self.delivery_date
        picking._action_done()
        self.assertIsNot(picking.carrier_tracking_ref, False, "DHL did not return any tracking number")

        picking.cancel_shipment()
        self.assertFalse(picking.carrier_tracking_ref, "Carrier Tracking code has not been properly deleted")
        self.assertEqual(picking.carrier_price, 0.0, "Carrier price has not been properly deleted")

    def dhl_flow_from_delivery_order(self):
        StockPicking = self.env['stock.picking']

        order1_vals = {
            'product_id': self.iPadMini.id,
            'uom_id': self.uom_unit.id,
            'product_uom_qty': 1.0,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id
        }

        do_vals = {
            'partner_id': self.delta_pc.id,
            'carrier_id': self.delivery_carrier_dhl_eu_intl.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'picking_type_id': self.env.ref('stock.picking_type_out').id,
            'state': 'draft',
            'move_ids': [(0, None, order1_vals)],
            'scheduled_date': self.delivery_date,
        }

        delivery_order = StockPicking.create(do_vals)
        self.assertEqual(delivery_order.state, 'draft', 'Shipment state should be draft.')

        delivery_order.action_confirm()
        self.assertEqual(delivery_order.state, 'assigned', 'Shipment state should be ready(assigned).')
        delivery_order.move_ids.quantity = 1.0
        delivery_order.move_ids.picked = True

        delivery_order.button_validate()
        self.assertEqual(delivery_order.state, 'done', 'Shipment state should be done.')


@tagged('-standard', 'external')
@tagged('at_install', '-post_install')  # LEGACY at_install
class TestDeliveryDHL(TestDeliveryDHLCommon):

    def test_01_dhl_basic_be_domestic_flow_with_insurance(self):
        super().dhl_basic_be_domestic_flow_with_insurance()

    def test_02_dhl_basic_international_flow(self):
        super().dhl_basic_international_flow()

    def test_03_dhl_multipackage_international_flow(self):
        super().dhl_multipackage_international_flow()

    def test_04_dhl_flow_from_delivery_order(self):
        super().dhl_flow_from_delivery_order()


@contextmanager
def _mock_request_call(specific_dhl_check=None):
    RATE_MOCK_RESPONSE = {
        "products": [
            {
                "productName": "MEDICAL EXPRESS",
                "productCode": "C",
                "localProductCode": "O",
                "localProductCountryCode": "BE",
                "networkTypeCode": "TD",
                "isCustomerAgreement": True,
                "weight": {
                    "volumetric": 19.01,
                    "provided": 19.5,
                    "unitOfMeasurement": "metric"
                },
                "totalPrice": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "price": 76.24
                    },
                    {
                        "currencyType": "PULCL",
                        "price": 0
                    },
                    {
                        "currencyType": "BASEC",
                        "price": 0
                    }
                ],
                "totalPriceBreakdown": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "priceBreakdown": [
                            {
                                "typeCode": "STTXA",
                                "price": 13.23
                            },
                            {
                                "typeCode": "SPRQT",
                                "price": 58.88
                            }
                        ]
                    }
                ],
                "detailedPriceBreakdown": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "breakdown": [
                            {
                                "name": "MEDICAL EXPRESS",
                                "price": 58.88,
                                "priceBreakdown": [
                                    {
                                        "priceType": "TAX",
                                        "typeCode": "EU_VAT",
                                        "price": 10.22,
                                        "rate": 21,
                                        "basePrice": 48.66
                                    }
                                ]
                            },
                            {
                                "name": "FUEL SURCHARGE",
                                "serviceCode": "FF",
                                "localServiceCode": "FF",
                                "serviceTypeCode": "SCH",
                                "price": 17.36,
                                "isCustomerAgreement": False,
                                "isMarketedService": False,
                                "priceBreakdown": [
                                    {
                                        "priceType": "TAX",
                                        "typeCode": "EU_VAT",
                                        "price": 3.01,
                                        "rate": 21,
                                        "basePrice": 14.35
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "pickupCapabilities": {
                    "nextBusinessDay": False,
                    "localCutoffDateAndTime": "2024-05-02T17:30:00",
                    "GMTCutoffTime": "19:00:00",
                    "pickupEarliest": "09:30:00",
                    "pickupLatest": "19:00:00",
                    "originServiceAreaCode": "BRU",
                    "originFacilityAreaCode": "ANN",
                    "pickupAdditionalDays": 0,
                    "pickupDayOfWeek": 4
                },
                "deliveryCapabilities": {
                    "deliveryTypeCode": "QDDF",
                    "estimatedDeliveryDateAndTime": "2024-05-03T23:59:00",
                    "destinationServiceAreaCode": "BRU",
                    "destinationFacilityAreaCode": "LG1",
                    "deliveryAdditionalDays": 0,
                    "deliveryDayOfWeek": 5,
                    "totalTransitDays": 1
                },
                "pricingDate": "2024-05-02"
            },
            {
                "productName": "EXPRESS DOMESTIC",
                "productCode": "N",
                "localProductCode": "L",
                "localProductCountryCode": "BE",
                "networkTypeCode": "TD",
                "isCustomerAgreement": False,
                "weight": {
                    "volumetric": 19.01,
                    "provided": 19.5,
                    "unitOfMeasurement": "metric"
                },
                "totalPrice": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "price": 56.25
                    },
                    {
                        "currencyType": "PULCL",
                        "price": 0
                    },
                    {
                        "currencyType": "BASEC",
                        "price": 0
                    }
                ],
                "totalPriceBreakdown": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "priceBreakdown": [
                            {
                                "typeCode": "STTXA",
                                "price": 9.76
                            },
                            {
                                "typeCode": "SPRQT",
                                "price": 43.44
                            }
                        ]
                    }
                ],
                "detailedPriceBreakdown": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "breakdown": [
                            {
                                "name": "EXPRESS DOMESTIC",
                                "price": 43.44,
                                "priceBreakdown": [
                                    {
                                        "priceType": "TAX",
                                        "typeCode": "EU_VAT",
                                        "price": 7.54,
                                        "rate": 21,
                                        "basePrice": 35.9
                                    }
                                ]
                            },
                            {
                                "name": "FUEL SURCHARGE",
                                "serviceCode": "FF",
                                "localServiceCode": "FF",
                                "serviceTypeCode": "SCH",
                                "price": 12.81,
                                "isCustomerAgreement": False,
                                "isMarketedService": False,
                                "priceBreakdown": [
                                    {
                                        "priceType": "TAX",
                                        "typeCode": "EU_VAT",
                                        "price": 2.22,
                                        "rate": 21,
                                        "basePrice": 10.59
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "pickupCapabilities": {
                    "nextBusinessDay": False,
                    "localCutoffDateAndTime": "2024-05-02T17:30:00",
                    "GMTCutoffTime": "19:00:00",
                    "pickupEarliest": "09:30:00",
                    "pickupLatest": "19:00:00",
                    "originServiceAreaCode": "BRU",
                    "originFacilityAreaCode": "ANN",
                    "pickupAdditionalDays": 0,
                    "pickupDayOfWeek": 4
                },
                "deliveryCapabilities": {
                    "deliveryTypeCode": "QDDF",
                    "estimatedDeliveryDateAndTime": "2024-05-03T23:59:00",
                    "destinationServiceAreaCode": "BRU",
                    "destinationFacilityAreaCode": "LG1",
                    "deliveryAdditionalDays": 0,
                    "deliveryDayOfWeek": 5,
                    "totalTransitDays": 1
                },
                "pricingDate": "2024-05-02"
            },
            {
                "productName": "EXPRESS WORLDWIDE",
                "productCode": "D",
                "localProductCode": "I",
                "localProductCountryCode": "BE",
                "networkTypeCode": "TD",
                "isCustomerAgreement": True,
                "weight": {
                    "volumetric": 19.01,
                    "provided": 19.5,
                    "unitOfMeasurement": "metric"
                },
                "totalPrice": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "price": 45
                    },
                    {
                        "currencyType": "PULCL",
                        "price": 0
                    },
                    {
                        "currencyType": "BASEC",
                        "price": 0
                    }
                ],
                "totalPriceBreakdown": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "priceBreakdown": [
                            {
                                "typeCode": "STTXA",
                                "price": 7.81
                            },
                            {
                                "typeCode": "SPRQT",
                                "price": 45
                            }
                        ]
                    }
                ],
                "detailedPriceBreakdown": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "breakdown": [
                            {
                                "name": "EXPRESS EASY",
                                "price": 45,
                                "priceBreakdown": [
                                    {
                                        "priceType": "TAX",
                                        "typeCode": "EU_VAT",
                                        "price": 7.81,
                                        "rate": 21,
                                        "basePrice": 37.19
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "pickupCapabilities": {
                    "nextBusinessDay": False,
                    "localCutoffDateAndTime": "2024-05-02T17:30:00",
                    "GMTCutoffTime": "19:00:00",
                    "pickupEarliest": "09:30:00",
                    "pickupLatest": "19:00:00",
                    "originServiceAreaCode": "BRU",
                    "originFacilityAreaCode": "ANN",
                    "pickupAdditionalDays": 0,
                    "pickupDayOfWeek": 4
                },
                "deliveryCapabilities": {
                    "deliveryTypeCode": "QDDF",
                    "estimatedDeliveryDateAndTime": "2024-05-03T23:59:00",
                    "destinationServiceAreaCode": "BRU",
                    "destinationFacilityAreaCode": "LG1",
                    "deliveryAdditionalDays": 0,
                    "deliveryDayOfWeek": 5,
                    "totalTransitDays": 1
                },
                "pricingDate": "2024-05-02"
            }
        ]
    }
    SHIP_MOCK_RESPONSE = {
        "shipmentTrackingNumber": "3436501003",
        "cancelPickupUrl": "https://express.api.dhl.com/mydhlapi/test/pickups/PRG240502001481",
        "trackingUrl": "https://express.api.dhl.com/mydhlapi/test/shipments/3436501003/tracking",
        "dispatchConfirmationNumber": "PRG240502001481",
        "packages": [
            {
                "referenceNumber": 1,
                "trackingNumber": "JD014600004860442740",
                "trackingUrl": "https://express.api.dhl.com/mydhlapi/test/shipments/3436501003/tracking?pieceTrackingNumber=JD014600004860442740"
            }
        ],
        "documents": [
            {
                "imageFormat": "PDF",
                "content": "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",
                "typeCode": "label"
            },
            {
                "imageFormat": "PDF",
                "content": "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biAKMDAwMDA0ODEzOSAwMDAwMCBuIAowMDAwMDQ4NDEyIDAwMDAwIG4gCjAwMDAwNTY5NzYgMDAwMDAgbiAKMDAwMDA1NzAyMiAwMDAwMCBuIAp0cmFpbGVyCjw8L0luZm8gMjYgMCBSL0lEIFs8OTE4NWU5ZTJjM2Y2NDAyZDNmMWY4NzZlYjI3NWNjYjc+PDc3OTcxMzY3MTMxMWU5MzRiYmVmYzU3OTg4NjBjMzY5Pl0vUm9vdCAyNSAwIFIvU2l6ZSAyNz4+CnN0YXJ0eHJlZgo1NzEzMwolJUVPRgo=+c3RyZWFtCnic7dzbcRRJFEXRMUDWtF+4hEfY1MMEwzxAqq5HZtYOWMuC+tihD/XJ+8cfAAzw+Hz3F8A3j+dTjSR8bfFrjW93fwZ8a/H5/KJG7vZ3i2rkdv+0qEZu9p8W1cit3r48/+dx9wfx2/qxRTVyl59bVCP3eK9FNXKH91tUIzf4/H6LamS5D1tUI4tttPh8frr76/idfNpqUY0s9KJFNbLMyxbVyCI7WjS3ZYldLaqRBR6vO1QjS+xu0aSMyQ60qEamOtSiGpnoYItqZJrDLX6t0Q/VzPB2vMWn2QQzfDRgVCOrnW1RjYx2vkU1MtaVFtXIUJtjWjWy0MUWTcoY5nKLamSQnaMxNTLdkBbVyACDWlQjlw1r0dyWiwa2qEYuOTHU2azRpIyzBrdo4Mhpw1tUIydNaFGNnDKlRTVywqQWn2YTHDWvRTVyzLUBoxoZZ26LamS/2S2qkb3mt6hGdlrQohrZZcCwew+TMl5a1KIaeWlZi2rkhZn/7FYjxwyd075ibsumpX8b1cgmNdKxtEaTMjapkQ410qFGOh5LfqD+XqMfqtmyYrrzLzWyRY10qJEONdLxtnDCo0ZeUCMdS2s0KWPT0kmZGtmkRjrUSIca6fAUgQ7jbzrW1mhSxhYDRzrUSIca6VAjHSZldKiRDjXSoUY6jL8JUSMdaqTDpIwONdKhRjrUSIfxNx3G33SokQ6TMjrUSIca6VAjHe7Q02HgSIca6VAjHWqkw1MEQtRIhzv0dBg40qFGOtRIhxrp8BSBDuNvOtyhp8PAkQ410qFGOtRIh0kZHWqkQ410qJEO429C1EiHGukwKaNDjXSokQ410mH8TYfxNx1qpMOkjA410qFGOtRIhzv0dBg40qFGOtRIhxrp8BSBEDXS4Q49HQaOdKiRDjXSoUY6PEWgw/ibDnfo6TBwpEONdKiRDjXSYVJGhxrpUCMdaqRDjYQYf9OhRjo8RaDDwJEONdKhRjqMv+kw/qZDjXSYlNGhRjrUSIca6XCHng6TMjrUSIca6VAjHe7QE6JGOoy/6TBwpEONdKiRDjXS4SkCHcbfdLhDT4eBIx1qpEONdKiRDpMyOtRIhxrpUCMdaiTE+JsONdLhKQIdBo50qJEONdJh/E2H8TcdaqTDpIwONdKhRjrUSMfaGv1QzRaTMjrUSIca6VAjHe7QE6JGOoy/6TBwpEO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",
                "typeCode": "invoice"
            },
        ],
    }
    INSURED_RATE_MOCK_RESPONSE = {
        "products": [
            {
                "productName": "EXPRESS DOMESTIC",
                "productCode": "N",
                "localProductCode": "L",
                "localProductCountryCode": "BE",
                "networkTypeCode": "TD",
                "isCustomerAgreement": False,
                "weight": {
                    "volumetric": 19.01,
                    "provided": 19.5,
                    "unitOfMeasurement": "metric",
                },
                "totalPrice": [
                    {"currencyType": "BILLC", "priceCurrency": "EUR", "price": 96.85},
                    {"currencyType": "PULCL", "price": 0},
                    {"currencyType": "BASEC", "price": 0},
                ],
                "totalPriceBreakdown": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "priceBreakdown": [
                            {"typeCode": "STTXA", "price": 14.9},
                            {"typeCode": "SPRQT", "price": 72.3},
                        ],
                    },
                ],
                "detailedPriceBreakdown": [
                    {
                        "currencyType": "BILLC",
                        "priceCurrency": "EUR",
                        "breakdown": [
                            {
                                "name": "EXPRESS DOMESTIC",
                                "price": 72.3,
                                "priceBreakdown": [
                                    {
                                        "priceType": "TAX",
                                        "typeCode": "EU_VAT",
                                        "price": 12.55,
                                        "rate": 21,
                                        "basePrice": 59.75,
                                    },
                                ],
                            },
                            {
                                "name": "FUEL SURCHARGE",
                                "serviceCode": "FF",
                                "localServiceCode": "FF",
                                "serviceTypeCode": "SCH",
                                "price": 13.55,
                                "isCustomerAgreement": False,
                                "isMarketedService": False,
                                "priceBreakdown": [
                                    {
                                        "priceType": "TAX",
                                        "typeCode": "EU_VAT",
                                        "price": 2.35,
                                        "rate": 21,
                                        "basePrice": 11.2,
                                    },
                                ],
                            },
                            {
                                "name": "SHIPMENT INSURANCE",
                                "serviceCode": "II",
                                "localServiceCode": "II",
                                "serviceTypeCode": "XCH",
                                "price": 11,
                                "isCustomerAgreement": False,
                                "isMarketedService": True,
                                "priceBreakdown": [
                                    {
                                        "priceType": "TAX",
                                        "typeCode": "Insura",
                                        "price": 0,
                                        "rate": 0,
                                        "basePrice": 11,
                                    },
                                ],
                            },
                        ],
                    },
                ],
                "pickupCapabilities": {
                    "nextBusinessDay": False,
                    "localCutoffDateAndTime": "2025-09-03T14:00:00",
                    "GMTCutoffTime": "16:00:00",
                    "pickupEarliest": "10:00:00",
                    "pickupLatest": "16:00:00",
                    "originServiceAreaCode": "BRU",
                    "originFacilityAreaCode": "LG1",
                    "pickupAdditionalDays": 0,
                    "pickupDayOfWeek": 3,
                },
                "deliveryCapabilities": {
                    "deliveryTypeCode": "QDDF",
                    "estimatedDeliveryDateAndTime": "2025-09-04T23:59:00",
                    "destinationServiceAreaCode": "BRU",
                    "destinationFacilityAreaCode": "LGG",
                    "deliveryAdditionalDays": 0,
                    "deliveryDayOfWeek": 4,
                    "totalTransitDays": 1,
                },
                "pricingDate": "2025-09-02",
            },
        ],
    }

    def is_insured_request(url, json):
        if 'rates' in url:
            return 'II' in [service['serviceCode'] for service in json['productsAndServices'][0]['valueAddedServices']]
        elif 'shipment' in url:
            return 'II' in [service['serviceCode'] for service in json.get('valueAddedServices', [])]

    def _mock_request(*args, **kwargs):
        url = kwargs.get('url')
        json_ = kwargs.get('json')  # not to override the json module
        responses = {
            'rates': INSURED_RATE_MOCK_RESPONSE,
            'shipments': SHIP_MOCK_RESPONSE,
        } if is_insured_request(url, json_) else {
            'rates': RATE_MOCK_RESPONSE,
            'shipments': SHIP_MOCK_RESPONSE,
        }

        for endpoint, content in responses.items():
            if endpoint in url:
                if specific_dhl_check:
                    specific_dhl_check(endpoint, kwargs['json'])
                response = requests.Response()
                response._content = json.dumps(content).encode()
                response.status_code = 200
                return response

    with patch.object(requests.Session, 'request', _mock_request):
        yield


@tagged('at_install', '-post_install')  # LEGACY at_install
class TestMockedDeliveryDHL(TestDeliveryDHLCommon):
    def test_01_dhl_basic_be_domestic_flow_with_insurance(self):
        with _mock_request_call():
            super().dhl_basic_be_domestic_flow_with_insurance()

    def test_02_dhl_basic_international_flow(self):
        def commercial_invoice_data_check(endpoint, payload):
            if endpoint == 'shipments':
                image_options = payload['outputImageProperties']['imageOptions']
                self.assertIn({
                    'typeCode': 'invoice',
                    'templateName': 'COMMERCIAL_INVOICE_P_10',
                    'languageCountryCode': 'BE',
                    'isRequested': True,
                    'invoiceType': 'commercial'
                }, image_options)

        with _mock_request_call(commercial_invoice_data_check):
            super().dhl_basic_international_flow()

    def test_03_dhl_multipackage_international_flow(self):
        with _mock_request_call():
            super().dhl_multipackage_international_flow()

    def test_04_dhl_flow_from_delivery_order(self):
        with _mock_request_call():
            super().dhl_flow_from_delivery_order()

    def test_05_dhl_test_export_declaration_rounding(self):
        """Test that the rounding respects the DHL requirements"""

        picking = self.env['stock.picking'].create({
            'partner_id': self.delta_pc.id,
            'picking_type_id': self.env.ref('stock.picking_type_out').id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'carrier_id': self.delivery_carrier_dhl_eu_intl.id,
            'move_ids': [
            Command.create({
                'product_id': self.iPadMini.id,
                'product_uom_qty': 7,
                'location_id': self.stock_location.id,
                'location_dest_id': self.customer_location.id,
            }),
            Command.create({
                'product_id': self.large_desk.id,
                'product_uom_qty': 7,
                'location_id': self.stock_location.id,
                'location_dest_id': self.customer_location.id,
            })
            ]
        })
        picking.action_confirm()
        picking.move_line_ids[0].sale_price = 11.43
        picking.move_line_ids[1].sale_price = 6.666666600000001
        dhl_provider = DHLProvider(self.delivery_carrier_dhl_eu_intl)
        export_declaration = dhl_provider._get_export_declaration_vals(self.delivery_carrier_dhl_eu_intl, picking)
        item_1, item_2 = export_declaration['lineItems']

        self.assertEqual(item_1['price'], 1.633)
        self.assertEqual(item_2['price'], 0.952)

    def test_06_dhl_weight_conversion_rounding(self):
        """Test that the weight conversion method correctly rounds according to DHL requirements"""

        weight_with_precision_issue = 0.7000000000000001
        rounded_weight_metric = self.delivery_carrier_dhl_eu_intl._dhl_rest_convert_weight(weight_with_precision_issue)
        self.assertEqual(rounded_weight_metric, 0.7)

        weight_needs_rounding = 1.23456789
        rounded_weight_precise = self.delivery_carrier_dhl_eu_intl._dhl_rest_convert_weight(weight_needs_rounding)
        self.assertEqual(rounded_weight_precise, 1.235)

    def test_07_dhl_specific_label_format_request(self):
        '''
        Ensure that label format settings of the delivery method are correctly communicated in the
        requests.
        '''
        def label_format_and_template_check_1(endpoint, payload):
            # ZPL format, ECOM26_84_001 and not A4 label
            if endpoint == 'shipments':
                properties = payload['outputImageProperties']
                self.assertEqual(properties['encodingFormat'], 'zpl')
                self.assertIn({
                    'typeCode': 'label',
                    'templateName': 'ECOM26_84_001',
                    'fitLabelsToA4': False,
                }, properties['imageOptions'])

        def label_format_and_template_check_2(endpoint, payload):
            # PDF format, ECOM26_A6_002 and A4 label
            if endpoint == 'shipments':
                properties = payload['outputImageProperties']
                self.assertEqual(properties['encodingFormat'], 'pdf')
                self.assertIn({
                    'typeCode': 'label',
                    'templateName': 'ECOM26_A6_002',
                    'fitLabelsToA4': True,
                }, properties['imageOptions'])

        sale_order_1, sale_order_2 = self.env['sale.order'].create([
            {
                'date_order': self.delivery_date,
                'carrier_id': self.delivery_carrier_dhl_eu_intl.id,
                'partner_id': self.delta_pc.id,
                'order_line': [Command.create({
                    'product_id': self.iPadMini.id,
                    'name': "[A1232] Large Cabinet",
                    'product_uom_id': self.uom_unit.id,
                    'product_uom_qty': 1.0,
                    'price_unit': self.iPadMini.lst_price,
                })],
            },
            {
                'date_order': self.delivery_date,
                'carrier_id': self.delivery_carrier_dhl_eu_intl.id,
                'partner_id': self.delta_pc.id,
                'order_line': [Command.create({
                    'product_id': self.iPadMini.id,
                    'name': "[A1232] Large Cabinet",
                    'product_uom_id': self.uom_unit.id,
                    'product_uom_qty': 2.0,
                    'price_unit': self.iPadMini.lst_price,
                })],
            },
        ])

        self.delivery_carrier_dhl_eu_intl.dhl_label_image_format = 'ZPL2'
        self.delivery_carrier_dhl_eu_intl.dhl_label_template = '8X4_thermal'
        with _mock_request_call():
            delivery_wizard = Form(self.env['choose.delivery.carrier'].with_context({
                'default_order_id': sale_order_1.id,
                'default_carrier_id': self.delivery_carrier_dhl_eu_intl.id
            }))
        with _mock_request_call(label_format_and_template_check_1):
            choose_delivery_carrier = delivery_wizard.save()
            choose_delivery_carrier.update_price()
            choose_delivery_carrier.button_confirm()

            sale_order_1.action_confirm()
            self.assertEqual(len(sale_order_1.picking_ids), 1)

            picking = sale_order_1.picking_ids[0]
            picking.move_ids[0].quantity = 1.0
            picking.move_ids[0].picked = True
            picking.scheduled_date = self.delivery_date
            picking._action_done()
            self.assertIsNot(picking.carrier_tracking_ref, False)

        self.delivery_carrier_dhl_eu_intl.dhl_label_image_format = 'PDF'
        self.delivery_carrier_dhl_eu_intl.dhl_label_template = '6X4_A4_PDF'
        with _mock_request_call():
            delivery_wizard = Form(self.env['choose.delivery.carrier'].with_context({
                'default_order_id': sale_order_2.id,
                'default_carrier_id': self.delivery_carrier_dhl_eu_intl.id
            }))
        with _mock_request_call(label_format_and_template_check_2):
            choose_delivery_carrier = delivery_wizard.save()
            choose_delivery_carrier.update_price()
            choose_delivery_carrier.button_confirm()

            sale_order_2.action_confirm()
            self.assertEqual(len(sale_order_2.picking_ids), 1)

            picking = sale_order_2.picking_ids[0]
            picking.move_ids[0].quantity = 1.0
            picking.move_ids[0].picked = True
            picking.scheduled_date = self.delivery_date
            picking._action_done()
            self.assertIsNot(picking.carrier_tracking_ref, False)

    def test_dhl_basic_international_flow_multi_company(self):
        def commercial_invoice_data_check(endpoint, payload):
            if endpoint == 'shipments':
                invoice_number_string = payload['content']['exportDeclaration']['invoice']['number']
                self.assertIsInstance(invoice_number_string, str)
                invoice_number_int = int(''.join(filter(str.isnumeric, invoice_number_string)))
                sequence = self.env['ir.sequence'].search([('code', '=', 'delivery_dhl_rest.commercial_invoice')])
                self.assertEqual(invoice_number_int + sequence.number_increment, sequence.number_next_actual)

        with _mock_request_call(commercial_invoice_data_check):
            self.patch(self, 'env', self.uk_co.env)
            super().dhl_basic_international_flow()
