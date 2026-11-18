# -*- coding: utf-8 -*-
"""Field and transition rules that security/ir.access.csv cannot express, in one place.
Skipped for code running as superuser (``env.su``): the module's engines check the caller's rights first;
a context key is never trusted alone."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain

MANAGER = 'bsc_strategy.group_bsc_manager'
ADMIN = 'bsc_strategy.group_bsc_admin'

# Initiative stages a contributor may put their own proposal in.
CONTRIBUTOR_INITIATIVE_STATES = ('proposed',)


def _is(env, group):
    return env.su or env.user.has_group(group)


def _check_can_refresh(env):
    """Refreshing from a source reads and writes as superuser, so it is a manager's action."""
    if not _is(env, MANAGER):
        raise AccessError(_(
            "Only a Balanced Scorecard manager can refresh figures from the source."))


class BscScorecardSecurity(models.Model):
    _inherit = 'bsc.scorecard'
    _mail_post_access = 'read'

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any('is_demo' in vals for vals in vals_list):
            raise AccessError(_("Only the demo-data loader can mark a scorecard as demo."))
        return super().create(vals_list)

    def write(self, vals):
        # "Remove demo data" deletes everything flagged demo, so the flag must not be set by hand.
        if 'is_demo' in vals and not self.env.su:
            raise AccessError(_("Only the demo-data loader can mark a scorecard as demo."))
        return super().write(vals)


class BscPerspectiveSecurity(models.Model):
    _inherit = 'bsc.perspective'

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any('is_demo' in vals for vals in vals_list):
            raise AccessError(_("Only the demo-data loader can mark a perspective as demo."))
        return super().create(vals_list)

    def write(self, vals):
        if 'is_demo' in vals and not self.env.su:
            raise AccessError(_("Only the demo-data loader can mark a perspective as demo."))
        return super().write(vals)


class BscObjectiveSecurity(models.Model):
    _inherit = 'bsc.objective'
    _mail_post_access = 'read'

    _RATING_FIELDS = {'qualitative_status', 'qualitative_note'}

    bsc_can_manage = fields.Boolean(
        compute='_compute_bsc_can_manage',
        help="Technical: lets the form lock everything but the rating for "
             "contributors, matching the check done on save.")

    def _compute_bsc_can_manage(self):
        can = _is(self.env, MANAGER)
        for objective in self:
            objective.bsc_can_manage = can

    def write(self, vals):
        """A contributor may rate the qualitative objectives they own; everything else is a manager's."""
        forbidden = set(vals) - self._RATING_FIELDS
        if forbidden and not _is(self.env, MANAGER):
            raise AccessError(_(
                "Only a Balanced Scorecard manager can change %s on an objective.",
                ", ".join(sorted(self._fields[f].string for f in forbidden if f in self._fields))))
        return super().write(vals)


class BscReviewSecurity(models.Model):
    _inherit = 'bsc.review'
    _mail_post_access = 'read'


class BscPeriodSecurity(models.Model):
    _inherit = 'bsc.period'

    def write(self, vals):
        # A manager can write the period directly, so the rule holds on the field itself.
        if vals.get('state') == 'open' and not _is(self.env, ADMIN) \
                and any(period.state == 'closed' for period in self):
            raise AccessError(_("Only a Balanced Scorecard administrator can reopen a period."))
        return super().write(vals)

    def action_refresh_automated(self):
        _check_can_refresh(self.env)
        return super().action_refresh_automated()


class BscKpiSourceSecurity(models.Model):
    _inherit = 'bsc.kpi.source'

    def _bsc_unreadable_reason(self, extra_domain, company=None):
        """Why the user cannot see every record this source counts: 'model' (no read access),
'filter' (reaches records they cannot open), else False.
        Call with the user's own env; the unfiltered figure stays company-wide by design."""
        self.ensure_one()
        if self.env.su:
            return False
        model = self.model_name
        if not model or model not in self.env:
            return False
        Model = self.env[model]
        if not Model.has_access('read'):
            return 'model'
        if extra_domain:
            if self.include_archived:
                Model = Model.with_context(active_test=False)
            domain = Domain.AND([self._domain_or_raise(), extra_domain])
            if company and self.company_field:
                domain = Domain.AND([domain, ['|', (self.company_field, '=', False),
                                              (self.company_field, '=', company.id)]])
            if Model.sudo().search_count(domain) != Model.search_count(domain):
                return 'filter'
        return False


class BscKpiSecurity(models.Model):
    _inherit = 'bsc.kpi'
    _mail_post_access = 'read'

    def _check_source_readable(self):
        """Whoever points a KPI at a source, or filters it, must be allowed to read that data.
        The source is read with elevated rights, so a filter could probe records they cannot open."""
        if self.env.su:
            return
        for kpi in self.filtered('source_id'):
            source = kpi.source_id
            reason = source._bsc_unreadable_reason(
                kpi._extra_domain(), kpi.scorecard_id.company_id)
            if reason == 'model':
                raise AccessError(_(
                    "You cannot connect '%(kpi)s' to '%(source)s': you have no access to "
                    "the records it counts.", kpi=kpi.name, source=source.name))
            if reason == 'filter':
                raise AccessError(_(
                    "The filter on '%s' reaches records you are not allowed to see. "
                    "Ask a Balanced Scorecard administrator to set it.", kpi.name))

    @api.model_create_multi
    def create(self, vals_list):
        kpis = super().create(vals_list)
        if any(vals.get('source_id') for vals in vals_list):
            kpis._check_source_readable()
        return kpis

    def write(self, vals):
        result = super().write(vals)
        if 'source_id' in vals or 'source_extra_domain' in vals:
            self._check_source_readable()
        return result

    def action_refresh_now(self):
        _check_can_refresh(self.env)
        return super().action_refresh_now()

    def action_test_source(self):
        _check_can_refresh(self.env)
        return super().action_test_source()


class BscInitiativeSecurity(models.Model):
    _inherit = 'bsc.initiative'
    _mail_post_access = 'read'

    _APPROVAL_FIELDS = {'approval_date', 'approved_by_id'}
    _LINK_FIELDS = {'project_id', 'task_id'}
    _EXECUTION_FIELDS = _LINK_FIELDS | {'use_project_progress'}

    def _check_initiative_rights(self, vals, records=None):
        """Status, company and approval stamps are never set by hand, even by a manager.
        A contributor may not move a decided initiative, change its decided budget or set/relink its project or task.
        On create, only a set project or task is refused."""
        if not self.env.su:
            if {'state', 'company_id'} & set(vals):
                raise AccessError(_(
                    "The status and the company of an initiative follow its stage and its "
                    "scorecard; they cannot be set directly."))
            if self._APPROVAL_FIELDS & set(vals):
                raise AccessError(_("Approval is recorded automatically when a manager approves."))
        if _is(self.env, MANAGER):
            return
        if records is not None:
            execution = self._EXECUTION_FIELDS & set(vals)
        else:
            execution = {f for f in self._LINK_FIELDS if vals.get(f)}
        if execution:
            raise AccessError(_(
                "Only a Balanced Scorecard manager can change the project, the task or the "
                "progress tracking of an initiative."))
        if 'stage_id' in vals:
            stage = self.env['bsc.initiative.stage'].browse(vals['stage_id'])
            if stage.state not in CONTRIBUTOR_INITIATIVE_STATES:
                raise AccessError(_(
                    "Only a Balanced Scorecard manager can move an initiative to "
                    "'%s'. Contributors propose; managers decide.", stage.name or '-'))
            decided = (records or self.browse()).filtered(
                lambda i: i.state not in CONTRIBUTOR_INITIATIVE_STATES)
            if decided:
                raise AccessError(_(
                    "'%s' has been decided; only a Balanced Scorecard manager can move it back.",
                    decided[0].name))
        if records is not None and 'budget_planned' in vals:
            decided = records.filtered(lambda i: i.state not in CONTRIBUTOR_INITIATIVE_STATES)
            if decided:
                raise AccessError(_(
                    "The planned budget of '%s' was approved; only a manager can change it.",
                    decided[0].name))

    @api.model_create_multi
    def create(self, vals_list):
        """The client sends ``default_<field>`` context keys with every call and
        create() applies them as values, so they are checked as if typed."""
        defaults = {key[8:]: value for key, value in self.env.context.items()
                    if key.startswith('default_')
                    and key[8:] in self._APPROVAL_FIELDS | self._LINK_FIELDS | {'stage_id'}}
        for vals in vals_list:
            self._check_initiative_rights(dict(defaults, **vals))
        return super().create(vals_list)

    def write(self, vals):
        self._check_initiative_rights(vals, records=self)
        return super().write(vals)


class BscMeasurementSecurity(models.Model):
    _inherit = 'bsc.measurement'

    bsc_can_manage = fields.Boolean(
        compute='_compute_bsc_can_manage',
        help="Technical: lets the views lock the target and a validated figure for "
             "contributors, matching the checks done on save.")

    def _compute_bsc_can_manage(self):
        can = self.env.user.has_group(MANAGER)
        for record in self:
            record.bsc_can_manage = can

    def action_refresh_automated(self):
        _check_can_refresh(self.env)
        return super().action_refresh_automated()
