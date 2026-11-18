# -*- coding: utf-8 -*-
"""Project execution for an initiative.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


TASK_STAGE_XMLIDS = {
    "To Do": 'task_stage_todo',
    "In Progress": 'task_stage_in_progress',
    "Done": 'task_stage_done',
    "Cancelled": 'task_stage_cancelled',
}


class BscScorecardProject(models.Model):
    _inherit = 'bsc.scorecard'

    task_project_id = fields.Many2one(
        'project.project', string='Initiatives Project', readonly=True, copy=False,
        check_company=True, ondelete='set null',
        help="The shared project that holds the single-task initiatives of this scorecard.")


class BscInitiativeProject(models.Model):
    _inherit = 'bsc.initiative'

    project_id = fields.Many2one(
        'project.project', string='Execution Project', ondelete='set null', copy=False,
        check_company=True,
        help="For an initiative big enough to need its own tasks, budget and team.")
    task_id = fields.Many2one(
        'project.task', string='Execution Task', ondelete='set null', copy=False,
        check_company=True,
        help="For an initiative that is really one piece of work.")
    task_count = fields.Integer(compute='_compute_project_progress')
    task_done_count = fields.Integer(compute='_compute_project_progress')
    project_progress = fields.Float(
        compute='_compute_project_progress', string='Progress in Project (%)',
        digits=(16, 1))
    use_project_progress = fields.Boolean(
        string='Track Progress from Project', default=True,
        help="When set, the progress figure follows the closed tasks of the linked "
             "project (or the state of the linked task) instead of being typed in.")

    @api.depends('project_id', 'task_id',
                 'project_id.task_ids.state', 'project_id.task_ids.stage_id',
                 'task_id.state', 'task_id.stage_id', 'task_id.child_ids.state')
    def _compute_project_progress(self):
        """Share of work units that are done.
        A work unit is a task without subtasks; cancelled tasks are left out.
        Done: state Done, or sitting in a folded column."""
        stage_ids = self.env['project.task']._bsc_stage_ids()
        for initiative in self:
            tasks = initiative._execution_tasks()
            done = tasks.filtered(lambda t: t._bsc_closed_kind(stage_ids) == 'done')
            initiative.task_count = len(tasks)
            initiative.task_done_count = len(done)
            initiative.project_progress = (len(done) / len(tasks) * 100.0) if tasks else 0.0

    def _execution_tasks(self):
        """The work units behind the initiative, cancelled ones excluded."""
        self.ensure_one()
        Task = self.env['project.task'].sudo().with_context(active_test=False)
        if self.project_id:
            tasks = Task.search([('project_id', '=', self.project_id.id)])
        elif self.task_id:
            tasks = Task.search([('id', 'child_of', self.task_id.id)])
        else:
            return Task.browse()
        stage_ids = Task._bsc_stage_ids()
        tasks = tasks.filtered(lambda t: t.active or t._bsc_closed_kind(stage_ids))
        leaves = tasks.filtered(lambda t: not (t.child_ids & tasks))
        return leaves.filtered(lambda t: t._bsc_closed_kind(stage_ids) != 'cancelled')

    def _check_can_create_execution(self):
        """A project or task is made only while the initiative is approved or running."""
        self.ensure_one()
        if self.state not in ('approved', 'in_progress'):
            raise UserError(_(
                "A project or task can be created only while the initiative is approved "
                "or in progress."))

    def action_create_project(self):
        """Create the project that carries out this initiative, with the user's rights.
        The link is written as superuser (manager's field, see bsc_security.py) after the write-right check."""
        self.check_access('write')
        self.ensure_one()
        if self.project_id:
            return self.action_open_project()
        self._check_can_create_execution()
        project = self.env['project.project'].create(self._prepare_project_values())
        self.sudo().write({'project_id': project.id, 'use_project_progress': True})
        self.action_sync_progress()
        self.message_post(body=_("Execution project created: %s", project.display_name))
        return self.action_open_project()

    def _prepare_project_values(self):
        self.ensure_one()
        return {
            'name': self.name,
            'user_id': self.owner_id.id,
            'company_id': self.company_id.id,
            'date_start': self.date_start,
            'date': self.date_end,
            'description': self.expected_impact or '',
            'type_ids': [(6, 0, self._initiative_task_stage_ids())],
        }

    # Odoo ships task stages only as demo data, so stock the board here.
    TASK_STAGES = [
        ("To Do", 10, False),
        ("In Progress", 20, False),
        ("Done", 30, True),
        ("Cancelled", 40, True),
    ]

    @api.model
    def _initiative_task_stage_ids(self):
        """The scorecard's shared task stages (data/bsc_task_stage_data.xml), not personal ones.
        A deleted stage is recreated; a stage with an owner is unreadable to others, so the owner is cleared."""
        Stage = self.env['project.task.type'].sudo()
        IrData = self.env['ir.model.data'].sudo()
        stage_ids = []
        for name, sequence, fold in self.TASK_STAGES:
            xmlid = 'bsc_strategy.%s' % TASK_STAGE_XMLIDS[name]
            stage = self.env.ref(xmlid, raise_if_not_found=False)
            if not stage:
                stage = Stage.create({'name': name, 'sequence': sequence, 'fold': fold,
                                      'user_id': False})
                IrData._update_xmlids([{'xml_id': xmlid, 'record': stage, 'noupdate': True}])
            elif stage.sudo().user_id:
                stage.sudo().user_id = False
            stage_ids.append(stage.id)
        return stage_ids

    def action_create_task(self):
        """Create a single task for a small initiative; linked as in action_create_project."""
        self.check_access('write')
        self.ensure_one()
        if self.task_id:
            return self.action_open_task()
        self._check_can_create_execution()
        project = self.project_id or self._get_default_task_project()
        stages = self._initiative_task_stage_ids()
        task = self.env['project.task'].create({
            'name': self.name,
            'project_id': project.id,
            'stage_id': stages[0] if stages else False,
            'user_ids': [(6, 0, self.owner_id.ids)],
            'date_deadline': self.date_end,
            'description': self.expected_impact or '',
        })
        self.sudo().write({'task_id': task.id, 'use_project_progress': True})
        self.action_sync_progress()
        self.message_post(body=_("Execution task created: %s", task.display_name))
        return self.action_open_task()

    def _get_default_task_project(self):
        """One shared project per scorecard for small initiatives, stored on the scorecard.
        Without a stored one, a project is matched by the standard name, else created."""
        self.ensure_one()
        card = self.scorecard_id
        project = card.task_project_id
        if not project:
            name = _("Strategic initiatives - %s", card.name)
            project = self.env['project.project'].search([
                ('name', '=', name),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if not project:
                project = self.env['project.project'].create({
                    'name': name,
                    'user_id': card.responsible_id.id,
                    'company_id': self.company_id.id,
                    'type_ids': [(6, 0, self._initiative_task_stage_ids())],
                })
            card.sudo().task_project_id = project
        return project

    def action_open_project(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.project',
            'res_id': self.project_id.id,
            'view_mode': 'form',
        }

    def action_open_task(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'res_id': self.task_id.id,
            'view_mode': 'form',
        }

    def action_open_project_tasks(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Tasks"),
            'res_model': 'project.task',
            'view_mode': 'kanban,list,form',
            'domain': [('project_id', '=', self.project_id.id)],
            'context': {'default_project_id': self.project_id.id},
        }

    def action_sync_progress(self):
        for initiative in self:
            if not (initiative.project_id or initiative.task_id):
                continue
            if not initiative.task_count:
                continue
            new = round(initiative.project_progress, 1)
            if abs(new - initiative.progress) < 0.05:
                continue
            reached_end = new >= 100.0 > initiative.progress
            initiative.progress = new
            if reached_end and initiative.state != 'done':
                initiative.message_post(body=_(
                    "Every task behind this initiative is done. Mark the initiative "
                    "done once its result has been confirmed."))
        return True

    def _sync_progress_from_tasks(self):
        """Called when a task changes, so the figure follows the work at once."""
        live = self.filtered(lambda i: i.use_project_progress
                             and i.state in ('approved', 'in_progress'))
        live.action_sync_progress()

    @api.model
    def _cron_sync_project_progress(self):
        initiatives = self.search([
            ('use_project_progress', '=', True),
            ('state', 'in', ('approved', 'in_progress')),
            '|', ('project_id', '!=', False), ('task_id', '!=', False),
        ])
        initiatives.action_sync_progress()
        return True

    def write(self, vals):
        """Offer the execution record at the moment work actually starts."""
        result = super().write(vals)
        if 'stage_id' in vals:
            stage = self.env['bsc.initiative.stage'].browse(vals['stage_id'])
            if stage.state == 'in_progress':
                for initiative in self:
                    if not initiative.project_id and not initiative.task_id:
                        initiative.message_post(body=_(
                            "This initiative is now in progress but has no project or "
                            "task behind it. Create one from the Execution tab if the "
                            "work needs tracking."))
        return result
