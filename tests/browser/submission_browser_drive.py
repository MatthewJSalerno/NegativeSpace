"""SUBMISSION_FIXTURE=1 DRIVER=submission_browser_drive.py sh tests/browser/webui_browser_test.sh"""
import re
import sys
import time
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok

    def wait(run_id):
        for _ in range(600):
            run = request.get(f'/api/v1/runs/{run_id}').json()
            if run['status'] not in ('Preparing', 'Running', 'Cancelling'):
                return run
            time.sleep(.1)
        raise AssertionError('Job did not settle')

    def start(**body):
        response = request.post('/api/v1/jobs/start', data=body)
        assert response.status == 202, response.text()
        return wait(response.json()['id'])

    def index_ui(page):
        page.get_by_role('button', name='Jobs', exact=True).click()
        page.get_by_role('menu', name='Jobs', exact=True).get_by_role('menuitem', name=re.compile('^Index')).click()

    start(mode='index')
    # Drop only the response, then let another tab finish a newer job first.
    page = browser.new_page(viewport={'width':1400, 'height':900})
    page.goto(sys.argv[1])
    captured = []
    blocked = [True]
    def lookup(route):
        route.abort() if blocked[0] else route.continue_()
    page.route('**/api/v1/job-requests/*', lookup)
    def lose_response(route):
        response = route.fetch()
        assert response.status == 202
        run = wait(response.json()['id'])
        captured.append((route.request.post_data_json['request_id'], run['id']))
        newer = start(mode='index', request_id='other-tab-request')
        assert newer['id'] > run['id']
        route.abort()
    page.route('**/api/v1/jobs/start', lose_response)
    index_ui(page)
    notice = page.get_by_role('status', name='Job submission status')
    expect(notice).to_contain_text('Checking job status')
    page.get_by_role('button', name='Jobs', exact=True).click()
    expect(page.get_by_role('menu', name='Jobs', exact=True).get_by_role('menuitem', name=re.compile('^Index'))).to_have_attribute('aria-disabled', 'true')
    page.keyboard.press('Escape')  # pending submission cannot start a second job
    assert len(captured) == 1
    expect(page.get_by_text('The job could not be started.', exact=True)).to_have_count(0)
    blocked[0] = False
    notice.get_by_role('button', name='Check again').click()
    expect(notice).to_contain_text(f'Request accepted as job #{captured[0][1]}')
    expect(notice.get_by_role('link', name='View this job')).to_have_attribute('href', f'/logs?run={captured[0][1]}')
    page.close()

    # A POST that never reached the server remains unknown across a reload.
    page = browser.new_page(viewport={'width':1400, 'height':900})
    page.goto(sys.argv[1])
    ids = []
    held_responses = []
    def drop_first(route):
        ids.append(route.request.post_data_json['request_id'])
        if len(ids) == 1:
            route.abort()
        elif len(ids) == 2:
            # The retry is accepted, but keep its response in flight. Lookup can
            # resolve it independently; that old fetch must not block a new ID.
            held_responses.append((route, route.fetch()))
        else:
            route.continue_()
    page.route('**/api/v1/jobs/start', drop_first)
    before = len(request.get('/api/v1/runs').json()['runs'])
    index_ui(page)
    notice = page.get_by_role('status', name='Job submission status')
    expect(notice).to_contain_text('Checking job status')
    assert request.get(f'/api/v1/job-requests/{ids[0]}').json()['state'] == 'unknown'
    page.reload()
    expect(notice).to_contain_text('Checking job status')
    assert len(ids) == 1 and len(request.get('/api/v1/runs').json()['runs']) == before
    notice.get_by_role('button', name='Retry same request').click()
    expect(notice).to_contain_text('Request accepted as job #')
    assert ids == [ids[0], ids[0]]
    assert len(request.get('/api/v1/runs').json()['runs']) == before + 1
    recovered = request.get(f'/api/v1/job-requests/{ids[0]}').json()['run']
    wait(recovered['id'])
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/jobs/start')) as next_response:
        index_ui(page)
    assert next_response.value.status == 202
    assert len(ids) == 3 and ids[2] != ids[0]
    for route, response in held_responses:
        route.fulfill(response=response)
    wait(next_response.value.json()['id'])
    page.close()

    # A slow selected Copy: the recovery controls must be usable inside its modal.
    page = browser.new_page(viewport={'width':1400, 'height':900})
    page.goto(sys.argv[1])
    expect(page.locator('.card').first).to_be_visible()
    page.locator('.card-check input').first.check()
    slow = []
    def lose_copy(route):
        response = route.fetch()
        assert response.status == 202
        run = response.json()
        assert run['status'] in ('Preparing', 'Running')
        slow.append((route.request.post_data_json['request_id'], run['id']))
        route.abort()
    page.route('**/api/v1/jobs/start', lose_copy)
    blocked[0] = True
    page.route('**/api/v1/job-requests/*', lookup)
    page.get_by_role('region', name='Selection').get_by_role('button', name='Copy (1)…').click()
    modal = page.get_by_role('alertdialog')
    modal.get_by_role('button', name='Copy', exact=True).click()
    expect(modal.get_by_role('status', name='Job submission status')).to_contain_text('Checking job status')
    blocked[0] = False
    modal.get_by_role('button', name='Check again').click()
    expect(modal).to_have_count(0)
    expect(page.get_by_role('status', name='Job submission status')).to_contain_text(f'Request accepted as job #{slow[0][1]}')
    assert len(slow) == 1
    wait(slow[0][1])
    browser.close()
print('Submission identity: lost fast/slow responses, newer tab job, unknown request, reload and same-ID retry passed')
