from odoo import api, models
from odoo.exceptions import MissingError
from odoo.tools import BinaryBytes

from .client_call import LOOKUP_BOUNDARY

SKIPPED_FIELDS = frozenset({'write_date', 'write_uid', 'create_date', 'create_uid', '__last_update'})
# secrets whose field group is the internal users': logged as "changed" all the same
MASKED_FIELDS = frozenset({('ir.attachment', 'access_token')})
VALUE_LENGTH = 200
WINDOW = 20


def cut_texts(old, new):
    """ Cut both texts to VALUE_LENGTH; when their heads are equal, cut a window around the first difference. """
    if old != new and old[:VALUE_LENGTH] == new[:VALUE_LENGTH]:
        at = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
        start = max(0, at - WINDOW)

        def window(text):
            end = start + 2 * WINDOW
            return ('...' if start else '') + text[start:end] + ('...' if end < len(text) else '')
        return window(old), window(new)
    return tuple(text if len(text) <= VALUE_LENGTH else text[:VALUE_LENGTH] + '...' for text in (old, new))


class Base(models.AbstractModel):
    _inherit = 'base'

    def _gec_audit(self, operation):
        """ Whether ``operation`` on this model, by the current user, is logged. """
        if self.env.su or not self.env.registry.ready:
            return False
        return self.env['gec.user.audit.rule']._gec_should_log(self._name, operation, self.env.uid)

    def _gec_audit_value(self, name):
        """ Snapshot full values, never display text: compare them before truncating. """
        field = self._fields[name]
        if field.translate:
            return dict(self._get_stored_translations(name) or {})
        value = self[name]
        if field.type == 'binary':
            if not value:
                return False
            if isinstance(value, BinaryBytes):
                return self.env['ir.attachment']._compute_checksum(value.content)
            return value.checksum
        if field.type == 'many2one':
            return value.id
        if field.type in ('one2many', 'many2many'):
            return tuple(sorted(value.ids))
        if field.type == 'properties':
            return dict(value._values)
        return value

    def _gec_audit_texts(self, name, ids, olds, news):
        """ The texts of the changes; resolves names of only the first ten relation changes, else shows model,id. """
        field = self._fields[name]
        if field.translate:
            return ['; '.join(
                f"[{lang}] {' → '.join(cut_texts(old.get(lang, ''), new.get(lang, '')))}"
                for lang in sorted(old.keys() | new.keys()) if old.get(lang) != new.get(lang)
            ) for old, new in zip(olds, news)]
        if field.type == 'binary':
            return [self.env._("(file) added") if not old else self.env._("(file) removed") if not new else self.env._("(file) replaced")
                    for old, new in zip(olds, news)]
        if field.type == 'properties':
            texts = []
            for id_, old, new in zip(ids, olds, news):
                definition = field._get_properties_definition(self.sudo().browse(id_)) or ()
                labels = {prop['name']: prop.get('string') or prop['name'] for prop in definition}
                keys = [key for key in {**old, **new} if old.get(key) != new.get(key)]
                texts.append(self.env._("changed (%s)", ', '.join(labels.get(key, key) for key in keys)))
            return texts
        if field.relational:
            many2one = field.type == 'many2one'
            if many2one:
                differences = [([old] if old else [], [new] if new else []) for old, new in zip(olds, news)]
            else:
                differences = []
                for old, new in zip(olds, news):
                    old_ids, new_ids = set(old), set(new)
                    differences.append(([id_ for id_ in old if id_ not in new_ids], [id_ for id_ in new if id_ not in old_ids]))
            comodel = self.env[field.comodel_name].sudo().with_context(active_test=False)
            records = comodel.browse(sorted({id_ for pair in differences for related_ids in pair for id_ in related_ids[:10]})).exists()
            names = {record.id: record.display_name for record in records}

            def record_name(id_):
                value = names.get(id_) or f'{field.comodel_name},{id_}'
                return value[:VALUE_LENGTH] + '...' if len(value) > VALUE_LENGTH else value

            def listing(sign, related_ids):
                text = ', '.join(f'{sign}{record_name(id_)}' for id_ in related_ids[:10])
                return text + (self.env._(" (+%s more)", len(related_ids) - 10) if len(related_ids) > 10 else '')

            texts = []
            for old, new in differences:
                if many2one:
                    texts.append(f"{record_name(old[0]) if old else ''} → {record_name(new[0]) if new else ''}")
                else:
                    texts.append('; '.join(filter(None, (listing('+', new), listing('-', old)))))
            return texts
        if field.type == 'selection':
            selection = dict(field._description_selection(self.env))
            olds = [selection.get(raw, raw or '') for raw in olds]
            news = [selection.get(raw, raw or '') for raw in news]

        def as_text(raw):
            return '' if raw is False and field.type != 'boolean' else str(raw)

        return [' → '.join(cut_texts(as_text(old), as_text(new))) for old, new in zip(olds, news)]

    def _gec_audit_values(self, names):
        """ The compared values of the fields, read as the superuser, per record id. """
        records = self.sudo().with_context(active_test=False, prefetch_fields=False)
        return {record.id: {name: record._gec_audit_value(name) for name in names} for record in records}

    def _gec_audit_names(self, vals):
        return [
            name for name in vals
            if name in self._fields and name not in SKIPPED_FIELDS and self._fields[name].store
            # computed fields count when a person can edit them (a price, a salesperson)
            and not (self._fields[name].compute and self._fields[name].readonly)
        ]

    def _gec_audit_buffer(self, vals_list):
        self.env['gec.user.audit.log']._gec_buffer(vals_list)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if records and self._gec_audit('create'):
            Log = self.env['gec.user.audit.log']
            self._gec_audit_buffer([Log._gec_values('create', model=self._name, res_id=record.id, res_name=record.sudo().display_name,
                method='create') for record in records])
        return records

    def write(self, vals):
        """ Log what changed by comparing raw values before and after, never their text. A field in a group other than
        the internal users, or in MASKED_FIELDS, shows only "changed". exists() runs only when a read raises
        MissingError (stale or deleted in the write), as core does, to avoid a query per write. """
        if not self or not self._gec_audit('write'):
            return super().write(vals)
        names = self._gec_audit_names(vals)
        if not names:
            return super().write(vals)
        records = self
        try:
            before = records._gec_audit_values(names)
        except MissingError:
            records = self.exists()
            if not records:
                return super().write(vals)
            before = records._gec_audit_values(names)
        result = super().write(vals)
        try:
            after = records._gec_audit_values(names)
        except MissingError:
            records = records.exists()
            after = records._gec_audit_values(names)
        Log = self.env['gec.user.audit.log']
        labels = {name: self._fields[name]._description_string(self.env) for name in names}
        restricted = {
            name for name in names
            if (self._fields[name].groups and self._fields[name].groups != 'base.group_user')
            or (self._name, name) in MASKED_FIELDS
        }
        changes = {record.id: [] for record in records}
        for name in names:
            ids = [record.id for record in records if before[record.id][name] != after[record.id][name]]
            if not ids:
                continue
            if name in restricted:
                texts = [self.env._("%s: changed", labels[name])] * len(ids)
            else:
                shown = self._gec_audit_texts(name, ids, [before[id_][name] for id_ in ids], [after[id_][name] for id_ in ids])
                texts = [f"{labels[name]}: {text}" for text in shown]
            for id_, text in zip(ids, texts):
                changes[id_].append(text)
        lines = [Log._gec_values('write', model=self._name, res_id=record.id, res_name=record.sudo().display_name, method='write',
            changes='\n'.join(changes[record.id])) for record in records if changes[record.id]]
        self._gec_audit_buffer(lines)
        return result

    def unlink(self):
        if not self or not self._gec_audit('unlink'):
            return super().unlink()
        Log = self.env['gec.user.audit.log']
        lines = [Log._gec_values('unlink', model=self._name, res_id=record.id, res_name=record.sudo().display_name,
            method='unlink') for record in self.sudo().exists()]
        result = super().unlink()
        self._gec_audit_buffer(lines)
        return result

    def _gec_audit_read(self, method, ids, fields=None, count=None):
        """Log a supported client read once, leaving internal ORM reads unrecorded."""
        if LOOKUP_BOUNDARY.get() == (self._name, method):
            return
        if not (self._gec_rpc_entry(method) and self._gec_audit('read')):
            return
        ids = [record_id for record_id in ids if isinstance(record_id, int)]
        self._gec_audit_buffer([self.env['gec.user.audit.log']._gec_values('read', model=self._name, method=method, record_ids=ids,
            record_count=len(ids) if count is None else count, detail=', '.join(sorted(fields)) if fields else False)])

    def _gec_audit_lookup_result(self, method, result):
        """Record final lookup results, including overrides which bypass base hooks."""
        if method == 'name_search':
            self._gec_audit_read(method, [id_ for id_, _name in result])
        elif method == 'web_name_search':
            self._gec_audit_read(method, [row['id'] for row in result])

    @api.model
    def search(self, domain, offset=0, limit=None, order=None):
        """Record explicit client searches without logging nested ORM searches."""
        result = super().search(domain, offset=offset, limit=limit, order=order)
        self._gec_audit_read('search', result.ids)
        return result

    @api.model
    def search_count(self, domain, limit=None):
        result = super().search_count(domain, limit=limit)
        self._gec_audit_read('search_count', [], count=result)
        return result

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        result = super().name_search(name, domain=domain, operator=operator, limit=limit)
        self._gec_audit_read('name_search', [id_ for id_, _name in result])
        return result

    @api.model
    def web_name_search(self, name, specification, domain=None, operator='ilike', limit=100):
        """Record the web client's name lookup once, including nested reads."""
        result = super().web_name_search(name, specification, domain=domain, operator=operator, limit=limit)
        self._gec_audit_read('web_name_search', [row['id'] for row in result], specification)
        return result

    def get_field_translations(self, field_name, langs=None):
        result = super().get_field_translations(field_name, langs=langs)
        self._gec_audit_read('get_field_translations', self.ids, [field_name])
        return result

    def read(self, fields=None, load='_classic_read'):
        result = super().read(fields, load)
        self._gec_audit_read('read', self.ids, fields)
        return result

    def web_read(self, specification):
        result = super().web_read(specification)
        self._gec_audit_read('web_read', self.ids, specification)
        return result

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, **read_kwargs):
        result = super().search_read(domain, fields, offset, limit, order, **read_kwargs)
        self._gec_audit_read('search_read', [row.get('id') for row in result], fields)
        return result

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        result = super().web_search_read(domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)
        self._gec_audit_read('web_search_read', [row.get('id') for row in result.get('records', ())], specification)
        return result

    @api.model
    def web_read_group(self, domain, groupby=(), aggregates=(), *args, **kwargs):
        result = super().web_read_group(domain, groupby, aggregates, *args, **kwargs)
        if isinstance(result, dict):
            self._gec_audit_read('web_read_group', [], groupby, count=len(result.get('groups', ())))
        return result

    @api.model
    def formatted_read_group(self, domain, groupby=(), aggregates=(), *args, **kwargs):
        result = super().formatted_read_group(domain, groupby, aggregates, *args, **kwargs)
        self._gec_audit_read('formatted_read_group', [], groupby, count=len(result))
        return result

    @api.model
    def read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        """Record public grouped reads without recording their internal queries."""
        result = super().read_group(domain, groupby, aggregates, having, offset, limit, order)
        self._gec_audit_read('read_group', [], groupby, count=len(result))
        return result

    @api.model
    def formatted_read_grouping_sets(self, domain, grouping_sets, aggregates=(), *, order=None):
        result = super().formatted_read_grouping_sets(domain, grouping_sets, aggregates, order=order)
        fields = {name for grouping in grouping_sets for name in grouping}
        self._gec_audit_read('formatted_read_grouping_sets', [], fields, count=sum(map(len, result)))
        return result

    def export_data(self, fields_to_export):
        result = super().export_data(fields_to_export)
        if (self._gec_rpc_entry('export_data') or self._gec_rpc_entry('*')) and self._gec_audit('export'):
            self._gec_audit_buffer([self.env['gec.user.audit.log']._gec_values('export', model=self._name, method='export_data', record_ids=self.ids,
                detail=', '.join(fields_to_export))])
        return result

    @api.model
    def load(self, fields, data):
        result = super().load(fields, data)
        if self._gec_audit('import'):
            ids = [record_id for record_id in result.get('ids') or () if record_id]
            self._gec_audit_buffer([self.env['gec.user.audit.log']._gec_values('import', model=self._name, method='load', record_ids=ids,
                detail=', '.join(fields))])
        return result
