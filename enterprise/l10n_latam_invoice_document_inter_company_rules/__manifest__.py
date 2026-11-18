{
    "name": "LATAM Document - Intercompany Rules",
    "summary": "LATAM invoice documents with intercompany rules",
    "category": "Accounting/Localizations",
    "description": """
    Ensure auto-generated intercompany vendor bills on LATAM-localized companies are posted with
    the correct document number.
    """,
    "depends": [
        "l10n_latam_invoice_document",
        "account_inter_company_rules",
    ],
    "auto_install": True,
    "author": "Odoo S.A.",
    "license": "OEEL-1",
}
