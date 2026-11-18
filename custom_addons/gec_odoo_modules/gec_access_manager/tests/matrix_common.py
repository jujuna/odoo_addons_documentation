import functools
import logging

_logger = logging.getLogger(__name__)


def known_gap(review_id):
    """Pass while the open review item still fails; fail once it works, so the mark gets removed.

    Odoo's runner drops unittest.expectedFailure. Do not use subTest inside a marked test.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                func(self, *args, **kwargs)
            except AssertionError as error:
                _logger.info("known gap %s still open: %s", review_id, str(error).splitlines()[0][:200])
                return
            self.fail(f"{review_id} now works: remove @known_gap('{review_id}') from {func.__name__}")
        return wrapper
    return decorator
