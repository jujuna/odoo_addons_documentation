from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

# Menus this app takes over from Accounting: (menu, parent here, sequence here, parent in Accounting, sequence there).
# The "in Accounting" values are what each declaration module's own XML sets, used to put the menus back.
MENU_MOVES = [
    ('gec_vat_declaration.menu_gec_vat_declaration',
     'gec_declarations.menu_declarations_filing', 10, 'account.menu_finance_reports', 61),
    ('gec_income_tax_report.menu_rs_form30_declaration',
     'gec_declarations.menu_declarations_filing', 20, 'account.menu_finance_reports', 60),
    ('gec_profit_tax_report.rs_cit_declaration_menu',
     'gec_declarations.menu_declarations_filing', 30, 'account.menu_finance_reports', 61),
    ('gec_property_tax_report.menu_rs_form15_declaration',
     'gec_declarations.menu_declarations_filing', 40, 'account.menu_finance_reports', 61),
    ('gec_profit_tax_report.rs_cit_taxed_item_menu',
     'gec_declarations.menu_declarations_registers', 10, 'account.menu_finance_reports', 62),
    ('gec_property_tax_report.menu_rs_form15_land_plot',
     'gec_declarations.menu_declarations_registers', 20, 'account.menu_finance_configuration', 91),
    ('gec_income_tax_report.menu_rs_form30_config',
     'gec_declarations.menu_declarations_config', 10, 'account.menu_finance_configuration', 90),
    ('gec_property_tax_report.menu_rs_form15_config',
     'gec_declarations.menu_declarations_config', 20, 'account.menu_finance_configuration', 92),
    ('gec_profit_tax_report.rs_cit_cell_menu',
     'gec_declarations.menu_declarations_config', 30, 'account.account_account_menu', 90),
]
MONTHLY_DUE_DAY = 15  # monthly rs.ge declarations are due by the 15th of the next month


class GecDeclarationCard(models.Model):
    """One card of the Declarations overview: a declaration module and the screen it opens."""
    _name = 'gec.declaration.card'
    _description = 'Declaration Card'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    description = fields.Char(translate=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer()
    module_name = fields.Char(string='Module', required=True, help="Technical name of the declaration module.")
    model_name = fields.Char(string='Model', required=True, help="Model of the declarations, e.g. gec.vat.declaration.")
    action_xmlid = fields.Char(string='Action', required=True, help="Window action that lists the declarations.")
    frequency = fields.Selection([('monthly', 'Monthly'), ('annual', 'Annual')], required=True, default='monthly')
    available = fields.Boolean(compute='_compute_stats', search='_search_available',
                               help="The declaration module is installed and the user may read its declarations.")
    latest_name = fields.Char(compute='_compute_stats', string='Latest')
    latest_state = fields.Char(compute='_compute_stats', string='Latest Status')
    draft_count = fields.Integer(compute='_compute_stats', string='Drafts')
    next_due = fields.Date(compute='_compute_stats', string='Next Due Date',
                           help="Monthly declarations: the 15th of the month the last month's declaration is due in.")

    _module_model_uniq = models.Constraint('UNIQUE(module_name, model_name)', 'One card per declaration model.')

    def _model(self):
        """The declaration model when its module is installed and the user may read it, else None."""
        self.ensure_one()
        if self.model_name not in self.env:
            return None
        Model = self.env[self.model_name]
        return Model if Model.has_access('read') else None

    def _compute_stats(self):
        today = fields.Date.context_today(self)
        due = today.replace(day=MONTHLY_DUE_DAY)
        if today.day > MONTHLY_DUE_DAY:
            due += relativedelta(months=1)
        for card in self:
            Model = card._model()
            latest = Model.search([], limit=1) if Model is not None else None
            states = dict(Model._fields['state']._description_selection(self.env)) if Model is not None else {}
            card.available = Model is not None
            card.latest_name = latest.display_name if latest else False
            card.latest_state = states.get(latest.state) if latest else False
            card.draft_count = Model.search_count([('state', '=', 'draft')]) if Model is not None else 0
            card.next_due = due if Model is not None and card.frequency == 'monthly' else False

    def _search_available(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        ids = self.search([]).filtered(lambda card: card._model() is not None).ids
        return [('id', 'in' if (operator == '=') == value else 'not in', ids)]

    def action_open(self):
        self.ensure_one()
        return self.env['ir.actions.act_window']._for_xml_id(self.action_xmlid)

    def action_new(self):
        self.ensure_one()
        action = self.action_open()
        action.update({'views': [(False, 'form')], 'view_mode': 'form', 'res_id': False,
                       'name': _('New %s', self.name)})
        return action

    def action_open_drafts(self):
        self.ensure_one()
        action = self.action_open()
        action['domain'] = [('state', '=', 'draft')]
        return action

    @api.model
    def _gec_place_menus(self, restore=False):
        """Move the declaration menus into this app, or back to Accounting with ``restore``. Missing modules are
        skipped, so the app works with any subset of the declaration modules."""
        Menu = self.env['ir.ui.menu'].sudo()
        for xmlid, parent_here, sequence_here, parent_back, sequence_back in MENU_MOVES:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            parent = self.env.ref(parent_back if restore else parent_here, raise_if_not_found=False)
            if not menu or not parent:
                continue
            sequence = sequence_back if restore else sequence_here
            if menu.parent_id != parent or menu.sequence != sequence:
                Menu.browse(menu.id).write({'parent_id': parent.id, 'sequence': sequence})

    def _register_hook(self):
        """Run after every module load: a declaration module installed or updated later puts its menus back in
        Accounting, and this moves them here again."""
        super()._register_hook()
        module = self.env['ir.module.module'].sudo().search([('name', '=', 'gec_declarations')], limit=1)
        if module.state == 'installed':
            self._gec_place_menus()
