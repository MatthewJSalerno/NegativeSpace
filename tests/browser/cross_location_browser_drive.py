"""Cross-location matching stays separate and offers actions for current locations."""
import json
import os
import re
import sys
import time
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1]
with sync_playwright() as p:
    request = p.request.new_context(base_url=BASE)
    def get(route):
        response = request.get('/api/v1/'+route)
        assert response.ok, response.text()
        return response.json()
    def job(mode, ids=None):
        response = request.post('/api/v1/jobs/start', data={'mode': mode, **({'file_ids': ids} if ids else {})})
        assert response.ok, response.text()
        ident = response.json()['id']
        for _ in range(600):
            run = get(f'runs/{ident}')
            if run['status'] not in ('Preparing', 'Running', 'Cancelling') and get('status')['active_job'] is None:
                assert run['status'] == 'Completed', run
                return
            time.sleep(.2)
        raise AssertionError('Job timed out')
    assert request.post('/api/v1/catalog').ok
    job('index'); job('copy')
    a = get('photos?view=similar&sort=matches&match_min=90')['items'][0]['id']
    before = get(f'similar/{a}?page_size=60')
    rejected = [item['id'] for item in before['items'][:13]]
    assert len(rejected) == 13
    job('reject', rejected)
    assert get(f'similar/{a}')['total'] == before['total']-13
    assert get(f'similar/{a}?scope=rejects')['total'] == 13
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    def shot(name):
        if os.environ.get('SHOTS'): page.screenshot(path=os.environ['SHOTS']+'/'+name+'.png')
    def open_library():
        page.goto(f'{BASE}/?view=organized&photo={a}&tab=similar&match=90')
        section = page.get_by_role('region', name='Matches in Rejects', exact=True)
        expect(section.get_by_role('button', name='Also matches 13 photos in Rejects')).to_be_visible()
        section.get_by_role('button', name='Also matches 13 photos in Rejects').click()
        return section
    section = open_library()
    expect(section.locator('.inspector-match')).to_have_count(12)
    # The Library's Keep action has only the active Library count.
    expect(page.get_by_role('button', name=f"Keep reference, reject {before['total']-13} matches…", exact=True)).to_be_visible()
    section.get_by_role('button', name='Next rejected matches').click()
    expect(section.locator('.inspector-match')).to_have_count(1)
    shot('cross-location-inspector')
    section.locator('.inspector-match').click()
    workspace = page.get_by_role('dialog', name='Review photo match')
    reference = workspace.locator('.review-photo').nth(0)
    candidate = workspace.locator('.review-photo').nth(1)
    expect(reference.get_by_text('Location: Library', exact=True)).to_be_visible()
    expect(candidate.get_by_text('Location: Rejects', exact=True)).to_be_visible()
    expect(reference.get_by_role('button', name='Reject…', exact=True)).to_be_visible()
    expect(candidate.get_by_role('button', name='Return to Library', exact=True)).to_be_visible()
    expect(candidate.get_by_role('button', name='Reject…', exact=True)).to_have_count(0)
    expect(workspace.get_by_role('button', name='Show this set in gallery')).to_have_count(0)
    expect(workspace.locator('.review-keep')).to_have_count(0)
    expect(workspace.locator('.workspace-step')).to_contain_text('13 of 13')
    workspace.get_by_role('button', name='Previous candidate', exact=True).click()
    expect(workspace.locator('.workspace-step')).to_contain_text('12 of 13')
    # Use-as-reference reverses locations and scopes the candidates to Library.
    candidate.get_by_role('button', name='Use as reference').click()
    expect(reference.get_by_text('Location: Rejects', exact=True)).to_be_visible()
    expect(candidate.get_by_text('Location: Library', exact=True)).to_be_visible()
    expect(workspace.get_by_role('heading', name='Candidates in Library')).to_be_visible()
    expect(workspace.locator('.review-keep')).to_have_count(0)
    # Copy link on ordinary HTTP uses the manual fallback, carrying the scope.
    workspace.get_by_role('button', name='Copy review link').click()
    link = workspace.get_by_role('textbox', name='Review link')
    expect(link).to_be_visible()
    saved = link.input_value()
    assert json.loads(parse_qs(urlparse(saved).query)['review'][0])['scope'] == 'library'
    page.goto(saved)
    expect(reference.get_by_text('Location: Rejects', exact=True)).to_be_visible()
    expect(candidate.get_by_text('Location: Library', exact=True)).to_be_visible()
    candidate.get_by_role('button', name='Use as reference').click()
    expect(reference.get_by_text('Location: Library', exact=True)).to_be_visible()
    expect(candidate.get_by_text('Location: Rejects', exact=True)).to_be_visible()
    expect(workspace.get_by_role('heading', name='Candidates in Rejects')).to_be_visible()
    workspace.get_by_role('button', name='Copy review link').click()
    saved = link.input_value()
    assert json.loads(parse_qs(urlparse(saved).query)['review'][0])['scope'] == 'rejects'
    page.goto(saved)
    expect(candidate.get_by_role('button', name='Return to Library', exact=True)).to_be_visible()
    for theme in ('light', 'dark'):
        page.emulate_media(color_scheme=theme)
        shot('cross-location-'+theme)
    page.set_viewport_size({'width': 800, 'height': 500})
    expect(candidate.get_by_role('button', name='Return to Library', exact=True)).to_be_visible()
    shot('cross-location-reflow')
    page.set_viewport_size({'width': 1600, 'height': 1000})
    candidate.get_by_role('button', name='Return to Library', exact=True).click()
    confirm = page.get_by_role('alertdialog')
    expect(confirm.get_by_role('button', name='Cancel', exact=True)).to_be_focused()
    confirm.get_by_role('button', name='Return to library', exact=True).click()
    expect(workspace.locator('.workspace-status')).to_contain_text('Returned ', timeout=60_000)
    assert get(f'similar/{a}?scope=rejects')['total'] == 12
    assert get(f'similar/{a}')['total'] == before['total']-12
    workspace.get_by_role('button', name='Back to gallery', exact=False).click()
    expect(page.get_by_role('button', name='Also matches 12 photos in Rejects')).to_be_visible()
    # Rejected Inspector: similarity remains useful, without review decisions.
    b = get(f'similar/{a}?scope=rejects')['items'][0]['id']
    page.goto(f'{BASE}/?view=rejects&photo={b}')
    inspector = page.locator('.inspector')
    expect(inspector.get_by_role('button', name='Review later…', exact=True)).to_have_count(0)
    expect(inspector.get_by_role('button', name='Review photo…', exact=True)).to_have_count(0)
    inspector.get_by_role('tab', name='Similar photos in Library', exact=True).click()
    expect(inspector.locator('.inspector-match').first).to_be_visible()
    expect(inspector.get_by_role('region', name='Matches in Rejects')).to_have_count(0)
    expect(inspector.get_by_role('button', name=re.compile('^Keep reference'))).to_have_count(0)
    inspector.locator('.inspector-match').first.click()
    expect(reference.get_by_text('Location: Rejects', exact=True)).to_be_visible()
    reference.get_by_role('button', name='Return to Library', exact=True).click()
    page.get_by_role('alertdialog').get_by_role('button', name='Return to library', exact=True).click()
    expect(reference.get_by_text('Location: Library', exact=True)).to_be_visible(timeout=60_000)
    expect(reference.get_by_role('button', name='Reject…', exact=True)).to_be_visible()
    assert not errors, errors
    print('PASS: separate scopes/counts, paging, reference switching, copied links, location-specific actions, confirmed Return both ways, themes/reflow')
    browser.close()
