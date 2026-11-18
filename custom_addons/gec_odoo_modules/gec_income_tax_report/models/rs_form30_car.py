from odoo import api, fields, models

from .rs_form30_declaration import _number, _refuse_exported_rows

HEADERS = ['რეგისტრაციის ნომერი(სახელმწიფო სანომრე ნიშანი)', 'ძრავის მოცულობა', 'გვარი,სახელი', 'პირადი ნომერი', 'გადასახადის ოდენობა']


class RsForm30CarLine(models.Model):
    _name = 'rs.form30.car.line'
    _description = 'rs.ge Form 30 Private Car Use Line'
    _order = 'license_plate, id'
    _check_company_auto = True

    declaration_id = fields.Many2one('rs.form30.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', ondelete='set null', check_company=True)
    license_plate = fields.Char(string='Registration Number')
    engine_id = fields.Many2one('rs.form30.car.engine', string='Engine Volume', required=True, ondelete='restrict')
    employee_id = fields.Many2one('hr.employee', string='Employee', ondelete='set null', check_company=True)
    name = fields.Char(string='Surname, Name')
    identification = fields.Char(string='Personal Number')
    amount = fields.Float(string='Tax Amount', compute='_compute_amount', store=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        _refuse_exported_rows(lines)
        return lines

    def write(self, vals):
        _refuse_exported_rows(self)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_exported(self):
        _refuse_exported_rows(self)

    @api.depends('engine_id')
    def _compute_amount(self):
        for line in self:
            line.amount = line.engine_id.amount

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        vehicle = self.vehicle_id
        if not vehicle:
            return
        self.license_plate = vehicle.license_plate
        if vehicle.rs_form30_engine_id:
            self.engine_id = vehicle.rs_form30_engine_id
        if vehicle.driver_employee_id:
            self.employee_id = vehicle.driver_employee_id

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        employee = self.employee_id
        if not employee or employee.company_id != self.company_id:
            return
        Line = self.env['rs.form30.line']
        # sudo: the accountant filing the declaration has no HR access
        employee = employee.sudo()
        first, last = Line._split_name(employee.legal_name or employee.name, False)
        self.name = ','.join(filter(None, [last, first]))
        self.identification = Line._clean_identification(employee.identification_id)

    @api.model
    def _rs_form30_headers(self):
        return HEADERS

    def _export_values(self):
        self.ensure_one()
        return [self.license_plate or '', self.engine_id.code or '', self.name or '', self.identification or '', _number(self.amount)]
