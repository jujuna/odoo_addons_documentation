#!/usr/bin/env python3
"""Regenerate the rs.ge Form 15 classifier CSVs from the portal's own workbooks.

    python3 tools/generate_classifier_csv.py ~/Downloads/15_data_1.xlsx \
                                             ~/Downloads/15_data_5.xlsx

Sheets are read by position, not by name: rs.ge ships them with typos and stray
spaces ("ტერიტორი ულიერთეული(ქონება) ").
"""
import argparse
import csv
import os
import re

import openpyxl

# Part III types with an acquisition year and the art. 202(1) coefficient; the portal hides columns 5 and 7 otherwise.
IMMOVABLE_TYPE_CODES = {'14', '18', '19', '22'}

# Part III property types for which the portal asks for the object's name (column 2).
NAMED_TYPE_CODES = {'14', '17', '18', '19', '21', '22'}

# Group 5 of the rs.ge list: property leased out. ASSUMPTION, see the model help.
LEASING_TYPE_CODES = {'21', '22'}

# Only non-agricultural land is in square metres; its rate is a coefficient on the base rate, not an amount per hectare.
NON_AGRI_TYPE_CODE = '33'

# Land territorial units in the workbook that the portal never offers (Kobuleti municipality territory,
# Tbilisi villages as separate units, Tianeti under Shida Kartli). Kept archived so the rate table loads.
PORTAL_HIDDEN_LAND_TERRITORY_CODES = {
    '77831', '77833', '78172', '78581', '78615', '78616', '78617', '78618', '78619',
    '78620', '78621', '78622', '78623', '78624', '78625', '78626', '78627', '78629',
    '78630', '78631', '78632', '78634', '78635', '78636', '78637', '78638', '78639',
    '78640', '78641', '78642', '78645',
}

# Names the workbook spells differently from the portal's tree; the portal's spelling wins.
PORTAL_LAND_TERRITORY_NAMES = {
    '78556': '/ქვემო ქართლი/ბოლნისი/სოფლები და ბოლნისის მუნიციპალიტეტის სხვა ტერიტორია',
    '78711': ('/თბილისი/მთაწმინდა-კრწანისი/მთაწმინიდის რაიონი/"მთაწ,სოლოლაკის" უბნის საზღვრებში '
              'მოქცეული ტერიტორია",რომელიც იწყება კოჯრის გზატ-დან და გასდევს კოჯრის გზატ-ის '
              'ღერძულა ხაზს ოქროყანის განაშ-ის ჩრდ-აღმ. საზღ-მდე'),
}

# (territory, land type) -> rate where the workbook differs from the portal; the portal wins.
PORTAL_LAND_RATES = {
    ('78736', '33'): '1.3',
}

# Land types in the workbook that the portal never offers (კონტური). Kept archived so the rate table loads.
PORTAL_HIDDEN_LAND_TYPE_CODES = {'46'}
NON_AGRI_BASE_RATE = '0.24'


def rows(sheet, skip=1):
    for row in sheet.iter_rows(min_row=skip + 1, values_only=True):
        if row and row[0] not in (None, ''):
            yield row


def text(value):
    return ('' if value is None else str(value)).strip()


def write(path, header, records):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        writer.writerows(records)
    print('%-44s %5d rows' % (os.path.basename(path), len(records)))


def property_types(sheet):
    records = []
    for index, row in enumerate(rows(sheet)):
        code, label = text(row[0]), text(row[1]).rstrip('.;').strip()
        display_code = label.split(' ', 1)[0] if ' ' in label else ''
        records.append([
            'property_type_%s' % code, code, display_code, label,
            (index + 1) * 10, '1' if code in IMMOVABLE_TYPE_CODES else '0',
            '1' if code in NAMED_TYPE_CODES else '0',
            '1' if code in LEASING_TYPE_CODES else '0',
        ])
    return records


def territories(sheet):
    return [
        ['territory_%s' % text(row[0]), text(row[0]), text(row[1]), (index + 1) * 10]
        for index, row in enumerate(rows(sheet))
    ]


def exemption_bases(sheet):
    records = []
    for index, row in enumerate(rows(sheet)):
        code, label = text(row[0]), text(row[1])
        note = text(row[2]) if len(row) > 2 else ''
        years = [int(year) for year in re.findall(r'\b(?:19|20)\d{2}\b', note)]
        if not years:
            valid_from, valid_to = 0, 0
        elif 'მხოლოდ' in note:
            valid_from, valid_to = min(years), max(years)
        else:
            valid_from, valid_to = min(years), 0
        records.append([
            'exemption_%s' % code, code, label, (index + 1) * 10, valid_from, valid_to, note,
        ])
    return records


def land_territories(sheet):
    records = []
    for index, row in enumerate(rows(sheet)):
        code, label = text(row[0]), text(row[1])
        label = PORTAL_LAND_TERRITORY_NAMES.get(code, label)
        parts = [part.strip() for part in label.strip('/').split('/') if part.strip()]
        records.append([
            'land_territory_%s' % code, code, label,
            parts[0] if parts else '', parts[1] if len(parts) > 1 else '', (index + 1) * 10,
            '0' if code in PORTAL_HIDDEN_LAND_TERRITORY_CODES else '1',
        ])
    return records


def land_types(sheet):
    records = []
    for index, row in enumerate(rows(sheet)):
        code, label = text(row[0]), text(row[1])
        non_agri = code == NON_AGRI_TYPE_CODE
        records.append([
            'land_type_%s' % code, code, label, (index + 1) * 10,
            'sqm' if non_agri else 'ha', '1' if non_agri else '0',
            NON_AGRI_BASE_RATE if non_agri else '0',
            '0' if code in PORTAL_HIDDEN_LAND_TYPE_CODES else '1',
        ])
    return records


def land_rates(sheet):
    records = []
    for row in rows(sheet):
        territory, land_type = text(row[0]), text(row[1])
        rate = PORTAL_LAND_RATES.get((territory, land_type), text(row[2]))
        records.append([
            'land_rate_%s_%s' % (territory, land_type),
            'land_territory_%s' % territory, 'land_type_%s' % land_type, rate,
        ])
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('property_workbook', help='15_data_<n>.xlsx holding the part III sheets')
    parser.add_argument('land_workbook', help='15_data_<n>.xlsx holding the part IV sheets')
    parser.add_argument(
        '-o', '--output',
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    args = parser.parse_args()

    out = os.path.abspath(args.output)
    prop = openpyxl.load_workbook(args.property_workbook, data_only=True).worksheets
    land = openpyxl.load_workbook(args.land_workbook, data_only=True).worksheets
    print('part III sheets:', [sheet.title for sheet in prop])
    print('part IV  sheets:', [sheet.title for sheet in land])

    write(os.path.join(out, 'rs.form15.property.type.csv'),
          ['id', 'code', 'display_code', 'name', 'sequence', 'is_immovable', 'has_name',
           'is_leasing'],
          property_types(prop[0]))
    write(os.path.join(out, 'rs.form15.territory.csv'),
          ['id', 'code', 'name', 'sequence'], territories(prop[1]))
    write(os.path.join(out, 'rs.form15.exemption.basis.csv'),
          ['id', 'code', 'name', 'sequence', 'valid_from', 'valid_to', 'note'],
          exemption_bases(prop[2]))
    write(os.path.join(out, 'rs.form15.land.territory.csv'),
          ['id', 'code', 'name', 'region', 'municipality', 'sequence', 'active'],
          land_territories(land[0]))
    write(os.path.join(out, 'rs.form15.land.type.csv'),
          ['id', 'code', 'name', 'sequence', 'unit', 'uses_base_rate', 'base_rate', 'active'],
          land_types(land[1]))
    write(os.path.join(out, 'rs.form15.land.rate.csv'),
          ['id', 'land_territory_id:id', 'land_type_id:id', 'rate'], land_rates(land[2]))


if __name__ == '__main__':
    main()
