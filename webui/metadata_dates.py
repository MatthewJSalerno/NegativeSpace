"""Date-only web boundary over the engine's metadata preview/save contract."""
from engine import metadata_command, metadata_edits, metadata_save
from . import catalog, metadata_view


def context(cfg, photo_id):
    if type(photo_id) is not int or not 1 <= photo_id <= 2**63-1:
        raise ValueError("Choose a valid photo.")
    with catalog.connect(cfg.db_path) as conn:
        conn.execute('BEGIN')
        active = metadata_save.active(conn, photo_id)
        row = conn.execute('SELECT MAX(m.capture_id) FROM metadata_captures m '
            'JOIN photo_files pf ON pf.file_id=m.file_id WHERE pf.photo_id=?', (photo_id,)).fetchone()
        capture_id = row[0]
        if active and active.get('primary_revision'):
            decision = conn.execute('SELECT capture_id FROM metadata_decisions WHERE decision_id=?',
                                    (active['primary_revision'],)).fetchone()
            if decision:
                capture_id = decision[0]
    if capture_id is None:
        raise ValueError('No recorded metadata capture is available for this photo.')
    sources, primary, year, relative, binding = metadata_edits._catalog_state(
        cfg.db_path, photo_id=photo_id, capture_id=capture_id, destination_root=cfg.dest)
    target, kind, creating = metadata_edits.write_target(sources, primary_id=primary,
        settings=binding['settings'], photo_name=relative)
    fields = sources.get(target, {}).get('fields', {})
    return dict(capture_id=capture_id, target=dict(source_id=target, kind=kind, create=creating),
        date=dict(present='date_taken' in fields, value=fields.get('date_taken')),
        current_path=relative, can_clear=kind != 'embedded_exif')


def validate_edit(photo_id, edit):
    if not isinstance(edit, dict) or edit.get('photo_id') != photo_id:
        raise ValueError('Choose this photo for the date edit.')
    metadata_command.validate({'edits':[edit]}, 'preview')
    if set(edit) not in ({'photo_id','capture_id','changes'}, {'photo_id','capture_id','changes','copy_fields'}):
        raise ValueError('This editor changes Date taken only.')
    if 'copy_fields' in edit:
        donor = edit['copy_fields']
        if edit['changes'] or not isinstance(donor,dict) or set(donor) != {'date_taken'} or not isinstance(donor['date_taken'],dict) or donor['date_taken'].get('photo_id') != photo_id:
            raise ValueError('Copy Date taken from a recorded source of this photo.')
    elif set(edit['changes']) != {'date_taken'} or not isinstance(edit['changes']['date_taken'],str) or len(edit['changes']['date_taken']) > 128:
        raise ValueError('Supply only a bounded Date taken value.')


def preview(cfg, photo_id, body):
    if not isinstance(body,dict) or set(body) not in ({'capture_id','value'}, {'capture_id','donor_id'}):
        raise ValueError('Choose a date or one recorded source to copy.')
    edit = dict(photo_id=photo_id,capture_id=body['capture_id'],changes={})
    if 'donor_id' in body:
        view = metadata_view.inspect(cfg.db_path,photo_id)
        source = next((s for s in (view or {}).get('sources',[]) if s['id']==body['donor_id']),None)
        if not source or not source['available'] or 'date_taken' not in source['fields']:
            raise ValueError('This source has no usable recorded Date taken to copy.')
        donor = dict(photo_id=photo_id,version_id=source['version_id']) if source.get('version_id') else dict(
            photo_id=photo_id,capture_id=body['capture_id'],source_id=source['id'])
        edit['copy_fields'] = {'date_taken':donor}
    else:
        edit['changes'] = {'date_taken':body['value']}
    validate_edit(photo_id,edit)
    planned = metadata_command.previews(cfg.db_path,cfg.dest,{'edits':[edit]})['previews'][0]
    if 'donor_id' in body and planned['changes']['date_taken'] != source['fields']['date_taken']:
        raise ValueError('This recorded source differs from its original capture. Enter the intended date explicitly.')
    previous = planned['sources_before'].get(planned['target']['source_id'],{}).get('fields',{})
    after = planned['changes']['date_taken']
    return dict(edit=edit,token=planned['token'],target=planned['target'],
        before=dict(present='date_taken' in previous,value=previous.get('date_taken')),
        after=after,filing=planned['filing'],
        no_change=not planned['target']['create'] and 'date_taken' in previous and previous['date_taken']==after and not planned['filing']['change'])
