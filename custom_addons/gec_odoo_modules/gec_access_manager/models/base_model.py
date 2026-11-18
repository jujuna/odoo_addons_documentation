import html
import logging

from lxml import etree
from markupsafe import escape

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain

from .field_guard import ARCHIVE_FIELDS, CLIENT_WRITE_ENTRIES
from .value_filters import eval_filter

_logger = logging.getLogger(__name__)

# what an import column of ARCHIVE_FIELDS may hold without archiving the record (Odoo's untranslated true words)
IMPORT_TRUE_WORDS = frozenset({'1', 'true', 'yes'})
# The user's own records that Read Only Everywhere still lets them change, as {model: (operations, domain)}, evaluated
# like an access domain; Odoo's own rules still apply. Not res.users and res.partner: the views derive their edit right
# from has_access('write') on the model, so every contact form would look editable.
READONLY_OWN_RECORDS = {
    'res.users.settings': (('write', 'create'), "[('user_id', '=', user.id)]"),
    'discuss.channel.member': (('write',), "[('is_self', '=', True)]"),
    'mail.notification': (('write',), "[('res_partner_id', '=', user.partner_id.id)]"),
    'ir.filters': (('write', 'create', 'unlink'), "[('user_ids', 'in', [user.id])]"),
}
# Read Only Everywhere skips wizards (scratch data) except the access wizards, settings and writers for the user
READONLY_KEPT_WIZARDS = frozenset({
    'gec.access.assign', 'gec.access.copy.access', 'res.config.settings', 'portal.wizard', 'portal.wizard.user',
    'mail.compose.message',
})

# the fields of hr.employee that decide res.users.employee_id (hr/models/res_users.py _compute_company_employee)
EMPLOYEE_LINK_FIELDS = frozenset({'user_id', 'company_id', 'active'})


class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def _gec_wizard(self):
        """ Whether this is a wizard that Read Only Everywhere leaves alone (ProfileRules.allows). """
        return self._transient and self._name not in READONLY_KEPT_WIZARDS

    @api.model
    @api.ormcache('operation', 'self.env._access_context')
    def _access_domain(self, operation):
        # Not short circuited on self.env.su: the cache key lacks the superuser
        # flag, so a sudo result would be served to the same user without it.
        domain = super()._access_domain(operation)
        if domain.is_false():
            return domain

        rules = self.env['gec.access.profile']._resolve(self.env.uid)
        if not rules.enabled:
            return domain
        if not rules.allows(self._name, operation, self._gec_wizard()):
            return Domain.FALSE
        restricted = self._gec_profile_domain(rules, operation)
        if restricted is not None:
            domain &= restricted
        if self._name == 'mail.message' and operation == 'read':
            if (hidden := self._gec_hidden_tracking_domain(rules)) is not None:
                domain &= hidden
        return domain

    @api.model
    def _gec_hidden_tracking_markers(self, rules):
        """ The ``<i>(label)</i>`` markers of tracked hidden fields, in every language, as written and as the sanitizer
        stores them: v20 renders tracking into the stored body, where the field guard cannot blank it. A properties
        field shows ``<i>(label: property)</i>``. Memoised on ``rules``. """
        if 'hidden_tracking_markers' in rules._memo:
            return rules._memo['hidden_tracking_markers']
        markers = set()
        for model_name, field_name in rules.hidden_field_pairs():
            if model_name not in self.env:
                continue
            field = self.env[model_name]._fields.get(field_name)
            record = self.env['ir.model.fields']._get(model_name, field_name)
            tracked = field is not None and (getattr(field, 'tracking', False) or field.type == 'properties')
            if not (record and tracked):
                continue
            pattern = '<i>(%s: ' if field.type == 'properties' else '<i>(%s)</i>'
            for label in (record._get_stored_translations('field_description') or {}).values():
                markers.update(pattern % text for text in (label, str(escape(label)), html.escape(label, quote=False)))
        rules._memo['hidden_tracking_markers'] = tuple(sorted(markers))
        return rules._memo['hidden_tracking_markers']

    @api.model
    def _gec_hidden_tracking_domain(self, rules):
        """ The messages left to read once the tracking messages that show a hidden field are out, or None when none is
        tracked. No model condition: a parent record's chatter may log the field of a child. """
        markers = self._gec_hidden_tracking_markers(rules)
        if not markers:
            return None
        return ~(Domain('message_type', '=', 'tracking') & Domain.OR(
            Domain('body', 'ilike', marker) for marker in markers))

    @api.model
    def _gec_profile_domain(self, rules, operation):
        """ The records the user's profiles leave to ``operation``, or None when they filter none. """
        own = self._gec_readonly_own_domain(rules, operation)
        or_groups, and_groups = rules.record_domains(self._name, operation, self._gec_wizard())
        if not or_groups and not and_groups:
            return own

        eval_context = self.env['gec.access.profile']._gec_eval_context()

        def parse(terms):
            return Domain.AND([self._gec_term_domain(term, eval_context) for term in terms])

        extra = [parse(terms) for terms in and_groups]
        if or_groups:
            extra.append(Domain.OR([parse(terms) for terms in or_groups]))
        restricted = Domain.AND(extra)
        if own is not None:
            restricted &= own
        if operation == 'read' and (own := self._gec_own_records_domain()):
            # a user reads their own user and contact: Odoo reads them for its own screens, and they reveal nothing new
            restricted |= own
        return restricted

    @api.model
    def _gec_readonly_own_domain(self, rules, operation):
        """ The user's own records of a READONLY_OWN_RECORDS model that a Read Only Everywhere profile lets them change
        (ProfileRules.allows), else None. """
        exempt = READONLY_OWN_RECORDS.get(self._name)
        if not exempt or operation not in exempt[0] or not rules.has_global_readonly():
            return None
        return self._gec_term_domain(exempt[1], self.env['gec.access.profile']._gec_eval_context())

    @api.model
    def _gec_term_domain(self, term, eval_context):
        """ The domain of one record filter text (see eval_filter). A text that cannot be evaluated matches
        no record: the filter fails closed. Not Domain.FALSE, see _access_domain in gec_access_preview.py. """
        try:
            return Domain(eval_filter(term, eval_context, self.env['res.users']))
        except Exception as error:  # noqa: BLE001
            _logger.warning("Record filter %r of %s not applied: %s", term, self._name, error)
            return Domain('id', '=', 0)

    @api.model
    def _gec_own_records_domain(self):
        if self._name == 'res.users':
            return Domain('id', '=', self.env.uid)
        if self._name == 'res.partner':
            return Domain('id', '=', self.env['res.users'].sudo().browse(self.env.uid).partner_id.id)
        return None

    def _make_access_error_message(self, operation, domain):
        # Say plainly that the profile refused, without naming the records: the user may not be allowed to know them.
        rules = self.env['gec.access.profile']._current_rules()
        if rules.enabled:
            model_label = self.env['ir.model']._get(self._name).name or self._name
            if not rules.allows(self._name, operation, self._gec_wizard()):
                return AccessError(_(
                    "Your access profile does not allow you to %(operation)s %(model)s.\n\n"
                    "Ask your administrator if you need to.",
                    operation=self._gec_operation_label(operation), model=model_label))
            core = super()._access_domain(operation)
            if self and not core.is_false() and self.sudo().filtered_domain(core) == self.sudo():
                return AccessError(_(
                    "Your access profile does not allow you to %(operation)s these %(model)s records. They are outside "
                    "the records allowed to you.\n\nAsk your administrator if you need to.",
                    operation=self._gec_operation_label(operation), model=model_label))
        return super()._make_access_error_message(operation, domain)

    def _gec_operation_label(self, operation):
        return {
            'read': _("read"), 'write': _("edit"), 'create': _("create"), 'unlink': _("delete"),
        }.get(operation, operation)

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id, view_type, **options)
        rules = self.env['gec.access.profile']._current_rules()
        if not rules.enabled or not rules.affects_views():
            return result
        tree = etree.fromstring(result['arch'])
        added = self.env['gec.access.profile']._apply_view_rules(rules, tree, self._name, view_type)
        # the models of the cached view are frozen: the names added to the arch go into a new dict
        models = dict(result.get('models') or {})
        for model_name, names in added.items():
            models[model_name] = tuple(dict.fromkeys((*models.get(model_name, ()), *sorted(names))))
        return dict(result, arch=etree.tostring(tree, encoding='unicode'), models=models)

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        result = super().fields_get(allfields=allfields, attributes=attributes)
        rules = self.env['gec.access.profile']._current_rules()
        if not rules.enabled:
            return result
        # The client offers Archive/Unarchive only while 'active' is writable: read-only removes the entries.
        if rules.model_flag(self._name, 'hide_archive'):
            for field_name in ARCHIVE_FIELDS:
                if field_name in result and 'readonly' in result[field_name]:
                    result[field_name]['readonly'] = True
        for field_name in rules.restricted_fields(self._name):
            if field_name in result and rules.field_mode(self._name, field_name) == 'readonly':
                if 'readonly' in result[field_name]:
                    result[field_name]['readonly'] = True
        return result

    def _gec_clear_employee_filters(self):
        """ Clear the cached rules when a filter reads a user's employee (``user.employee_id.id``). Run after
        ``super()``: its access check caches the rules again with the old link. """
        users = self.env['res.users']
        if any(getattr(users._fields.get(name), 'comodel_name', None) == 'hr.employee'
               for name in self.env['gec.access.profile']._gec_user_fields_in_filters()):
            self.env.transaction.invalidate_ormcache('default')

    @api.model_create_multi
    def create(self, vals_list):
        """ Clear the cached filters that read the user's employee when an employee is created. """
        records = super().create(vals_list)
        if self._name == 'hr.employee' and records:
            self._gec_clear_employee_filters()
        return records

    def unlink(self):
        """ Clear the cached filters that read the user's employee when an employee is deleted. """
        result = super().unlink()
        if self._name == 'hr.employee' and self:
            self._gec_clear_employee_filters()
        return result

    def write(self, vals):
        """ Refuses Archive and Unarchive when a profile hides them, only on the action_archive and action_unarchive the
        client called itself, and on the gantt view's writes: Odoo's own archiving passes. A client write of ``active``
        is refused at the controllers (gec.access.profile._check_archive_call). """
        if not ARCHIVE_FIELDS.isdisjoint(vals) and (
                self._gec_rpc_entry('action_archive') or self._gec_rpc_entry('action_unarchive')
                or any(self._gec_rpc_entry(method) for method in CLIENT_WRITE_ENTRIES[1:])):
            self.env['gec.access.profile']._check_archive(self._name)
        if self._gec_changes_properties(vals):
            rules = self.env['gec.access.profile']._current_rules()
            if rules.enabled and rules.has_flag('block_properties'):
                raise self.env['gec.access.profile']._gec_refusal(
                    _("Your access profile does not allow changing the properties of a form."),
                    model=self._name, record_ids=self.ids)
        result = super().write(vals)
        if self._name == 'hr.employee' and self and not EMPLOYEE_LINK_FIELDS.isdisjoint(vals):
            self._gec_clear_employee_filters()
        return result

    def _gec_changes_properties(self, vals):
        """ Whether ``vals`` changes the definition of properties: the definition field, or a value carrying one. """
        for name, value in vals.items():
            field = self._fields.get(name)
            if field is None:
                continue
            if field.type == 'properties_definition':
                return True
            if field.type == 'properties' and isinstance(value, list) and any(
                    isinstance(item, dict) and (item.get('definition_changed') or item.get('definition_deleted'))
                    for item in value):
                return True
        return False

    def copy(self, default=None):
        """ Refuses Duplicate when a profile hides it, only on the copy the client called itself. copy() goes
        through create(), so neither the button check nor _access_domain() sees it; Odoo's own copies
        (backorders, returns, reversals) pass. """
        if self._gec_rpc_entry('copy'):
            rules = self.env['gec.access.profile']._current_rules()
            if rules.enabled and rules.model_flag(self._name, 'hide_duplicate'):
                raise UserError(_(
                    "Your access profile does not allow duplicating '%s'.",
                    self.env['ir.model']._get(self._name).name or self._name))
        return super().copy(default)

    @api.model
    def load(self, fields, data):
        """ Every import lands here (import="0" on the view only hides the menu entry): refused when a profile hides
        Import, and when an imported column sets ``active`` to anything but a true word on a model whose Archive a
        profile hides (a blank cell of a nested column is no value). """
        rules = self.env['gec.access.profile']._current_rules()
        if rules.enabled and rules.model_flag(self._name, 'hide_import'):
            raise UserError(_(
                "Your access profile does not allow importing '%s'.",
                self.env['ir.model']._get(self._name).name or self._name))
        for index, path in enumerate(fields):
            *relations, last = path.split('/')
            if last not in ARCHIVE_FIELDS:
                continue
            model = self
            for name in relations:
                field = model._fields.get(name)
                if field is None or not field.relational:
                    break
                model = self.env[field.comodel_name]
            else:
                values = (str(row[index] if index < len(row) else '').strip().lower() for row in data)
                if any(value not in IMPORT_TRUE_WORDS and (value or not relations) for value in values):
                    self.env['gec.access.profile']._check_archive(model._name)
        return super().load(fields, data)

    def export_data(self, fields_to_export):
        """ Refuse an export of a model, or through a model its paths cross (partner_id/email), that a profile keeps
        out of the exports: core exports the related records without their export_data. """
        rules = self.env['gec.access.profile']._current_rules()
        if rules.enabled:
            crossed, opaque = self._gec_export_path_models(fields_to_export)
            blocked = next((self.env['ir.model']._get(name).name or name for name in (self._name, *crossed)
                            if rules.model_flag(name, 'hide_export')), None)
            if not blocked and opaque and rules.sets_model_flag('hide_export'):
                # a property or a reference names its model per record: below one, refuse when an export is blocked
                blocked = opaque
            if blocked:
                raise UserError(_("Your access profile does not allow exporting '%s'.", blocked))
        return super().export_data(fields_to_export)

    def _gec_export_path_models(self, paths):
        """ ``(models, opaque)``: the models the export paths cross after this one, read as core splits them
        (``partner_id@en_US/email``), and the label of a property or reference field a path goes below, whose model only
        its value tells (else None). """
        crossed, opaque = set(), None
        for path in paths:
            model = self
            for name in models.fix_import_export_id_paths(path)[:-1]:
                fname, __, prop = name.split('@')[0].partition('.')
                field = model._fields.get(fname)
                if field is not None and ((field.type == 'properties' and prop) or field.type == 'reference'):
                    opaque = opaque or field.string
                    break
                if field is None or not field.relational:
                    break
                model = self.env[field.comodel_name]
                crossed.add(model._name)
        return crossed, opaque
