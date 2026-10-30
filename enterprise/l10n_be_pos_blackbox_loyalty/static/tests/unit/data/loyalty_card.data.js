import { LoyaltyCard } from "@pos_loyalty/../tests/unit/data/loyalty_card.data";

const { DateTime } = luxon;

LoyaltyCard._records = [
    ...LoyaltyCard._records,
    {
        // A 50.0 gift card of program 33, redeemed by applying its code to the order.
        id: 33,
        code: "GIFT_CARD_33",
        points: 50,
        partner_id: false,
        program_id: 33,
        expiration_date: DateTime.now().plus({ years: 1 }).toISODate(),
        write_date: DateTime.now().toFormat("yyyy-MM-dd HH:mm:ss"),
    },
    {
        // A 30.0 eWallet balance of program 36.
        id: 36,
        code: "EWALLET_36",
        points: 30,
        partner_id: false,
        program_id: 36,
        expiration_date: false,
        write_date: DateTime.now().toFormat("yyyy-MM-dd HH:mm:ss"),
    },
];
