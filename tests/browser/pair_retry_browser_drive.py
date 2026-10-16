"""Real failed pair jobs, shared retry controls and Copy/Move confirmations."""
import os
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    request=p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    def wait(run):
        for _ in range(600):
            result=request.get(f'/api/v1/runs/{run}').json()
            if result['status'] not in ('Preparing','Running','Cancelling') and request.get('/api/v1/jobs/active').json()['active'] is None:
                return result
            time.sleep(.1)
        raise AssertionError('Job did not finish')
    def start(body):
        response=request.post('/api/v1/jobs/start',data=body)
        assert response.ok,response.text()
        return wait(response.json()['id'])
    start({'mode':'index'})
    browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    for mode,name in (('copy','photo-000.jpg'),('move','photo-001.jpg')):
        photo=request.get('/api/v1/photos?view=unorganized&q='+name).json()['items'][0]['id']
        source=Path('/src')/name;side=Path(str(source)+'.xmp')
        original=[source.read_bytes(),side.read_bytes()]
        failed=start({'mode':mode,'file_ids':[photo]})
        assert [source.read_bytes(),side.read_bytes()]==original
        page.emulate_media(color_scheme='dark' if mode == 'move' else 'light')
        # Retry chains retain earlier issues. Inspector shows the newest failure
        # once, regardless of response order, without changing recorded history.
        def earlier_attempts(route):
            response=route.fetch();data=response.json()
            latest=next(i for i in data['issues'] if i['category']=='metadata_pair_incomplete')
            earlier={**latest,'operation_id':latest['operation_id']-1,'issue_id':latest['issue_id']-1,
                     'summary':'Earlier attempt failed: a different problem.'}
            data['issues']=[earlier,latest] if mode=='copy' else [latest,earlier]
            route.fulfill(response=response,json=data)
        inspect_pattern=f'**/api/v1/photos/{photo}/inspect'
        page.route(inspect_pattern,earlier_attempts)
        page.goto(sys.argv[1]+f'/?view=unorganized&photo={photo}')
        section=page.get_by_role('region',name='Incomplete photo/XMP transfer',exact=True)
        expect(section).to_contain_text('Generated XMP publication failure')
        expect(section.get_by_text(re.compile('Generated XMP publication failure'))).to_have_count(1)
        expect(section).not_to_contain_text('Earlier attempt failed')
        expect(section).not_to_contain_text('PairRefused:')
        expect(section).not_to_contain_text('Published files were preserved')
        expect(section.get_by_role('link',name='View photo logs')).to_have_attribute('href',re.compile(r'photo='+str(photo)+r'(?:&|$)'))
        for width,height in ((1440,1000),(720,500),(640,1000)):
            page.set_viewport_size({'width':width,'height':height})
            assert section.evaluate('(e)=>e.scrollWidth <= e.clientWidth+1')
            if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/pair-notice-{mode}-{width}.png")
        page.set_viewport_size({'width':1440,'height':1000})
        page.unroute(inspect_pattern,earlier_attempts)
        section.get_by_role('button',name=re.compile('^Retry photo')).click()
        dialog=page.get_by_role('dialog',name='Retry photo/XMP transfers',exact=True)
        expect(dialog).to_contain_text('Generated XMP publication failure')
        expect(dialog).to_contain_text('Failed step: Transferring XMP.')
        expect(dialog).not_to_contain_text('PairRefused:')
        expect(dialog).not_to_contain_text('Published files were preserved')
        dest_group=dialog.get_by_role('group',name='Destination',exact=True)
        photo_row=dest_group.locator('.file-location-entry').filter(has=page.get_by_text('Photo',exact=True))
        xmp_row=dest_group.locator('.file-location-entry').filter(has=page.get_by_text('XMP',exact=True))
        expect(photo_row).to_contain_text('Verified at destination')
        expect(xmp_row).to_contain_text('Delivery incomplete — file may be partial')
        expect(photo_row.locator('code')).to_have_class('ok')
        expect(xmp_row.locator('code')).to_have_class('warning')
        assert photo_row.locator('code').evaluate('(e)=>getComputedStyle(e).color') != xmp_row.locator('code').evaluate('(e)=>getComputedStyle(e).color')
        expect(dialog.get_by_role('group',name='Source',exact=True)).not_to_contain_text('In failed step')
        expect(dialog).to_contain_text('not a live check')
        if mode == 'copy':
            # Missing historical observations must not inherit a prior green row.
            def older_result(route):
                response=route.fetch();data=response.json()
                for item in data['items']:
                    item['delivery']={'photo':'unknown','xmp':'unknown'}
                    item['failure_context']=None
                route.fulfill(response=response,json=data)
            pattern='**/api/v1/pair-retries/preview'
            page.route(pattern,older_result)
            dialog.get_by_role('button',name='Refresh list',exact=True).click()
            expect(dest_group.get_by_text('Delivery not confirmed — no recorded result',exact=True)).to_have_count(2)
            expect(dest_group.locator('code.ok')).to_have_count(0)
            page.unroute(pattern,older_result)
            dialog.get_by_role('button',name='Refresh list',exact=True).click()
            expect(photo_row).to_contain_text('Verified at destination')
            expect(xmp_row).to_contain_text('Delivery incomplete — file may be partial')
        divider=dialog.locator('.file-location-group').nth(1)
        assert divider.evaluate('(e)=>getComputedStyle(e).borderTopStyle')=='solid'
        assert divider.evaluate('(e)=>parseFloat(getComputedStyle(e).borderTopWidth)')>=1
        # Both source/destination paths use the same grouping in the Inspector.
        expect(page.locator('.inspector .file-locations').first.get_by_role('group',name='Source',exact=True)).to_have_count(1)
        expect(dialog).to_contain_text(name+'.xmp')
        for width,zoom in ((1440,1),(1440,2),(640,1)):
            page.set_viewport_size({'width':round(width/zoom),'height':round(1000/zoom)})
            expect(dialog.get_by_role('button',name=re.compile('^Retry '+mode.title()))).to_be_enabled()
            assert dialog.evaluate('(e)=>e.scrollWidth <= e.clientWidth+1')
            if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/pair-{mode}-{width}-{zoom}.png")
        page.set_viewport_size({'width':1440,'height':1000})
        dialog.get_by_role('button',name=re.compile('^Retry '+mode.title())).click()
        confirm=page.get_by_role('alertdialog')
        expect(confirm.get_by_role('button',name='Cancel',exact=True)).to_be_focused()
        expect(confirm).to_contain_text('This resumes the original '+mode.title()+'.')
        expect(confirm).to_contain_text('source files are removed' if mode=='move' else 'source files stay')
        for width,zoom in ((1440,2),(640,1)):
            page.set_viewport_size({'width':round(width/zoom),'height':round(1000/zoom)})
            expect(confirm.get_by_role('button',name='Retry '+mode.title(),exact=True)).to_be_enabled()
            assert confirm.evaluate('(e)=>e.scrollWidth <= e.clientWidth+1')
            if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/pair-confirm-{mode}-{width}-{zoom}.png")
        page.set_viewport_size({'width':1440,'height':1000})
        confirm.get_by_role('button',name='Cancel',exact=True).click()
        page.get_by_role('dialog',name='Retry photo/XMP transfers',exact=True).get_by_role('button',name='Close',exact=True).click()
        assert [source.read_bytes(),side.read_bytes()]==original
        # Selection uses the same dialog, while ordinary Copy/Move stays unavailable.
        page.goto(sys.argv[1]+'/?view=unorganized&q='+name)
        page.locator('.card-check input').first.check()
        selection=page.get_by_role('region',name='Selection',exact=True)
        selection.get_by_role('button',name=re.compile('^Retry photo')).click()
        page.get_by_role('dialog',name='Retry photo/XMP transfers',exact=True).get_by_role('button',name=re.compile('^Retry '+mode.title())).click()
        with page.expect_response(lambda r:r.url.endswith('/api/v1/pair-retries/start')) as response:
            page.get_by_role('alertdialog').get_by_role('button',name='Retry '+mode.title(),exact=True).click()
        assert response.value.ok,response.value.text()
        wait(response.value.json()['id'])
        remaining=request.post('/api/v1/pair-retries/preview',data={'file_ids':[photo]}).json()
        assert remaining=={'items':[],'groups':[]},remaining
        if mode=='copy':assert [source.read_bytes(),side.read_bytes()]==original
        else:assert not source.exists() and not side.exists()
        page.get_by_role('button',name='Clear selection',exact=True).click()
    assert not errors,errors
    print('PASS: failed Copy/Move pairs, Inspector and selection, cancel, confirmed retry, source preservation, narrow/200% dialogs')
    browser.close()
