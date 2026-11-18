# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRestaurantTable(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.floor = cls.env['restaurant.floor'].create({'name': 'Main Floor'})

    def _create_table(self, table_number, seats):
        return self.env['restaurant.table'].create({
            'floor_id': self.floor.id,
            'table_number': table_number,
            'seats': seats,
        })

    def assertResource(self, table, name, capacity, active):
        resource = table.appointment_resource_id
        self.assertRecordValues(resource, [{'name': name, 'capacity': capacity, 'active': active}])
        self.assertEqual(resource.with_context(active_test=False).pos_table_ids, table)

    def test_resource_created_with_table(self):
        self.assertResource(self._create_table(1, 4), 'Table 1', 4, True)
        # A table needs at least one seat, as its resource capacity can't be lower than 1
        table = self._create_table(2, 0)
        self.assertEqual(table.seats, 1)
        self.assertResource(table, 'Table 2', 1, True)

    def test_resource_synced_with_table(self):
        table = self._create_table(1, 4)
        resource = table.appointment_resource_id

        # Same values as the floor plan editor saves
        table.write({'table_number': 5, 'seats': 6})
        self.assertResource(table, 'Table 5', 6, True)

        # A table keeps at least one seat
        table.seats = 0
        self.assertEqual(table.seats, 1)
        self.assertResource(table, 'Table 5', 1, True)
        table.seats = 2
        self.assertResource(table, 'Table 5', 2, True)

        table.active = False
        self.assertResource(table, 'Table 5', 2, False)
        table.write({'active': True, 'seats': 3})
        self.assertResource(table, 'Table 5', 3, True)

        self.assertEqual(table.appointment_resource_id, resource)
