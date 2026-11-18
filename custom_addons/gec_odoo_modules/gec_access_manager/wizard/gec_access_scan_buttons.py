import logging

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.gec_access_manager.models.gec_access_profile_element import ELEMENT_TYPES

_logger = logging.getLogger(__name__)

SCANNED_VIEW_TYPES = ('form', 'list', 'kanban')


class GecAccessScanButtons(models.TransientModel):
    _name = 'gec.access.scan.buttons'
    _description = 'Scan the Views of a Model'

    profile_id = fields.Many2one('gec.access.profile', required=True, ondelete='cascade')
    model_id = fields.Many2one('ir.model', string='Model', required=True, ondelete='cascade')
    target = fields.Selection(
        [('buttons', 'Buttons'), ('elements', 'Tabs and Search Filters')],
        default='buttons', required=True, string='Look for')
    mode = fields.Selection(
        [('hide', 'Hide only'),
         ('block', 'Block only'),
         ('hide_block', 'Hide and block')],
        default='hide_block', required=True,
        help="Used for every button you tick in the next step.")
    state = fields.Selection([('model', 'Model'), ('select', 'Selection')], default='model', required=True)
    line_ids = fields.One2many('gec.access.scan.buttons.line', 'wizard_id', string='Found')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'profile_id' in fields_list and self.env.context.get('active_model') == 'gec.access.profile':
            values.setdefault('profile_id', self.env.context.get('active_id'))
        return values

    @api.model
    def _scan(self, model_name):
        """ Yield one dict per button found in the views of ``model_name``. """
        model = self.env[model_name].sudo()
        seen = set()
        for view_type in SCANNED_VIEW_TYPES:
            try:
                arch = model.get_view(view_type=view_type)['arch']
            except Exception:  # noqa: BLE001 - the model may have no such view
                _logger.debug("no %s view for %s", view_type, model_name, exc_info=True)
                continue
            for node in etree.fromstring(arch).xpath('//button[@name and not(@special)]'):
                if any(ancestor.tag == 'field' for ancestor in node.iterancestors()):
                    continue  # belongs to the nested view of an x2many
                button_type = node.get('type') or 'object'
                if button_type not in ('object', 'action'):
                    continue
                name = node.get('name')
                button_id = node.get('id') or ''
                key = (view_type, button_type, name, button_id)
                if key in seen:
                    continue
                seen.add(key)
                yield {
                    'view_type': view_type,
                    'button_type': button_type,
                    'button_name': name,
                    'button_id': button_id,
                    'button_label': self._label(node, button_type, name),
                }

    @api.model
    def _label(self, node, button_type, name):
        label = node.get('string')
        if not label:
            child = node.find('field')
            if child is not None:
                label = child.get('string')
        if not label and button_type == 'action':
            try:
                action = self.env['ir.actions.actions'].sudo().browse(int(name)).exists()
            except (TypeError, ValueError):
                action = None
            label = action.name if action else None
        return label or name

    @api.model
    def _scan_elements(self, model_name):
        """ Yield the notebook tabs and the search filters of a model. """
        model = self.env[model_name].sudo()
        seen = set()
        for view_type, tag, element_type in (
            ('form', 'page', 'page'),
            ('search', 'filter', 'filter'),
            ('search', 'searchpanel', 'searchpanel'),
        ):
            try:
                arch = model.get_view(view_type=view_type)['arch']
            except Exception:  # noqa: BLE001 - the model may have no such view
                _logger.debug("no %s view for %s", view_type, model_name, exc_info=True)
                continue
            for node in etree.fromstring(arch).iter(tag):
                if any(ancestor.tag == 'field' for ancestor in node.iterancestors()):
                    continue  # belongs to the nested view of an x2many
                name = node.get('name') or ''
                if element_type != 'searchpanel' and not name:
                    continue  # nothing to match it by
                key = (element_type, name)
                if key in seen:
                    continue
                seen.add(key)
                label = node.get('string') or name
                if element_type == 'filter' and 'group_by' in (node.get('context') or ''):
                    label = _("%s (group by)", label)
                yield {'element_type': element_type, 'element_name': name, 'element_label': label}

    def _existing_keys(self):
        self.ensure_one()
        return {
            (line.view_type, line.button_type, line.button_name, line.button_id or '')
            for line in self.profile_id.button_ids
            if line.model_id == self.model_id
        }

    def _existing_element_keys(self):
        self.ensure_one()
        return {
            (line.element_type, line.element_name or '')
            for line in self.profile_id.element_ids
            if line.model_id == self.model_id
        }

    def action_scan(self):
        self.ensure_one()
        if self.target == 'buttons':
            existing = self._existing_keys()
            found = [
                values for values in self._scan(self.model_id.model)
                if (values['view_type'], values['button_type'],
                    values['button_name'], values['button_id']) not in existing
            ]
        else:
            existing = self._existing_element_keys()
            found = [
                values for values in self._scan_elements(self.model_id.model)
                if (values['element_type'], values['element_name']) not in existing
            ]
        if not found:
            raise UserError(_(
                "Nothing new was found in the views of %s. This profile already covers everything there.", self.model_id.model))
        self.write({'state': 'select', 'line_ids': [(5, 0, 0)] + [(0, 0, values) for values in found]})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Scan Buttons'),
        }

    def action_apply(self):
        self.ensure_one()
        selected = self.line_ids.filtered('selected')
        if not selected:
            raise UserError(_("Tick at least one line."))
        if self.target == 'elements':
            self.env['gec.access.profile.element'].create([
                {
                    'profile_id': self.profile_id.id,
                    'model_id': self.model_id.id,
                    'element_type': line.element_type,
                    'element_name': line.element_name,
                    'element_label': line.element_label,
                }
                for line in selected
            ])
            return self._back_to_profile()
        self.env['gec.access.profile.button'].create([
            {
                'profile_id': self.profile_id.id,
                'model_id': self.model_id.id,
                'view_type': line.view_type,
                'button_type': line.button_type,
                'button_name': line.button_name,
                'button_id': line.button_id,
                'button_label': line.button_label,
                'mode': self.mode,
            }
            for line in selected
        ])
        return self._back_to_profile()

    def _back_to_profile(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'gec.access.profile',
            'res_id': self.profile_id.id,
            'view_mode': 'form',
            'target': 'current',
            'name': _('Access Profile'),
        }


class GecAccessScanButtonsLine(models.TransientModel):
    _name = 'gec.access.scan.buttons.line'
    _description = 'Scanned Button'
    _order = 'view_type, button_label, element_label, id'

    wizard_id = fields.Many2one('gec.access.scan.buttons', required=True, ondelete='cascade')
    selected = fields.Boolean(string='Restrict')
    view_type = fields.Selection([('form', 'Form'), ('list', 'List'), ('kanban', 'Kanban')])
    button_type = fields.Selection([('object', 'Method'), ('action', 'Action')])
    button_name = fields.Char(string='Button')
    button_id = fields.Char(string='Button Id')
    button_label = fields.Char(string='Label')
    element_type = fields.Selection(ELEMENT_TYPES)
    element_name = fields.Char(string='Name')
    element_label = fields.Char(string='Element Label')
