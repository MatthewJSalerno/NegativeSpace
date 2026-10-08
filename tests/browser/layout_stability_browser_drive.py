"""Measure navigation and filter anchors before/after routine user actions."""
import os
from pathlib import Path
import re
import sys
import time
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser=p.chromium.launch()
    request=p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    Path('/src/broken.jpg').write_bytes(b'not an image')
    settings=request.get('/api/v1/settings').json()
    assert request.put('/api/v1/settings',data={'values':{'small_image_min':800,'suspicious_min_year':2020},
        'revisions':{'small_image_min':settings['small_image_min']['revision'],'suspicious_min_year':settings['suspicious_min_year']['revision']}}).ok
    for mode in ('index','copy'):
        response=request.post('/api/v1/jobs/start',data={'mode':mode})
        assert response.ok,response.text()
        run=response.json()['id']
        for _ in range(600):
            state=request.get(f'/api/v1/runs/{run}').json()
            if state['status'] not in ('Preparing','Running','Cancelling') and request.get('/api/v1/status').json()['active_job'] is None:
                assert state['status']=='Completed',state
                break
            time.sleep(.2)
        else: raise AssertionError('Job timed out')
    page=browser.new_page(viewport={'width':1440,'height':1100})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def y(selector):
        return page.locator(selector).first.evaluate('e=>e.getBoundingClientRect().top+scrollY')
    def anchors(selectors): return {s: y(s) for s in selectors}
    def unchanged(before):
        for selector,old in before.items():
            assert abs(y(selector)-old)<=1,(selector,old,y(selector))
    for width in (1440,1000,720):
        page.set_viewport_size({'width':width,'height':1100})
        page.goto(sys.argv[1]+'/logs')
        page.evaluate('document.fonts.ready')
        expect(page.locator('.job-list-head')).to_be_visible()
        expect(page.get_by_role('button',name='Show only Failed',exact=True)).to_be_visible()
        all_entries=page.locator('.job-list-head > span').inner_text()
        before=anchors(('.log-filters','.status-checks','.log-filter-summary','.job-list-head'))
        failed=page.get_by_role('checkbox',name=re.compile('^Failed '))
        x=failed.bounding_box()['x']
        page.get_by_role('button',name='Show only Failed',exact=True).click()
        expect(page.get_by_role('heading',name='Failures',exact=True)).to_be_visible()
        unchanged(before)
        assert abs(failed.bounding_box()['x']-x)<=1
        page.get_by_role('checkbox',name='All statuses',exact=True).check()
        expect(page.get_by_role('heading',name='Log',exact=True)).to_be_visible()
        expect(page.locator('.job-list-head > span')).to_have_text(all_entries)
        unchanged(before)
        if os.environ.get('SHOTS'):page.screenshot(path=os.path.join(os.environ['SHOTS'],f'logs-stable-{width}.png'))
        positions=[]
        for path in ('/','/logs','/stats'):
            page.goto(sys.argv[1]+path)
            nav=page.get_by_role('navigation',name='Pages',exact=True)
            expect(nav).to_be_visible()
            positions.append(nav.get_by_role('link',name='Logs',exact=True).bounding_box()['x'])
        assert max(positions)-min(positions)<=1,positions
        for place in ('organized','review'):
            page.goto(sys.argv[1]+f'/?view={place}')
            expect(page.locator('.card')).to_have_count(60)
            expect(page.locator('.gallery-summary > span').first).to_have_text('130 photos')
            before=anchors(('.gallery-summary','.gallery-filter-summary','.gallery-head','.pager'))
            chips=page.get_by_role('group',name='Review reason' if place == 'review' else 'Filter photos')
            for name in ('Suspicious dates','No capture date','Small images'):
                button=chips.get_by_role('button',name=re.compile('^'+name))
                button.click()
                expect(button).to_have_attribute('aria-pressed','true')
                expect(page.locator('.gallery-summary > span').first).to_have_text({'Suspicious dates':'60 photos','No capture date':'128 photos','Small images':'130 photos'}[name])
                unchanged(before)
                button.click()
                expect(button).to_have_attribute('aria-pressed','false')
                expect(page.locator('.gallery-summary > span').first).to_have_text('130 photos')
                expect(page.locator('.card')).to_have_count(60)
                unchanged(before)
            if os.environ.get('SHOTS'):page.screenshot(path=os.path.join(os.environ['SHOTS'],f'gallery-stable-{place}-{width}.png'))
    assert not errors,errors
    browser.close()
print('Navigation, Logs filters/statuses, and gallery filter anchors stayed within 1px at desktop and narrow widths')
