# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo import Command
from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestPosOrder(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.module_pos_restaurant = True
        floor = cls.env['restaurant.floor'].create({
            'name': 'Main Floor',
            'pos_config_ids': [(4, cls.config.id)],
        })
        cls.table1, cls.table2 = cls.env['restaurant.table'].create([
            {'table_number': 1, 'floor_id': floor.id},
            {'table_number': 2, 'floor_id': floor.id},
        ])
        cls.product = cls.create_product('Coconut', cls.categ_basic, 10)
        cls.kitchen_display = cls.env['pos.prep.display'].create({
            'name': 'Kitchen',
            'pos_config_ids': [Command.link(cls.config.id)],
        })
        cls.bar_display = cls.env['pos.prep.display'].create({
            'name': 'Bar',
            'pos_config_ids': [Command.link(cls.config.id)],
            'category_ids': [Command.link(cls.env['pos.category'].create({'name': 'Drinks'}).id)],
        })

    def _create_table_order(self, table):
        return next(iter(self._create_orders([{
            'pos_order_lines_ui_args': [(self.product, 1)],
            'pos_order_ui_args': {'table_id': table.id, 'state': 'draft'},
        }]).values()))

    def test_table_transfer_reloads_the_preparation_display(self):
        self.open_new_session()
        sent_order = self._create_table_order(self.table1)
        draft_order = self._create_table_order(self.table1)
        self.env['pos.prep.order'].update_last_order_change(sent_order)

        reloads = []
        with patch(
            'odoo.addons.pos_enterprise.models.pos_prep_display.PosPrepDisplay._send_load_orders_message',
            autospec=True,
            side_effect=lambda display, sound=False, notification=None, orderId=None: reloads.append((display.id, orderId)),
        ):
            sent_order.write({'table_id': self.table2.id})
            self.assertEqual(
                reloads, [(self.kitchen_display.id, sent_order.id)],
                "Transferring a sent order must reload the kitchen display, not the bar one",
            )

            draft_order.write({'table_id': self.table2.id})
            self.assertEqual(len(reloads), 1, "An order never sent to the kitchen must not reload the display")

            sent_order.write({'table_id': False, 'floating_order_name': 'Alice'})
            self.assertEqual(
                reloads, [(self.kitchen_display.id, sent_order.id)] * 2,
                "Moving an order to a floating name must reload the display exactly once",
            )

            sent_order.write({'floating_order_name': 'Alice'})
            self.assertEqual(len(reloads), 2, "Writing the same name again must not reload the display")
