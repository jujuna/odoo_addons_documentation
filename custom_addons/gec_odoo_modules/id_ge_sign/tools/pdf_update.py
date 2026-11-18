import io
import re

from odoo.tools.pdf import ArrayObject, DictionaryObject, IndirectObject, NullObject, NumberObject, PdfFileReader, generic

from .cms import CmsVerificationError

SKIPPED_KEYS = {'/Catalog': {'/AcroForm', '/OutputIntents'}, '/Page': {'/Annots'}}
FORM_KEYS = {'/Fields', '/SigFlags'}
FIELD_KEYS = {'/FT', '/Type', '/Subtype', '/F', '/T', '/V', '/P', '/Rect', '/AP'}
_NUMBERS = (NumberObject, generic.FloatObject)
_OBJECT = re.compile(rb'(?:^|(?<=[\r\n]))(\d+) (\d+) obj')
_TABLE = re.compile(rb'xref\s+((?:\d+ \d+\s+(?:\d{10} \d{5} [nf]\s+)+)+)trailer\s*<<([^#]*?)>>\s*startxref\s+\d+\s+%%EOF\s*')
_SECTION = re.compile(rb'(\d+) (\d+)\s+((?:\d{10} \d{5} [nf]\s+)+)')
_ROW = re.compile(rb'(\d{10}) (\d{5}) ([nf])')
_START = re.compile(rb'startxref\s+(\d+)')
_END = re.compile(rb'\s+%%EOF\s*')
_PREVIOUS = re.compile(rb'/Prev\s+(\d+)')
_INDEX = re.compile(rb'/Index\s*\[([\d\s]+)\]')


def check_signature_update(frozen, signed_pdf, max_area_percent):
    """Raise unless ``signed_pdf`` is ``frozen`` plus one signature field, whose visible block stays within ``max_area_percent`` of its page."""
    try:
        blocks = _signature_blocks(frozen, signed_pdf)
    except Exception:  # noqa: BLE001 the bytes come from the signer's PC: whatever the PDF parser raises on them is a refusal
        blocks = None
    if blocks is None:
        raise CmsVerificationError("The signed PDF changes the document beyond adding one signature.")
    if any(area * 100 > page_area * max_area_percent for area, page_area in blocks):
        raise CmsVerificationError("The signature block covers too much of the page.")


def _table_objects(table):
    """The {object number: offset} a classic cross-reference table lists; None when it frees an object or uses a generation."""
    listed = {}
    for first, count, rows in _SECTION.findall(table[1]):
        rows = _ROW.findall(rows)
        if len(rows) != int(count):
            return None
        listed.update((int(first) + index, (int(offset), int(generation), kind)) for index, (offset, generation, kind) in enumerate(rows))
    if listed.pop(0, (0, 65535, b'f')) != (0, 65535, b'f') or any(row[1:] != (0, b'n') for row in listed.values()):
        return None
    return {number: row[0] for number, row in listed.items()}


def _update_objects(frozen, signed_pdf):
    """The {object number: offset} the updates write; None unless each update is plain objects and one cross-reference listing exactly them.

    PDF readers disagree on a broken cross-reference (one shows the old object, another the new one), so only updates every
    reader reads the same way are compared at all. A cross-reference stream is accepted only on a file that already ends in one."""
    written, position, previous = {}, len(frozen), _START.findall(frozen)[-1:]
    classic = bool(previous) and frozen.startswith(b'xref', int(previous[0]))
    while position < len(signed_pdf):
        start = _START.search(signed_pdf, position)
        end = start and _END.match(signed_pdf, start.end())
        if not end or not position <= int(start[1]) < start.start():
            return None
        table = _TABLE.fullmatch(signed_pdf, int(start[1]), end.end())
        header = signed_pdf[int(start[1]):max(int(start[1]), signed_pdf.find(b'stream', int(start[1]), start.start()))]
        objects = [(int(match[1]), int(match[2]), match.start()) for match in _OBJECT.finditer(signed_pdf, position, (table or start).start())]
        if table:
            one_trailer = b'XRefStm' not in table[2] and table[2].count(b'/Root') == 1 and _PREVIOUS.findall(table[2]) == previous
            listed = _table_objects(table) if one_trailer else None
            if listed is None or sorted(objects) != sorted((number, 0, offset) for number, offset in listed.items()):
                return None
        else:
            index = _INDEX.findall(header)
            ranges = [int(number) for number in index[0].split()] if len(index) == 1 else []
            # A range longer than the objects written can never match them; capping it keeps a huge count from being expanded.
            listed = {first + step for first, count in zip(ranges[::2], ranges[1::2]) for step in range(min(count, len(objects) + 2))}
            numbers = [number for number, generation, _offset in objects if not generation]
            listed_as_written = len(numbers) == len(objects) == len(set(numbers)) and listed - {0} == set(numbers)
            if classic or not objects or not listed_as_written or _PREVIOUS.findall(header) != previous or objects[-1][2] != int(start[1]):
                return None
        written.update((number, offset) for number, _generation, offset in objects)
        position, previous = end.end(), [start[1]]
    return written


def _resolve(value):
    return value.get_object() if isinstance(value, IndirectObject) else value


def _same(old, new):
    """Whether two PDF objects, each read from its own file, hold the same content; the keys the card app may add are skipped."""
    seen, todo = set(), [(old, new)]
    while todo:
        old, new = todo.pop()
        if isinstance(old, IndirectObject) and isinstance(new, IndirectObject):
            pair = (old.idnum, old.generation, new.idnum, new.generation)
            if pair in seen:
                continue
            seen.add(pair)
        old, new = _resolve(old), _resolve(new)
        if isinstance(old, DictionaryObject) and isinstance(new, DictionaryObject):
            keys = set(old) - SKIPPED_KEYS.get(old.get('/Type'), set())
            is_stream = isinstance(old, generic.StreamObject)
            if keys != set(new) - SKIPPED_KEYS.get(new.get('/Type'), set()) or is_stream != isinstance(new, generic.StreamObject):
                return False
            if is_stream and old._data != new._data:
                return False
            todo += [(old.raw_get(key), new.raw_get(key)) for key in keys]
        elif isinstance(old, ArrayObject) and isinstance(new, ArrayObject):
            if len(old) != len(new):
                return False
            todo += zip(old, new)
        elif isinstance(old, _NUMBERS) and isinstance(new, _NUMBERS):
            # A writer may turn 0.0 into 0 when it rewrites a page.
            if float(old) != float(new):
                return False
        elif isinstance(old, NullObject) != isinstance(new, NullObject):
            return False
        elif not isinstance(old, NullObject) and (type(old) is not type(new) or old != new):
            # PyPDF2 nulls never compare equal, hence the two branches.
            return False
    return True


def _same_start(old, new):
    return len(new) >= len(old) and all(_same(a, b) for a, b in zip(old, new))


def _signature_blocks(frozen, signed_pdf):
    """The (block area, page area) of each page that got the new field; None when the update is more than adding one signature."""
    written = _update_objects(frozen, signed_pdf)
    if written is None:
        return None
    old, new = PdfFileReader(io.BytesIO(frozen), strict=False), PdfFileReader(io.BytesIO(signed_pdf), strict=False)
    # Readers disagree on a repeated key and on a stream longer or shorter than its /Length: strict reading refuses both.
    new.strict = True
    for number in written:
        new.get_object(IndirectObject(number, 0, new))
    new.strict = False
    old_root, new_root = old.trailer['/Root'], new.trailer['/Root']
    old_form, new_form = _resolve(old_root.get('/AcroForm')) or {}, _resolve(new_root.get('/AcroForm')) or {}
    old_fields, new_fields = list(_resolve(old_form.get('/Fields')) or []), list(_resolve(new_form.get('/Fields')) or [])
    unchanged = (
        not new.is_encrypted and len(old.pages) == len(new.pages) and _same(old.trailer.raw_get('/Root'), new.trailer.raw_get('/Root'))
        and all(_same(old_form.get(key), new_form.get(key)) for key in (set(old_form) | set(new_form)) - FORM_KEYS)
        and len(new_fields) == len(old_fields) + 1 and _same_start(old_fields, new_fields)
    )
    if not unchanged:
        return None
    field_ref = new_fields[-1]
    field = _resolve(field_ref)
    if not (isinstance(field_ref, IndirectObject) and set(field) <= FIELD_KEYS and field.get('/FT') == '/Sig' and field.get('/Subtype') == '/Widget'):
        return None
    blocks = []
    for old_page, new_page in zip(old.pages, new.pages):
        old_annots, new_annots = list(_resolve(old_page.get('/Annots')) or []), list(_resolve(new_page.get('/Annots')) or [])
        added = new_annots[len(old_annots):]
        if not _same_start(old_annots, new_annots) or any(annot != field_ref for annot in added):
            return None
        if added:
            left, bottom, right, top = (float(number) for number in field['/Rect'])
            blocks.append((abs((right - left) * (top - bottom)), float(new_page.mediabox.width) * float(new_page.mediabox.height)))
    read_as_written = all(new.xref.get(0, {}).get(number) == offset for number, offset in written.items())
    return blocks if read_as_written and new.xref_objStm.items() <= old.xref_objStm.items() else None
