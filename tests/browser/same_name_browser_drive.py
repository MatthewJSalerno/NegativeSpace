"""Same-name labels load with the result and remain stable across pages and themes."""
import os
from pathlib import Path
import sys
import time
from playwright.sync_api import expect, sync_playwright

# Generated harness files only. Distinct trailers retain valid JPEGs without
# duplicating the existing photos' bytes and being folded into their cards.
for folder, number in [('Camera/DCIM', 10), ('Phone/DCIM', 20)]:
    target = Path('/src') / folder / 'same-name.jpg'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(Path(f'/src/photo-{number:03d}.jpg').read_bytes() + folder.encode())
    os.utime(target, (1686000000, 1686000000))

with sync_playwright() as p:
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    def job(mode):
        response = request.post('/api/v1/jobs/start', data={'mode':mode})
        assert response.ok, response.text()
        run = response.json()['id']
        for _ in range(600):
            if (request.get(f'/api/v1/runs/{run}').json()['status'] not in ('Preparing','Running','Cancelling')
                    and request.get('/api/v1/jobs/active').json()['active'] is None):
                return
            time.sleep(.2)
        raise AssertionError('Job did not finish')
    job('index')
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1440,'height':900}, color_scheme='dark')
    errors=[]
    page.on('pageerror', lambda e:errors.append(str(e)))
    page.goto(sys.argv[1]+'/?view=unorganized&q=same-name&sort=name')
    expect(page.locator('.card')).to_have_count(2)
    page.get_by_role('button',name='Close index summary',exact=True).click()
    labels=page.locator('.card-folder')
    expect(labels).to_have_text(['…/Camera/DCIM','…/Phone/DCIM'])
    for i, folder in enumerate(['Camera','Phone']):
        expect(page.locator('.card-name').nth(i)).to_have_attribute('title', f'/data/source/{folder}/DCIM/same-name.jpg')
    # Page-size-one API reads must already contain the same labels.
    for n, folder in enumerate(['Camera','Phone'],1):
        result=request.get(f'/api/v1/photos?view=unorganized&q=same-name&sort=name&page_size=1&page={n}').json()
        assert result['items'][0]['name_context']['folder']==f'…/{folder}/DCIM'
    for theme in ('dark','light'):
        page.evaluate("theme => { localStorage.setItem('ns.theme',theme); location.reload(); }",theme)
        expect(labels).to_have_count(2)
        before=labels.evaluate_all('els => els.map(e => e.getBoundingClientRect().top)')
        page.locator('.card-name').first.hover()
        after=labels.evaluate_all('els => els.map(e => e.getBoundingClientRect().top)')
        assert before==after,(before,after)
        if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+f'/same-name-{theme}.png')
    page.set_viewport_size({'width':800,'height':600})
    page.locator('html').evaluate("el => el.style.fontSize='200%'")
    expect(labels).to_have_count(2)
    assert labels.evaluate_all('els => els.every(e => e.clientHeight > 0 && e.scrollHeight === e.clientHeight)')
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/same-name-reflow.png',full_page=True)
    # Narrowing the actual result removes the labels, without changing selection.
    page.goto(sys.argv[1]+'/?view=source&folder=Camera&q=same-name')
    expect(page.locator('.card')).to_have_count(1)
    expect(labels).to_have_count(0)
    job('copy')
    page.goto(sys.argv[1]+'/?view=organized&q=same-name&sort=name')
    expect(page.locator('.card')).to_have_count(2)
    expect(labels).to_have_count(0)
    renamed=page.locator('.card-name').filter(has_text='same-name_1.jpg')
    expect(renamed).to_have_count(1)
    assert 'Renamed on arrival: another photo already had this name' in renamed.get_attribute('title')
    assert '/data/source/' in renamed.get_attribute('title')
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/same-name-renamed.png')
    assert not errors,errors
    browser.close()
print('Same-name cards: full-result labels, filtering, hover history, themes and reflow passed.')
