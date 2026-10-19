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
        export=page.get_by_role('group',name='Export filtered log')
        expect(export.get_by_role('link',name='CSV',exact=True)).to_be_visible()
        expect(page.locator('.log-filters a')).to_have_count(0)
        fields=page.locator('.log-filters input').evaluate_all('els => els.map(e => {const r=e.getBoundingClientRect(); return {y:r.y,h:r.height};})')
        for a in fields:
            for b in fields:
                if abs(a['y']-b['y'])<4:
                    assert abs(a['y']-b['y'])<=1 and abs(a['h']-b['h'])<=1,fields
        all_entries=page.locator('.job-list-head > span').inner_text()
        before=anchors(('.log-filters','.status-checks','.log-filter-summary','.job-list-head'))
        failed=page.get_by_role('checkbox',name=re.compile('^Failed '))
        x=failed.bounding_box()['x']
        page.get_by_role('button',name='Show only Failed',exact=True).click()
        expect(page.get_by_role('heading',name='Failures',exact=True)).to_be_visible()
        unchanged(before)
        expect(export.get_by_role('link',name='CSV',exact=True)).to_have_attribute('href',re.compile(r'status=Failed'))
        assert abs(failed.bounding_box()['x']-x)<=1
        page.get_by_role('checkbox',name='All statuses',exact=True).check()
        expect(page.get_by_role('heading',name='Log',exact=True)).to_be_visible()
        expect(page.locator('.job-list-head > span')).to_have_text(all_entries)
        unchanged(before)
        if os.environ.get('SHOTS'):page.screenshot(path=os.path.join(os.environ['SHOTS'],f'logs-stable-{width}.png'))
        positions=[]
        for path in ('/','/logs','/stats'):
            page.goto(sys.argv[1]+path)
            # The sidebar never moves sideways between pages (banners above it may differ);
            # narrow, its Menu button stays put.
            if width > 800:
                nav=page.get_by_role('navigation', name='Main',exact=True)
                expect(nav).to_be_visible()
                box=nav.get_by_role('link',name='Logs',exact=True).bounding_box()
                positions.append((box['x'],0))
            else:
                box=page.get_by_role('button',name='Menu',exact=True).bounding_box()
                positions.append((box['x'],box['y']))
        assert all(abs(x-positions[0][0])<=1 and abs(y-positions[0][1])<=1 for x,y in positions),positions
        for place in ('organized','review'):
            page.goto(sys.argv[1]+f'/?view={place}')
            expect(page.locator('.card')).to_have_count(60)
            if place == 'review': expect(page.locator('.gallery-result-count')).to_have_text('Showing 130 of 130 photos')
            else: expect(page.locator('.gallery-result-count')).to_have_count(0)
            expect(page.get_by_role('navigation',name='Main',include_hidden=True).get_by_role('link',name=re.compile(r'^' + 'Library' + r'\b'),include_hidden=True).locator('.sidebar-count')).to_have_text('130')
            before=anchors(('.gallery-summary','.gallery-filter-summary','.gallery-head','.pager'))
            chips=page.get_by_role('group',name='Refine photos')
            for name in ('Odd dates','No date'):
                button=chips.get_by_role('button',name=re.compile('^'+name+':'))
                button.click()
                expect(button).to_have_attribute('aria-pressed','true')
                expect(page.locator('.gallery-result-count')).to_have_text({'Odd dates':'Showing 60 of 130 photos','No date':'Showing 128 of 130 photos'}[name])
                unchanged(before)
                button.click()
                expect(button).to_have_attribute('aria-pressed','false')
                if place == 'review': expect(page.locator('.gallery-result-count')).to_have_text('Showing 130 of 130 photos')
                else: expect(page.locator('.gallery-result-count')).to_have_count(0)
                expect(page.locator('.card')).to_have_count(60)
                unchanged(before)
            if place == 'review':
                reason=page.get_by_label('Review reason',exact=True)
                reason.select_option('small')
                expect(page.locator('.gallery-result-count')).to_have_text('Showing 130 of 130 photos')
                unchanged(before)
                reason.select_option('all')
                unchanged(before)
            if os.environ.get('SHOTS'):page.screenshot(path=os.path.join(os.environ['SHOTS'],f'gallery-stable-{place}-{width}.png'))
    # Ordinary On/Off choices retain the minimum field and the controls beneath it.
    # Measure relative to the dialog, independent of browser focus scrolling.
    for width,theme in ((1440,'light'),(1000,'dark'),(720,'light')):
        page.set_viewport_size({'width':width,'height':1100})
        page.evaluate("theme => {localStorage.setItem('ns.theme',theme)}",theme)
        page.goto(sys.argv[1]+'/logs')
        page.get_by_role('button',name='Settings',exact=True).click()
        page.get_by_role('tab',name=re.compile('^Files')).click()
        choice=page.get_by_label('Small-image reminders',exact=True)
        minimum=page.get_by_label('Minimum shorter side (pixels)',exact=True)
        def settings_positions():
            return page.locator('.settings-body').evaluate("""e => {
                const origin=e.getBoundingClientRect().top;
                return ['#settings-small','#small-hint','.settings-actions'].map(s =>
                    e.querySelector(s).getBoundingClientRect().top-origin);
            }""")
        choice.select_option('on')
        expect(minimum).to_be_enabled()
        before=settings_positions()
        choice.select_option('off')
        expect(minimum).to_be_disabled()
        after=settings_positions()
        assert all(abs(a-b)<=1 for a,b in zip(before,after)),(width,before,after)
        choice.select_option('on')
        expect(minimum).to_be_enabled()
        assert all(abs(a-b)<=1 for a,b in zip(before,settings_positions()))
        choice.scroll_into_view_if_needed()
        if os.environ.get('SHOTS'):page.screenshot(path=os.path.join(os.environ['SHOTS'],f'settings-stable-{width}.png'))
        page.get_by_role('button',name='Close settings',exact=True).click()
    assert not errors,errors
    browser.close()
print('Navigation, Logs filters/statuses, and gallery filter anchors stayed within 1px at desktop and narrow widths')
