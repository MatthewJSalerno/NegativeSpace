"""Read-only edit plans and first-sidecar construction; no file publication or edits.

Common-field edits are validated as one request. Catalog previews are not
filesystem verification, collision reservations or authorization to execute a plan.
"""
import base64
import contextlib
import copy
from datetime import datetime
import hashlib
import json
from pathlib import PurePosixPath, Path
import re
from xml.sax import saxutils

from engine import metadata, metadata_adapter, metadata_capture, metadata_decisions, metadata_gps, metadata_save, ns_db, xmp
from engine.metadata import MetadataSource

EDITABLE = frozenset({'date_taken', 'orientation', 'title', 'caption', 'keywords', 'rating', 'creators', 'rights', 'gps'})
_EXIF_DATE = re.compile(r'([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]+))?([+-][0-9]{2}:[0-9]{2})?')
NEW_SIDECAR = 'new_sidecar'


def _changes(changes):
    if not isinstance(changes, dict) or not changes or not set(changes) <= EDITABLE:
        raise ValueError('Expected explicit supported metadata changes')
    copied = metadata._json_copy(changes)
    result = metadata_adapter.for_comparison(MetadataSource('edit', 'embedded', {}, copied)).fields
    if result.get('orientation') == '':
        raise ValueError('An empty Orientation is not supported; use explicit field removal')
    if 'gps' in result:metadata_gps.validate(result['gps'],editing=True)
    # Use the standard language-alternative form for new Dublin Core text.
    for field in ('title','caption','rights'):
        if field in result and isinstance(result[field],str):result[field]={'x-default':result[field]}
        if field in result and any(re.fullmatch(r'[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*',lang) is None for lang in result[field]):
            raise ValueError('Invalid language identifier')
    for value in result.values():
        if len(json.dumps(value,ensure_ascii=False).encode('utf-8'))>xmp.MAX_BYTES:
            raise ValueError('Metadata edit exceeds the bounded packet size')
    return result


def _removals(fields, changes):
    if not isinstance(changes, dict):
        raise ValueError('Expected explicit metadata changes')
    if not isinstance(fields, (list, tuple)) or any(not isinstance(f, str) for f in fields):
        raise ValueError('Expected supported fields to remove')
    if len(fields) != len(set(fields)) or not set(fields) <= EDITABLE or set(fields) & set(changes):
        raise ValueError('Invalid or conflicting metadata removals')
    return sorted(fields)


def _removal_edits(kind, fields):
    if kind == 'embedded_exif':
        tags = {field:[tag for tag,mapped in metadata_adapter._EMBEDDED.items() if mapped == field]
                for field in EDITABLE}
        tags['date_taken'] = ['ExifIFD:DateTimeOriginal','ExifIFD:SubSecTimeOriginal','ExifIFD:OffsetTimeOriginal']
        tags['gps'] = sorted(metadata_adapter.GPS_KEYS)
        return [{'tag':tag,'operation':'remove','value':None} for field in fields for tag in tags[field]]
    return [{**edit, 'operation':'remove', 'value':None}
            for edit in _tag_edits(kind, {f:({} if f == 'gps' else '') for f in fields})]


def first_sidecar(changes):
    """Construct a minimal new XMP containing only requested, validated fields.

    Never use this to replace an existing sidecar: unrelated/unknown properties in
    that original need a preservation-aware writer and read-back verification.
    """
    changes = _changes(changes)
    names = {'date_taken':'exif:DateTimeOriginal', 'orientation':'tiff:Orientation',
             'title':'dc:title','caption':'dc:description','keywords':'dc:subject',
             'creators':'dc:creator','rights':'dc:rights','rating':'xmp:Rating'}
    properties=[]
    for key,value in sorted(changes.items()):
        if key=='gps':
            gps=value or {'latitude':'','longitude':''}
            properties.extend(f'<exif:{tag}>{saxutils.escape(gps[part])}</exif:{tag}>'
                              for tag,part in metadata_gps.PARTS.items() if part in gps)
            continue
        if isinstance(value,dict):
            body='<rdf:Alt>'+''.join('<rdf:li xml:lang='+saxutils.quoteattr(lang)+'>'+saxutils.escape(text)+'</rdf:li>'
                                    for lang,text in value.items())+'</rdf:Alt>'
        elif isinstance(value,list):
            array='Bag' if key=='keywords' else 'Seq'
            body=f'<rdf:{array}>'+''.join('<rdf:li>'+saxutils.escape(text)+'</rdf:li>' for text in value)+f'</rdf:{array}>'
        else:body=saxutils.escape(str(value))
        properties.append(f'<{names[key]}>{body}</{names[key]}>')
    packet = (f'<x:xmpmeta xmlns:x="{xmp.XMP_META}"><rdf:RDF xmlns:rdf="{xmp.RDF}">'
              f'<rdf:Description rdf:about="" xmlns:exif="{xmp.EXIF}" xmlns:tiff="{xmp.TIFF}" '
              f'xmlns:dc="{xmp.DC}" xmlns:xmp="{xmp.XAP}">'
              f'{"".join(properties)}</rdf:Description></rdf:RDF></x:xmpmeta>').encode('utf-8')
    parsed = xmp.parse_bytes(packet, source_id='new')
    if parsed.state != 'valid' or metadata_adapter.for_comparison(parsed.source).fields != changes:
        raise ValueError('Generated XMP did not preserve the requested values')
    return packet


def _tag_edits(kind, changes):
    edits = []
    for field,value in sorted(changes.items()):
        if kind != 'embedded_exif':
            tags={'date_taken':'XMP-exif:DateTimeOriginal','orientation':'XMP-tiff:Orientation',
                  'title':'XMP-dc:Title','caption':'XMP-dc:Description','keywords':'XMP-dc:Subject',
                  'creators':'XMP-dc:Creator','rights':'XMP-dc:Rights','rating':'XMP-xmp:Rating'}
            if field=='gps':
                for name,part in metadata_gps.PARTS.items():
                    edits.append({'tag':'XMP-exif:'+name,'operation':'set' if part in value else 'remove','value':value.get(part)})
            else:edits.append({'tag':tags[field], 'operation':'set', 'value':value})
        elif field == 'orientation':
            edits.append({'tag':'IFD0:Orientation','operation':'set','value':value})
        elif field == 'date_taken':
            match = _EXIF_DATE.fullmatch(value)
            if match is None:
                raise ValueError('Embedded EXIF date planning requires a complete date and time; partial/blank dates need XMP')
            day, clock, fraction, offset = match.groups()
            edits.append({'tag':'ExifIFD:DateTimeOriginal','operation':'set',
                          'value':day.replace('-',':') + ' ' + clock})
            for tag,component in (('SubSecTimeOriginal',fraction),('OffsetTimeOriginal',offset)):
                edits.append({'tag':'ExifIFD:' + tag,'operation':'set' if component is not None else 'remove',
                              'value':component})
        elif field in ('title', 'caption', 'rights'):
            if not isinstance(value, dict) or set(value) != {'x-default'}:
                raise ValueError('EXIF text requires exactly one default-language value; choose XMP explicitly for localized text')
            text = value['x-default']
            if not text or '\x00' in text or (field != 'title' and not text.isascii()):
                raise ValueError('This EXIF text value is not losslessly representable; no primary was changed')
            tag = {'title':'XPTitle', 'caption':'ImageDescription', 'rights':'Copyright'}[field]
            edits.append({'tag':'IFD0:'+tag, 'operation':'set', 'value':text})
        elif field in ('creators', 'keywords'):
            if not isinstance(value, list) or not value or any(not text or '\x00' in text for text in value):
                raise ValueError('Empty EXIF lists require XMP; use explicit field removal to remove the EXIF value')
            if field == 'creators':
                if len(value) != 1 or not value[0].isascii():
                    raise ValueError('EXIF Artist supports one ASCII creator; choose XMP explicitly for other values')
                tag, text = 'Artist', value[0]
            else:
                if any(';' in text for text in value):
                    raise ValueError('EXIF keywords cannot preserve a semicolon inside a keyword')
                tag, text = 'XPKeywords', ';'.join(value)
            edits.append({'tag':'IFD0:'+tag, 'operation':'set', 'value':text})
        elif field == 'rating':
            if value not in ('0','1','2','3','4','5'):
                raise ValueError('EXIF Rating supports whole values from zero through five')
            edits.append({'tag':'IFD0:Rating', 'operation':'set', 'value':int(value)})
        else:
            raise ValueError('This field requires further EXIF writer qualification; no primary was changed')
    return edits


def _folder(fields, original_year):
    value = fields.get('date_taken')
    if isinstance(value,str) and len(value) >= 10 and xmp._valid_date(value):
        # Calendar components exactly as recorded; an offset never shifts the day.
        return PurePosixPath('library',value[:4],value[5:7],value[8:10])
    if type(original_year) is not int or not 1 <= original_year <= 9999:
        raise ValueError('Undated filing requires the original source modification year')
    return PurePosixPath('library','Undated',f'{original_year:04d}')


def write_target(sources, *, primary_id, settings, photo_name):
    """Resolve the qualified write target without proposing any field changes."""
    preferences = {**ns_db.METADATA_DEFAULTS, **{k:v for k,v in settings.items() if k in ns_db.METADATA_DEFAULTS}}
    ns_db.validate_settings(preferences)
    extension = Path(photo_name).suffix.lower()
    raw = extension in ns_db.RAW_EXTENSIONS
    if extension not in ns_db.SUPPORTED_EXTENSIONS:
        raise ValueError('Metadata writes for this file format are not specified')
    order = [key for key in ('embedded_xmp','exif') if key in sources]
    if primary_id is not None:
        if primary_id not in sources:
            raise ValueError('The established primary source is unavailable')
        target = primary_id
    else:
        if any(source.get('kind') == 'sidecar_xmp' for source in sources.values()):
            raise ValueError('Resolve the existing sidecar primary before planning an edit')
        preference = preferences['metadata_write_raw' if raw else 'metadata_write_non_raw']
        target = NEW_SIDECAR if preference == 'xmp' else (order[0] if order else 'exif')
    creating = target == NEW_SIDECAR
    kind = 'sidecar_xmp' if creating else sources.get(target,{}).get('kind','embedded_exif')
    if kind not in ('sidecar_xmp','embedded_xmp','embedded_exif'):
        raise ValueError('Unknown primary source kind')
    if raw and kind != 'sidecar_xmp':
        raise ValueError('Embedded RAW editing requires a separately implemented consent and verified-write path')
    if kind != 'sidecar_xmp' and extension not in ('.jpg','.jpeg','.jpe','.jfif'):
        raise ValueError('Embedded writing is qualified for JPEG only; choose a sidecar primary explicitly')
    return target, kind, creating


def plan(sources, *, primary_id, changes, settings, photo_name, original_year, current_relative_path, remove_fields=()):
    """Plan changes against captured sources, never mutate them or choose a new donor.

    Caller binds captures/settings/file identity before execution. This function cannot
    prove on-disk files are current. Empty XMP values suppress fallback; missing values
    still fall through. A new sidecar contains only edited fields, not a metadata clone.
    """
    name = xmp.relative_path(photo_name)
    if len(name.parts) != 1 or name.name in ('.','..'):
        raise ValueError('Expected a photo filename, not a path')
    current = xmp.relative_path(current_relative_path)
    if current.parts[0] != 'library' or current.name != name.name:
        raise ValueError('Edits must target the current Library filename')
    sources = metadata._json_copy(sources)
    if not isinstance(sources,dict) or NEW_SIDECAR in sources:
        raise ValueError('Expected captured sources without a proposed new sidecar')
    if any(not isinstance(v,dict) or not isinstance(v.get('fields'),dict) for v in sources.values()):
        raise ValueError('Expected captured source fields')
    remove_fields = _removals(remove_fields, changes)
    changes = _changes(changes) if changes or not remove_fields else {}
    target, kind, creating = write_target(sources, primary_id=primary_id, settings=settings, photo_name=name)
    before = metadata_capture.resolve(sources, list(sources) if primary_id else [key for key in ('embedded_xmp','exif') if key in sources], primary_id=primary_id)
    removal_edits = _removal_edits(kind, remove_fields)
    if creating and remove_fields:
        raise ValueError('Cannot remove fields from a sidecar that does not exist')
    after_sources = copy.deepcopy(sources)
    after_sources.setdefault(target,{'kind':kind,'fields':{}})['fields'].update(changes)
    for field in remove_fields:
        after_sources[target]['fields'].pop(field, None)
    after = metadata_capture.resolve(after_sources,list(after_sources),primary_id=target)
    target_fields = after_sources[target]['fields']
    differences = [{'field':key, 'before':{'present':key in before['proposed_effective'],
                    'value':before['proposed_effective'].get(key)}, 'after':value,
                    'previous_source':before['field_sources'].get(key), 'new_source':target}
                   for key,value in sorted(changes.items())]
    differences.extend({'field':key, 'before':{'present':key in before['proposed_effective'],
                        'value':before['proposed_effective'].get(key)}, 'after':after['proposed_effective'].get(key),
                        'after_present':key in after['proposed_effective'], 'operation':'remove',
                        'previous_source':before['field_sources'].get(key),
                        'new_source':after['field_sources'].get(key)} for key in remove_fields)
    proposed = _folder(after['proposed_effective'],original_year)/name if 'date_taken' in changes or 'date_taken' in remove_fields else current
    result = {'version':1,'mode':'preview_only','applied':False,'changes':changes,
              'primary_before':primary_id,'primary_after':target,'sources_before':sources,
              'target':{'source_id':target,'kind':kind,'create':creating,
                        'sidecar_name':str(name)+'.xmp' if kind=='sidecar_xmp' else None},
              'before':before,'after':after,'target_fields_after':target_fields,
              'tag_edits':_tag_edits(kind,changes)+removal_edits,'differences':differences,
              'filing':{'current':current.as_posix(),'proposed':proposed.as_posix(),
                        'change':current != proposed,'collision_check_pending':True},
              'filesystem_verification_pending':True}
    if remove_fields:
        result['remove_fields'] = remove_fields
    if creating:
        result['new_sidecar_base64'] = base64.b64encode(first_sidecar(changes)).decode('ascii')
    return result


def _catalog_state(db_path, *, photo_id, capture_id, destination_root, settings=None, allow_primary_choice=False, allow_rejected=False):
    """Read captured sources plus the last verified edit in one catalog snapshot."""
    if type(photo_id) is not int or not 1 <= photo_id <= 2**63-1:
        raise ValueError('Invalid photo identity')
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        conn.execute('BEGIN')
        row = conn.execute('SELECT pf.file_id,pf.revision,p.status,p.dest_path,p.sha1_hash '
                           'FROM photos p JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?',(photo_id,)).fetchone()
        statuses = ('Copied','Completed','Found_At_Destination') + (('Rejected','Rejected_Copied') if allow_rejected else ())
        if row is None or row[2] not in statuses or not row[3]:
            raise ValueError('Metadata edit previews require an organized Library photo')
        file_id, revision, status, dest_path, digest = row
        captured_file,_,report,_ = metadata_decisions._capture(conn,capture_id,allow_edited=True)
        if captured_file != file_id:
            raise ValueError('Capture belongs to a different photo')
        if report['issues'] and not allow_primary_choice:
            raise ValueError('Resolve capture issues before planning an edit')
        saved = metadata_decisions.current(conn,'primary',str(file_id))
        sources, primary_id = report['sources'], None
        activated = metadata_save.active(conn, photo_id)
        if saved:
            primary_id = saved['value']['primary_id']
            original = conn.execute('SELECT catalog_sha1,report_json FROM metadata_captures WHERE capture_id=?',
                                    (saved['capture_id'],)).fetchone()
            if original[0] != digest and not (activated and activated.get('content_changed') and activated['sha1_hash']==digest):
                raise ns_db.RevisionConflict('Photo content changed since the primary decision; reconcile before editing')
            sources = json.loads(original[1])['sources']
        if activated:
            if activated['sha1_hash'] != digest:
                raise ns_db.RevisionConflict('Photo content changed after the last verified metadata edit')
            if not allow_primary_choice and (saved['revision'] if saved else 0) != activated['primary_revision']:
                raise ns_db.RevisionConflict('A different primary choice awaits verified activation')
            sources, primary_id = activated['sources'], activated['primary_id']
        original = conn.execute('SELECT file_mtime FROM source_snapshots WHERE file_id=?',(file_id,)).fetchone()
        original_year = datetime.fromtimestamp(original[0]).year if original and original[0] is not None else None
        settings = settings if settings is not None else {key:item['value'] for key,item in ns_db.read_settings(conn).items() if key in ns_db.METADATA_DEFAULTS}
        root = Path(destination_root)
        if not root.is_absolute():
            raise ValueError('Expected the configured absolute destination root')
        relative = Path(dest_path).relative_to(root).as_posix()
        binding = {'photo_id':photo_id,'file_id':file_id,'file_revision':revision,'sha1':digest,
            'capture_id':capture_id,'primary_revision':saved['revision'] if saved else 0,
            'settings':{k:settings.get(k,v) for k,v in ns_db.METADATA_DEFAULTS.items()},'destination_root':str(root)}
        return sources, primary_id, original_year, relative, binding


def _token(result):
    result.pop('token', None)
    result['token'] = hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return result


def preview_catalog(db_path, *, photo_id, capture_id, changes, destination_root, settings=None, remove_fields=()):
    """Read-only identity-bound preview; never silently changes the primary source."""
    sources, primary, year, relative, binding = _catalog_state(db_path, photo_id=photo_id,
        capture_id=capture_id, destination_root=destination_root, settings=settings)
    result = plan(sources, primary_id=primary, changes=changes, settings=binding['settings'],
        photo_name=Path(relative).name, original_year=year, current_relative_path=relative, remove_fields=remove_fields)
    result['binding'] = binding
    return _token(result)


def _donor(conn, selection):
    """Resolve one immutable, associated donor without borrowing fallback fields."""
    from engine import xmp_store
    if not isinstance(selection, dict) or set(selection) not in (
            {'photo_id','capture_id','source_id'}, {'photo_id','version_id'}):
        raise ValueError('Expected a captured source or retained XMP version donor')
    donor_photo = selection['photo_id']
    if type(donor_photo) is not int or not 1 <= donor_photo <= 2**63-1:
        raise ValueError('Invalid donor photo')
    owner = conn.execute('SELECT pf.file_id,p.dest_path FROM photo_files pf JOIN photos p ON p.id=pf.photo_id '
                         'WHERE p.id=?', (donor_photo,)).fetchone()
    if not owner:
        raise ValueError('Unknown donor photo')
    if 'version_id' in selection:
        version = selection['version_id']
        if type(version) is not int or not 1 <= version <= 2**63-1:
            raise ValueError('Invalid donor metadata version')
        retained = conn.execute("SELECT file_id FROM file_states WHERE current_path=? AND location_role='destination' "
            "AND presence_state='present'", (owner[1],)).fetchone()
        identities = (owner[0], retained[0] if retained else owner[0])
        if not conn.execute('SELECT 1 FROM xmp_arrivals a JOIN xmp_arrival_files f USING(arrival_id) '
            'WHERE a.version_id=? AND f.file_id IN (?,?)', (version, *identities)).fetchone():
            raise ValueError('The XMP version does not belong to this donor photo')
        packet = xmp_store.original_bytes(conn, version)
        parsed = xmp.parse_bytes(packet, source_id='donor')
        if parsed.state != 'valid':
            raise ValueError('The donor XMP is not usable metadata')
        fields = metadata_adapter.for_comparison(parsed.source).fields
        evidence = {**selection, 'sha256':hashlib.sha256(packet).hexdigest()}
    else:
        if not isinstance(selection['source_id'], str):
            raise ValueError('Invalid donor source identifier')
        donor_capture = selection['capture_id']
        if type(donor_capture) is not int or not 1 <= donor_capture <= 2**63-1:
            raise ValueError('Invalid donor capture')
        row = conn.execute('SELECT report_json,catalog_sha1 FROM metadata_captures WHERE capture_id=? AND file_id=?',
                           (donor_capture, owner[0])).fetchone()
        if not row:
            raise ValueError('The capture does not belong to this donor photo')
        report = json.loads(row[0])
        source = report['sources'].get(selection['source_id'])
        if source is None or report['issues']:
            raise ValueError('The donor source is unavailable or needs attention')
        fields = source['fields']
        evidence = {**selection, 'photo_sha1':row[1]}
    return fields, evidence


def preview_copy(db_path, *, photo_id, capture_id, changes, copy_fields, destination_root, settings=None, base=None):
    """Copy explicit whole fields from immutable captures or retained XMP versions.

    Donor selection never changes the target primary. Absence is not a clearing
    instruction, and a Location/Date comes from one source with all its companions.
    A base supplies its present supported fields; absent fields remain unchanged,
    never inferred as clears. Explicit changes/donors override that base.
    Every donor must be associated with a catalog photo; arbitrary blob IDs refuse.
    """
    if not isinstance(copy_fields, dict) or (not copy_fields and base is None) or not set(copy_fields) <= EDITABLE:
        raise ValueError('Choose supported logical fields to copy')
    if not isinstance(changes, dict) or set(changes) & set(copy_fields):
        raise ValueError('A field cannot have both a typed value and a donor')
    composed = metadata._json_copy(changes)
    donors = {}
    base_fields, base_evidence = {}, None
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        conn.execute('BEGIN')
        if base is not None:
            base_fields, base_evidence = _donor(conn, base)
            composed = {key:metadata._json_copy(value) for key,value in base_fields.items() if key in EDITABLE}
            donors = {key:base_evidence for key in composed}
            composed.update(metadata._json_copy(changes))
            for key in changes:
                donors.pop(key, None)
        for field, selection in copy_fields.items():
            fields, evidence = _donor(conn, selection)
            if field not in fields:
                raise ValueError('The selected donor field is absent; use explicit Clear instead of guessing')
            composed[field] = metadata._json_copy(fields[field])
            donors[field] = evidence
    result = preview_catalog(db_path, photo_id=photo_id, capture_id=capture_id, changes=composed,
                             destination_root=destination_root, settings=settings)
    result['composition'] = {'changes':metadata._json_copy(changes), 'copy_fields':metadata._json_copy(copy_fields),
                             'donors':donors}
    if base is not None:
        composition = result['composition']
        composition.update(base=metadata._json_copy(base), base_evidence=base_evidence,
                           base_absent_fields=sorted(EDITABLE-set(base_fields)))
        effective = result['after']['proposed_effective']
        composition['fields'] = {
            field: {'present':field in effective, 'value':effective.get(field),
                    'origin':('typed' if field in changes else 'override' if field in copy_fields
                              else 'base' if field in composed else 'unchanged'),
                    'donor':donors.get(field),
                    'effective_source':result['after']['field_sources'].get(field)}
            for field in sorted(EDITABLE)}
    return _token(result)


def preview_primary(db_path, *, photo_id, capture_id, version_id, destination_root, settings=None):
    """Deliberate activation of one retained, associated XMP version in Library.

    This chooses a complete packet; it is separate from copying fields into the
    existing primary. No caller-supplied packet, filesystem path or fields are trusted.
    """
    from engine import metadata_incoming, xmp_store
    if type(version_id) is not int or not 1 <= version_id <= 2**63-1:
        raise ValueError('Invalid metadata version')
    sources, primary, year, relative, binding = _catalog_state(db_path, photo_id=photo_id,
        capture_id=capture_id, destination_root=destination_root, settings=settings, allow_primary_choice=True)
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        retained = conn.execute("SELECT file_id FROM file_states WHERE current_path=? AND location_role='destination' "
            "AND presence_state='present'", (str(Path(destination_root)/relative),)).fetchone()
        if not retained:
            raise ValueError('No retained destination identity')
        linked = conn.execute("SELECT 1 FROM xmp_arrivals a JOIN xmp_arrival_files f USING(arrival_id) "
            "WHERE a.version_id=? AND f.file_id IN (?,?) AND f.role='owner'",
            (version_id, binding['file_id'], retained[0])).fetchone()
        incoming = any(v['version_id']==version_id for d in metadata_incoming.alternatives(conn, retained[0])
                       for v in d['versions'])
        if not linked and not incoming:
            raise ValueError('This XMP version has no confirmed association with the photo')
        data = xmp_store.original_bytes(conn, version_id)
        parsed = xmp.parse_bytes(data, source_id='primary')
        if parsed.state != 'valid':
            raise ValueError('An unreadable XMP cannot become primary')
        fields = metadata_adapter.for_comparison(parsed.source).fields
    return _primary_preview(sources, primary, year, relative, binding, version_id, data, fields)


def _primary_preview(sources, primary, year, relative, binding, version_id, data, fields):
    before = metadata_capture.resolve(sources, [k for k in ('embedded_xmp','exif') if k in sources], primary_id=primary)
    chosen = 'sidecar:version:'+str(version_id)
    after_sources = copy.deepcopy(sources)
    after_sources[chosen] = {'kind':'sidecar_xmp', 'fields':fields}
    after = metadata_capture.resolve(after_sources, list(after_sources), primary_id=chosen)
    old, new = before['proposed_effective'], after['proposed_effective']
    differences = [{'field':key,'before':{'present':key in old,'value':old.get(key)},
                    'after':{'present':key in new,'value':new.get(key)},
                    'previous_source':before['field_sources'].get(key),'new_source':after['field_sources'].get(key)}
                   for key in sorted(old.keys() | new.keys())
                   if [key in old,old.get(key)] != [key in new,new.get(key)]]
    changes = {d['field']:new.get(d['field']) for d in differences}
    proposed = (_folder(new,year)/Path(relative).name).as_posix() if 'date_taken' in changes else relative
    return _token({'version':1,'mode':'preview_only','applied':False,
        'activation':{'version_id':version_id,'sha256':hashlib.sha256(data).hexdigest()},
        'changes':changes,'primary_before':primary,'primary_after':chosen,'sources_before':sources,
        'target':{'source_id':chosen,'kind':'sidecar_xmp','create':False,'sidecar_name':Path(relative).name+'.xmp'},
        'before':before,'after':after,'target_fields_after':fields,'differences':differences,
        'filing':{'current':relative,'proposed':proposed,'change':relative!=proposed,'collision_check_pending':True},
        'filesystem_verification_pending':True,'binding':binding})


def preview_embedded_primary(db_path, *, photo_id, capture_id, primary_id, destination_root, settings=None):
    """Select an existing embedded source without copying or rewriting any tags."""
    if primary_id not in ('exif','embedded_xmp'):
        raise ValueError('Choose an embedded EXIF or embedded XMP source')
    sources,primary,year,relative,binding=_catalog_state(db_path,photo_id=photo_id,
        capture_id=capture_id,destination_root=destination_root,settings=settings,allow_primary_choice=True)
    # A saved decision may still await activation. Preview against the verified
    # import, not against that unapplied choice, or date refiling disappears.
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        if metadata_save.active(conn,photo_id) is None:
            row=conn.execute("SELECT e.detail_json FROM operation_events e JOIN operations o ON o.id=e.operation_id "
                "WHERE o.photo_id=? AND e.step IN ('metadata_activated','photo_metadata_activated') "
                "ORDER BY e.event_id DESC LIMIT 1",(photo_id,)).fetchone()
            if row:
                imported=json.loads(row[0]);primary=imported['primary_id']
                captured=conn.execute('SELECT report_json FROM metadata_captures WHERE capture_id=?',(imported['capture_id'],)).fetchone()
                sources=imported.get('sources') or json.loads(captured[0])['sources']
    if primary_id not in sources:
        raise ValueError('The chosen embedded source is absent; no source was invented')
    order=[key for key in ('embedded_xmp','exif') if key in sources]
    before=metadata_capture.resolve(sources,order,primary_id=primary)
    after=metadata_capture.resolve(sources,order,primary_id=primary_id)
    old,new=before['proposed_effective'],after['proposed_effective']
    differences=[{'field':key,'before':{'present':key in old,'value':old.get(key)},
        'after':{'present':key in new,'value':new.get(key)},
        'previous_source':before['field_sources'].get(key),'new_source':after['field_sources'].get(key)}
        for key in sorted(old.keys() | new.keys()) if [key in old,old.get(key)]!=[key in new,new.get(key)]]
    proposed=(_folder(new,year)/Path(relative).name).as_posix() if any(d['field']=='date_taken' for d in differences) else relative
    return _token(dict(version=1,mode='preview_only',applied=False,primary_activation={'primary_id':primary_id},
        primary_before=primary,primary_after=primary_id,sources_before=sources,before=before,after=after,
        changes={d['field']:new.get(d['field']) for d in differences},differences=differences,
        target={'source_id':primary_id,'kind':sources[primary_id]['kind'],'create':False,'sidecar_name':None},
        target_fields_after=sources[primary_id]['fields'],binding=binding,
        filing={'current':relative,'proposed':proposed,'change':relative!=proposed,'collision_check_pending':True},
        filesystem_verification_pending=True))
