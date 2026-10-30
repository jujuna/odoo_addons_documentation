import { ProductTemplate } from "@point_of_sale/../tests/unit/data/product_template.data";
// The blackbox module replaces the whole record list with Belgian products; import it so it
// always runs before this file appends to it.
import "@l10n_be_pos_blackbox/../tests/unit/data/product_template.data";

const loyaltyProduct = (id, name) => ({
    id: id,
    display_name: name,
    standard_price: 0.0,
    categ_id: false,
    pos_categ_ids: [],
    // A gift card / eWallet product may never carry taxes on a certified blackbox,
    // see `models/product_template.py`.
    taxes_id: [],
    barcode: false,
    name: name,
    list_price: 100.0,
    is_favorite: false,
    default_code: false,
    to_weight: false,
    uom_id: 1,
    description_sale: false,
    description: false,
    type: "consu",
    service_tracking: "no",
    is_storable: false,
    write_date: "2025-07-23 12:22:34",
    color: 3,
    available_in_pos: true,
    attribute_line_ids: [],
    active: true,
    image_128: false,
    combo_ids: [],
    product_variant_ids: [id],
    public_description: false,
    pos_optional_product_ids: [],
    sequence: 1,
    product_tag_ids: [],
});

ProductTemplate._records = [
    ...ProductTemplate._records,
    // Trigger product of the gift card program: the product the customer buys.
    loyaltyProduct(100, "Gift card"),
    // Discount line product of the gift card reward: the line the redemption produces.
    loyaltyProduct(101, "Gift Card Redemption"),
    // Discount line product of the promotion rewards.
    loyaltyProduct(102, "Discount"),
    // Discount line product of the eWallet reward.
    loyaltyProduct(103, "EWallet Redemption"),
];
