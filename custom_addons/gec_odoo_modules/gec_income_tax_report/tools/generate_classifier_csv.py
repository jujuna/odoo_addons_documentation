"""Regenerate the classifier CSVs and the res.country codes from an rs.ge Form 30 classifier workbook.

Usage: python3 tools/generate_classifier_csv.py 30_data_<version>_<period>.xlsx data/

Sheets expected: კატეგორია, განაცემის სახე, ქვეყნები, განაკვეთები (version 7, period 202505).
The category usage columns are kept from the existing rs.form30.category.csv in the output folder.
Income types and rate rules whose validity ended before the current month are not written.
"""
import ast
import csv
import re
import sys
from datetime import date
from pathlib import Path

import openpyxl

# ISO 3166-1 alpha-2 -> numeric table shipped by the core payment module; read at generation time only.
ISO_TABLE = Path(__file__).resolve().parents[4] / 'addons' / 'payment' / 'const.py'
COUNTRY_XMLID_EXCEPTIONS = {'GB': 'uk'}

TYPE_VALIDITY = {'18': ('', 202411), '22': (202201, ''), '23': (202401, ''), '24': (202505, '')}
# (category id, type id, rate): (valid_from, valid_to) for cells whose note mixes several rates.
OVERRIDES = {
    ('4', '1', 5.0): (202011, ''),
    ('4', '1', 12.0): (202412, ''),
    ('34', '1', 5.0): (202011, ''),
    ('30', '22', 2.0): (202201, 202312),
    ('30', '22', 5.0): (202401, ''),
    ('30', '23', 5.0): (202401, ''),
    ('29', '24', 5.0): (202505, ''),
    ('40', '6', 3.0): (202301, ''),
    ('41', '6', 5.0): (202301, ''),
    ('42', '22', 0.0): (202412, ''),
}
# rs.ge category ids of enterprises and organizations; their rows feed main-part cells 40 to 56.
ORGANIZATION_CATEGORIES = {'2', '31', '33', '38', '39'}
USAGE_COLUMNS = ['use_salary', 'use_entry', 'use_bill', 'usage_note']


def country_xmlids():
    """{ISO numeric code: base.<alpha2>} so rs.ge codes resolve to res.country records."""
    if not ISO_TABLE.exists():
        print('WARNING: %s not found, only Georgia is mapped' % ISO_TABLE)
        return {'268': 'base.ge'}
    source = ISO_TABLE.read_text(encoding='utf-8')
    start = source.index('COUNTRY_NUMERIC_CODES = ') + len('COUNTRY_NUMERIC_CODES = ')
    table = ast.literal_eval(source[start:source.index('\n}', start) + 2])
    return {numeric: 'base.' + COUNTRY_XMLID_EXCEPTIONS.get(alpha2, alpha2.lower()) for alpha2, numeric in table.items()}


def category_usage(path):
    """Return {category xmlid: usage column values} from the existing category CSV, which a regeneration keeps."""
    if not Path(path).exists():
        return {}
    with open(path, newline='', encoding='utf-8') as handle:
        return {row['id']: [row.get(column) or '' for column in USAGE_COLUMNS] for row in csv.DictReader(handle)}


def rows(workbook, sheet):
    return [r for r in workbook[sheet].iter_rows(min_row=2, values_only=True) if r[0] is not None]


def write(path, header, data):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        writer.writerows(data)
    print(path, len(data), 'rows')


def previous_month(period):
    year, month = divmod(period, 100)
    return year * 100 + month - 1 if month > 1 else (year - 1) * 100 + 12


def validity(note):
    """(valid_from, valid_to) from a dated rs.ge note, empty strings when undated."""
    found = re.search(r'(\d{6})', note)
    if not found:
        return '', ''
    if 'გაუქმდა' in note:
        return '', previous_month(int(found.group(1)))
    if 'ძალაშია' in note:
        return int(found.group(1)), ''
    return '', ''


def expired(valid_to):
    return bool(valid_to) and int(valid_to) < int(date.today().strftime('%Y%m'))


def main(xlsx, out):
    workbook = openpyxl.load_workbook(xlsx, data_only=True)

    usage = category_usage(f'{out}/rs.form30.category.csv')
    categories = []
    for sequence, (code, name) in enumerate(rows(workbook, 'კატეგორია'), 1):
        match = re.match(r'^\s*([\d._]+)\s*[:.]\s*(.*?)\s*$', str(name))
        display, label = (match.group(1), match.group(2)) if match else ('', str(name).strip())
        categories.append([f'category_{code}', str(code), display, label, sequence * 10, int(str(code) in ORGANIZATION_CATEGORIES),
            *usage.get(f'category_{code}', ['0', '0', '0', ''])])
    write(f'{out}/rs.form30.category.csv', ['id', 'code', 'display_code', 'name', 'sequence', 'is_organization', *USAGE_COLUMNS], categories)

    types = []
    for sequence, row in enumerate(rows(workbook, 'განაცემის სახე'), 1):
        code, name = str(row[0]), str(row[1]).strip()
        valid_from, valid_to = TYPE_VALIDITY.get(code, ('', ''))
        if expired(valid_to):
            continue
        types.append([f'income_type_{code}', code, name, sequence * 10, valid_from, valid_to])
    write(f'{out}/rs.form30.income.type.csv', ['id', 'code', 'name', 'sequence', 'valid_from', 'valid_to'], types)

    countries, unmapped = [], []
    xmlids = country_xmlids()
    for code, name in rows(workbook, 'ქვეყნები'):
        code = str(code).strip()
        code = code.zfill(3) if code.isdigit() else code
        if code in xmlids:
            countries.append([xmlids[code], code])
        else:
            unmapped.append(f'{code} {str(name).strip()}')
    print('rs.ge codes without an Odoo country, not written:', '; '.join(unmapped))
    write(f'{out}/res.country.csv', ['id', 'rs_form30_code'], countries)

    type_ids = {income_type[0] for income_type in types}
    rules = []
    for row in rows(workbook, 'განაკვეთები'):
        category, income_type, rates, note = str(row[0]), str(row[2]), str(row[4]), (row[5] or '').strip()
        for token in rates.replace(' ', '').split(';'):
            if not token:
                continue
            rate = float(token)
            valid_from, valid_to = OVERRIDES.get((category, income_type, rate)) or validity(note)
            if expired(valid_to) or f'income_type_{income_type}' not in type_ids:
                continue
            rules.append([f'rate_rule_{category}_{income_type}_{int(rate)}', f'category_{category}',
                          f'income_type_{income_type}', f'{rate:g}', valid_from, valid_to, note])
    ids = [rule[0] for rule in rules]
    assert len(ids) == len(set(ids)), 'duplicate rule ids'
    write(f'{out}/rs.form30.rate.rule.csv', ['id', 'category_id:id', 'income_type_id:id', 'rate', 'valid_from', 'valid_to', 'note'], rules)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2].rstrip('/'))
