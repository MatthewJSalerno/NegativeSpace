"""Source failures stay outside Library review, including explicit saved URLs."""
import re
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
        expect(panel.get_by_role('button',name='Inspect photo…',exact=True)).to_have_count(0)
        expect(panel.get_by_role('button',name='Review later…',exact=True)).to_have_count(0)
        expect(panel).not_to_contain_text('potential match')
        page.goto(base+f'/?view=unorganized&review_photo={ident}')
        review=page.get_by_role('dialog',name='Review photos',exact=True)
        expect(review.get_by_role('alert')).to_contain_text('Only organized photos in Library can be reviewed')
        expect(review.get_by_role('button',name='Review later…',exact=True)).to_have_count(0)
        review.get_by_role('button',name='Back to gallery',exact=False).click()
    page.goto(base+'/?view=unorganized')
    expect(page.get_by_role('navigation',name='Main').get_by_role('link',name=re.compile(r'^Not organized\b')).locator('.sidebar-count')).to_have_text(f'{expected+3:,}')
    expect(page.get_by_role('combobox',name='Files loaded at a time')).to_be_visible()
    expect(page.locator('.gallery-result-count')).to_have_count(0)
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
    expect(summary_panel).not_to_contain_text('These totals cover all successfully indexed photos')
    expect(summary_panel).not_to_contain_text('Similar photos')
    expect(summary_panel.get_by_role('button',name='Copy all photos…',exact=True)).to_have_count(0)
    expect(summary_panel.get_by_role('button',name='Move all photos…',exact=True)).to_have_count(0)
    attention_link=summary_panel.get_by_role('link',name='View 3 files needing attention',exact=True)
    expect(attention_link).to_have_attribute('href','/?view=unorganized&reason=attention')
    attention_link.click()
    expect(page).to_have_url(re.compile(r'reason=attention'))
    expect(page.locator('.gallery-result-count')).to_have_text('Showing 3 of 3 files')
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/remaining-source-failures.png')
    sidebar=page.get_by_role('navigation',name='Main',exact=True)
    attention=sidebar.get_by_role('link',name=re.compile(r'^Needs attention'))
    expect(attention.locator('.sidebar-count')).to_have_text('3')
    expect(attention).to_have_attribute('aria-current','page')
    sidebar.get_by_role('link',name=re.compile(r'^Library')).click()
    expect(attention.locator('.sidebar-count')).to_have_text('3')
    expect(attention).not_to_have_attribute('aria-disabled','true')
    attention.click()
    expect(page.locator('.grid .card')).to_have_count(3)
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
    # Empty folder rows are still tree rows, not whole-gallery empty-state panels.
    def folder_rows(route):
        data=get('photos/folders?view=unorganized&every=true')
        data['folders']=[dict(name=name,path=name,photos=n,folders=[],eligible={'copy':n,'move':n}) for name,n in
                         [('empty-one',0),('empty-two',0),('populated',3)]]
        route.fulfill(json=data)
    page.route('**/api/v1/photos/folders?*',folder_rows)
    page.goto(base+'/?view=unorganized&tree=1')
    for width in (1440,1000,720):
        page.set_viewport_size({'width':width,'height':1000})
        labels=[page.locator('.folder-name').filter(has_text=name) for name in ('empty-one','empty-two','populated')]
        for label in labels: expect(label).to_be_visible()
        boxes=[label.bounding_box() for label in labels]
        assert max(b['x'] for b in boxes)-min(b['x'] for b in boxes)<=1,boxes
        rows=page.locator('.folder-row').evaluate_all('els=>els.map(e=>e.getBoundingClientRect().height)')
        assert max(rows)-min(rows)<=1,rows
        if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+f'/folder-row-alignment-{width}.png')
    panel=page.get_by_role('navigation',name='Source folders',exact=True)
    page.set_viewport_size({'width':1440,'height':1000})
    first=panel.locator('.folder-row').first
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    def tree_offset():
        return first.bounding_box()['y']-panel.bounding_box()['y']
    origin=tree_offset()
    panel.get_by_role('checkbox',name='Show only populated',exact=True).check()
    expect(page.get_by_role('button',name='Copy this folder (3)…',exact=True)).to_be_enabled()
    assert abs(tree_offset()-origin)<=1,(origin,tree_offset())
    panel.get_by_role('checkbox',name='Show only empty-one',exact=True).check()
    expect(page.get_by_role('button',name='Copy this folder…',exact=True)).to_be_disabled()
    expect(page.get_by_role('button',name='Move this folder…',exact=True)).to_be_disabled()
    assert abs(tree_offset()-origin)<=1,(origin,tree_offset())
    panel.get_by_role('button',name='Show all',exact=True).click()
    assert abs(tree_offset()-origin)<=1,(origin,tree_offset())
    page.unroute_all(behavior='wait')
    assert not errors,errors
    print('PASS: empty/text/undecodable sources, separate failure counts, no source review through saved links, destination scope and Stats')
    browser.close()
