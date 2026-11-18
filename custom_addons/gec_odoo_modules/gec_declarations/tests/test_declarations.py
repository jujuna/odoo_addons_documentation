from odoo.tests import TransactionCase, tagged

from ..models.gec_declaration_card import MENU_MOVES


@tagged('post_install', '-at_install')
class TestDeclarations(TransactionCase):

    def _installed_moves(self):
        return [move for move in MENU_MOVES if self.env.ref(move[0], raise_if_not_found=False)]

    def test_menus_moved_and_restored(self):
        """The declaration menus sit in this app, go back to Accounting on restore, and return here again."""
        moves = self._installed_moves()
        self.assertTrue(moves, "at least one declaration module should be installed to test the move")
        for xmlid, parent_here, sequence_here, _back, _sequence_back in moves:
            self.assertEqual(self.env.ref(xmlid).parent_id, self.env.ref(parent_here), xmlid)
        Card = self.env['gec.declaration.card']
        Card._gec_place_menus(restore=True)
        for xmlid, _here, _sequence_here, parent_back, sequence_back in moves:
            menu = self.env.ref(xmlid)
            self.assertEqual((menu.parent_id, menu.sequence), (self.env.ref(parent_back), sequence_back), xmlid)
        Card._gec_place_menus()
        for xmlid, parent_here, sequence_here, _back, _sequence_back in moves:
            self.assertEqual(self.env.ref(xmlid).parent_id, self.env.ref(parent_here), xmlid)

    def test_cards_show_installed_modules_only(self):
        Card = self.env['gec.declaration.card']
        available = Card.search([('available', '=', True)])
        self.assertEqual(set(available.mapped('model_name')),
                         {card.model_name for card in Card.search([]) if card.model_name in self.env})
        card = Card.create({'name': 'Missing', 'module_name': 'no_such_module', 'model_name': 'no.such.model',
                            'action_xmlid': 'no_such_module.action'})
        self.assertFalse(card.available)
        self.assertNotIn(card, Card.search([('available', '=', True)]))

    def test_card_counts_drafts_and_opens_the_existing_action(self):
        card = self.env['gec.declaration.card'].search([('available', '=', True)], limit=1)
        if not card:
            self.skipTest("no declaration module installed")
        Model = self.env[card.model_name]
        self.assertEqual(card.draft_count, Model.search_count([('state', '=', 'draft')]))
        action = card.action_open()
        self.assertEqual(action['res_model'], card.model_name)
        self.assertEqual(card.action_new()['views'], [(False, 'form')])
        self.assertEqual(card.action_open_drafts()['domain'], [('state', '=', 'draft')])
        if card.frequency == 'monthly':
            self.assertEqual(card.next_due.day, 15)
