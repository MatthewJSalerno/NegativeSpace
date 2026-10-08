"""Source failures stay outside Library review, including explicit saved URLs."""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base=sys.argv[1]
expected=int(sys.argv[2])+int(sys.argv[3])
Path('/src/empty.jpg').write_bytes(b'')
Path('/src/text.jpg').write_text('This is plain text, not image data.')
whole=Path('/src/photo-004.jpg').read_bytes()
Path('/src/truncated.jpg').write_bytes(whole[:len(whole)*4//5])
with sync_playwright() as p:
    request=p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    def get(route):
        response=request.get('/api/v1/'+route)
        assert response.ok,response.text()
        return response.json()
    def job(mode):
        response=request.post('/api/v1/jobs/start',data={'mode':mode})
        assert response.ok,response.text()
        run=response.json()['id']
        for _ in range(600):
            if get(f'runs/{run}')['status'] not in ('Preparing','Running','Cancelling') and get('status')['active_job'] is None:return
            time.sleep(.2)
        raise AssertionError('Job timed out')
    job('index')
    listing=get('photos?view=unorganized&page_size=240')
    summary=listing['index_summary']
    assert summary['ready']==expected and summary['failed']==3,summary
    failures=[i for i in listing['items'] if i['status']=='Failed']
    assert len(failures)==3
    ids={i['id'] for i in failures}
    for item in failures:
        assert get(f"photos/{item['id']}/inspect")['failure'] == item['failure']
    assert not ids.intersection(i['id'] for i in get('photos?view=unorganized&undated=1&page_size=240')['items'])
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000},color_scheme='dark')
    page.goto(base+f"/?view=unorganized&photo={failures[0]['id']}")
    expect(page.get_by_role('region',name='Photo details',exact=True)).to_contain_text(failures[0]['failure'])
    expect(page.locator('.inspector .notice').filter(has_text=failures[0]['failure'])).to_be_visible()
    if os.environ.get('SHOTS'):
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        page.screenshot(path=os.environ['SHOTS']+'/source-failure-inspector.png', animations='disabled')

    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    for item in failures:
        ident=item['id']
        page.goto(base+f'/?view=unorganized&photo={ident}&tab=similar')
        panel=page.locator('.inspector')
        expect(panel.get_by_text('File needs attention.',exact=True)).to_be_visible()
        expect(panel.get_by_role('link',name='View failure details',exact=True)).to_have_attribute('href',f'/logs?status=Failed&photo={ident}')
        expect(panel.get_by_role('tab',name='Similar photos',exact=True)).to_have_count(0)
        expect(panel.get_by_role('button',name='Review photo…',exact=True)).to_have_count(0)
        expect(panel.get_by_role('button',name='Review later…',exact=True)).to_have_count(0)
        expect(panel).not_to_contain_text('potential match')
        page.goto(base+f'/?view=unorganized&review_photo={ident}')
        review=page.get_by_role('dialog',name='Review photos',exact=True)
        expect(review.get_by_role('alert')).to_contain_text('Only organized photos in Library can be reviewed')
        expect(review.get_by_role('button',name='Review later…',exact=True)).to_have_count(0)
        review.get_by_role('button',name='Back to gallery',exact=False).click()
    page.goto(base+'/?view=unorganized')
    expect(page.locator('.pager').first).to_contain_text(f'{expected+3} files')
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/source-failure-summary.png')
    summary_panel=page.get_by_role('region',name='Index summary')
    summary_panel.get_by_role('button',name='Copy all photos…',exact=True).click()
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/jobs/start')) as copied:
        page.get_by_role('alertdialog').get_by_role('button',name='Copy',exact=True).click()
    assert copied.value.ok
    run=copied.value.json()['id']
    for _ in range(600):
        if get(f'runs/{run}')['status'] not in ('Preparing','Running','Cancelling') and get('jobs/active')['active'] is None:break
        time.sleep(.2)
    else:raise AssertionError('Copy did not settle')
    # Update in place without a reload: only failed source files remain.
    expect(summary_panel.get_by_role('heading',name='3 files need attention',exact=True)).to_be_visible(timeout=15000)
    expect(summary_panel.locator('dl')).to_have_count(0)
    expect(summary_panel).not_to_contain_text('Photo facts below')
    expect(summary_panel).not_to_contain_text('Similar photos')
    expect(summary_panel.get_by_role('button',name='Copy all photos…',exact=True)).to_have_count(0)
    expect(summary_panel.get_by_role('button',name='Move all photos…',exact=True)).to_have_count(0)
    expect(summary_panel.get_by_role('link',name='View failures',exact=True)).to_have_attribute('href','/logs?status=Failed')
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/remaining-source-failures.png')
    library=get('photos?view=organized')
    assert library['total']==expected
    matches=get(f"similar/{library['items'][0]['id']}")
    assert matches['state']['unavailable']==0 and matches['state']['pending']==0,matches['state']
    # Source decoding failures must not produce a permanent warning on valid Library photos.
    page.goto(base+f"/?view=organized&review_photo={library['items'][0]['id']}")
    expect(page.locator('.review-evidence')).to_be_visible()
    expect(page.get_by_text('Matching is incomplete; other copies may exist.',exact=True)).to_have_count(0)

    assert get('photos?view=unorganized')['total']==3
    assert get('photos?view=review')['total']==0
    stats=get('stats')['library']
    assert stats['failed_source']==3 and stats['photos']==expected and stats['organized']==expected,stats
    page.goto(base+'/stats')
    expect(page.get_by_role('heading',name='Catalog overview',exact=True)).to_be_visible()
    expect(page.get_by_text('3 files · View failure details',exact=True)).to_be_visible()
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/catalog-scope-stats.png')
    assert not errors,errors
    print('PASS: empty/text/undecodable sources, separate failure counts, no source review through saved links, destination scope and Stats')
    browser.close()
