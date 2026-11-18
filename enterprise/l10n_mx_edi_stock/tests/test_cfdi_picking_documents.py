import json
from unittest.mock import Mock, patch

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from .common import TestMXEdiStockCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestCFDIPickingWorkflow(TestMXEdiStockCommon):

    def test_picking_workflow(self):
        picking = self._create_picking()

        # No pac found.
        self.env.company.l10n_mx_edi_pac = None
        with freeze_time('2017-01-05'):
            picking.l10n_mx_edi_cfdi_try_send()
        self.assertRecordValues(picking.l10n_mx_edi_document_ids, [
            {
                'datetime': fields.Datetime.from_string('2017-01-05 00:00:00'),
                'message': "No PAC specified.",
                'state': 'picking_sent_failed',
                'sat_state': False,
                'cancellation_reason': False,
                'cancel_button_needed': False,
                'retry_button_needed': True,
            },
        ])
        self.assertRecordValues(picking, [{'l10n_mx_edi_cfdi_state': None}])

        # Set back the PAC but make it raising an error.
        self.env.company.l10n_mx_edi_pac = 'solfact'
        with freeze_time('2017-01-06'), self.with_mocked_pac_sign_error():
            picking.l10n_mx_edi_cfdi_try_send()
        self.assertRecordValues(picking.l10n_mx_edi_document_ids, [
            {
                'datetime': fields.Datetime.from_string('2017-01-06 00:00:00'),
                'message': "turlututu",
                'state': 'picking_sent_failed',
                'sat_state': False,
                'cancellation_reason': False,
                'cancel_button_needed': False,
                'retry_button_needed': True,
            },
        ])
        self.assertRecordValues(picking, [{'l10n_mx_edi_cfdi_state': None}])

        # The failing attachment remains accessible for the user.
        self.assertTrue(picking.l10n_mx_edi_document_ids.attachment_id)

        # Sign.
        with freeze_time('2017-01-07'), self.with_mocked_pac_sign_success():
            picking.l10n_mx_edi_document_ids.action_retry()
        sent_doc_values = {
            'datetime': fields.Datetime.from_string('2017-01-07 00:00:00'),
            'message': False,
            'state': 'picking_sent',
            'sat_state': 'not_defined',
            'cancellation_reason': False,
            'cancel_button_needed': True,
            'retry_button_needed': False,
        }
        self.assertRecordValues(picking.l10n_mx_edi_document_ids, [sent_doc_values])
        self.assertTrue(picking.l10n_mx_edi_cfdi_attachment_id)
        self.assertTrue(picking.l10n_mx_edi_document_ids.attachment_id)
        self.assertRecordValues(picking, [{'l10n_mx_edi_cfdi_state': 'sent'}])

        # Cancel failed.
        self.env.company.l10n_mx_edi_pac = None
        with freeze_time('2017-02-01'):
            picking._l10n_mx_edi_cfdi_try_cancel(picking.l10n_mx_edi_document_ids)
        self.assertRecordValues(picking.l10n_mx_edi_document_ids.sorted(), [
            {
                'datetime': fields.Datetime.from_string('2017-02-01 00:00:00'),
                'message': "No PAC specified.",
                'state': 'picking_cancel_failed',
                'sat_state': False,
                'cancellation_reason': '02',
                'cancel_button_needed': False,
                'retry_button_needed': True,
            },
            sent_doc_values,
        ])

        # Set back the PAC but make it raising an error.
        self.env.company.l10n_mx_edi_pac = 'solfact'
        with freeze_time('2017-02-06'), self.with_mocked_pac_cancel_error():
            picking.l10n_mx_edi_document_ids.sorted()[0].action_retry()
        self.assertRecordValues(picking.l10n_mx_edi_document_ids.sorted(), [
            {
                'datetime': fields.Datetime.from_string('2017-02-06 00:00:00'),
                'message': "turlututu",
                'state': 'picking_cancel_failed',
                'sat_state': False,
                'cancellation_reason': '02',
                'cancel_button_needed': False,
                'retry_button_needed': True,
            },
            sent_doc_values,
        ])

        # Cancel
        with freeze_time('2017-02-07'), self.with_mocked_pac_cancel_success():
            picking.l10n_mx_edi_document_ids.sorted()[0].action_retry()

        picking.l10n_mx_edi_document_ids.invalidate_recordset(fnames=['cancel_button_needed'])
        sent_doc_values['cancel_button_needed'] = False
        sent_doc_values['sat_state'] = 'skip'

        cancel_doc_values = {
            'datetime': fields.Datetime.from_string('2017-02-07 00:00:00'),
            'message': False,
            'state': 'picking_cancel',
            'sat_state': 'not_defined',
            'cancellation_reason': '02',
            'cancel_button_needed': False,
            'retry_button_needed': False,
        }
        self.assertRecordValues(picking.l10n_mx_edi_document_ids.sorted(), [
            cancel_doc_values,
            sent_doc_values,
        ])
        self.assertRecordValues(picking, [{'l10n_mx_edi_cfdi_state': 'cancel'}])

        # Sign again.
        with freeze_time('2017-03-10'), self.with_mocked_pac_sign_success():
            picking.l10n_mx_edi_cfdi_try_send()
        sent_doc_values2 = {
            'datetime': fields.Datetime.from_string('2017-03-10 00:00:00'),
            'message': False,
            'state': 'picking_sent',
            'sat_state': 'not_defined',
            'cancellation_reason': False,
            'cancel_button_needed': True,
            'retry_button_needed': False,
        }
        self.assertRecordValues(picking.l10n_mx_edi_document_ids.sorted(), [
            sent_doc_values2,
            cancel_doc_values,
            sent_doc_values,
        ])
        self.assertRecordValues(picking, [{'l10n_mx_edi_cfdi_state': 'sent'}])

        # Sat.
        with freeze_time('2017-04-01'), self.with_mocked_sat_call(lambda x: 'valid' if x['state'] == 'picking_sent' else 'cancelled'):
            picking.l10n_mx_edi_cfdi_try_sat()
        sent_doc_values2['sat_state'] = 'valid'
        cancel_doc_values['sat_state'] = 'cancelled'
        self.assertRecordValues(picking.l10n_mx_edi_document_ids.sorted(), [
            sent_doc_values2,
            cancel_doc_values,
            sent_doc_values,
        ])
        self.assertRecordValues(picking, [{'l10n_mx_edi_cfdi_state': 'sent'}])

    def test_picking_production_sign_flow_cancel_from_the_sat(self):
        """ Test the case the invoice/payment is signed but the user manually cancel the document from the SAT portal (production environment). """
        self.env.company.l10n_mx_edi_pac_test_env = False
        self.env.company.l10n_mx_edi_pac_username = 'test'
        self.env.company.l10n_mx_edi_pac_password = 'test'

        with freeze_time('2017-01-01'):
            picking = self._create_picking()
            with self.with_mocked_pac_sign_success():
                picking.l10n_mx_edi_cfdi_try_send()
            with self.with_mocked_sat_call(lambda _x: 'valid'):
                picking.l10n_mx_edi_cfdi_try_sat()
            sent_doc_values = {
                'picking_id': picking.id,
                'state': 'picking_sent',
                'sat_state': 'valid',
            }
            self.assertRecordValues(picking.l10n_mx_edi_document_ids, [sent_doc_values])
            self.assertRecordValues(picking, [{
                'l10n_mx_edi_update_sat_needed': True,
                'l10n_mx_edi_cfdi_sat_state': 'valid',
                'l10n_mx_edi_cfdi_state': 'sent',
            }])

        # Manual cancellation from the SAT portal.
        with self.with_mocked_sat_call(lambda _x: 'cancelled'):
            picking.l10n_mx_edi_cfdi_try_sat()

        cancel_doc_values = {
            'picking_id': picking.id,
            'state': 'picking_cancel',
            'sat_state': 'cancelled',
        }
        self.assertRecordValues(picking.l10n_mx_edi_document_ids.sorted(), [
            cancel_doc_values,
            sent_doc_values,
        ])
        self.assertRecordValues(picking, [{
            'l10n_mx_edi_update_sat_needed': False,
            'l10n_mx_edi_cfdi_sat_state': 'cancelled',
            'l10n_mx_edi_cfdi_state': 'cancel',
        }])

    def test_picking_mapbox_coordinates_and_distance(self):
        self.env['ir.config_parameter'].sudo().set_str('web_map.token_map_box', 'dummy_token')
        warehouse = self.mx_warehouse
        picking = self._create_picking(warehouse)
        mapbox_responses = [
            self._mapbox_response({'features': [{'geometry': {'coordinates': [-100.3161, 25.6866]}}]}),
            self._mapbox_response({'features': [{'geometry': {'coordinates': [-99.1332, 19.4326]}}]}),
            self._mapbox_response({'distances': [[0, 903000]]}),
        ]
        with patch.object(self.env.registry['stock.picking'], '_l10n_mx_edi_request_mapbox', side_effect=mapbox_responses) as mapbox:
            picking.l10n_mx_edi_action_set_partner_coordinates()
            picking.l10n_mx_edi_action_calculate_distance()

        self.assertEqual(
            (warehouse.partner_id.partner_latitude, warehouse.partner_id.partner_longitude),
            (25.6866, -100.3161),
            "Warehouse partner: Mapbox [lon, lat] must be stored as latitude 25.6866, longitude -100.3161",
        )
        self.assertEqual(
            (picking.partner_id.partner_latitude, picking.partner_id.partner_longitude),
            (19.4326, -99.1332),
            "Delivery partner: Mapbox [lon, lat] must be stored as latitude 19.4326, longitude -99.1332",
        )
        self.assertEqual(
            mapbox.call_args_list[2].args[0],
            'https://api.mapbox.com/directions-matrix/v1/mapbox/driving/-100.3161,25.6866;-99.1332,19.4326',
            "Distance matrix URL: each coordinate pair must be lon,lat",
        )
        self.assertEqual(picking.l10n_mx_edi_distance, 903, "Distance: the matrix distance must be stored in km")

    def test_picking_mapbox_distance_with_outdated_coordinates(self):
        self.env['ir.config_parameter'].sudo().set_str('web_map.token_map_box', 'dummy_token')
        warehouse = self.mx_warehouse
        picking = self._create_picking(warehouse)
        warehouse.partner_id.write({'partner_latitude': -100.3161, 'partner_longitude': 25.6866})
        picking.partner_id.write({'partner_latitude': -99.1332, 'partner_longitude': 19.4326})
        error = self._mapbox_response({'code': 'InvalidInput', 'message': 'Coordinate is invalid'})
        with patch.object(self.env.registry['stock.picking'], '_l10n_mx_edi_request_mapbox', return_value=error):
            with self.assertRaisesRegex(UserError, 'Get Coordinates'):
                picking.l10n_mx_edi_action_calculate_distance()

    def _mapbox_response(self, payload):
        return Mock(content=json.dumps(payload))
