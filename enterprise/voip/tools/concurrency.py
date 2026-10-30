import logging
from contextlib import contextmanager
from contextvars import ContextVar

from psycopg2 import IntegrityError, errorcodes

_expecting_unique_violation = ContextVar("expecting_unique_violation", default=False)


def _is_not_an_expected_unique_violation(record):
    return not (
        _expecting_unique_violation.get()
        and record.args
        and isinstance(record.args[-1], IntegrityError)
        and record.args[-1].pgcode == errorcodes.UNIQUE_VIOLATION
    )


logging.getLogger("odoo.sql_db").addFilter(_is_not_an_expected_unique_violation)


@contextmanager
def expected_unique_violation():
    """Run an ORM insert another transaction may race us to, without logging its unique violation.

    Two writers create some rows of a call milliseconds apart: the browser that
    got the INVITE and the phone-service webhook for the same channel (the
    conversation, the call, the callee's leg), or two deliveries of the same
    event. Each searches, finds nothing and inserts; the loser hits the unique
    index, and its caller reads that ``UniqueViolation`` as expected (retry as a
    ``ConcurrencyError``, or drop a duplicate). ``odoo.sql_db`` would still log
    the failed query as an ERROR, on every call.

    Within the block, ``odoo.sql_db`` does not log a unique violation; any other
    failed query is logged as before. The block is bound to the current context,
    so no other request is affected.
    """
    token = _expecting_unique_violation.set(True)
    try:
        yield
    finally:
        _expecting_unique_violation.reset(token)
