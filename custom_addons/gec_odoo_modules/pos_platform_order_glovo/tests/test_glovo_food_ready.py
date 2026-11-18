from unittest.mock import patch

import requests

from odoo.tests import tagged

from odoo.addons.pos_platform_order_glovo.tests.common import TestGlovoCommon

CLIENT = 'odoo.addons.glovo_base.utils.glovo_client'
TOKEN_MSG = "Glovo refused the store's token. Ask a POS manager to check the Glovo token."
DOWN_MSG = "Glovo isn't responding. Try again in a minute."
CHECK_MSG = "Glovo couldn't mark this order ready. Check the order in the Glovo Partner Webapp or ask a POS manager."


class FakeGlovo:
    """Answers the client's calls in turn and keeps a fake clock: a timeout uses up the time it was given."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.now = 0.0
        self.timeouts = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def request(self, method, url, headers=None, timeout=None):
        self.timeouts.append(timeout)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, type) and issubclass(answer, Exception):
            self.now += timeout
            raise answer("simulated")
        response = requests.Response()
        response.status_code = answer
        response._content = b'{"error": "simulated"}' if answer >= 400 else b''
        return response


@tagged('post_install', '-at_install')
class TestGlovoFoodReady(TestGlovoCommon):

    def setUp(self):
        super().setUp()
        self.main_pos_config.with_user(self.pos_user).open_ui()

    def _food_ready(self, order, glovo):
        with patch(f'{CLIENT}.requests.request', glovo.request), patch(f'{CLIENT}.time', glovo):
            return order.with_user(self.pos_user).platform_order_status_update_from_ui('food_ready')

    def test_plain_messages_and_retry_after_failure(self):
        self._webhook('dispatched', '7901')
        order = self._glovo_order('7901')
        cases = [
            (401, TOKEN_MSG, 1), (404, CHECK_MSG, 1), (409, CHECK_MSG, 1), (503, CHECK_MSG, 1),
            (429, DOWN_MSG, 3), (500, DOWN_MSG, 3), (502, DOWN_MSG, 3),
            (requests.Timeout, DOWN_MSG, 2), (requests.ConnectionError, DOWN_MSG, 2),
        ]
        for answer, message, calls in cases:
            with self.subTest(answer=answer):
                glovo = FakeGlovo(answer)
                with self.assertLogs('odoo.addons.pos_platform_order_glovo.models.pos_order', 'ERROR') as logs:
                    result = self._food_ready(order, glovo)
                self.assertEqual(result, {'success': False, 'message': message})
                self.assertEqual(len(glovo.timeouts), calls)
                self.assertIn("failed to mark order 7901 ready for pickup", logs.output[0])
                self.assertFalse(order.platform_order_food_ready)
        # the button works again: the next Set Food Ready reaches Glovo and succeeds
        self.assertTrue(self._food_ready(order, FakeGlovo(204))['success'])
        self.assertTrue(order.platform_order_food_ready)

    def test_timeout_retried_once_within_15_seconds(self):
        self._webhook('dispatched', '7902')
        order = self._glovo_order('7902')
        glovo = FakeGlovo(requests.Timeout)
        with self.assertLogs('odoo.addons.pos_platform_order_glovo.models.pos_order', 'ERROR'):
            self.assertEqual(self._food_ready(order, glovo)['message'], DOWN_MSG)
        self.assertEqual(glovo.timeouts, [10, 5])
        self.assertLessEqual(glovo.now, 15)

        # a retry after a timeout that gets 204 is a success; the spec defines no "already ready" answer
        glovo = FakeGlovo(requests.Timeout, 204)
        self.assertTrue(self._food_ready(order, glovo)['success'])
        self.assertEqual(len(glovo.timeouts), 2)
        self.assertTrue(order.platform_order_food_ready)

    def test_already_ready_is_success_without_calling_glovo(self):
        self._webhook('dispatched', '7903')
        order = self._glovo_order('7903')
        self.assertTrue(self._food_ready(order, FakeGlovo(204))['success'])
        glovo = FakeGlovo(500)
        self.assertTrue(self._food_ready(order, glovo)['success'])
        self.assertEqual(glovo.timeouts, [])

    def test_preparation_display_done_waits_for_glovo(self):
        self._webhook('dispatched', '7904')
        order = self._glovo_order('7904')
        self.env['pos.prep.display'].search([]).unlink()
        stage = self.env['pos.prep.stage'].create({'name': 'Ready', 'sequence': 1})
        display = self.env['pos.prep.display'].create({
            'name': 'Glovo display', 'pos_config_ids': [(4, self.main_pos_config.id)], 'stage_ids': [(4, stage.id)],
        })
        self.env['pos.prep.order'].update_last_order_change(order)
        # first Done: Glovo answers 500 three times; second Done: 204
        glovo = FakeGlovo(500, 500, 500, 204)
        with patch(f'{CLIENT}.requests.request', glovo.request), patch(f'{CLIENT}.time', glovo):
            self.start_tour(f"/pos_preparation_display/web?display_id={display.id}", 'glovo_prep_display_tour', login='pos_user')
        self.assertTrue(order.platform_order_food_ready)
        self.assertEqual(len(glovo.timeouts), 4)
