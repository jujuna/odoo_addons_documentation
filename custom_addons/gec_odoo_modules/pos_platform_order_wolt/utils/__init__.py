def preorder_status(order_data):
    return (order_data.get('pre_order') or {}).get('pre_order_status')


def wolt_option_lines(template):
    """The attribute lines the menu sends as Wolt options; a line with one value is part of the product itself."""
    return template.attribute_line_ids.filtered(
        lambda line: len(line.product_template_value_ids._only_active()) > 1 or line.attribute_id.display_type == 'multi')
