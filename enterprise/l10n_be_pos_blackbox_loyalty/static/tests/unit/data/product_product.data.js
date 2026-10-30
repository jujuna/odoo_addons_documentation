import { ProductProduct } from "@point_of_sale/../tests/unit/data/product_product.data";
// See the note in `product_template.data.js`.
import "@l10n_be_pos_blackbox/../tests/unit/data/product_product.data";

const loyaltyVariant = (id, name) => ({
    id: id,
    product_tmpl_id: id,
    lst_price: 100,
    standard_price: 0,
    display_name: name,
    product_tag_ids: [],
    barcode: false,
    default_code: false,
    product_template_attribute_value_ids: [],
    product_template_variant_value_ids: [],
});

ProductProduct._records = [
    ...ProductProduct._records,
    loyaltyVariant(100, "Gift card"),
    loyaltyVariant(101, "Gift Card Redemption"),
    loyaltyVariant(102, "Discount"),
    loyaltyVariant(103, "EWallet Redemption"),
];
