from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EmployeeRegistryRsBrowser(models.TransientModel):
    _name = 'employee.registry.rs.browser'
    _description = 'RS Employee Registry Browser'

    filter_tin = fields.Char(string='TIN')
    filter_fullname = fields.Char(string='Full Name')
    filter_status = fields.Selection([('1', 'Active'), ('0', 'Terminated'), ('-1', 'Suspended')], string='Status')
    filter_citizenship = fields.Char(string='Citizenship',
        help="Georgian country name (e.g. 'საქართველო', 'ავსტრალია'). Comma-separate for multiple.")
    filter_max_rows = fields.Integer(string='Max Rows', default=100)
    line_ids = fields.One2many('employee.registry.rs.browser.line', 'browser_id', string='Results', readonly=True)
    total_count = fields.Integer(string='Total in RS', readonly=True,
        help="Total number of records matching the filter on the RS side (may exceed Max Rows).")
    has_results = fields.Boolean(compute='_compute_has_results')

    @api.depends('line_ids')
    def _compute_has_results(self):
        for rec in self:
            rec.has_results = bool(rec.line_ids)

    def action_search(self):
        self.ensure_one()
        filters = {}
        if self.filter_tin:
            filters['TIN'] = self.filter_tin.strip()
        if self.filter_fullname:
            filters['FULLNAME'] = self.filter_fullname.strip()
        if self.filter_status:
            filters['STATUS'] = self.filter_status
        if self.filter_citizenship:
            filters['CITIZENSHIP'] = self.filter_citizenship.strip()
        if self.filter_max_rows:
            filters['MAXIMUM_ROWS'] = self.filter_max_rows

        self.line_ids.unlink()

        data = self.env['employee.registry.rs.service'].list_employees(filters)
        inner = data.get('Data') or {}
        fields_list = inner.get('Fields') or []
        rows = inner.get('Rows') or []
        summary = data.get('Summary') or {}
        self.total_count = int(summary.get('_Count') or 0)

        idx = {name: i for i, name in enumerate(fields_list)}

        def get(row, name):
            i = idx.get(name)
            if i is None or i >= len(row):
                return None
            return row[i]

        vals_list = []
        for row in rows:
            vals_list.append({
                'browser_id': self.id,
                'rs_id': int(get(row, 'ID') or 0),
                'tin': get(row, 'TIN') or '',
                'fullname': get(row, 'FULLNAME') or '',
                'phone': get(row, 'PHONE') or '',
                'status': str(int(get(row, 'STATUS') or 0)),
                'status_txt': get(row, 'STATUS_TXT') or '',
                'citizenship': get(row, 'CITIZENSHIP') or '',
                'is_foreigner': bool(get(row, 'IS_FOREIGNER')),
                'gender_txt': get(row, 'GENDER_TXT') or '',
                'birth_date': get(row, 'BIRTH_DATE') or '',
                'work_type_txt': get(row, 'WORK_TYPE_TXT') or '',
                'create_date_rs': get(row, 'CREATE_DATE') or '',
                'last_change_date': get(row, 'LAST_CHANGE_DATE') or '',
            })
        if vals_list:
            self.env['employee.registry.rs.browser.line'].create(vals_list)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'employee.registry.rs.browser',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context),
        }


class EmployeeRegistryRsBrowserLine(models.TransientModel):
    _name = 'employee.registry.rs.browser.line'
    _description = 'RS Employee Registry Browser — Row'
    _order = 'id asc'

    browser_id = fields.Many2one('employee.registry.rs.browser', required=True, ondelete='cascade')
    rs_id = fields.Integer(string='RS ID')
    tin = fields.Char(string='TIN')
    fullname = fields.Char(string='Full Name')
    phone = fields.Char(string='Phone')
    status = fields.Selection([('1', 'Active'), ('0', 'Terminated'), ('-1', 'Suspended')], string='Status')
    status_txt = fields.Char(string='Status (GE)')
    citizenship = fields.Char(string='Citizenship')
    is_foreigner = fields.Boolean(string='Foreigner')
    gender_txt = fields.Char(string='Gender')
    birth_date = fields.Char(string='Birth Date')
    work_type_txt = fields.Char(string='Work Type')
    create_date_rs = fields.Char(string='Created (RS)')
    last_change_date = fields.Char(string='Last Change')
    matching_employee_id = fields.Many2one('hr.employee', compute='_compute_matching_employee', string='Odoo Employee')
    in_odoo = fields.Boolean(compute='_compute_matching_employee', string='In Odoo')

    @api.depends_context('company')
    @api.depends('tin')
    def _compute_matching_employee(self):
        """Employee (archived included) with the row's TIN in the active company or its branches.
        Normal access rules apply, so a user never links an employee of a company they cannot use."""
        root_company = self.env.company.root_id
        for rec in self:
            if rec.tin:
                match = self.env['hr.employee'].with_context(active_test=False).search([
                    ('identification_id', '=', rec.tin),
                    ('company_id', 'child_of', root_company.id),
                ], limit=1)
            else:
                match = self.env['hr.employee']
            rec.matching_employee_id = match
            rec.in_odoo = bool(match)

    def action_open_in_odoo(self):
        self.ensure_one()
        if not self.matching_employee_id:
            raise UserError(_("No Odoo employee has identification_id = '%s'. Create the employee in Odoo first, or set their Identification ID to "
                "match the RS TIN.", self.tin))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'res_id': self.matching_employee_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_link_to_odoo(self):
        """Store this RS record's ID on the matching Odoo employee."""
        self.ensure_one()
        if not self.matching_employee_id:
            raise UserError(_("No matching Odoo employee to link."))
        self.matching_employee_id.write({'rs_registry_id': str(self.rs_id), 'rs_status': self.status})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("RS Employee Registry"),
                'message': _("Linked Odoo employee %(name)s ↔ RS id %(id)s.", name=self.matching_employee_id.display_name, id=self.rs_id),
                'sticky': False,
            },
        }
