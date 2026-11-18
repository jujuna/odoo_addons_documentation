import json
import re

from markupsafe import Markup, escape

from odoo import _, api, models
from odoo.exceptions import UserError

FORMAT = 'gec_access_manager'
VERSION = 1
COMPANY_XMLID = re.compile(r'^\d+_')

# the plain fields of a profile and of its lines, carried as they are
PROFILE_FIELDS = (
    'strictness', 'apply_to_admin', 'for_new_users', 'global_readonly', 'hide_chatter_all',
    'block_export', 'block_import', 'block_archive', 'block_duplicate', 'hide_activities',
    'hide_settings_menu', 'lock_statusbar', 'block_rpc', 'block_developer_mode', 'block_login',
    'hide_print_all', 'hide_action_menu_all', 'hide_send_message_all', 'hide_followers_all',
    'hide_attachments_all', 'hide_costs', 'hide_sale_prices', 'note', 'block_custom_filter',
    'block_custom_group', 'block_favorites', 'block_properties', 'block_apps',
    'login_tz', 'allowed_ips', 'single_session', 'active', 'sequence',
)
MODEL_LINE_FIELDS = (
    'perm_read', 'perm_write', 'perm_create', 'perm_unlink', 'domain', 'domain_read',
    'domain_write', 'domain_create', 'domain_unlink', 'hide_chatter', 'hide_export', 'hide_import',
    'hide_archive', 'hide_duplicate', 'hide_print', 'hide_action_menu', 'hide_send_message',
    'hide_followers', 'hide_attachments',
)
MENU_LINE_FIELDS = MODEL_LINE_FIELDS[:4] + MODEL_LINE_FIELDS[9:] + ('records', 'edit_draft_only', 'include_shared')
FIELD_LINE_FIELDS = ('mode', 'no_open', 'no_create', 'no_export', 'field_domain', 'condition')
BUTTON_LINE_FIELDS = ('view_type', 'button_type', 'button_id', 'button_label', 'mode', 'condition')
ELEMENT_LINE_FIELDS = ('element_type', 'element_name', 'element_label', 'condition')
LOGIN_SLOT_FIELDS = ('dayofweek', 'hour_from', 'hour_to')


class GecAccessProfile(models.Model):
    _inherit = 'gec.access.profile'

    @api.model
    def _gec_ref(self, record):
        if not record:
            return None
        record = record.sudo()
        # the name travels with the external id: some hold a company id (account.1_sale) that differs per database
        ref = {'name': record.display_name}
        xmlid = record.get_external_id().get(record.id)
        if xmlid and not xmlid.startswith('__'):
            ref['xmlid'] = xmlid
        if 'company_id' in record._fields and record.company_id:
            ref['company'] = record.company_id.name
        if record._name == 'ir.ui.menu':
            ref['path'] = record.complete_name
        return ref

    @api.model
    def _gec_find(self, ref, model_name):
        """ The record ``ref`` designates on this database, or an empty recordset. """
        Model = self.env[model_name].sudo()
        if not ref:
            return Model
        if ref.get('xmlid'):
            record = self.env.ref(ref['xmlid'], raise_if_not_found=False)
            company = COMPANY_XMLID.match(ref['xmlid'].partition('.')[2]) and ref.get('company')
            if record and record._name == model_name and (not company or record.sudo().company_id.name == company):
                return record.sudo()
        if ref.get('path') and model_name == 'ir.ui.menu':
            menu = Model
            for part in ref['path'].split('/'):
                menu = Model.search([('name', '=', part.strip()), ('parent_id', '=', menu.id or False)], limit=1)
                if not menu:
                    return Model
            return menu
        if ref.get('name') and model_name != 'ir.ui.menu':
            # the displayed name first ("WH/Stock" for a location), then the name
            found = Model.browse([
                record_id for record_id, _name in Model.name_search(ref['name'], operator='=', limit=2)])
            if len(found) != 1 and 'name' in Model._fields:
                found = Model.search([('name', '=', ref['name'])], limit=2)
            return found if len(found) == 1 else Model
        return Model

    def _gec_export_profile(self, with_users=False):
        self.ensure_one()
        profile = self.sudo()
        data = {'name': profile.name}
        data.update({name: profile[name] or False for name in PROFILE_FIELDS})
        data['home_action'] = self._gec_ref(profile.home_action_id)
        data['company'] = self._gec_ref(profile.company_id)
        data['groups'] = [self._gec_ref(group) for group in profile.group_ids]
        data['granted_groups'] = [self._gec_ref(group) for group in profile.granted_group_ids]
        data['hidden_menus'] = [self._gec_ref(menu) for menu in profile.hidden_menu_ids]
        data['hidden_reports'] = [self._gec_ref(report) for report in profile.hidden_report_ids]
        data['hidden_server_actions'] = [self._gec_ref(action) for action in profile.hidden_action_ids]
        data['hidden_window_actions'] = [self._gec_ref(action) for action in profile.hidden_window_action_ids]
        data['models'] = [
            dict({name: line[name] or False for name in MODEL_LINE_FIELDS}, model=line.model_id.model)
            for line in profile.model_ids
        ]
        data['menu_rules'] = [
            dict({name: line[name] or False for name in MENU_LINE_FIELDS}, menu=self._gec_ref(line.menu_id))
            for line in profile.menu_rule_ids
        ]
        data['fields'] = [
            dict({name: line[name] or False for name in FIELD_LINE_FIELDS},
                 model=line.model_id.model, field=line.field_id.name)
            for line in profile.field_ids
        ]
        buttons = []
        for line in profile.button_ids:
            button = dict({name: line[name] or False for name in BUTTON_LINE_FIELDS}, model=line.model_id.model)
            if line.button_type == 'action' and (line.button_name or '').isdigit():
                # an action button names its action by id: carry the action itself
                action = self.env['ir.actions.actions'].sudo().browse(int(line.button_name)).exists()
                if action:
                    action = self.env[action.type].sudo().browse(action.id)
                button['action'] = dict(self._gec_ref(action) or {}, type=action.type) if action else None
            else:
                button['button_name'] = line.button_name
            buttons.append(button)
        data['buttons'] = buttons
        data['elements'] = [
            dict({name: line[name] or False for name in ELEMENT_LINE_FIELDS}, model=line.model_id.model)
            for line in profile.element_ids
        ]
        allowed = []
        for line in profile.allowed_ids:
            item = {'kind': line.kind, 'per_user': line.per_user}
            if not line.per_user and line.res_model in self.env:
                item['record'] = self._gec_ref(self.env[line.res_model].sudo().browse(line.res_id).exists())
            allowed.append(item)
        data['allowed'] = allowed
        data['login_slots'] = [{name: slot[name] for name in LOGIN_SLOT_FIELDS} for slot in profile.login_slot_ids]
        if with_users:
            data['users'] = profile.user_ids.mapped('login')
        return data

    def _gec_export(self, with_users=False):
        return json.dumps({
            'format': FORMAT,
            'version': VERSION,
            'profiles': [profile._gec_export_profile(with_users) for profile in self],
        }, indent=2, default=str)

    def action_export_profiles(self):
        """ Download the profiles as a file, for readers only: the file carries the users' logins. """
        self.check_access('read')
        # the logins travel too; assigning them is a choice made at import
        content = self._gec_export(with_users=True)
        name = 'access_profiles.json' if len(self) != 1 else '%s.json' % self.name
        attachment = self.env['ir.attachment'].create({
            'name': name,
            'raw': content.encode(),
            'mimetype': 'application/json',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'download',
        }

    @api.model
    def _gec_import(self, content, replace=False, with_users=False):
        try:
            payload = json.loads(content)
        except (ValueError, TypeError) as error:
            raise UserError(_("This file is not an export of access profiles.")) from error
        if not isinstance(payload, dict) or payload.get('format') != FORMAT:
            raise UserError(_("This file is not an export of access profiles."))
        if payload.get('version', 0) > VERSION:
            raise UserError(_("This file comes from a newer version of the module. Upgrade the module first."))
        profiles = self.browse()
        for data in payload.get('profiles', []):
            profiles |= self._gec_import_profile(data, replace, with_users)
        return profiles

    @api.model
    def _gec_import_profile(self, data, replace, with_users):
        name = data.get('name') or _("Imported Profile")
        existing = self.with_context(active_test=False).search([('name', '=', name)], limit=1)
        if existing and replace:
            profile = existing
        else:
            profile = self.create({'name': _("%s (imported)", name) if existing else name})
        notes = profile._gec_apply_export(data, with_users)
        body = Markup('<p>%s</p>') % _("Imported from a file.")
        if notes:
            body += profile._gec_notes_html(notes)
        profile.message_post(body=body, subtype_xmlid='mail.mt_note')
        return profile

    @api.model
    def _gec_notes_html(self, notes):
        return Markup('<p>%s</p><ul>%s</ul>') % (
            _("Skipped, because this database does not have them:"),
            Markup('').join(Markup('<li>%s</li>') % escape(note) for note in notes))

    def _gec_apply_export(self, data, with_users):
        """ Set this profile from ``data``, replacing its lines; return notes of what this database lacks. """
        self.ensure_one()
        profile = self
        notes = []
        values = {key: data[key] for key in PROFILE_FIELDS if key in data and key in self._fields}
        # resolve the allowlist before clearing: dropping its last unresolved entry would lift the restriction
        self._gec_apply_allowed(data, values)
        self._gec_apply_clear(data)

        self._gec_apply_home(data, values, notes)
        self._gec_apply_company(data, values, notes)

        records = self._gec_records_finder(notes)
        self._gec_apply_groups(data, values, records)
        self._gec_apply_models(data, values, notes)
        self._gec_apply_menu_rules(data, values, records)
        self._gec_apply_fields(data, values, notes)
        self._gec_apply_buttons(data, values, notes)
        self._gec_apply_elements(data, values, notes)
        self._gec_apply_login_slots(data, values)
        self._gec_apply_users(data, values, with_users, notes)

        profile.write(values)
        return notes

    def _gec_apply_clear(self, data):
        profile = self
        clear = {
            'model_ids': [(5,)], 'menu_rule_ids': [(5,)], 'field_ids': [(5,)], 'button_ids': [(5,)], 'element_ids': [(5,)],
            'allowed_ids': [(5,)], 'group_ids': [(5,)], 'granted_group_ids': [(5,)], 'hidden_menu_ids': [(5,)], 'hidden_report_ids': [(5,)],
            'hidden_action_ids': [(5,)], 'hidden_window_action_ids': [(5,)],
        }
        if 'login_slots' in data:
            # exports made before the sign-in rules travelled leave them as they are
            clear['login_slot_ids'] = [(5,)]
        profile.write(clear)

    def _gec_apply_home(self, data, values, notes):
        home = self._gec_find(data.get('home_action'), 'ir.actions.act_window')
        values['home_action_id'] = home.id or False
        if data.get('home_action') and not home:
            notes.append(_("Home page: not found"))

    def _gec_apply_company(self, data, values, notes):
        """ A company this database lacks archives the profile: without it, it would apply in every company. """
        if 'company' not in data:
            return
        company = self._gec_find(data['company'], 'res.company')
        values['company_id'] = company.id or False
        if data['company'] and not company:
            values['active'] = False
            notes.append(_("Company %s was not found, so the profile was archived", self._gec_ref_label(data['company'])))

    def _gec_records_finder(self, notes):
        """ Return ``records(refs, model_name, label)``: finds the refs here, adds the ones not found to ``notes``. """
        def records(refs, model_name, label):
            found = self.env[model_name].sudo()
            for ref in refs or ():
                record = self._gec_find(ref, model_name)
                if record:
                    found |= record
                else:
                    notes.append(_("%(what)s not found: %(ref)s", what=label,
                                   ref=ref.get('xmlid') or ref.get('path') or ref.get('name')))
            return found
        return records

    def _gec_apply_groups(self, data, values, records):
        """ Put the exported groups, hidden menus, reports and actions in ``values``. """
        values['group_ids'] = [(6, 0, records(data.get('groups'), 'res.groups', _("Group")).ids)]
        values['granted_group_ids'] = [(6, 0, records(data.get('granted_groups'), 'res.groups', _("Group")).ids)]
        values['hidden_menu_ids'] = [(6, 0, records(data.get('hidden_menus'), 'ir.ui.menu', _("Menu")).ids)]
        values['hidden_report_ids'] = [(6, 0, records(
            data.get('hidden_reports'), 'ir.actions.report', _("Report")).ids)]
        values['hidden_action_ids'] = [(6, 0, records(
            data.get('hidden_server_actions'), 'ir.actions.server', _("Action")).ids)]
        values['hidden_window_action_ids'] = [(6, 0, records(
            data.get('hidden_window_actions'), 'ir.actions.act_window', _("Action")).ids)]

    def _gec_apply_models(self, data, values, notes):
        IrModel = self.env['ir.model'].sudo()
        model_lines = []
        for line in data.get('models', []):
            ir_model = IrModel._get(line.get('model')) if line.get('model') in self.env else IrModel
            if not ir_model:
                notes.append(_("Data not installed: %s", line.get('model')))
                continue
            model_lines.append((0, 0, dict(
                {key: line[key] for key in MODEL_LINE_FIELDS if key in line}, model_id=ir_model.id)))
        values['model_ids'] = model_lines

    def _gec_apply_menu_rules(self, data, values, records):
        menu_lines = []
        for line in data.get('menu_rules', []):
            menu = records([line['menu']] if line.get('menu') else [], 'ir.ui.menu', _("Menu"))
            if menu:
                menu_lines.append((0, 0, dict(
                    {key: line[key] for key in MENU_LINE_FIELDS if key in line}, menu_id=menu.id)))
        values['menu_rule_ids'] = menu_lines

    def _gec_apply_fields(self, data, values, notes):
        field_lines = []
        for line in data.get('fields', []):
            field = (self.env['ir.model.fields'].sudo()._get(line.get('model'), line.get('field'))
                     if line.get('model') in self.env else None)
            if not field:
                notes.append(_("Field not installed: %(model)s / %(field)s",
                               model=line.get('model'), field=line.get('field')))
                continue
            field_lines.append((0, 0, dict(
                {key: line[key] for key in FIELD_LINE_FIELDS if key in line},
                model_id=field.model_id.id, field_id=field.id)))
        values['field_ids'] = field_lines

    def _gec_apply_buttons(self, data, values, notes):
        IrModel = self.env['ir.model'].sudo()
        button_lines = []
        for line in data.get('buttons', []):
            if line.get('model') not in self.env:
                notes.append(_("Data not installed: %s", line.get('model')))
                continue
            button_name = line.get('button_name')
            if line.get('button_type') == 'action':
                action_ref = line.get('action') or {}
                action = (self._gec_find(action_ref, action_ref.get('type') or 'ir.actions.act_window')
                          if action_ref.get('type', 'ir.actions.act_window') in self.env else None)
                if not action:
                    notes.append(_("Button action not found: %s", action_ref.get('xmlid') or action_ref.get('name')))
                    continue
                button_name = str(action.id)
            button_lines.append((0, 0, dict(
                {key: line[key] for key in BUTTON_LINE_FIELDS if key in line},
                model_id=IrModel._get(line['model']).id, button_name=button_name)))
        values['button_ids'] = button_lines

    def _gec_apply_elements(self, data, values, notes):
        IrModel = self.env['ir.model'].sudo()
        element_lines = []
        for line in data.get('elements', []):
            if line.get('model') not in self.env:
                notes.append(_("Data not installed: %s", line.get('model')))
                continue
            element_lines.append((0, 0, dict(
                {key: line[key] for key in ELEMENT_LINE_FIELDS if key in line},
                model_id=IrModel._get(line['model']).id)))
        values['element_ids'] = element_lines

    def _gec_apply_allowed(self, data, values):
        """ Resolve every allowed record, refusing an incomplete import or restore. """
        allowed_lines = []
        kinds = dict(self.env['gec.access.allowed']._selection_kinds())
        Allowed = self.env['gec.access.allowed']
        for line in data.get('allowed', []):
            if line.get('kind') not in kinds:
                raise UserError(_(
                    "Cannot import or restore this profile. Allowed records of type '%s' are not available. Install the"
                    " app they need, then try again.", line.get('kind')))
            if line.get('per_user'):
                allowed_lines.append((0, 0, {'kind': line['kind'], 'per_user': True}))
                continue
            model_name = Allowed.new({'kind': line['kind']}).res_model
            record = self._gec_find(line.get('record'), model_name)
            if not record:
                raise UserError(_(
                    "Cannot import or restore this profile. The allowed record '%s' was not found, or more than one "
                    "record matches it. Create the record or make it unique, then try again. This limit cannot be "
                    "skipped.",
                    (line.get('record') or {}).get('xmlid') or (line.get('record') or {}).get('name')
                    or line['kind']))
            allowed_lines.append((0, 0, {'kind': line['kind'], 'res_id': record.id}))
        values['allowed_ids'] = allowed_lines

    def _gec_apply_login_slots(self, data, values):
        if 'login_slots' in data:
            values['login_slot_ids'] = [
                (0, 0, {key: slot[key] for key in LOGIN_SLOT_FIELDS if key in slot})
                for slot in data['login_slots']
            ]

    def _gec_apply_users(self, data, values, with_users, notes):
        if with_users and 'users' in data:
            users = self.env['res.users'].sudo().search([('login', 'in', data['users'])])
            values['user_ids'] = [(6, 0, users.ids)]
            for login in set(data['users']) - set(users.mapped('login')):
                notes.append(_("User not found: %s", login))
