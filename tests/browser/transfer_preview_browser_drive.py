"""Destination folders in the existing confirmation, on generated photos only."""
import os
import re
import sys
import time
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    request=p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    def wait(run):
        for _ in range(600):
            state=request.get(f'/api/v1/runs/{run}').json()
            if state['status'] not in ('Preparing','Running','Cancelling') and request.get('/api/v1/jobs/active').json()['active'] is None:return state
            time.sleep(.1)
        raise AssertionError('Job did not finish')
    response=request.post('/api/v1/jobs/start',data={'mode':'index'})
    assert response.ok,response.text();wait(response.json()['id'])
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':900},color_scheme='dark')
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(sys.argv[1])
    def copy_all():
        page.get_by_role('button',name='Jobs',exact=True).click()
        page.get_by_role('menu',name='Jobs',exact=True).get_by_role('menuitem',name='Copy',exact=True).click()
        page.get_by_role('menu',name='Copy',exact=True).get_by_role('menuitem',name=re.compile('^Copy all')).click()
        dialog=page.get_by_role('alertdialog')
        expect(dialog.get_by_role('button',name='Cancel',exact=True)).to_be_focused()
        expect(dialog.get_by_role('button',name='Copy',exact=True)).to_be_enabled()
        return dialog
    # Selected Copy must also show the preview before starting a job.
    page.goto(sys.argv[1]+'/?view=unorganized&q=photo-00')
    # Exact duplicates share a card; either recorded filename can represent it.
    dated_cards=page.get_by_role('checkbox',name=re.compile(r'^Select (?:photo|copy-of)-00[01]\.jpg$'))
    expect(dated_cards).to_have_count(2)
    dated_cards.nth(0).check();dated_cards.nth(1).check()
    page.get_by_role('region',name='Selection',exact=True).get_by_role('button',name='Copy (2)…',exact=True).click()
    page.get_by_role('button',name='Copy these 2 photos',exact=True).click()
    selected_dialog=page.get_by_role('alertdialog')
    expect(selected_dialog.get_by_role('region',name='Destination folders',exact=True)).to_contain_text('library/2023/01/15')
    selected_dialog.get_by_role('button',name='Cancel',exact=True).click()
    assert request.get('/api/v1/status').json()['library_photos']==0
    page.goto(sys.argv[1])
    dialog=copy_all();section=dialog.get_by_role('region',name='Destination folders',exact=True)
    expect(section).to_contain_text('library/2023/01/15')
    expect(section).to_contain_text('library/Undated/2019')
    expect(section).to_contain_text('library/Undated/2023')
    assert section.locator('a[download]').count()==0
    folder=section.locator('details').filter(has=page.locator('summary',has_text='library/Undated/2023'))
    folder.locator('summary').click()
    expect(folder.locator('li')).to_have_count(20)
    first=folder.locator('li').first.inner_text()
    folder.get_by_role('button',name='Next page',exact=True).click()
    expect(folder.locator('li').first).not_to_have_text(first)
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    assert request.get('/api/v1/status').json()['library_photos']==0
    dialog=copy_all()
    for width,size in ((1440,'100%'),(720,'200%')):
        page.set_viewport_size({'width':width,'height':900})
        page.locator('html').evaluate('(e,s)=>e.style.fontSize=s',size)
        dialog.get_by_role('button',name='Copy',exact=True).scroll_into_view_if_needed()
        assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        expect(dialog.get_by_role('button',name='Copy',exact=True)).to_be_visible()
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/destination-preview-{width}.png")
    page.keyboard.press('Escape');expect(dialog).to_have_count(0)
    page.set_viewport_size({'width':1440,'height':900});page.locator('html').evaluate('(e)=>e.style.fontSize="100%"')
    dialog=copy_all()
    # A settings change in another browser invalidates the existing confirmation.
    setting=request.get('/api/v1/settings').json()['small_image_min']
    result=request.put('/api/v1/settings',data={'values':{'small_image_min':640},'revisions':{'small_image_min':setting['revision']}})
    assert result.ok,result.text()
    dialog.get_by_role('button',name='Copy',exact=True).click()
    expect(dialog).to_contain_text('The destination preview changed')
    assert request.get('/api/v1/status').json()['library_photos']==0
    dialog.get_by_role('button',name='Refresh Copy preview',exact=True).click()
    expect(dialog.get_by_role('button',name='Copy',exact=True)).to_be_enabled()
    with page.expect_response(lambda response:response.url.endswith('/api/v1/jobs/start') and response.request.method=='POST') as submitted:
        dialog.get_by_role('button',name='Copy',exact=True).click()
    response=submitted.value;assert response.ok,response.text()
    body=response.request.post_data_json
    assert body['transfer_preview_token'] and len(body['file_ids'])==132,body
    wait(response.json()['id']);page.reload()
    assert request.get('/api/v1/status').json()['library_photos']==130
    assert not errors,errors
    browser.close()
print('PASS: numeric paths, grouped counts, paged filenames, cancel, keyboard/reflow, stale refresh and confirmed Copy')
