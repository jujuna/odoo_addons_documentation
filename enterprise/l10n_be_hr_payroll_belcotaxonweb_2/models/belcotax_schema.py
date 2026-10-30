# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import re
from datetime import date
from decimal import Decimal
from functools import cache, lru_cache

from odoo.tools import file_open

# The JSON schemas are published in the technical documentation of Belcotax-on-web:
# https://finances.belgium.be/fr/E-services/Belcotaxonweb/documentation-technique
# A new version is published every year for each fiche (urn:f:d:<income year>:<fiche>:<version>), the fr, nl
# and de variants being the same but for their titles. To support a new income year, add its fr fiche schemas
# in data/schemas/<income year> and list them below.
SCHEMAS_PATH = 'l10n_be_hr_payroll_belcotaxonweb_2/data/schemas'
FICHE_SCHEMA_FILES = {
    2025: [
        'fiche_2025_10_1203_fr.json',
        'fiche_2025_13_1203_fr.json',
        'fiche_2025_18_1203_fr.json',
        'fiche_2025_20_1203_fr.json',
        'fiche_2025_30_1203_fr.json',
        'fiche_2025_45_1203_fr.json',
    ],
}
RESOURCE_SCHEMA_FILES = [
    'delete-fiche.json',
    'resource_contact_fr.json',
    'resource_organisation_fr.json',
    'resource_person_fr.json',
]
DELETE_FICHE_SCHEMA = 'urn:f:x:1'
PERSON_SCHEMA = 'urn:r:d:p:1'
ORGANISATION_SCHEMA = 'urn:r:d:o:1'
CONTACT_SCHEMA = 'urn:r:d:c:1'


def _load(path):
    # Decimals, so that multipleOf can be checked exactly: 0.29 / 0.01 is 28.999... as a float
    with file_open(f'{SCHEMAS_PATH}/{path}') as schema_file:
        return json.load(schema_file, parse_float=Decimal)


def _base_id(schema):
    # 'urn:r:d:p:1:fr' -> 'urn:r:d:p:1'
    return re.sub(r':(fr|nl|de)$', '', schema['$id'])


@lru_cache
def get_fiche_schemas(year):
    """:return: {'281.10': schema, ...} for the income year, the last version of each fiche"""
    schemas = {}
    for file_name in FICHE_SCHEMA_FILES.get(year, []):
        schema = _load(f'{year}/{file_name}')
        _urn, _f, _d, _year, fiche, version = _base_id(schema).split(':')
        form = f'281.{fiche}'
        if form not in schemas or int(version) > int(schemas[form]['$id'].split(':')[5]):
            schemas[form] = schema
    return schemas


@cache
def get_resource_schemas():
    """:return: {'urn:r:d:p:1': schema, ...} for the resources and the deletions, which don't depend on the year"""
    return {_base_id(schema): schema for schema in (_load(f'resources/{file_name}') for file_name in RESOURCE_SCHEMA_FILES)}


def get_schema_id(schema):
    return _base_id(schema)


def validate(schema, instance):
    """Validate the instance against the subset of JSON Schema 2020-12 used by the Belcotax-on-web schemas.

    The numbers of the instance must be Decimal or int, as parsed by json.loads(..., parse_float=Decimal).

    :return: list of error messages
    """
    errors = []
    _validate(schema, instance, '', errors, schema)
    return errors


def _is_valid(schema, instance, root):
    errors = []
    _validate(schema, instance, '', errors, root)
    return not errors


def _validate(schema, instance, path, errors, root):
    if schema is True:
        return
    if '$ref' in schema:
        # Only local references to $defs are used
        schema = root['$defs'][schema['$ref'].split('/')[-1]]
    name = path or '/'

    expected_type = schema.get('type')
    if expected_type and not _has_type(instance, expected_type):
        errors.append(f"{name}: {instance!r} is not of type {expected_type}")
        return
    if 'const' in schema and instance != schema['const']:
        errors.append(f"{name}: {instance!r} should be {schema['const']!r}")
    for keyword in ('oneOf', 'anyOf'):
        if keyword in schema:
            matches = [sub for sub in schema[keyword] if _is_valid(sub, instance, root)]
            if not matches or (keyword == 'oneOf' and len(matches) > 1):
                allowed = ', '.join(repr(sub['const']) for sub in schema[keyword] if 'const' in sub)
                errors.append(f"{name}: {instance!r} is not one of the allowed values {allowed}")
    if 'not' in schema and _is_valid(schema['not'], instance, root):
        errors.append(f"{name}: {instance!r} is not allowed")

    if isinstance(instance, dict):
        properties = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in instance:
                errors.append(f"{name}: the property {key} is required")
        if len(instance) < schema.get('minProperties', 0):
            errors.append(f"{name}: at least {schema['minProperties']} properties are required")
        for key, value in instance.items():
            if key in properties:
                _validate(properties[key], value, f"{path}/{key}", errors, root)
            elif schema.get('additionalProperties') is False:
                errors.append(f"{name}: the property {key} is not allowed")
    elif isinstance(instance, list):
        if len(instance) < schema.get('minItems', 0):
            errors.append(f"{name}: at least {schema['minItems']} items are required")
        if 'maxItems' in schema and len(instance) > schema['maxItems']:
            errors.append(f"{name}: at most {schema['maxItems']} items are allowed")
        if schema.get('uniqueItems') and len({json.dumps(item, sort_keys=True, default=str) for item in instance}) < len(instance):
            errors.append(f"{name}: the items must be unique")
        for index, item in enumerate(instance):
            if 'items' in schema:
                _validate(schema['items'], item, f"{path}/{index}", errors, root)
    elif isinstance(instance, str):
        if len(instance) < schema.get('minLength', 0):
            errors.append(f"{name}: {instance!r} is too short")
        if 'maxLength' in schema and len(instance) > schema['maxLength']:
            errors.append(f"{name}: {instance!r} is longer than {schema['maxLength']} characters")
        if 'pattern' in schema and not re.search(schema['pattern'], instance):
            errors.append(f"{name}: {instance!r} doesn't match {schema['pattern']}")
        if schema.get('format') == 'date':
            try:
                date.fromisoformat(instance)
            except ValueError:
                errors.append(f"{name}: {instance!r} is not a date (YYYY-MM-DD)")
    elif _has_type(instance, 'number'):
        if 'minimum' in schema and instance < schema['minimum']:
            errors.append(f"{name}: {instance} is lower than {schema['minimum']}")
        if 'maximum' in schema and instance > schema['maximum']:
            errors.append(f"{name}: {instance} is greater than {schema['maximum']}")
        if 'multipleOf' in schema and Decimal(instance) % Decimal(schema['multipleOf']):
            errors.append(f"{name}: {instance} is not a multiple of {schema['multipleOf']}")


def _has_type(instance, expected_type):
    if isinstance(expected_type, list):
        return any(_has_type(instance, single_type) for single_type in expected_type)
    if expected_type == 'number':
        return isinstance(instance, (int, Decimal)) and not isinstance(instance, bool)
    if expected_type == 'integer':
        return isinstance(instance, int) and not isinstance(instance, bool)
    return isinstance(instance, {
        'object': dict,
        'array': list,
        'string': str,
        'boolean': bool,
    }[expected_type])
