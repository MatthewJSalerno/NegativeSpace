"""Real Index/Copy: low-detail notes mark both real and unrelated matches without hiding them."""
import os
import re
import sys
import time
from playwright.sync_api import expect, sync_playwright

NOTE = "Mostly dark or plain: matches like this are often unrelated photos."
with sync_playwright() as p:
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    def job(mode):
        response = request.post('/api/v1/jobs/start', data={'mode':mode})
        assert response.ok, response.text()
        run = response.json()['id']
        for _ in range(600):
            outcome = request.get(f'/api/v1/runs/{run}').json()
            if (outcome['status'] not in ('Preparing','Running','Cancelling')
                    and request.get('/api/v1/jobs/active').json()['active'] is None):
                assert outcome['status'] == 'Completed', outcome
                return
            time.sleep(.2)
        raise AssertionError('Job did not finish')
    job('index')
    job('copy')
    photos = request.get('/api/v1/photos?view=organized&q=scn-low-detail').json()
    assert photos['total'] == 5, photos
    by_name = {item['filename']:item for item in photos['items']}
    moon = by_name['scn-low-detail-moon.png']['id']
    matches = request.get(f'/api/v1/similar/{moon}').json()
    assert matches['total'] == 2, matches
    assert {r['filename'] for r in matches['items']} == {'scn-low-detail-moon-brighter.png','scn-low-detail-lamp.png'}
    assert all(r['score'] == 100 and r['low_detail_match'] for r in matches['items'])
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1440,'height':1000},color_scheme='dark')
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(sys.argv[1]+'/?view=organized&q=scn-low-detail-moon.png')
    page.locator('.card').get_by_role('button',name=re.compile('^Open ')).click()
    page.get_by_role('tab',name='Similar photos',exact=True).click()
    expect(page.locator('.inspector-match-list').get_by_text(NOTE,exact=True)).to_have_count(2)
    def shot(name):
        if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/'+name+'.png',full_page=True)
    page.locator('.inspector-match-list').get_by_text(NOTE,exact=True).first.scroll_into_view_if_needed()
    shot('low-detail-inspector')
    page.get_by_role('button',name='Review side by side: scn-low-detail-lamp.png',exact=True).click()
    review=page.get_by_role('dialog',name='Review photo match',exact=True)
    expect(review.locator('.workspace-status').get_by_text('· '+NOTE,exact=True)).to_be_visible()
    expect(review.locator('.review-filmstrip button')).to_have_count(2)
    shot('low-detail-comparison')
    page.set_viewport_size({'width':1000,'height':800})
    page.locator('html').evaluate("el=>el.style.fontSize='200%'")
    expect(review.locator('.workspace-status').get_by_text('· '+NOTE,exact=True)).to_be_visible()
    assert review.evaluate('el=>el.scrollWidth <= el.clientWidth+1')
    shot('low-detail-comparison-zoom')
    review.get_by_role('button',name='Back to gallery',exact=False).click()
    page.locator('html').evaluate("el=>el.style.fontSize=''")
    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_role('link',name='Stats',exact=True).click()
    expect(page.get_by_text('Low-detail photos',exact=True)).to_be_visible()
    # Flat generated harness photos count too; the catalog response defines the total.
    health=request.get('/api/v1/stats').json()['health']
    assert health['low_detail_photos'] >= 5
    row=page.get_by_text('Low-detail photos',exact=True).locator('..')
    expect(row).to_contain_text(str(health['low_detail_photos']))
    shot('low-detail-stats')
    assert errors == [], errors
    browser.close()
print('Low-detail match notes, scores, counts, Stats and zoom: PASS')
