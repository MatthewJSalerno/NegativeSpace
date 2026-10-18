"""Web boundary for deliberate, verified Library primary-source changes."""
from engine import metadata_command, ns_db
from . import metadata_view


def validate_edit(photo_id, edit):
    if type(photo_id) is not int or not 1 <= photo_id <= 2**63-1:
        raise ValueError('Choose a valid photo.')
    if not isinstance(edit, dict) or set(edit) not in (
        {'photo_id', 'capture_id', 'primary_id'}, {'photo_id', 'capture_id', 'version_id'}
    ) or edit['photo_id'] != photo_id:
        raise ValueError('Choose a recorded primary source for this photo.')
    metadata_command.validate({'edits': [edit]}, 'preview')


def preview(cfg, photo_id, body):
    if not isinstance(body, dict) or set(body) != {'source_id', 'capture_id'}:
        raise ValueError('Choose one recorded metadata source.')
    if type(photo_id) is not int or not 1 <= photo_id <= 2**63-1:
        raise ValueError('Choose a valid photo.')
    view = metadata_view.inspect(cfg.db_path, photo_id)
    if not view or type(body['capture_id']) is not int or body['capture_id'] != view['capture_id']:
        raise ns_db.RevisionConflict('Recorded metadata changed. Reload the photo before choosing a source.')
    source = next((s for s in view['sources'] if s['id'] == body['source_id']), None)
    if not source or not source['available']:
        raise ValueError('This metadata source is unavailable. Choose a readable recorded source.')
    if source['id'] == view['primary_id']:
        raise ValueError('This source is already primary. Reload the photo to see its current state.')
    edit = dict(photo_id=photo_id, capture_id=body['capture_id'])
    edit.update(version_id=source['version_id']) if source.get('version_id') else edit.update(primary_id=source['id'])
    validate_edit(photo_id, edit)
    plan = metadata_command.previews(cfg.db_path, cfg.dest, {'edits': [edit]})['previews'][0]
    return dict(edit=edit, token=plan['token'], source_id=source['id'], label=source['label'],
        kind=source['kind'], version_id=source.get('version_id'),
        before=plan['before']['proposed_effective'], after=plan['after']['proposed_effective'],
        differences=[d['field'] for d in plan['differences']], filing=plan['filing'])
