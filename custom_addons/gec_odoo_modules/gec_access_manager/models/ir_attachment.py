from collections import defaultdict

from odoo import models
from odoo.fields import Domain

from odoo.addons.base.models.ir_attachment import condition_values

from .conditions import condition_domain


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _gec_binary_rules(self):
        """ The real user's rules, or None when no check is needed. Settings users under an apply_to_admin profile are
        judged too: core skips its own field check for them (odoo/addons/base/models/ir_attachment.py:702). """
        rules = self.sudo(False).env['gec.access.profile']._current_rules()
        return rules if rules.enabled else None

    def _compute_res_access(self, operation):
        """ After core, refuse reading a file of a hidden field and writing one locked (hidden or read only), always or
        under a condition when its record matches; a derived image (image_128 of image_1920) follows its source. """
        super()._compute_res_access(operation)
        rules = self._gec_binary_rules()
        if not rules:
            return
        modes = ('hide',) if operation == 'read' else ('hide', 'readonly')
        by_model = defaultdict(list)
        for attachment in self:
            if attachment.res_field and attachment.res_id:
                by_model[attachment.res_model].append(attachment)
        for res_model, attachments in by_model.items():
            names = rules.fields_in_modes(res_model, modes)
            conditions = rules.conditional_fields(res_model, modes)
            if not names and not conditions:
                continue
            model = self.env[res_model]
            locked = model._gec_binary_family(set(names))
            for attachment in attachments:
                if attachment.res_field in locked:
                    attachment[f'res_access_{operation}'] = False
            for name, condition in conditions.items():
                family = model._gec_binary_family({name})
                hit = [attachment for attachment in attachments if attachment.res_field in family]
                matching = model._gec_matching(condition, [attachment.res_id for attachment in hit])
                for attachment in hit:
                    if attachment.res_id in matching:
                        attachment[f'res_access_{operation}'] = False

    def _search_res_access(self, operation, domain_operator):
        """ The rule of _compute_res_access as a domain for searches, looking only at the models searched, as core does;
        a condition SQL cannot express hides the field on every record of its model. """
        domain = super()._search_res_access(operation, domain_operator)
        rules = operation == 'read' and domain is not NotImplemented and self._gec_binary_rules()
        if not rules:
            return domain
        search_domain = self.env.context.get('search_domain')
        searched = condition_values(self, 'res_model', search_domain if isinstance(search_domain, Domain)
                                    else Domain.TRUE)
        hidden = []
        for res_model in {model for model, _field in rules.hidden_field_pairs()}:
            if searched and res_model not in searched:
                continue
            model = self.env[res_model]
            family = model._gec_binary_family(set(rules.fields_in_modes(res_model, ('hide',))))
            names = [field for field in family if model._fields[field].type in ('binary', 'image')]
            if names:
                hidden.append(Domain('res_model', '=', res_model) & Domain('res_field', 'in', names))
        for res_model in rules.conditional_models():
            if searched and res_model not in searched:
                continue
            model = self.env[res_model]
            for name, condition in rules.conditional_fields(res_model, ('hide',)).items():
                names = [field for field in model._gec_binary_family({name})
                         if model._fields[field].type in ('binary', 'image')]
                if not names:
                    continue
                family = Domain('res_model', '=', res_model) & Domain('res_field', 'in', names)
                try:
                    records = model._search(Domain(condition_domain(condition, model, self.env.uid)), active_test=False)
                except ValueError:
                    hidden.append(family)
                    continue
                if not records.is_empty():
                    hidden.append(family & Domain('res_id', 'in', records))
        return domain & ~Domain.OR(hidden) if hidden else domain
