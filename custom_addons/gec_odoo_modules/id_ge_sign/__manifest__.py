{
    'name': "Sign with Georgian ID Card (QES)",
    'version': '20.0.3.2.0',
    'category': 'Productivity/Sign',
    'summary': "Sign Odoo Sign documents with the Georgian ID Card (id.ge) as a Qualified Electronic Signature",
    'description': """
Adds "Georgian ID Card" as an extra authentication step on a Sign role. When a
signer validates, Odoo renders the document and launches the Georgian ID Card
Universal Program (geoeid-unitool://). The desktop app downloads the PDF, stamps
its own visible signature block (signer name and personal number from the card),
produces the PAdES signature and uploads the finished, signed PDF back to Odoo
(document mode). Odoo verifies the embedded signature, records the certificate
identity (name, personal number, serial, expiry) and stores the signed PDF as
the completed document.

Scope: one PDF per request, with regular signers first and Georgian ID Card
signers stacked afterward as PAdES Baseline-B signatures. Verification uses
cryptography + asn1crypto (already in Odoo), no extra Python dependency. LT/LTA
and server-side TSA/OCSP validation are out of scope of this version (see
documentations/id_ge_sign.md).

Standard Odoo Sign is untouched: every other role/auth method keeps working and
uninstalling this module restores stock behaviour.

Full documentation: README.md and README_DEV.md in the module directory.
""",
    'author': 'GEC',
    'license': 'LGPL-3',
    'depends': ['sign'],
    'external_dependencies': {
        'python': ['cryptography', 'asn1crypto'],
    },
    'data': [
        'data/ir_config_parameter.xml',
        'report/sign_completion_report.xml',
        'views/res_config_settings_views.xml',
        'views/sign_item_role_views.xml',
    ],
    'assets': {
        # Backend Sign app (internal signers) and the public/portal signing page
        # (external signers) load 'Document' from different bundles; cover both.
        'web.assets_backend': [
            'id_ge_sign/static/src/**/*',
        ],
        'sign.assets_public_sign': [
            'id_ge_sign/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'id_ge_sign/static/tests/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
