"""Recovery UI with generated files and an opt-in disposable catalog mount."""
import os
import re
import sqlite3
import sys
import time
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    created = request.post('/api/v1/catalog')
    assert created.ok, created.text()
    def wait(run):
        for _ in range(600):
            result = request.get(f'/api/v1/runs/{run}').json()
            if (result['status'] not in ('Preparing','Running','Cancelling')
                    and request.get('/api/v1/jobs/active').json()['active'] is None):
                assert result['status'] == 'Completed', result
                return
            time.sleep(.2)
        raise AssertionError('Job did not finish')
    for mode in ('index','copy'):
        response = request.post('/api/v1/jobs/start',data={'mode':mode})
        assert response.ok, response.text()
        wait(response.json()['id'])
    with sqlite3.connect('/catalog/db/ns_sqlite.db') as conn:
        records = conn.execute("SELECT id,sha1_hash FROM photos WHERE status='Copied' ORDER BY id LIMIT 2").fetchall()
        photo, digest = records[0]
        other, other_digest = records[1]
        conn.execute("UPDATE contents SET phash=NULL,phash_state='error' WHERE digest=?",(digest,))
        conn.execute("UPDATE contents SET phash=NULL,phash_state='not_supported' WHERE digest=?",(other_digest,))
        conn.execute('DELETE FROM similarity_hashes')
    page = browser.new_page(viewport={'width':1440,'height':1000})
    errors = []
    page.on('pageerror',lambda e: errors.append(str(e)))
    def shot(name):
        if os.environ.get('SHOTS'):
            page.screenshot(path=os.path.join(os.environ['SHOTS'],name+'.png'))
    page.goto(f'{sys.argv[1]}/?photo={photo}&tab=similar&match=90')
    expect(page.get_by_text('Visual matching is unavailable:',exact=False)).to_be_visible()
    def busy_status(route):
        result = route.fetch().json()
        result['active_job'] = {'id':999,'mode':'INDEX','status':'Running'}
        route.fulfill(json=result)
    page.route('**/api/v1/status',busy_status)
    page.get_by_role('button',name='Review matching status',exact=True).click()
    dialog = page.get_by_role('dialog',name='Matching status',exact=True)
    repair = dialog.get_by_role('button',name='Recheck file after external fix',exact=True)
    expect(repair).to_be_disabled()
    expect(dialog.get_by_text('Wait for the running job',exact=False)).to_be_visible()
    page.unroute('**/api/v1/status')
    expect(repair).to_be_enabled(timeout=10000)
    expect(dialog.get_by_role('button',name='Generate missing hashes',exact=True)).to_be_disabled()
    expect(dialog.get_by_text('The file could not be decoded for visual matching.',exact=False)).to_be_visible()
    shot('missing-hash-recovery')
    with page.expect_response(lambda r: r.request.method=='POST' and r.url.endswith('/api/v1/similar/recovery')) as response:
        repair.click()
    assert response.value.ok
    wait(response.value.json()['id'])
    expect(dialog.get_by_text('Similarity recovery finished',exact=False)).to_be_visible(timeout=10000)
    with sqlite3.connect('/catalog/db/ns_sqlite.db') as conn:
        assert conn.execute('SELECT phash_state FROM contents WHERE digest=?',(digest,)).fetchone()==('ok',)
    expect(dialog).to_be_visible()  # A resolved warning must not dismiss its results.
    dialog.get_by_role('button',name='Close',exact=True).click()
    expect(page.get_by_role('button',name=re.compile('^90% or higher:'))).to_be_visible()
    page.goto(sys.argv[1]+'/?view=similar')
    page.route('**/api/v1/similar/recovery?*',lambda route: route.fulfill(status=503,json={'message':'Recovery list temporarily unavailable'}))
    page.get_by_role('button',name='Review matching status',exact=True).click()
    expect(dialog.get_by_role('alert')).to_be_visible()
    page.unroute('**/api/v1/similar/recovery?*')
    dialog.get_by_role('button',name='Retry status',exact=True).click()
    expect(dialog.get_by_text('This format is not supported by the visual decoder',exact=False)).to_be_visible()
    expect(dialog.get_by_role('button',name='Generate missing hashes',exact=True)).to_be_disabled()
    expect(dialog.get_by_role('button',name='Recheck file after external fix',exact=True)).to_have_count(0)
    # Comparison-only recovery runs even when there are no retryable missing hashes.
    with sqlite3.connect('/catalog/db/ns_sqlite.db') as conn:
        conn.execute('DELETE FROM similarity_hashes')
    resume = dialog.get_by_role('button',name='Resume comparisons',exact=True)
    expect(resume).to_be_enabled(timeout=10000)
    with page.expect_response(lambda r: r.request.method=='POST' and r.url.endswith('/api/v1/similar/recovery')) as response:
        resume.click()
    wait(response.value.json()['id'])
    expect(resume).to_be_disabled(timeout=10000)
    page.set_viewport_size({'width':700,'height':844})
    assert dialog.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
    shot('matching-recovery-narrow')
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    assert not errors, errors
    browser.close()
    print('Similarity recovery browser checks passed')
