import ast
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

# kind: (label, model of the records, {model to filter: domain with {ids}})
ALLOWED_KINDS = {
    'journal': (_lt("Journals"), 'account.journal', {
        'account.journal': "[('id', 'in', {ids})]",
        'account.move': "[('journal_id', 'in', {ids})]",
        'account.move.line': "[('journal_id', 'in', {ids})]",
        'account.payment': "[('journal_id', 'in', {ids})]",
        'account.bank.statement': "[('journal_id', 'in', {ids})]",
        'account.bank.statement.line': "[('journal_id', 'in', {ids})]",
        'account.invoice.report': "[('journal_id', 'in', {ids})]",
        'report.pos.order': "[('journal_id', 'in', {ids})]",
    }),
    'pos': (_lt("Points of Sale"), 'pos.config', {
        'pos.config': "[('id', 'in', {ids})]",
        'pos.session': "[('config_id', 'in', {ids})]",
        'pos.order': "[('config_id', 'in', {ids})]",
        'pos.payment': "[('session_id.config_id', 'in', {ids})]",
        'report.pos.order': "[('config_id', 'in', {ids})]",
    }),
    'warehouse': (_lt("Warehouses"), 'stock.warehouse', {
        'stock.warehouse': "[('id', 'in', {ids})]",
        # operation types and locations of no warehouse (dropship, customer and vendor locations) are shared by all
        'stock.picking.type': "['|', ('warehouse_id', '=', False), ('warehouse_id', 'in', {ids})]",
        'stock.location': "['|', ('warehouse_id', '=', False), ('warehouse_id', 'in', {ids})]",
        'stock.picking': "[('picking_type_id.warehouse_id', 'in', {ids})]",
        'stock.quant': "[('location_id.warehouse_id', 'in', {ids})]",
        'stock.move': "['|', ('location_id.warehouse_id', 'in', {ids}), "
                      "('location_dest_id.warehouse_id', 'in', {ids})]",
        'stock.move.line': "['|', ('location_id.warehouse_id', 'in', {ids}), "
                           "('location_dest_id.warehouse_id', 'in', {ids})]",
    }),
    'location': (_lt("Locations"), 'stock.location', {
        # non-internal locations (customers, vendors...) stay usable
        'stock.location': "['|', ('usage', '!=', 'internal'), ('id', 'child_of', {ids})]",
        'stock.quant': "[('location_id', 'child_of', {ids})]",
        'stock.picking': "['|', ('location_id', 'child_of', {ids}), ('location_dest_id', 'child_of', {ids})]",
        'stock.move': "['|', ('location_id', 'child_of', {ids}), ('location_dest_id', 'child_of', {ids})]",
        'stock.move.line': "['|', ('location_id', 'child_of', {ids}), ('location_dest_id', 'child_of', {ids})]",
    }),
    'dashboard': (_lt("Dashboards"), 'spreadsheet.dashboard', {
        'spreadsheet.dashboard': "[('id', 'in', {ids})]",
    }),
    'team': (_lt("Sales Teams"), 'crm.team', {
        'crm.team': "[('id', 'in', {ids})]",
        'sale.order': "[('team_id', 'in', {ids})]",
        'sale.order.line': "[('order_id.team_id', 'in', {ids})]",
        'sale.report': "[('team_id', 'in', {ids})]",
        'crm.lead': "[('team_id', 'in', {ids})]",
    }),
}

# journals Odoo posts to on its own, whoever the user is: exchange differences and cash basis taxes (set on the
# companies); the deferral journals are left out: on Enterprise they default to MISC, which would open it to everyone
COMPANY_JOURNAL_FIELDS = ('currency_exchange_journal_id', 'tax_cash_basis_journal_id')


class GecAccessAllowed(models.Model):
    _name = 'gec.access.allowed'
    _inherit = ['gec.access.history.mixin']
    _description = 'Allowed Record'

    def _gec_history_kind(self):
        return _("allowed record")

    def _gec_history_label(self):
        kind = dict(self._selection_kinds()).get(self.kind, self.kind)
        return '%s: %s' % (kind, self.display_name or '')
    _order = 'id'

    # the rules are cached per user: any change here must reach them
    _clear_cache_name = 'default'

    profile_id = fields.Many2one('gec.access.profile', ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', ondelete='cascade', index=True)
    kind = fields.Selection(selection='_selection_kinds', string='Allowed', required=True)
    res_model = fields.Char(compute='_compute_res_model', store=True)
    res_id = fields.Many2oneReference(string='Record', model_field='res_model')
    per_user = fields.Boolean(
        string="Each User's Own",
        help="Instead of one record, use the records set on each user's form. One profile then works for every cashier,"
             " each on their own point of sale.")

    def _gec_check_users_editor(self):
        """ Check with their editor the profiles of the users the lines are set on, however they carry them: a user
        line has no profile of its own for the history mixin to check, yet it changes what their profiles give. """
        Profile = self.env['gec.access.profile']
        for user in self.user_id.sudo():
            Profile._gec_profiles_of(user)._gec_check_editor()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._gec_check_users_editor()
        return lines

    def write(self, vals):
        self._gec_check_users_editor()
        result = super().write(vals)
        if 'user_id' in vals:
            self._gec_check_users_editor()
        return result

    def unlink(self):
        self._gec_check_users_editor()
        return super().unlink()

    @api.model
    def _selection_kinds(self):
        lang = self.env.lang or 'en_US'
        return [(kind, label._translate(lang) if hasattr(label, '_translate') else str(label))
                for kind, (label, model_name, _filters) in ALLOWED_KINDS.items()
                if model_name in self.env]

    @api.depends('kind')
    def _compute_res_model(self):
        for line in self:
            line.res_model = ALLOWED_KINDS[line.kind][1] if line.kind in ALLOWED_KINDS else False

    @api.constrains('profile_id', 'user_id', 'res_id', 'per_user', 'kind', 'res_model')
    def _check_target(self):
        for line in self:
            if line.res_model != (ALLOWED_KINDS[line.kind][1] if line.kind in ALLOWED_KINDS else False):
                raise ValidationError(_(
                    "The allowed record does not match its kind (%(kind)s).",
                    kind=dict(self._selection_kinds()).get(line.kind, line.kind)))
            if bool(line.profile_id) == bool(line.user_id):
                raise ValidationError(_("An allowed record needs either a profile or a user, but not both."))
            if line.user_id and line.per_user:
                raise ValidationError(_("'Each user's own' can only be set on a profile, not on a user."))
            if not line.per_user and not line.res_id:
                raise ValidationError(_("Pick the allowed record, or tick 'Each user's own'."))

    @api.depends('res_model', 'res_id', 'per_user')
    @api.depends_context('uid')
    def _compute_display_name(self):
        ids_of = defaultdict(list)
        for line in self:
            if not line.per_user and line.res_model in self.env and line.res_id:
                ids_of[line.res_model].append(line.res_id)
        names = {
            model_name: {record.id: record.display_name
                         for record in self.env['gec.access.profile']._gec_readable_records(model_name, ids)}
            for model_name, ids in ids_of.items()
        }
        for line in self:
            if line.per_user:
                line.display_name = _("Each user's own")
            elif line.res_model in self.env and line.res_id:
                line.display_name = names[line.res_model].get(line.res_id, _("Record (not readable by you)"))
            else:
                line.display_name = False

    @api.model
    def _filters(self, kind, ids):
        """ {model: domain string} restricting the models of ``kind`` to ``ids``. Journals also take the companies'
        exchange difference and cash basis journals (Odoo posts to them as the user), not the deferral ones. Rules are
        cached: a change of those journals shows at the next clearing of the 'default' cache. """
        result = {}
        if kind == 'journal':
            companies = self.env['res.company'].sudo().search([])
            ids = set(ids).union(*(
                companies.mapped(name).ids for name in COMPANY_JOURNAL_FIELDS if name in companies._fields))
        ids = sorted(ids)
        for model_name, template in ALLOWED_KINDS[kind][2].items():
            if model_name not in self.env:
                continue
            model = self.env[model_name]
            # a filter on a field the installed version lacks is left out, not breaking the model's access checks
            leaves = ast.literal_eval(template.format(ids=[]))
            if all(leaf[0].split('.')[0] in model._fields for leaf in leaves if isinstance(leaf, tuple)):
                result[model_name] = template.format(ids=ids)
        return result
