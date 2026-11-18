import logging

_logger = logging.getLogger(__name__)

# The transfer trail moved to gec_bank fields; without the copy a transfer TBC holds could be sent twice.
RENAMED_COLUMNS = {
    'account_payment': [
        # (old tbc_bank column, new gec_bank column, column type); the state first, see _copy_condition.
        ('tbc_state', 'gec_bank_state', 'varchar'),
        ('tbc_transfer_id', 'gec_bank_reference', 'varchar'),
        ('tbc_external_id', 'gec_bank_request_id', 'varchar'),
        ('tbc_error_message', 'gec_bank_error', 'varchar'),
        ('tbc_approved_by', 'gec_bank_approved_by', 'int4'),
        ('tbc_approved_date', 'gec_bank_approved_date', 'timestamp'),
        ('tbc_confirmed_source', 'gec_bank_confirmed_source', 'varchar'),
    ],
    'account_bank_statement_line': [
        ('tbc_match_keys', 'gec_bank_match_keys', 'varchar'),
    ],
}
# Old tbc_state had default='pending' on every payment: only outbound TBC transfers carry a real trail.
TBC_PAYMENT_FILTER = """
    payment_type = 'outbound'
    AND payment_method_id IN (SELECT id FROM account_payment_method WHERE code = 'tbc_transfer')"""


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column))
    return bool(cr.fetchone())


def _copy_condition(table, new):
    """Rows whose new column holds nothing newer than the old one. The new state wins once the gec_bank code
    sent the transfer (a request id); a 'pending' it only computed is replaced by the old state."""
    if new == 'gec_bank_state':
        condition = ('("gec_bank_state" IS NULL OR ("gec_bank_state" = \'pending\''
                     ' AND "gec_bank_request_id" IS NULL))')
    else:
        condition = '"%s" IS NULL' % new
    if table == 'account_payment':
        condition += ' AND' + TBC_PAYMENT_FILTER
    return condition


def migrate(cr, version):
    """Copy the old tbc_* values of TBC transfers into empty gec_bank_* columns; other payments keep no state."""
    for table, columns in RENAMED_COLUMNS.items():
        for old, new, column_type in columns:
            if not _column_exists(cr, table, old):
                continue
            if not _column_exists(cr, table, new):
                cr.execute('ALTER TABLE "%s" ADD COLUMN "%s" %s' % (table, new, column_type))
            if table == 'account_payment' and not _column_exists(cr, table, 'gec_bank_request_id'):
                cr.execute('ALTER TABLE account_payment ADD COLUMN gec_bank_request_id varchar')
            cr.execute('UPDATE "%s" SET "%s" = "%s" WHERE "%s" IS NOT NULL AND %s'
                       % (table, new, old, old, _copy_condition(table, new)))
            _logger.info("tbc_bank: copied %s %s.%s -> %s", cr.rowcount, table, old, new)
