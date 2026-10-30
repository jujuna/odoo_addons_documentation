import { LoyaltyRule } from "@pos_loyalty/../tests/unit/data/loyalty_rule.data";

LoyaltyRule._records = [
    ...LoyaltyRule._records,
    {
        // One point per order, which is what the free product reward of program 34 costs.
        id: 33,
        program_id: 34,
        valid_product_ids: [],
        any_product: true,
        currency_id: 1,
        reward_point_amount: 1,
        reward_point_split: false,
        reward_point_mode: "order",
        minimum_qty: 0,
        minimum_amount: 0,
        minimum_amount_tax_mode: "incl",
        mode: "auto",
        code: false,
    },
    {
        // Activates program 35, so its 10% discount only applies to an order that opted in
        // with `order.applied_codes = [BLACKBOX_DISCOUNT_CODE]`.
        id: 34,
        program_id: 35,
        valid_product_ids: [],
        any_product: true,
        currency_id: 1,
        reward_point_amount: 1,
        reward_point_split: false,
        reward_point_mode: "order",
        minimum_qty: 0,
        minimum_amount: 0,
        minimum_amount_tax_mode: "incl",
        mode: "with_code",
        code: "BB_DISCOUNT_10",
    },
];
