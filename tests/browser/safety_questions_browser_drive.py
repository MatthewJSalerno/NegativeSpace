"""NETWORK_FIXTURE=1 DRIVER=safety_questions_browser_drive.py sh tests/browser/webui_browser_test.sh"""
import shutil
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok

    def wait(run_id):
        # Settled, and the engine idle: it still holds its lock for the catalog backup
        # it takes after a run settles, and a start in that moment is refused.
        for _ in range(600):
            run = request.get(f'/api/v1/runs/{run_id}').json()
            if (run['status'] not in ('Preparing', 'Running', 'Cancelling')
                    and request.get('/api/v1/jobs/active').json()['active'] is None):
                return run
            time.sleep(.2)
        raise AssertionError('Job did not settle')

    def start(**body):
        response = request.post('/api/v1/jobs/start', data=body)
        assert response.status == 202, response.text()
        return wait(response.json()['id'])

    def open_page():
        page = browser.new_page(viewport={'width':1400, 'height':900})
        page.goto(sys.argv[1])
        expect(page.get_by_role('region', name='Job needs a decision')).to_be_visible()
        return page

    def confirm_answer(page, action):
        modal = page.get_by_role('alertdialog')
        expect(modal).to_be_visible()
        expect(modal.get_by_role('button', name='Cancel', exact=True)).to_be_focused()
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/answer')) as response:
            modal.get_by_role('button', name=action, exact=True).click()
        assert response.value.status == 202
        return wait(response.value.json()['id'])

    start(mode='index')
    photo = request.get('/api/v1/photos', params={'q':'photo-010.jpg'}).json()['items'][0]
    original = Path('/src/photo-010.jpg')
    refused = start(mode='move', file_ids=[photo['id']])
    page = open_page()
    # A question alone, dismissal, or cancellation must not answer/start anything.
    page.get_by_role('button', name='Move anyway…', exact=True).click()
    expect(page.get_by_role('alertdialog')).to_contain_text('synchronously')
    page.get_by_role('alertdialog').get_by_role('button', name='Cancel', exact=True).click()
    assert request.get('/api/v1/jobs/active').json()['last']['id'] == refused['id']
    assert original.exists()
    page.get_by_role('button', name='Leave unchanged', exact=True).click()
    expect(page.get_by_role('region', name='Job needs a decision')).to_have_count(0)
    assert request.get('/api/v1/jobs/active').json()['last']['id'] == refused['id']
    page.close()
    # Dismissal is shared through catalog UI state. A new request asks afresh.
    start(mode='move', file_ids=[photo['id']])
    page = open_page()
    page.get_by_role('button', name='Copy instead (recommended)', exact=True).click()
    copied = confirm_answer(page, 'Copy instead')
    assert copied['mode'] == 'COPY' and copied['targeting']['selection'] == 1
    assert original.exists()
    page.close()
    start(mode='move', file_ids=[photo['id']])
    page = open_page()
    page.get_by_role('button', name='Move anyway…', exact=True).click()
    moved = confirm_answer(page, 'Confirm and Move')
    assert moved['outcome']['copied_only'] == 1  # harness source remains :ro
    assert moved['questions'] == []
    page.close()

    with tempfile.TemporaryDirectory(prefix='ns-held-source-') as held:
        def hide():
            for item in Path('/src').iterdir():
                shutil.move(str(item), held)
        def restore():
            for item in Path(held).iterdir():
                shutil.move(str(item), '/src')
        hide()
        start(mode='index')
        page = open_page()
        page.get_by_role('button', name='I reconnected it — retry', exact=True).click()
        still_empty = confirm_answer(page, 'Retry original job')
        assert still_empty['questions'] == ['source_empty']
        page.close()
        restore()
        page = open_page()
        page.get_by_role('button', name='I reconnected it — retry', exact=True).click()
        assert confirm_answer(page, 'Retry original job')['questions'] == []
        page.close()
        hide()
        start(mode='index')
        page = open_page()
        page.get_by_role('button', name='It really is empty', exact=True).click()
        confirmed = confirm_answer(page, 'Confirm empty source')
        assert confirmed['questions'] == []
        page.close()
        restore()
    browser.close()
print('Safety questions: no action before choice, scoped Copy/Move, empty confirmation and reconnect passed')
