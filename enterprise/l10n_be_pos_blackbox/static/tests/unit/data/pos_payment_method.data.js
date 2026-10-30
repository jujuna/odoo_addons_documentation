import { PosPaymentMethod } from "@point_of_sale/../tests/unit/data/pos_payment_method.data";

PosPaymentMethod._records = [
    {
        id: 1,
        name: "Bank",
        type: "bank",
        image: false,
        sequence: 0,
        payment_method_type: "none",
        default_qr: false,
    },
    {
        id: 2,
        name: "Cash",
        type: "cash",
        image: false,
        sequence: 0,
        payment_method_type: "none",
        default_qr: false,
    },
    {
        id: 3,
        name: "Customer Account",
        type: "pay_later",
        image: false,
        sequence: 0,
        payment_method_type: "none",
        default_qr: false,
    },
];
