from . import models
from . import wizards


def _rs_create_pickup_types(env):
    """ Every existing warehouse gets its "Customer Pickup" Operation Type. """
    for warehouse in env['stock.warehouse'].search([]):
        warehouse._rs_pickup_type()
