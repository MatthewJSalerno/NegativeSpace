"""Bulk review through the shared selection bar, with generated photos only."""
import os
import sys
import time
import uuid
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    request=p.request.new_context(base_url=sys.argv[1])
    def get(path):
        response=request.get('/api/v1/'+path); assert response.ok,response.text(); return response.json()
    def setting(values):
        current=get('settings')
        response=request.put('/api/v1/settings',data={'values':values,'revisions':{key:current[key]['revision'] for key in values}})
        assert response.ok,response.text()
    def job(mode):
        response=request.post('/api/v1/jobs/start',data={'mode':mode}); assert response.ok,response.text()
        for _ in range(600):
            if get('jobs/active')['active'] is None:return
            time.sleep(.1)
        raise AssertionError('Job did not finish')
    assert request.post('/api/v1/catalog').ok
    setting({'small_image_min':800,'suspicious_min_year':2024})
    job('index'); job('copy')
    photos=get('photos?view=organized&q=photo-00&sort=name')['items']
    selected=photos[:2]; ids=[photo['id'] for photo in selected]
    def bookmark(pid, preset='keep'):
        detail=get(f'photos/{pid}/review')
        response=request.post(f'/api/v1/photos/{pid}/review',data={'photo_id':pid,'sha1':detail['sha1'],'revision':detail['revision'],'reason':'later','action':'later','bookmark_reason':preset,'note':'Generated bulk check','request_id':uuid.uuid4().hex})
        assert response.ok,response.text()
    for pid in ids:bookmark(pid)
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':900},color_scheme='dark')
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    def open_selection(reason):
        page.goto(sys.argv[1]+'/?view=review&reason='+reason+'&sort=name&q=photo-00')
        for photo in selected:page.get_by_role('checkbox',name='Select '+photo['filename'],exact=True).check()
        expect(page.get_by_role('region',name='Selection')).to_contain_text('2 photos selected')
    open_selection('small')
    page.get_by_role('button',name='Mark reviewed…',exact=True).click()
    dialog=page.get_by_role('alertdialog',name='Mark reviewed',exact=True)
    expect(dialog).to_contain_text('2 photos will receive this answer')
    expect(dialog.get_by_role('button',name='Cancel',exact=True)).to_be_focused()
    page.keyboard.press('Escape');expect(dialog).to_have_count(0)
    assert all(any(r['reason']=='small' for r in get(f'photos/{pid}/review')['reasons']) for pid in ids)
    page.get_by_role('button',name='Mark reviewed…',exact=True).click()
    page.set_viewport_size({'width':720,'height':600})
    page.add_style_tag(content='html{font-size:200% !important}')
    expect(dialog.get_by_role('button',name='Mark reviewed',exact=True)).to_be_visible()
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/bulk-review-enlarged.png')
    page.get_by_role('button',name='Mark reviewed',exact=True).click()
    expect(dialog).to_contain_text('2 photos answered')
    dialog.get_by_role('button',name='Close',exact=True).click()
    expect(page.get_by_role('region',name='Selection')).to_have_count(0)
    for pid in ids:
        reasons={r['reason'] for r in get(f'photos/{pid}/review')['reasons']}
        assert reasons=={'later','date'},reasons
    page.set_viewport_size({'width':1440,'height':900})
    open_selection('date')
    page.get_by_role('button',name='These dates are correct…',exact=True).click()
    dialog=page.get_by_role('alertdialog',name='These dates are correct',exact=True)
    expect(dialog).to_contain_text('2 photos will receive this answer')
    bookmark(ids[1], 'ask')  # Another tab changes one photo after confirmation loads.
    dialog.get_by_role('button',name='These dates are correct',exact=True).click()
    expect(dialog).to_contain_text('1 photo answered')
    expect(dialog.get_by_role('region',name='Photos left unchanged')).to_contain_text(selected[1]['filename'])
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/bulk-review-partial.png')
    dialog.get_by_role('button',name='Close',exact=True).click()
    expect(page.get_by_role('region',name='Selection')).to_contain_text('1 photo selected')
    page.get_by_role('button',name='Clear selection',exact=True).click()
    open_selection('later')
    expect(page.get_by_role('button',name='Keep these photos…',exact=True)).to_have_count(0)
    page.get_by_role('button',name='Remove bookmarks…',exact=True).click()
    dialog=page.get_by_role('alertdialog',name='Remove bookmarks',exact=True)
    expect(dialog).to_contain_text('2 photos will receive this answer')
    # Simulate a lost successful response; retry must not add a second answer.
    def lose_response(route):
        response=route.fetch(); assert response.ok,response.text()
        route.fulfill(status=503,content_type='application/json',body='{"error":"generated_failure","message":"Generated lost response"}')
    page.route('**/api/v1/review-batch',lose_response,times=1)
    dialog.get_by_role('button',name='Remove bookmarks',exact=True).click()
    expect(dialog.get_by_role('alert')).to_contain_text('Generated lost response')
    dialog.get_by_role('button',name='Retry saving',exact=True).click()
    expect(dialog).to_contain_text('2 photos answered')
    dialog.get_by_role('button',name='Close',exact=True).click()
    for pid in ids:
        history=get(f'photos/{pid}/review')['history'];assert sum(e['action']=='done' for e in history)==1
        bookmark(pid)
    open_selection('later')
    page.get_by_role('button',name='Keep these photos…',exact=True).click()
    dialog=page.get_by_role('alertdialog',name='Keep these photos',exact=True)
    expect(dialog).to_contain_text('2 photos will receive this answer')
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/bulk-review-keep.png')
    dialog.get_by_role('button',name='Keep these photos',exact=True).click()
    expect(dialog).to_contain_text('2 photos answered')
    dialog.get_by_role('button',name='Close',exact=True).click()
    assert all(get(f'photos/{pid}/review')['history'][0]['action']=='keep' for pid in ids)
    assert not errors,errors
    browser.close()
print('Bulk review: shared actions, Cancel/Escape, 200% text, independent reasons, stale partial results, replay and Keep history passed.')
