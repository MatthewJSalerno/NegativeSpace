"""Read-only source snapshots. Never open photo paths or decompress retained XMP."""
import json

from engine import metadata_adapter
from engine.metadata import MetadataSource

from . import catalog


def _load(value):
    return json.loads(value or '{}') or {}


def inspect(db_path, photo_id):
    with catalog.connect(db_path) as conn:
        conn.execute('BEGIN')
        photo = conn.execute('SELECT p.sha1_hash,p.status,pf.file_id FROM photos p '
            'LEFT JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?', (photo_id,)).fetchone()
        if photo is None:
            return None
        capture = conn.execute('SELECT * FROM metadata_captures WHERE file_id=? '
            'ORDER BY capture_id DESC LIMIT 1', (photo['file_id'],)).fetchone()
        # Decisions can be pending. Only an applied receipt establishes the displayed
        # primary; newer Index observations must not replace a saved Library version.
        event = conn.execute("SELECT e.detail_json,e.step FROM operations o JOIN operation_events e "
            "ON e.operation_id=o.id WHERE o.photo_id=? AND e.step IN "
            "('metadata_saved','metadata_activated','photo_metadata_activated') "
            "ORDER BY e.event_id DESC LIMIT 1", (photo_id,)).fetchone()
        receipt = _load(event[0]) if event else {}
        capture_id = receipt.get('capture_id')
        if receipt.get('primary_revision'):
            decision = conn.execute('SELECT capture_id FROM metadata_decisions WHERE decision_id=?',
                (receipt['primary_revision'],)).fetchone()
            if decision:
                capture_id = decision[0]
        if capture_id:
            bound = conn.execute('SELECT * FROM metadata_captures WHERE capture_id=? AND file_id=?',
                (capture_id, photo['file_id'])).fetchone()
            if bound:
                capture = bound
        report = _load(capture['report_json']) if capture else {}
        embedded = _load(capture['embedded_json']) if capture else {}
        sources = receipt.get('sources', report.get('sources', {}))
        primary = receipt.get('primary_id') or receipt.get('resolution', {}).get('proposed_primary')
        issues = list(report.get('issues', [])) if not receipt else []
        recorded_hash = receipt.get('sha1_hash') or (capture['catalog_sha1'] if receipt and capture else None)
        if recorded_hash and recorded_hash != photo['sha1_hash']:
            issues.append({'code':'content_changed', 'detail':'Recorded metadata belongs to an earlier photo version. Review photo history before using it.'})
            primary = None
        resolution = receipt.get('resolution', report.get('resolution', {}))
        raw = receipt.get('metadata', {}) if receipt.get('content_changed') else embedded.get('tags', {})
        result = []
        for key, kind, label in [('exif','embedded_exif','EXIF'), ('embedded_xmp','embedded_xmp','Embedded XMP')]:
            tags = {k:v for k,v in raw.items() if (k.startswith('XMP-') if key=='embedded_xmp'
                    else k.split(':')[0] in ('IFD0','ExifIFD','GPS','InteropIFD','IFD1'))}
            problems = [i for i in issues if i.get('source') in (key,'photo')]
            result.append(dict(id=key, kind=kind, label=label, fields=sources.get(key, {}).get('fields', {}),
                tags=tags, available=key in sources, issues=problems))
        versions = conn.execute('SELECT DISTINCT v.version_id,v.sha256,v.validation_state,v.validation_code,'
            'v.fields_json,v.tags_json FROM xmp_versions v JOIN xmp_arrivals a USING(version_id) '
            'JOIN xmp_arrival_files f USING(arrival_id) WHERE f.file_id=? '
            'UNION SELECT v.version_id,v.sha256,v.validation_state,v.validation_code,v.fields_json,v.tags_json '
            'FROM xmp_versions v JOIN operation_events e ON v.version_id=json_extract(e.detail_json,\"$.version_id\") '
            'JOIN operations o ON o.id=e.operation_id WHERE o.photo_id=? AND e.step=\"metadata_saved\" '
            'ORDER BY version_id DESC', (photo['file_id'],photo_id)).fetchall()
        # Include a saved first sidecar even when it has no source arrival ownership.
        if receipt.get('version_id') and all(v['version_id'] != receipt['version_id'] for v in versions):
            version = conn.execute('SELECT version_id,sha256,validation_state,validation_code,fields_json,tags_json '
                'FROM xmp_versions WHERE version_id=?', (receipt['version_id'],)).fetchone()
            if version:
                versions.insert(0, version)
        active_version = receipt.get('version_id') if primary and primary not in ('exif','embedded_xmp') else None
        sidecars = report.get('sidecars', [])
        for version in versions:
            observed = next((s for s in sidecars if s.get('sha256')==version['sha256']), None)
            source_key = 'sidecar:'+observed['path'] if observed else None
            key = 'xmp:'+str(version['version_id'])
            is_primary = active_version == version['version_id'] or (active_version is None and primary is not None and primary==source_key)
            fields = sources[primary]['fields'] if is_primary and primary in sources else _load(version['fields_json'])
            problems = [] if version['validation_state']=='valid' else [{'code':version['validation_code']}]
            if not problems:
                try:
                    fields = metadata_adapter.for_comparison(MetadataSource(key, 'embedded', {}, fields)).fields
                except ValueError as exc:
                    problems = [{'code':str(exc)}]
            result.append(dict(id=key, kind='sidecar_xmp', label='XMP Sidecar', version_id=version['version_id'],
                fields=fields, tags=_load(version['tags_json']), available=not problems, issues=problems))
            if is_primary:
                primary = key
        # A refused/unreadable sidecar may have no archived version. Its tab must
        # still say why it is unavailable, rather than claiming there was no source.
        retained_digests = {v['sha256'] for v in versions}
        unretained = {}
        for issue in issues:
            source = issue.get('source', '')
            if not source.startswith('sidecar:'):
                continue
            observed = next((s for s in sidecars if 'sidecar:'+s['path'] == source), {})
            if observed.get('sha256') not in retained_digests:
                unretained.setdefault(source, []).append(issue)
        for source, problems in unretained.items():
            result.append(dict(id='unretained:'+source, kind='sidecar_xmp', label='XMP Sidecar',
                fields={}, tags={}, available=False, issues=problems))
        if not any(s['kind']=='sidecar_xmp' for s in result):
            result.append(dict(id='xmp:none',kind='sidecar_xmp',label='XMP Sidecar',fields={},tags={},available=False,issues=[]))
        return dict(photo_id=photo_id, primary_id=primary, sources=result, issues=issues,
            recorded=bool(capture or receipt), applied=bool(receipt),
            field_sources=resolution.get('field_sources', {}),
            notice=None if receipt else 'Index observations only; no primary source has been activated.')
