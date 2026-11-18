"""Builders for rs.ge's SOAP replies, one per ntosservice.asmx operation the tests use. Element names and order follow
test_files/ntosservice.wsdl, which zeep validates against; DataTable replies are parsed by the service, so only rows
matter."""

SOAP_NS = 'http://schemas.xmlsoap.org/soap/envelope/'
RS_NS = 'http://tempuri.org/'


def _xml(value):
    return str(value).lower() if isinstance(value, bool) else str(value)


def envelope(operation, **fields):
    """Wrap ``fields``, in declaration order, in the envelope rs.ge answers ``operation`` with."""
    body = ''.join('<%s>%s</%s>' % (name, _xml(value), name)
                   for name, value in fields.items() if value is not None)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="%s"><soap:Body>'
        '<%sResponse xmlns="%s">%s</%sResponse>'
        '</soap:Body></soap:Envelope>' % (SOAP_NS, operation, RS_NS, body, operation)
    )


def chek(result=True, user_id=783):
    return envelope('chek', chekResult=result, user_id=user_id, sua=0)


def get_un_id_from_tin(un_id=1149251, name='GE Customer'):
    return envelope('get_un_id_from_tin', get_un_id_from_tinResult=un_id, name=name)


def get_un_id_from_user_id(un_id=731937):
    return envelope('get_un_id_from_user_id', get_un_id_from_user_idResult=un_id)


def save_invoice(invois_id=700123, result=True):
    return envelope('save_invoice', save_invoiceResult=result, invois_id=invois_id)


def save_invoice_desc(id=800001, result=True):
    return envelope('save_invoice_desc', save_invoice_descResult=result, id=id)


def change_invoice_status(result=True):
    return envelope('change_invoice_status', change_invoice_statusResult=result)


def get_invoice(status=1, f_series='AA', f_number='12345', reg_dt='2026-09-20T10:30:00',
                seller_un_id=731937, buyer_un_id=1149251, k_id=-1, k_type=-1, result=True):
    return envelope(
        'get_invoice',
        get_invoiceResult=result,
        f_series=f_series,
        f_number=f_number,
        operation_dt='2026-09-20T00:00:00',
        reg_dt=reg_dt,
        seller_un_id=seller_un_id,
        buyer_un_id=buyer_un_id,
        overhead_no='',
        overhead_dt='0001-01-01T00:00:00',
        status=status,
        seq_num_s='',
        seq_num_b='',
        k_id=k_id,
        r_un_id=0,
        k_type=k_type,
        b_s_user_id=0,
        dec_status=0,
    )


def datatable(operation, rows, table='Table'):
    """The DataTable reply of a list operation: one ``table`` element per row, or no diffgram
    at all when there are no rows, as rs.ge answers."""
    body = ''.join(
        '<%s>%s</%s>' % (table, ''.join('<%s>%s</%s>' % (k, _xml(v), k) for k, v in row.items()), table)
        for row in rows
    )
    diffgram = (
        '<diffgr:diffgram xmlns:msdata="urn:schemas-microsoft-com:xml-msdata" '
        'xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">'
        '<DocumentElement xmlns="">%s</DocumentElement></diffgr:diffgram>' % body
        if rows else ''
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="%s"><soap:Body>'
        '<%sResponse xmlns="%s"><%sResult>%s</%sResult></%sResponse>'
        '</soap:Body></soap:Envelope>' % (SOAP_NS, operation, RS_NS, operation, diffgram, operation, operation)
    )


def fault(string='Server was unable to process request.'):
    """The SOAP fault rs.ge returns for a server-side error; zeep raises it as ``Fault``."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="%s"><soap:Body><soap:Fault>'
        '<faultcode>soap:Server</faultcode><faultstring>%s</faultstring><detail/>'
        '</soap:Fault></soap:Body></soap:Envelope>' % (SOAP_NS, string)
    )
