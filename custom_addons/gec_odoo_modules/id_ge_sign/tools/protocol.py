GEOEID_SCHEME = "geoeid-unitool://"

# Reserved (RFC 6761) non-routable domain for a public card signer's placeholder email.
GEOEID_PLACEHOLDER_EMAIL_DOMAIN = "id-card.invalid"

# ETSI EN 319 412-1 semantic identifier prefix of the personal number in the certificate subject serialNumber.
GEOEID_PERSONAL_NUMBER_PREFIX = "PNOGE-"

GEOEID_MAX_SIGNATURE_INCREMENT = 5 * 1024 * 1024
GEOEID_MAX_SIGNATURE_AREA_PERCENT = 2.0
GEOEID_MULTIPART_OVERHEAD = 64 * 1024


def is_placeholder_email(email):
    return (email or '').strip().lower().rstrip('>').endswith('@' + GEOEID_PLACEHOLDER_EMAIL_DOMAIN)


def launch_url(base_url, token):
    """The ``geoeid-unitool://`` URL the browser opens; the app turns it into a GET on init."""
    netloc_path = base_url.split("://", 1)[-1].rstrip("/")
    return "%s%s/sign/geoeid/init/%s" % (GEOEID_SCHEME, netloc_path, token)


def build_init_document_json(base_url, token, description, language="ka"):
    """The JSON spec the Universal Program fetches from the init endpoint; its keys map 1:1 onto the app's ``JsonMessage``
    model. In document mode the app downloads the PDF from ``dataUrl`` and posts the signed one to ``submitUrl`` as ``signedFile``."""
    base = base_url.rstrip("/")
    return {
        "dataType": "document",
        "docType": "PDF",
        "dataUrl": "%s/sign/geoeid/document/%s" % (base, token),
        "submitUrl": "%s/sign/geoeid/submit/%s" % (base, token),
        "signAlg": "sha256withRSA",
        "padesUsage": True,
        "description": description or "",
        "language": language or "ka",
        "keyId": "sign",
        "signatureProfile": "B",
    }
