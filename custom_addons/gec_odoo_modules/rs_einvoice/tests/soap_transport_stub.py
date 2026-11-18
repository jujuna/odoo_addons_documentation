from lxml import etree
from requests import Response
from zeep.transports import Transport

from odoo.tools import file_open

WSDL_PATH = 'rs_einvoice/tests/test_files/ntosservice.wsdl'


class SoapTransportStub(Transport):
    """Answers rs.ge's SOAP calls from reply envelopes, not the network. Only the sockets are replaced: zeep still
    validates arguments and parses replies. Replies are keyed by operation; a list gives one per call, last
    repeating."""

    def __init__(self, **responses):
        super().__init__()
        self.calls = []
        self.responses = responses

    def load(self, url):
        with file_open(WSDL_PATH, 'rb') as wsdl:
            return wsdl.read()

    def post(self, address, message, headers):
        operation = self._operation_of(message)
        self.calls.append(operation)
        return self._response_for(operation)

    def _operation_of(self, message):
        envelope = etree.fromstring(message if isinstance(message, bytes) else message.encode())
        body = envelope.find('{http://schemas.xmlsoap.org/soap/envelope/}Body')
        return etree.QName(body[0]).localname

    def _response_for(self, operation):
        content = self.responses.get(operation)
        if isinstance(content, list):
            content = content.pop(0) if len(content) > 1 else content[0]
        if content is None:
            raise AssertionError("No recorded rs.ge reply for %s()" % operation)
        response = Response()
        response.status_code = 200
        response.encoding = 'utf-8'
        response._content = content if isinstance(content, bytes) else content.encode()
        response.headers['Content-Type'] = 'text/xml; charset=utf-8'
        return response
