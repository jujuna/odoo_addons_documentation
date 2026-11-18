import json
import logging
import re
import time

import psycopg2

from odoo import _, fields, models
from odoo.exceptions import UserError

from .gec_bank_guard_mixin import GEC_BANK_WRITE_TOKEN

_logger = logging.getLogger(__name__)


class GecBankService(models.AbstractModel):
    """What every bank client shares: durable row writes, the audit log on its own cursor,
    response parsing and secret redaction. A bank service adds its own auth, endpoints and payloads."""

    _name = 'gec.bank.service'
    _description = 'Bank API Client Base'

    # The model holding this bank's API log rows; set by each bank service.
    _gec_bank_log_model = None
    # Keys whose values never reach a log row, in payloads and in raw response text.
    _gec_bank_sensitive_keys = frozenset()

    @staticmethod
    def _durable_columns(record, vals):
        """Column names of ``vals``; refuses any that is not a plain stored column of ``record``."""
        columns = list(vals)
        for column in columns:
            field = record._fields.get(column)
            if not (field and field.store and field.column_type):
                raise ValueError("cannot write field %r durably" % column)
        return columns

    def _durable_write(self, record, vals, expected_state=None):
        """Write ``vals`` on an own committed cursor (True when durable; a row lock falls back to the ORM and logs).
        With ``expected_state`` ({field: value}) it writes only if the field still holds it, else returns None."""
        record.ensure_one()
        record.flush_recordset()
        columns = self._durable_columns(record, vals)
        assignments = ', '.join('"%s" = %%s' % column for column in columns)
        params = [None if vals[column] is False else vals[column] for column in columns]
        condition, condition_params = '', []
        if expected_state:
            (state_field, state_value), = expected_state.items()
            self._durable_columns(record, {state_field: None})
            condition = ' AND "%s" IS NOT DISTINCT FROM %%s' % state_field
            condition_params = [state_value or None]
        try:
            with self.env.registry.cursor() as own_cr:
                own_cr.execute("SET LOCAL lock_timeout = '2s'")
                own_cr.execute(
                    'UPDATE "%s" SET %s, write_uid = %%s, write_date = %%s WHERE id = %%s%s'
                    % (record._table, assignments, condition),
                    params + [self.env.uid, fields.Datetime.now(), record.id] + condition_params)
                if expected_state and not own_cr.rowcount:
                    _logger.info("%s %s changed meanwhile; %s not written", record._name, record.id, columns)
                    record.invalidate_recordset()
                    return None
        except psycopg2.errors.LockNotAvailable:
            if expected_state:
                _logger.info("%s %s is locked; %s not written", record._name, record.id, columns)
                return None
            _logger.warning("%s %s is locked by this transaction; %s written non-durably",
                            record._name, record.id, columns)
            record.with_context(gec_bank_write_token=GEC_BANK_WRITE_TOKEN).write(vals)
            return False
        record._update_cache(vals)
        return True

    def _reserve_send(self, record, vals, state_field, blocked_states):
        """Claim ``record`` for one send before any money moves; True when this call got the claim. One
        conditional UPDATE on an own cursor writes ``vals`` unless ``state_field`` is in ``blocked_states``:
        durable and atomic."""
        record.ensure_one()
        record.flush_recordset()
        self._durable_columns(record, {state_field: None})
        columns = self._durable_columns(record, vals)
        assignments = ', '.join('"%s" = %%s' % column for column in columns)
        params = [None if vals[column] is False else vals[column] for column in columns]
        try:
            with self.env.registry.cursor() as own_cr:
                own_cr.execute("SET LOCAL lock_timeout = '2s'")
                own_cr.execute(
                    'UPDATE "%(table)s" SET %(assignments)s, write_uid = %%s, write_date = %%s'
                    ' WHERE id = %%s AND ("%(state)s" IS NULL OR "%(state)s" NOT IN %%s)'
                    % {'table': record._table, 'assignments': assignments, 'state': state_field},
                    params + [self.env.uid, fields.Datetime.now(), record.id, tuple(blocked_states)])
                claimed = bool(own_cr.rowcount)
        except psycopg2.errors.LockNotAvailable:
            raise UserError(_("This payment is being changed by another operation. Reload it and "
                              "send again."))
        if claimed:
            record._update_cache(vals)
        return claimed

    def _log_vals(self, connection, endpoint, request_payload, response_text,
                  http_status, error_message, start_monotonic):
        """The values every bank's API log row shares, with secrets redacted."""
        return {
            'connection_id': connection.id,
            'endpoint': endpoint,
            'http_status': http_status,
            'error_message': (error_message or '')[:255],
            'request_payload': self._dump_redacted(request_payload),
            'response_payload': self._dump_redacted_text(response_text or ''),
            'duration_ms': int((time.monotonic() - start_monotonic) * 1000),
        }

    def _write_log(self, vals):
        """Create the log row on an own cursor so it survives the caller's rollback."""
        try:
            with self.env.registry.cursor() as own_cr:
                self.env(cr=own_cr)[self._gec_bank_log_model].sudo().create(vals)
        except Exception:
            _logger.exception("Failed to record the bank API log for %s", vals.get('endpoint'))

    @staticmethod
    def _parse_json(text):
        """Parse a response body; None if not JSON. The result may be a list or a scalar, not only a dict."""
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return None

    @staticmethod
    def _first_key(data, candidates, default=None):
        """Value of the first present key in ``candidates``: banks document one payload in several casings."""
        if not isinstance(data, dict):
            return default
        for key in candidates:
            if data.get(key) is not None:
                return data[key]
        return default

    @classmethod
    def _redact_data(cls, data):
        if isinstance(data, dict):
            return {key: ('[REDACTED]' if key in cls._gec_bank_sensitive_keys
                          else cls._redact_data(value))
                    for key, value in data.items()}
        if isinstance(data, list):
            return [cls._redact_data(value) for value in data]
        return data

    @classmethod
    def _redact_text(cls, text):
        """Mask the sensitive values in text that is not valid JSON."""
        if not text or not cls._gec_bank_sensitive_keys:
            return text
        pattern = r'("(?:%s)"\s*:\s*)("[^"]*"|[^\s,}\]]+)' % '|'.join(
            re.escape(key) for key in sorted(cls._gec_bank_sensitive_keys))
        return re.sub(pattern, r'\1"[REDACTED]"', text)

    @classmethod
    def _dump_redacted(cls, payload):
        try:
            return json.dumps(cls._redact_data(payload), ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return cls._redact_text(str(payload))

    @classmethod
    def _dump_redacted_text(cls, text):
        if not text:
            return text
        try:
            return json.dumps(cls._redact_data(json.loads(text)), ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return cls._redact_text(text)
