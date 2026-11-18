from odoo import models


class AccountMoveLine(models.Model):
    """Carry the matched distribution model's activity onto the analytic items a line creates.

    Done on the outgoing values dict, not in ``_compute_analytic_distribution`` or ``_get_distribution``."""
    _inherit = 'account.move.line'

    def _create_analytic_lines(self):
        if 'gec_activity_cache' not in self.env.context:
            self = self.with_context(gec_activity_cache={})
        return super()._create_analytic_lines()

    def _prepare_analytic_lines(self):
        vals_list = super()._prepare_analytic_lines()
        activity_id = self._gec_activity_from_distribution_models()
        if activity_id:
            for vals in vals_list:
                vals['gec_activity_id'] = activity_id
        return vals_list

    def _gec_activity_from_distribution_models(self):
        """Activity of the first matching distribution model that names one.
        An activity cannot be merged: the lowest ``sequence, id desc`` wins, as in core."""
        self.ensure_one()
        Distribution = self.env['account.analytic.distribution.model']
        if 'gec_activity_id' not in Distribution._fields:
            return False

        arguments = self._get_analytic_distribution_arguments(
            self.env['account.analytic.account'].browse().root_plan_id
        )
        arguments.pop('related_root_plan_ids', None)

        cache = self.env.context.get('gec_activity_cache')
        key = tuple(sorted(
            (name, tuple(value) if isinstance(value, list) else value)
            for name, value in arguments.items()
        ))
        if cache is not None and key in cache:
            return cache[key]

        activity_id = False
        for model in Distribution._get_applicable_models(arguments):
            if model.gec_activity_id:
                activity_id = model.gec_activity_id.id
                break

        if cache is not None:
            cache[key] = activity_id
        return activity_id
