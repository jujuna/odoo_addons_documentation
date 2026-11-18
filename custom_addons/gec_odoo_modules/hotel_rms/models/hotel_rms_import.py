import csv
import io
import math
import re
from collections import defaultdict
from datetime import date, datetime

from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools.misc import format_date
from odoo.tools.translate import _lt

REQUIRED_COLUMNS = {'reservations': ('reference', 'booked_on', 'arrival', 'departure', 'room_type'), 'rates': ('date', 'room_type', 'price')}
PREVIEW_COLUMNS = {
    'reservations': {
        'source_ref': _lt("Reference"),
        'booking_date': _lt("Booked on"),
        'arrival': _lt("Arrival"),
        'departure': _lt("Departure"),
        'room_type_id': _lt("Room type"),
        'rooms': _lt("Rooms"),
        'revenue': _lt("Revenue"),
        'status': _lt("Status"),
        'channel': _lt("Channel"),
    },
    'rates': {'stay_date': _lt("Night"), 'room_type_id': _lt("Room type"), 'price': _lt("Price")},
}
RESERVATION_FIELDS = ('source_ref', 'booking_date', 'arrival', 'departure', 'room_type_id', 'rooms', 'revenue', 'status', 'cancel_date', 'channel')
PREVIEW_ROWS = 10
DATE_FORMATS = ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d.%m.%Y', '%d/%m/%Y')
SLASH_FORMAT = '%d/%m/%Y'
STATUSES = {'': 'confirmed', 'confirmed': 'confirmed', 'cancelled': 'cancelled', 'canceled': 'cancelled', 'no_show': 'no_show', 'no-show': 'no_show'}
XLSX_MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
CSV_MIMETYPES = ('text/csv', 'text/plain')
CSV_EXTENSIONS = ('.csv', '.txt')
THOUSANDS_COMMA = re.compile(r'^\d{1,3}(,\d{3})+$')


class AmbiguousDate(ValueError):
    pass


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(str(value).strip(), date_format).date()
        except ValueError:
            continue
        if date_format == SLASH_FORMAT and parsed.day <= 12 and parsed.day != parsed.month:
            raise AmbiguousDate(value)
        return parsed
    raise ValueError(value)


def _parse_number(value, comma_decimal):
    """comma_decimal is True for ';' CSV files, where a comma is the decimal separator."""
    if isinstance(value, int | float):
        return float(value)
    text = re.sub(r'\s', '', str(value))
    if comma_decimal and ',' in text:
        text = text.replace('.', '')
    number = float(text.replace(',', '.'))
    if not math.isfinite(number):
        raise ValueError(value)
    return number


class HotelRmsImport(models.Model):
    _name = 'hotel.rms.import'
    _description = "Data Import"
    _order = 'id desc'
    _rec_name = 'filename'
    _check_company_auto = True

    property_id = fields.Many2one('hotel.rms.property', string="Hotel", required=True, ondelete='cascade',
                                  check_company=True, help="The hotel the file is for.")
    company_id = fields.Many2one(related='property_id.company_id', store=True, index=True)
    kind = fields.Selection([('reservations', "Bookings"), ('rates', "Current prices")], string="Type", required=True, default='reservations',
        help="Bookings: your reservations. Current prices: the prices that are live now.")
    file = fields.Binary(string="File", copy=False, help="A CSV or Excel (.xlsx) file; use the template below.")
    filename = fields.Char(copy=False, help="The name of the uploaded file.")
    state = fields.Selection([('draft', "Draft"), ('done', "Done"), ('failed', "Failed")], default='draft', required=True, copy=False,
        help="Draft: not imported yet. Done: imported. Failed: nothing was imported, see the errors.")
    created = fields.Integer(readonly=True, copy=False, help="Rows added.")
    updated = fields.Integer(readonly=True, copy=False, help="Rows that existed and were changed.")
    kept = fields.Integer(readonly=True, copy=False, help="Prices left as they are because they are waiting to be published.")
    error_count = fields.Integer(string="Errors", readonly=True, copy=False, help="Rows of the file with a problem.")
    errors = fields.Text(string="Error Details", readonly=True, copy=False, help="Every problem found in the file, with its row number.")
    preview_html = fields.Html(string="Preview", readonly=True, copy=False, sanitize=False,
                               help="The first rows of the file as they will be imported.")
    user_id = fields.Many2one('res.users', string="Imported By", default=lambda self: self.env.user,
                              ondelete='set null', readonly=True, help="Who made this import.")
    date = fields.Datetime(default=fields.Datetime.now, readonly=True, help="When the import was made.")

    @api.depends('filename', 'kind', 'date')
    def _compute_display_name(self):
        kinds = dict(self._fields['kind']._description_selection(self.env))
        for record in self:
            record.display_name = record.filename or self.env._(
                "%(kind)s of %(date)s", kind=kinds[record.kind], date=format_date(self.env, record.date))

    @api.onchange('property_id', 'kind', 'file')
    def _onchange_file(self):
        self.preview_html = self.errors = False
        self.error_count = 0
        if self.state == 'failed':
            self.state = 'draft'

    def _read_rows(self):
        """Returns (header, rows, comma_decimal); a row is (row number, dict by lower-case header)."""
        mimetype = self.file.mimetype
        comma_decimal = False
        if mimetype == XLSX_MIMETYPE:
            import openpyxl  # noqa: PLC0415
            workbook = openpyxl.load_workbook(self.file.open(), data_only=True, read_only=True)
            raw = [list(row) for row in workbook.active.iter_rows(values_only=True)]
        elif mimetype in CSV_MIMETYPES or (self.filename or '').lower().endswith(CSV_EXTENSIONS):
            try:
                text = self.file.content.decode('utf-8-sig')
            except UnicodeDecodeError:
                raise ValueError(self.env._("Save the file as UTF-8 CSV.")) from None
            first_line = text.splitlines()[0] if text else ''
            delimiter = ',' if first_line.count(',') >= first_line.count(';') else ';'
            comma_decimal = delimiter == ';'
            try:
                raw = list(csv.reader(io.StringIO(text), delimiter=delimiter))
            except csv.Error as exc:
                raise ValueError(self.env._("The CSV file could not be read: %s", exc)) from None
        else:
            raise ValueError(self.env._("The file must be a CSV or XLSX file (save it as CSV or Excel .xlsx)."))
        header = [str(cell or '').strip().lower() for cell in raw[0]] if raw else []
        rows = [(number, dict(zip(header, row))) for number, row in enumerate(raw[1:], start=2) if any(cell not in (None, '') for cell in row)]
        return header, rows, comma_decimal

    def _check_file(self):
        """Writes nothing; returns (parsed rows, error messages)."""
        self.ensure_one()
        try:
            header, rows, comma_decimal = self._read_rows()
        except ValueError as exc:
            return [], [str(exc)]
        errors = [self.env._("Missing column: %s", column) for column in REQUIRED_COLUMNS[self.kind] if column not in header]
        records = []
        if not errors:
            room_types = self.property_id.with_context(active_test=self.kind != 'reservations').room_type_ids
            by_code, by_name = {}, {}
            for room_type in sorted(room_types, key=lambda rt: rt.active):
                by_name[room_type.name] = room_type
                if room_type.code:
                    by_code[room_type.code] = room_type
            for number, row in rows:
                try:
                    records.append(self._check_row(row, by_code, by_name, comma_decimal))
                except ValueError as exc:
                    errors.append(self.env._("Row %(number)s: %(error)s", number=number, error=exc))
        return records, errors

    def _check_row(self, row, by_code, by_name, comma_decimal):
        """Values of one file row, or ValueError with what to fix."""
        def cell(name):
            value = row.get(name)
            return '' if value is None else value

        def date_cell(name):
            if cell(name) == '':
                raise ValueError(self.env._("%s is required", name))
            try:
                return _parse_date(cell(name))
            except AmbiguousDate:
                raise ValueError(
                    self.env._("%(name)s %(value)s can be read as two dates: write it as YYYY-MM-DD", name=name, value=cell(name))) from None
            except ValueError:
                raise ValueError(self.env._("%s is not a date", name)) from None

        def number_cell(name, default=None):
            value = cell(name)
            if value == '':
                if default is None:
                    raise ValueError(self.env._("%s is required", name))
                return default
            if isinstance(value, str) and not comma_decimal and THOUSANDS_COMMA.match(value.strip()):
                raise ValueError(self.env._("Use a dot for decimals, without thousands separators: %s", value.strip().replace(',', '')))
            try:
                return _parse_number(value, comma_decimal)
            except ValueError:
                raise ValueError(self.env._("%s is not a number", name)) from None

        room_type = by_code.get(str(cell('room_type')).strip()) or by_name.get(str(cell('room_type')).strip())
        if not room_type:
            raise ValueError(self.env._("room_type %s is unknown", cell('room_type')))
        currency = self.property_id.currency_id
        if self.kind == 'rates':
            return {'stay_date': date_cell('date'), 'room_type_id': room_type.id, 'price': currency.round(number_cell('price'))}
        arrival, departure = date_cell('arrival'), date_cell('departure')
        if departure <= arrival:
            raise ValueError(self.env._("departure must be after arrival"))
        status = STATUSES.get(str(cell('status')).strip().lower())
        if status is None:
            raise ValueError(self.env._("status %s is unknown", cell('status')))
        if not str(cell('reference')).strip():
            raise ValueError(self.env._("reference is required"))
        return {
            'source_ref': str(cell('reference')).strip(),
            'booking_date': date_cell('booked_on'),
            'arrival': arrival,
            'departure': departure,
            'room_type_id': room_type.id,
            'rooms': int(number_cell('rooms', default=1)),
            'revenue': currency.round(number_cell('revenue', default=0)),
            'status': status,
            'cancel_date': date_cell('cancelled_on') if cell('cancelled_on') != '' else False,
            'channel': str(cell('channel')).strip() or False,
        }

    def _get_preview(self, records, errors):
        if not records:
            return False if errors else Markup("<p class=\"text-muted\">%s</p>") % self.env._("The file has no rows to import.")
        room_types = {room_type.id: room_type.name for room_type in self.property_id.with_context(active_test=False).room_type_ids}

        statuses = dict(self.env['hotel.rms.reservation']._fields['status']._description_selection(self.env))

        def shown(record, key):
            value = record[key]
            if key == 'room_type_id':
                return room_types[value]
            if key == 'status':
                return statuses[value]
            if isinstance(value, date):
                return format_date(self.env, value)
            return '' if value is False else value

        columns = PREVIEW_COLUMNS[self.kind].items()
        head = Markup("").join(Markup("<th>%s</th>") % self.env._(label) for _key, label in columns)
        body = Markup("").join(
            Markup("<tr>%s</tr>") % Markup("").join(Markup("<td>%s</td>") % shown(record, key) for key, _label in columns)
            for record in records[:PREVIEW_ROWS])
        return Markup(
            "<p class=\"text-muted\">%s</p><div class=\"table-responsive\">"
            "<table class=\"table table-sm table-striped mb-0\"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>"
        ) % (self.env._("The first %(shown)s of %(total)s rows:", shown=min(PREVIEW_ROWS, len(records)),
                        total=len(records)), head, body)

    def action_check(self):
        """Stores the preview and row errors on the import; no booking or price is written."""
        self.ensure_one()
        records, errors = self._check_file()
        self.write({
            'preview_html': self._get_preview(records, errors),
            'errors': "\n".join(errors) or False,
            'error_count': len(errors),
        })

    def action_import(self):
        """All or nothing: with one row error no booking or price is written."""
        self.ensure_one()
        records, errors = self._check_file()
        values = {'preview_html': self._get_preview(records, errors), 'errors': "\n".join(errors) or False, 'error_count': len(errors)}
        if errors:
            self.write(dict(values, state='failed', created=0, updated=0, kept=0))
            return
        created, updated, kept = (self._write_reservations if self.kind == 'reservations' else self._write_rates)(records)
        self.write(dict(values, state='done', created=created, updated=updated, kept=kept))
        if self.kind == 'reservations':
            self.property_id.last_data_at = fields.Datetime.now()
        self.property_id._run_engine()

    def _write_reservations(self, records):
        """Returns (created, updated, kept); kept is always 0 for reservations."""
        Reservation = self.env['hotel.rms.reservation']
        by_ref = {record['source_ref']: record for record in records}
        existing = Reservation.search_fetch([('property_id', '=', self.property_id.id), ('source_ref', 'in', list(by_ref))], RESERVATION_FIELDS)
        updates = defaultdict(list)
        for res in existing:
            vals = by_ref[res.source_ref]
            current = res._convert_to_write({name: res[name] for name in vals})
            changed = {name: value for name, value in vals.items() if current[name] != value}
            if changed:
                updates[frozenset(changed.items())].append(res.id)
        for changed, ids in updates.items():
            Reservation.browse(ids).write(dict(changed))
        known = set(existing.mapped('source_ref'))
        created = Reservation.create([dict(record, property_id=self.property_id.id) for ref, record in by_ref.items() if ref not in known])
        return len(created), sum(len(ids) for ids in updates.values()), 0

    def _write_rates(self, records):
        """Prices waiting to be published are kept; returns (created, updated, kept)."""
        Price = self.env['hotel.rms.price']
        currency = self.property_id.currency_id
        by_key = {(record['stay_date'], record['room_type_id']): record['price'] for record in records}
        existing = {(price.stay_date, price.room_type_id.id): price for price in Price.search_fetch([
            ('property_id', '=', self.property_id.id),
            ('stay_date', 'in', [key[0] for key in by_key]),
        ], ['stay_date', 'room_type_id', 'published_rate', 'to_export'])}
        old_rates = {}
        updates = defaultdict(list)
        kept = 0
        for key, price in existing.items():
            if key not in by_key:
                continue
            if price.to_export:
                kept += 1
            elif currency.compare_amounts(price.published_rate, by_key[key]):
                old_rates[price.id] = price.published_rate
                updates[by_key[key]].append(price.id)
        for rate, ids in updates.items():
            Price.browse(ids).write({'published_rate': rate, 'exported_rate': rate})
        new = Price.create([{
            'property_id': self.property_id.id,
            'stay_date': key[0],
            'room_type_id': key[1],
            'published_rate': rate,
            'exported_rate': rate,
            'state': 'hold',
        } for key, rate in by_key.items() if key not in existing])
        (new + Price.browse(old_rates))._log_audit('import', old_rates)
        return len(new), len(old_rates), kept
