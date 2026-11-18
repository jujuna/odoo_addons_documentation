import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

WEEKLY_DIGEST_PARAM = 'employee_registry_rs.last_weekly_digest'
WEEKLY_DIGEST_INTERVAL_DAYS = 7

RS_STATUS_SELECTION = [('1', 'Active'), ('0', 'Terminated'), ('-1', 'Suspended')]

RS_WORK_TYPE_SELECTION = [('1', 'Full-time'), ('2', 'Part-time')]

RS_SYNC_MODE_SELECTION = [('auto', 'Automatic (follow contract)'), ('manual', 'Manual only (buttons)'), ('off', 'Disabled')]


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    rs_registry_id = fields.Char(string='RS Registry ID', copy=False, readonly=True,
        help="ID returned by the Revenue Service after the first successful sync.", groups='hr.group_hr_user')
    rs_status = fields.Selection(RS_STATUS_SELECTION, string='RS Status', copy=False, readonly=True, tracking=True, index=True,
        help="Last status pushed to the Revenue Service.", groups='hr.group_hr_user')
    rs_log_ids = fields.One2many('employee.registry.rs.log', 'employee_id', string='RS Sync Log', readonly=True, groups='hr.group_hr_user')
    rs_last_sync_date = fields.Datetime(string='Last RS Sync', copy=False, readonly=True, groups='hr.group_hr_user')
    rs_sync_error = fields.Text(string='Last RS Sync Error', copy=False, readonly=True, groups='hr.group_hr_user')
    rs_sync_mode = fields.Selection(RS_SYNC_MODE_SELECTION, string='RS Status Sync Mode', default='auto', required=True, tracking=True,
        help=("Automatic: daily cron syncs status based on contract dates + active flag. Manual only: cron skips, status changes only via the "
        "buttons on this page. Disabled: this employee is excluded from RS entirely (buttons refuse too)."), groups='hr.group_hr_user')
    rs_work_type = fields.Selection(RS_WORK_TYPE_SELECTION, string='RS Work Type', default='1', help="Work type reported to the Revenue Service.",
        groups='hr.group_hr_user')
    rs_target_status = fields.Selection(RS_STATUS_SELECTION, string='RS Target Status', compute='_compute_rs_target_status',
        help="Status the employee should have at the Revenue Service, derived from contract state.", groups='hr.group_hr_user')
    rs_needs_sync = fields.Boolean(compute='_compute_rs_needs_sync', string='RS Needs Sync', groups='hr.group_hr_user')
    rs_is_foreigner = fields.Boolean(compute='_compute_rs_is_foreigner', string='RS Foreign Citizen', groups='hr.group_hr_user')

    @api.depends('active', 'identification_id', 'departure_date', 'current_version_id', 'current_version_id.is_in_contract',
        'current_version_id.contract_date_end')
    def _compute_rs_target_status(self):
        today = fields.Date.today()
        for emp in self:
            emp_su = emp.sudo()
            if not emp_su.identification_id:
                emp.rs_target_status = False
                continue
            version = emp_su.current_version_id
            contract_ended = bool(version and version.contract_date_end and version.contract_date_end < today)
            departed = bool(emp_su.departure_date and emp_su.departure_date <= today)
            if not emp_su.active or departed or contract_ended:
                emp.rs_target_status = '0'
            elif version and version.is_in_contract:
                emp.rs_target_status = '1'
            else:
                emp.rs_target_status = False

    @api.depends('rs_target_status', 'rs_status', 'rs_registry_id', 'rs_sync_mode')
    def _compute_rs_needs_sync(self):
        """True when the cron must push the target status.
        A termination is pushed only for an employee RS already knows; Sync Now still pushes any."""
        for emp in self:
            emp.rs_needs_sync = (
                emp.rs_sync_mode == 'auto'
                and bool(emp.rs_target_status)
                and emp.rs_target_status != emp.rs_status
                and (emp.rs_target_status != '0' or bool(emp.rs_status or emp.rs_registry_id))
            )

    def _check_rs_sync_allowed(self):
        """Raise if sync is disabled or the employee is of another legal entity than the active company.
        The RS login is the active entity's, so pushing another entity's employee would use the wrong RS account."""
        self.ensure_one()
        if self.rs_sync_mode == 'off':
            raise UserError(_("Employee %s has RS Sync Mode set to 'Disabled'. Change it to 'Manual' or 'Automatic' to perform this action.",
                self.display_name))
        if self.company_id.root_id != self.env.company.root_id:
            raise UserError(self.env._("Employee %(employee)s belongs to %(company)s: switch to that company before syncing with RS.",
                employee=self.display_name, company=self.company_id.display_name))

    @api.depends('country_id', 'country_id.code')
    def _compute_rs_is_foreigner(self):
        for emp in self:
            country = emp.sudo().country_id
            emp.rs_is_foreigner = bool(country) and country.code != 'GE'

    def _rs_phone(self):
        self.ensure_one()
        emp_su = self.sudo()
        raw = (self.mobile_phone or emp_su.private_phone or self.work_phone or '').strip()
        if not raw:
            return ''
        return ''.join(ch for ch in raw if ch.isdigit())

    def _build_rs_payload(self, status_override=None):
        self.ensure_one()
        if not self.identification_id:
            raise UserError(_("Employee %s has no Identification ID (TIN) set — cannot sync to RS.", self.display_name))
        status = status_override if status_override else self.rs_target_status
        if not status:
            raise UserError(_("Employee %s has no resolvable RS status. Check that the current version has contract dates set.", self.display_name))

        phone = self._rs_phone()
        if not phone:
            raise UserError(_("Employee %s has no phone number set — RS requires PHONE.", self.display_name))

        payload = {
            'ID': int(self.rs_registry_id) if self.rs_registry_id else 0,
            'IS_FOREIGNER': 1 if self.rs_is_foreigner else 0,
            'STATUS': int(status),
            'TIN': self.identification_id.strip(),
            'PHONE': phone,
            'WORK_TYPE': int(self.rs_work_type or '1'),
        }
        if self.rs_is_foreigner:
            country = self.sudo().country_id
            if not country.rs_country_code:
                self.env['employee.registry.rs.service'].ensure_country_codes()
                country.invalidate_recordset(['rs_country_code'])
            if not country.rs_country_code:
                raise UserError(_("Foreign employee %s has country '%s' but no RS country code. RS did not return a matching code — verify the "
                    "country name matches the Georgian name in RS's list, or contact api-support@rs.ge.", self.display_name, country.name))
            payload['CITIZEN_COUNTRY_ID'] = country.rs_country_code
            payload['FULLNAME'] = self.name or ''
            gender_map = {'male': '1', 'female': '2'}
            gender = gender_map.get(self.sudo().sex)
            if not gender:
                raise UserError(_("Foreign employee %s must have gender (male or female) set.", self.display_name))
            payload['GENDER'] = gender
            birthday = self.sudo().birthday
            if not birthday:
                raise UserError(_("Foreign employee %s must have a birthday set.", self.display_name))
            payload['BIRTH_DATE'] = birthday.strftime('%d-%m-%Y')
        return payload

    def _resolve_rs_id_by_tin(self):
        """Return the current RS ID (int) for this employee's TIN, or None; recovers a stale `rs_registry_id`.
        ListEmployees returns only active (STATUS=1) by default, so each status is queried."""
        self.ensure_one()
        if not self.identification_id:
            return None
        service = self.env['employee.registry.rs.service']
        tin = self.identification_id.strip()
        for status in ('1', '-1', '0'):
            try:
                data = service.list_employees({'TIN': tin, 'STATUS': status, 'MAXIMUM_ROWS': 5})
            except UserError:
                continue
            inner = data.get('Data') or {}
            fields_list = inner.get('Fields') or []
            rows = inner.get('Rows') or []
            if rows and 'ID' in fields_list:
                id_idx = fields_list.index('ID')
                return int(rows[0][id_idx])
        return None

    def _sync_single_to_rs(self, status_override=None):
        """Push this employee to RS (status_override or the computed target) and store the result.
        RS may change the RS id on every save; a missing or stale id is recovered through a TIN lookup."""
        self.ensure_one()
        self._check_rs_sync_allowed()
        payload = self._build_rs_payload(status_override=status_override)
        service = self.env['employee.registry.rs.service']
        try:
            data = service.save_employee(payload, employee_id=self.id)
        except UserError as e:
            msg = str(e)
            # Create (ID=0) but the TIN already exists in RS: link it via TIN and retry as update.
            if not payload.get('ID') and '[-801]' in msg:
                resolved = self._resolve_rs_id_by_tin()
                if not resolved:
                    raise
                _logger.info("RS Employee Registry: TIN %s already exists in RS as id %s. Linking and retrying as update.", self.identification_id,
                    resolved)
                self.write({'rs_registry_id': str(resolved)})
                payload['ID'] = resolved
                data = service.save_employee(payload, employee_id=self.id)
            # Update (ID>0) with a stale id ([-2] / [-30]): the TIN lookup gives the new id, none means create.
            # The same id means RS rejected another field (e.g. phone used 3 times): re-raise.
            elif (payload.get('ID') and self.rs_registry_id and ('[-2]' in msg or '[-30]' in msg)):
                resolved = self._resolve_rs_id_by_tin()
                if resolved == int(self.rs_registry_id):
                    raise
                if resolved:
                    _logger.info("RS Employee Registry: resolved new ID %s for TIN %s (was %s). Retrying update.", resolved, self.identification_id,
                        self.rs_registry_id)
                    self.write({'rs_registry_id': str(resolved)})
                    payload['ID'] = resolved
                    data = service.save_employee(payload, employee_id=self.id)
                else:
                    _logger.warning("RS Employee Registry: stored ID %s is stale and no record exists for TIN %s. Clearing rs_registry_id and "
                        "creating fresh.", self.rs_registry_id, self.identification_id)
                    self.write({'rs_registry_id': False})
                    payload['ID'] = 0
                    data = service.save_employee(payload, employee_id=self.id)
            else:
                raise
        vals = {'rs_last_sync_date': fields.Datetime.now(), 'rs_status': str(payload['STATUS']), 'rs_sync_error': False}
        returned_id = data.get('ID')
        if returned_id:
            # RS is authoritative for the ID.
            vals['rs_registry_id'] = str(returned_id)
        self.write(vals)
        return data

    def action_rs_sync_now(self):
        for emp in self:
            emp._sync_single_to_rs()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("RS Employee Registry"),
                'message': _("Synced %s employee(s) to RS.", len(self)),
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_rs_activate(self):
        for emp in self:
            emp._sync_single_to_rs(status_override='1')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("RS Employee Registry"),
                'message': _("Marked %s employee(s) as active in RS.", len(self)),
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_rs_suspend(self):
        for emp in self:
            emp._sync_single_to_rs(status_override='-1')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("RS Employee Registry"),
                'message': _("Marked %s employee(s) as suspended in RS.", len(self)),
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_rs_terminate(self):
        for emp in self:
            emp._sync_single_to_rs(status_override='0')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("RS Employee Registry"),
                'message': _("Marked %s employee(s) as terminated in RS.", len(self)),
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_rs_fetch(self):
        self.ensure_one()
        self._check_rs_sync_allowed()
        service = self.env['employee.registry.rs.service']
        if not self.rs_registry_id:
            # No local ID: try the TIN (RS changes the ID when the TIN is edited).
            resolved = self._resolve_rs_id_by_tin()
            if not resolved:
                raise UserError(_("This employee has no RS Registry ID and no record exists for TIN '%s'. Sync the employee first, or use the RS "
                    "Employee Browser to find and link an existing record.", self.identification_id or ''))
            self.write({'rs_registry_id': str(resolved)})
        try:
            data = service.get_employee(self.rs_registry_id, employee_id=self.id)
        except UserError as e:
            if '[-30]' in str(e):
                resolved = self._resolve_rs_id_by_tin()
                if resolved and str(resolved) != self.rs_registry_id:
                    _logger.info("RS Employee Registry: stored ID %s invalid, re-resolved to %s via TIN %s.", self.rs_registry_id, resolved,
                        self.identification_id)
                    self.write({'rs_registry_id': str(resolved)})
                    data = service.get_employee(resolved, employee_id=self.id)
                else:
                    raise UserError(_("RS record with id %(id)s no longer exists and no record found for TIN '%(tin)s'. The record may have been "
                        "deleted on RS, or the TIN changed. Use the RS Employee Browser (Employees > Configuration > RS Employee Browser) to find "
                        "and link the correct record.", id=self.rs_registry_id, tin=self.identification_id or ''))
            else:
                raise
        emp_data = data.get('EMPLOYEE') or {}
        changes = self._apply_rs_fetch_data(emp_data)
        if changes:
            message = _("Pulled from RS. Updated: %(changes)s.\nRemote status: %(status)s (%(status_txt)s).", changes='; '.join(changes),
                status=emp_data.get('STATUS') or '-', status_txt=emp_data.get('STATUS_TXT') or '-')
            msg_type = 'success'
        else:
            message = _("Odoo already matches RS. Remote status: %(status)s (%(status_txt)s). Last change: %(last)s.",
                status=emp_data.get('STATUS') or '-', status_txt=emp_data.get('STATUS_TXT') or '-', last=emp_data.get('LAST_CHANGE_DATE') or '-')
            msg_type = 'info'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': msg_type,
                'title': _("RS Employee Registry"),
                'message': message,
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def _apply_rs_fetch_data(self, emp_data):
        """Write RS data back onto the employee; returns readable change descriptions for the notification."""
        self.ensure_one()
        changes = []
        vals = {'rs_last_sync_date': fields.Datetime.now(), 'rs_sync_error': False}

        remote_status = emp_data.get('STATUS')
        if remote_status is not None:
            remote_status_str = str(remote_status)
            if self.rs_status != remote_status_str:
                changes.append(_("RS status: %(old)s → %(new)s", old=self.rs_status or '∅', new=remote_status_str))
                vals['rs_status'] = remote_status_str

        remote_phone = (emp_data.get('PHONE') or '').strip()
        if remote_phone:
            local_digits = ''.join(c for c in (self.mobile_phone or '') if c.isdigit())
            remote_digits = ''.join(c for c in remote_phone if c.isdigit())
            if local_digits != remote_digits:
                changes.append(_("Mobile phone: %(old)s → %(new)s", old=self.mobile_phone or '∅', new=remote_phone))
                vals['mobile_phone'] = remote_phone

        remote_tin = (emp_data.get('TIN') or '').strip()
        if remote_tin and remote_tin != (self.identification_id or '').strip():
            changes.append(_("Identification ID (TIN): %(old)s → %(new)s", old=self.identification_id or '∅', new=remote_tin))
            vals['identification_id'] = remote_tin

        remote_is_foreigner_txt = emp_data.get('IS_FOREIGNER')
        is_foreigner_remote = str(remote_is_foreigner_txt) in ('1', 'დიახ', 'True', 'true')

        if is_foreigner_remote:
            remote_fullname = (emp_data.get('FULLNAME') or '').strip()
            if remote_fullname and remote_fullname != (self.name or '').strip():
                changes.append(_("Name: %(old)s → %(new)s", old=self.name or '∅', new=remote_fullname))
                vals['name'] = remote_fullname

            remote_birthday_str = (emp_data.get('BIRTH_DATE') or '').strip()
            if remote_birthday_str:
                try:
                    from datetime import datetime as _dt
                    remote_birthday = _dt.strptime(remote_birthday_str, '%d-%m-%Y').date()
                    if self.sudo().birthday != remote_birthday:
                        changes.append(_("Birthday: %(old)s → %(new)s", old=self.sudo().birthday or '∅', new=remote_birthday))
                        vals['birthday'] = remote_birthday
                except ValueError:
                    pass

            remote_gender = str(emp_data.get('GENDER') or '')
            gender_map = {'1': 'male', '2': 'female'}
            remote_sex = gender_map.get(remote_gender)
            if remote_sex and self.sudo().sex != remote_sex:
                changes.append(_("Gender: %(old)s → %(new)s", old=self.sudo().sex or '∅', new=remote_sex))
                vals['sex'] = remote_sex

            remote_country_code = (emp_data.get('CITIZEN_COUNTRY_ID') or '').strip()
            if remote_country_code:
                country = self.env['res.country'].sudo().search([('rs_country_code', '=', remote_country_code)], limit=1)
                if country and self.sudo().country_id != country:
                    changes.append(_("Nationality: %(old)s → %(new)s", old=self.sudo().country_id.name or '∅', new=country.name))
                    vals['country_id'] = country.id

        self.write(vals)
        return changes

    @api.model
    def _cron_sync_employees_to_rs(self):
        """Push the target status of automatic employees, one pass per legal entity.
        Each pass runs as its RS Responsible User; an entity without one is skipped and logged;
        a failing entity never stops the others."""
        param = self.env['ir.config_parameter'].sudo()
        if not param.get_bool('employee_registry_rs.sync_enabled'):
            _logger.info("RS Employee Registry: sync disabled, skipping cron run.")
            return
        Users = self.env['res.users']
        if not hasattr(Users, '_rs_responsible_user'):
            _logger.error("RS Employee Registry: rs_base_methods is not installed, no responsible user can be resolved — skipping.")
            return
        for company in self.env['res.company'].sudo().search([('parent_id', '=', False)]):
            user = Users._rs_responsible_user(company)
            if not user:
                _logger.info("RS Employee Registry: %s has no RS Responsible User with a login — skipped.", company.display_name)
                continue
            try:
                # sudo after with_user: full access, while env.user is the responsible user whose login the calls read.
                self.with_user(user).sudo().with_company(company)._cron_sync_company_employees()
            except Exception:
                _logger.exception("RS Employee Registry: sync failed for %s as %s — continuing with the others.", company.display_name, user.login)

    def _cron_sync_company_employees(self):
        """The sync pass of the active company and its branches, as the active user.
        Each employee runs in its own savepoint and commits at once,
        so a failure or timeout never undoes what RS accepted."""
        employees = self.with_context(active_test=False).search([
            ('identification_id', '!=', False),
            ('rs_sync_mode', '=', 'auto'),
            ('company_id', 'child_of', self.env.company.root_id.id),
        ])
        to_sync = employees.filtered('rs_needs_sync')
        self.env['ir.cron']._commit_progress(remaining=len(to_sync))
        synced = 0
        failed_entries = []
        for emp in to_sync:
            try:
                with self.env.cr.savepoint():
                    emp._sync_single_to_rs()
                synced += 1
            except Exception as e:
                failed_entries.append((emp.id, emp.display_name, str(e)))
                emp.write({'rs_sync_error': str(e)})
                _logger.exception("RS Employee Registry: failed to sync employee id=%s name=%s", emp.id, emp.display_name)
            self.env['ir.cron']._commit_progress(1)
        _logger.info("RS Employee Registry: daily sync complete — synced=%s failed=%s total_candidates=%s", synced, len(failed_entries),
            len(employees))
        if failed_entries:
            self._cron_send_failure_digest(synced, failed_entries)
        self._cron_maybe_send_weekly_digest(synced, len(failed_entries), len(employees))

    def _cron_maybe_send_weekly_digest(self, synced, failed_count, total_candidates):
        param = self.env['ir.config_parameter'].sudo()
        key = f'{WEEKLY_DIGEST_PARAM}.{self.env.company.id}'
        last = param.get_str(key)
        now = fields.Datetime.now()
        if last:
            try:
                last_dt = fields.Datetime.from_string(last)
            except (ValueError, TypeError):
                last_dt = None
            if last_dt and last_dt > now - timedelta(days=WEEKLY_DIGEST_INTERVAL_DAYS):
                return
        recipient = self.env.user.email
        if not recipient:
            return
        body = (
            f"<p>Weekly RS Employee Registry health report.</p>"
            f"<ul>"
            f"<li><b>This run — synced:</b> {synced}</li>"
            f"<li><b>This run — failed:</b> {failed_count}</li>"
            f"<li><b>Candidates considered:</b> {total_candidates}</li>"
            f"</ul>"
            f"<p>Immediate failure emails still go out on every failing run. This is the "
            f"scheduled weekly confirmation that the integration is running.</p>"
        )
        try:
            mail = self.env['mail.mail'].sudo().create({
                'subject': "RS Employee Registry: Weekly Health Report",
                'body_html': body,
                'email_to': recipient,
                'auto_delete': True,
            })
            mail.send()
            # A sent mail is auto-deleted; a failed one stays in 'exception' and the next run tries again
            if mail.exists().state != 'exception':
                param.set_str(key, fields.Datetime.to_string(now))
        except Exception:
            _logger.exception("Failed to send RS Employee Registry weekly digest email")

    def _cron_send_failure_digest(self, synced, failed_entries):
        recipient = self.env.user.email
        if not recipient:
            _logger.info("RS Employee Registry: cron user has no email; skipping failure digest.")
            return
        rows_html = "".join(
            f"<tr><td>{emp_id}</td><td>{html_escape(name)}</td>"
            f"<td><code>{html_escape(err)}</code></td></tr>"
            for emp_id, name, err in failed_entries[:50]
        )
        truncated = "" if len(failed_entries) <= 50 else (
            f"<p><i>+{len(failed_entries) - 50} more — see Employees &gt; Configuration "
            f"&gt; RS Sync Log.</i></p>"
        )
        body = (
            f"<p>Daily RS Employee Registry sync finished.</p>"
            f"<ul>"
            f"<li><b>Synced:</b> {synced}</li>"
            f"<li><b>Failed:</b> {len(failed_entries)}</li>"
            f"</ul>"
            f"<table border='1' cellpadding='4' cellspacing='0'>"
            f"<tr><th>Employee ID</th><th>Name</th><th>Error</th></tr>"
            f"{rows_html}"
            f"</table>"
            f"{truncated}"
        )
        try:
            self.env['mail.mail'].sudo().create({
                'subject': f"RS Employee Registry: {len(failed_entries)} sync failures",
                'body_html': body,
                'email_to': recipient,
                'auto_delete': True,
            }).send()
        except Exception:
            _logger.exception("Failed to send RS Employee Registry failure digest email")
