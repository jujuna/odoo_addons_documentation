# -*- coding: utf-8 -*-
"""Fill the new dropdown many2ones from the hand-typed technical names.
Runs before the ORM update, which would wipe the stored related fields
(model_name, date_field, value_field, company_field)."""


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        ALTER TABLE bsc_kpi_source
            ADD COLUMN IF NOT EXISTS model_id integer,
            ADD COLUMN IF NOT EXISTS date_field_id integer,
            ADD COLUMN IF NOT EXISTS value_field_id integer,
            ADD COLUMN IF NOT EXISTS company_field_id integer
    """)

    cr.execute("""
        UPDATE bsc_kpi_source source
           SET model_id = model.id
          FROM ir_model model
         WHERE model.model = source.model_name
           AND source.model_id IS NULL
    """)

    for column, target in (('date_field_id', 'date_field'),
                           ('value_field_id', 'value_field'),
                           ('company_field_id', 'company_field')):
        cr.execute("""
            UPDATE bsc_kpi_source source
               SET %(column)s = field.id
              FROM ir_model_fields field
             WHERE field.model = source.model_name
               AND field.name = source.%(target)s
               AND source.%(target)s IS NOT NULL
               AND source.%(column)s IS NULL
        """ % {'column': column, 'target': target})

    # A name that no longer resolves is left alone; the definition constraint refuses it on the next save.
