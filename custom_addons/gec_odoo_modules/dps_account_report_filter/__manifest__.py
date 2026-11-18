{
    "name": "Odoo Financial Reports: Currency Filter | Account Report in Multiple Currencies | Account Reports Multi Currency (Original)",
    "summary": "Add multi-currency support to financial reports for accurate global financial analysis. Simplify your financial reporting across multiple currencies with our Multi-Currency Accounting Report module. Tailored for businesses handling international transactions, this app delivers accurate, real-time insights into your accounting data across various currencies.",
    "version": "20.0.2.4.0",
    "category": "Accounting",
    'author': 'Dotsprime System',
    'sequence': 1,
    'email': 'dotsprime@gmail.com',
    'support': 'sales@dotsprime.com',
    "website":'https://dotsprime.com/',
    "license": 'OPL-1',
    'price': 9.9,
    'currency': 'USD',
    "description": """
        Empower your accounting team with enhanced financial reporting by enabling multiple currency support 
        across key financial statements such as Balance Sheet, Profit and Loss, Cash Flow Statement, Executive Summary, Tax Return, General Ledger, Trial Balance, Journal Audit, Check Register, Partner Ledger, Aged Receivable .

        This module integrates seamlessly with Odoo's accounting reports to allow switching between the 
        company's base currency and a selected alternate currency, improving visibility for international 
        operations and financial audits.

        Odoo Financial Reports: Currency Filter :
            Balance Sheet
            Profit and Loss
            Cash Flow Statement
            Executive Summary
            Tax Return
            General Ledger
            Trail Balance
            Journal Audi
            Check Register
            Partner Ledger
            Aged Receivable
            Aged Payable

        Key Features:
        - Add currency selection filters to financial reports
        - View reports in alternate currencies for better insights
        - Improve decision-making for businesses with multi-currency transactions
    """,
    "depends": [
        "account_reports",
    ],
    "data": [
        "data/supported_reports.xml",
        "views/pdf_export_templates.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "dps_account_report_filter/static/src/components/**/*",
        ],
    },
    'images': ['static/description/main_screenshot.png'],
    "live_test_url" : "https://youtu.be/AEuwyXlqJ7A",
    'demo': [],
    'installable': True,
    'auto_install': False,
    'application': True,
}

