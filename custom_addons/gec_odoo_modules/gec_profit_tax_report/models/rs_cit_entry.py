from odoo import _, api, fields, models


class RsCitEntry(models.Model):
    """One value the accountant types on rs.ge, with an Entered tick: the checklist of the rs.ge Entry screen.
    Rows are rebuilt from the declaration each time the screen opens; see rs.cit.declaration._rs_entry_sync()."""
    _name = 'rs.cit.entry'
    _description = 'rs.ge Profit Tax Entry Checklist Row'
    _order = 'sequence, id'

    declaration_id = fields.Many2one('rs.cit.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True, index=True)
    key = fields.Char(required=True, readonly=True, help="Which value of the declaration this row holds.")
    sequence = fields.Integer(readonly=True)
    section = fields.Char(readonly=True, help="Part or annex of the rs.ge form.")
    code = fields.Char(string='Line', readonly=True)
    name = fields.Char(string='Description', readonly=True)
    value = fields.Char(readonly=True, help="The value as rs.ge takes it: amounts with a dot and no thousands separator.")
    entered = fields.Boolean(string='Entered on rs.ge', help="Ticked by the accountant once this value is typed on rs.ge.")

    _declaration_key_uniq = models.Constraint(
        'UNIQUE(declaration_id, key)', 'Each value appears once per declaration.')


class RsCitDeclaration(models.Model):
    _inherit = 'rs.cit.declaration'

    rs_entry_ids = fields.One2many('rs.cit.entry', 'declaration_id', string='rs.ge Entry Rows', readonly=True)
    rs_entry_progress = fields.Char(string='Entered on rs.ge', compute='_compute_rs_entry_progress',
                                    help="Values ticked as entered on rs.ge, out of the values to type there.")

    @api.depends('rs_entry_ids.entered')
    def _compute_rs_entry_progress(self):
        for declaration in self:
            entries = declaration.rs_entry_ids
            declaration.rs_entry_progress = (
                f"{len(entries.filtered('entered'))} / {len(entries)}" if entries else False)

    def _rs_entry_values(self):
        """Every value typed on rs.ge, in form order, as (key, section, code, description, value). Values rs.ge
        works out itself (totals, tax, formula lines of the annexes) and empty or zero values are left out."""
        self.ensure_one()
        rows = []
        money = lambda amount: f'{amount:.2f}' if amount else False
        date = lambda value: value.strftime('%d.%m.%Y') if value else False

        def add(key, section, code, name, value):
            if value:
                rows.append((key, section, code, name, value))

        def label(record, fname):
            return dict(record._fields[fname]._description_selection(self.env)).get(record[fname], False)

        part1 = "ნაწილი I"
        add('p1_status', part1, '6', "საწარმოს სტატუსი", label(self, 'company_status'))

        part3 = "ნაწილი III"
        for line in self.line_ids.filtered(lambda l: l.kind != 'calc'):
            add(f'p3_{line.code}', part3, line.code, line.name, money(line.amount))
            add(f'p3_{line.code}_col3', part3, f"{line.code} (სვეტი 3)", line.name, money(line.amount3))

        for n in range(1, 6):
            add(f'p4_{n}', "ნაწილი IV", str(n), self._fields[f'g{n}'].help, money(self[f'g{n}']))

        for annex, prefix in (("დანართი 1", 'a1'), ("დანართი 1.3", 'a13')):
            for n in range(1, 5):
                add(f'{prefix}_{n}', annex, str(n), f"სტრიქონი {n}", money(self[f'{prefix}_{n}']))

        for annex, prefix, lines, cols in (("დანართი 1.1", 'a11', self.annex11_line_ids, ("25.1", "16.1.1")),
                                           ("დანართი 1.4", 'a14', self.annex14_line_ids, ("25.3", "16.1.2"))):
            for i, line in enumerate(lines, 1):
                add(f'{prefix}_l{line.id}_period', f"{annex}, ნაწილი I", str(i), "თვე/წელი", line.name)
                add(f'{prefix}_l{line.id}_1', f"{annex}, ნაწილი I", str(i), f"სტრიქონი {cols[0]}", money(line.amount1))
                add(f'{prefix}_l{line.id}_2', f"{annex}, ნაწილი I", str(i), f"სტრიქონი {cols[1]}", money(line.amount2))
            for n in range(1, 5):
                add(f'{prefix}_{n}', f"{annex}, ნაწილი II", str(n), f"სტრიქონი {n}", money(self[f'{prefix}_{n}']))
            add(f'{prefix}_extra', f"{annex}, ნაწილი III", '', "ჩასათვლელი თანხა", money(self[f'{prefix}_extra']))

        for i, recovery in enumerate(self.recovery_ids, 1):
            add(f'a12_r{recovery.id}_period', "დანართი 1.2", str(i), "დაბეგვრის პერიოდი", recovery.taxed_period)
            add(f'a12_r{recovery.id}_code', "დანართი 1.2", str(i), "დაბეგრილი სტრიქონი", recovery.taxed_code)
            add(f'a12_r{recovery.id}_amount', "დანართი 1.2", str(i), "თანხა", money(recovery.amount))

        for i, line in enumerate(self.annex15_line_ids, 1):
            add(f'a15_l{line.id}_name', "დანართი 1.5", str(i), "საგადასახადო მოთხოვნის ნომერი", line.name)
            add(f'a15_l{line.id}_date', "დანართი 1.5", str(i), "თარიღი", date(line.date))
            add(f'a15_l{line.id}_amount', "დანართი 1.5", str(i), "თანხა", money(line.amount1))

        for i, line in enumerate(self.annex16_line_ids, 1):
            add(f'a16_l{line.id}_year', "დანართი 1.6", str(i), "წელი", line.name)
            add(f'a16_l{line.id}_1', "დანართი 1.6", str(i), "წმინდა მოგება", money(line.amount1))
            add(f'a16_l{line.id}_2', "დანართი 1.6", str(i), "დივიდენდი", money(line.amount2))
            add(f'a16_l{line.id}_3', "დანართი 1.6", str(i), "ხარჯი საქართველოში", money(line.amount3))

        for n in range(1, 4):
            add(f'a17_{n}', "დანართი 1.7", str(n), f"სვეტი {n}", money(self[f'a17_{n}']))

        if self.is_march:
            add('a2_inventory', "დანართი 2", '1', "სასაქონლო-მატერიალური მარაგი წლის ბოლოს", money(self.a2_inventory))
            add('a2_fixed', "დანართი 2", '2', "ძირითადი საშუალებები წლის ბოლოს", money(self.a2_fixed))

        add('a3_none', "დანართი 3", '', "ინფორმაცია არ გაქვთ", self.annex3_none and "კი")
        for line in self.annex3_line_ids:
            for n in range(1, 7):
                add(f'a3_l{line.id}_{n}', "დანართი 3", line.name, f"სვეტი {n}", money(line[f'amount{n}']))

        for i, line in enumerate(self.annex4_line_ids, 1):
            columns = [
                ("პირი", line.partner_id.name),
                ("საიდენტიფიკაციო ნომერი", line.partner_vat),
                ("რეზიდენტობა", line.partner_country_id.name),
                ("კავშირი", label(line, 'relation')),
                ("ოპერაცია", label(line, 'operation')),
                ("ვალუტა", line.operation_currency_id.name),
                ("მოცულობა ვალუტაში", money(line.amount1)),
                ("მოცულობა ლარში", money(line.amount2)),
                ("ნაშთი წლის ბოლოს, ვალუტაში", money(line.amount3)),
                ("ოპერაციის დაწყების თარიღი", date(line.date)),
                ("დოკუმენტაცია", label(line, 'documentation')),
            ]
            for n, (name, value) in enumerate(columns, 1):
                add(f'a4_l{line.id}_{n}', "დანართი 4", str(i), name, value)
        return rows

    def _rs_entry_sync(self):
        """Rebuild the checklist from the declaration. A row keeps its tick while its value stays the same; a
        changed value loses it, so the accountant checks it on rs.ge again. Runs as superuser so that read-only
        accounting users can open the screen too: it only touches this declaration's checklist rows."""
        self.ensure_one()
        Entry = self.env['rs.cit.entry'].sudo()
        existing = {entry.key: entry for entry in self.sudo().rs_entry_ids}
        keep = Entry
        to_create = []
        for sequence, (key, section, code, name, value) in enumerate(self._rs_entry_values()):
            vals = {'sequence': sequence, 'section': section, 'code': code, 'name': name, 'value': value}
            entry = existing.get(key)
            if not entry:
                to_create.append(dict(vals, declaration_id=self.id, key=key))
                continue
            if entry.value != value:
                vals['entered'] = False
            entry.write(vals)
            keep |= entry
        (Entry.browse([e.id for e in existing.values()]) - keep).unlink()
        Entry.create(to_create)

    def action_open_rs_entry(self):
        """Open the values to type on rs.ge, in form order, each with a copy button and an Entered tick."""
        self.ensure_one()
        self._rs_entry_sync()
        return {
            'type': 'ir.actions.act_window',
            'name': _('rs.ge Entry: %s', self.period_label),
            'res_model': 'rs.cit.entry',
            'view_mode': 'list',
            'views': [(self.env.ref('gec_profit_tax_report.rs_cit_entry_view_list').id, 'list')],
            'domain': [('declaration_id', '=', self.id)],
            'context': {'create': False, 'delete': False},
        }
