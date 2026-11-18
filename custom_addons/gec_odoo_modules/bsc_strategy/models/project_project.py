# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    bsc_initiative_ids = fields.One2many(
        'bsc.initiative', 'project_id', string='Strategic Initiatives')
    bsc_initiative_count = fields.Integer(compute='_compute_bsc_initiative_count')

    @api.depends('bsc_initiative_ids')
    def _compute_bsc_initiative_count(self):
        for project in self:
            project.bsc_initiative_count = len(project.bsc_initiative_ids)

    def action_open_bsc_initiatives(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Strategic Initiatives"),
            'res_model': 'bsc.initiative',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.bsc_initiative_ids.ids)],
        }


class ProjectTask(models.Model):
    _inherit = 'project.task'

    bsc_initiative_ids = fields.One2many(
        'bsc.initiative', 'task_id', string='Strategic Initiatives')

    # Fields whose change can move an initiative's progress.
    _BSC_PROGRESS_FIELDS = {'state', 'stage_id', 'project_id', 'parent_id', 'active'}

    # A folded column whose name says so is a cancellation, not a finish.
    _BSC_NOT_DONE_WORDS = ('cancel', 'lost', 'hold', 'გაუქმ', 'შეჩერ')

    @api.model
    def _bsc_stage_ids(self):
        """(done stage id, cancelled stage id) of the scorecard's own board, from the cached xmlid lookup."""
        IrData = self.env['ir.model.data']
        return (IrData._xmlid_to_res_id('bsc_strategy.task_stage_done'),
                IrData._xmlid_to_res_id('bsc_strategy.task_stage_cancelled'))

    def _bsc_closed_kind(self, stage_ids=None):
        """'done', 'cancelled' or False, as the scorecard reads this task.
        Odoo's state decides first; a card in a folded column counts as done
unless the column is named a cancellation or pause."""
        self.ensure_one()
        done_id, cancel_id = stage_ids or self._bsc_stage_ids()
        if self.state == '1_canceled' or (cancel_id and self.stage_id.id == cancel_id):
            return 'cancelled'
        if self.state == '1_done' or (done_id and self.stage_id.id == done_id):
            return 'done'
        if self.stage_id.fold:
            name = (self.stage_id.with_context(lang='en_US').name or '').lower() + ' ' + \
                (self.stage_id.name or '').lower()
            if any(word in name for word in self._BSC_NOT_DONE_WORDS):
                return 'cancelled'
            return 'done'
        return False

    def _bsc_state_for_stage(self, stage_id):
        """Dropping a card into the scorecard's Done / Cancelled column closes it; other boards are left alone."""
        done_id, cancel_id = self._bsc_stage_ids()
        if done_id and stage_id == done_id:
            return '1_done'
        if cancel_id and stage_id == cancel_id:
            return '1_canceled'
        return False

    def _bsc_related_initiatives(self):
        tasks = self.sudo().with_context(active_test=False)
        ancestors = self.env['project.task'].sudo().with_context(active_test=False).search(
            [('id', 'parent_of', tasks.ids)]) if tasks else tasks
        return self.env['bsc.initiative'].sudo().search([
            '|', ('project_id', 'in', (tasks.project_id | ancestors.project_id).ids),
            ('task_id', 'in', ancestors.ids),
        ])

    @api.model_create_multi
    def create(self, vals_list):
        """A task created in the scorecard's Done / Cancelled column gets the matching state (see write)."""
        default_stage = self.env.context.get('default_stage_id')
        closed = [None if 'state' in vals else self._bsc_state_for_stage(
            vals.get('stage_id') or default_stage) for vals in vals_list]
        vals_list = [dict(vals, state=state) if state else vals
                     for vals, state in zip(vals_list, closed)]
        tasks = super().create(vals_list)
        tasks._bsc_related_initiatives()._sync_progress_from_tasks()
        return tasks

    def write(self, vals):
        reopen = self.browse()
        if vals.get('stage_id') and 'state' not in vals:
            state = self._bsc_state_for_stage(vals['stage_id'])
            if state:
                vals = dict(vals, state=state)
            elif not self.env['project.task.type'].browse(vals['stage_id']).fold:
                # Odoo keeps a closed task closed when it leaves Done / Cancelled; reopen it.
                bsc_stages = [sid for sid in self._bsc_stage_ids() if sid]
                reopen = self.filtered(lambda t: t.state in ('1_done', '1_canceled')
                                       and t.stage_id.id in bsc_stages)
        touches = bool(self._BSC_PROGRESS_FIELDS & set(vals))
        before = self._bsc_related_initiatives() if touches else None
        result = super().write(vals)
        if reopen:
            super(ProjectTask, reopen).write({'state': '01_in_progress'})
        if touches:
            (before | self._bsc_related_initiatives())._sync_progress_from_tasks()
        return result

    def unlink(self):
        initiatives = self._bsc_related_initiatives()
        result = super().unlink()
        initiatives.exists()._sync_progress_from_tasks()
        return result
