"""Notification acknowledgments, recovery and selection geometry on generated fixtures."""
import os
import re
import sys
import time
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1]
with sync_playwright() as p:
    request = p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    def job(mode):
        response = request.post('/api/v1/jobs/start', data={'mode': mode})
        assert response.ok, response.text()
        run = response.json()['id']
        for _ in range(600):
            if request.get('/api/v1/jobs/active').json()['active'] is None:
                return run
            time.sleep(.2)
        raise AssertionError('Job did not settle')
    # Generated invalid image exercises real failure explanations without sample data.
    with open('/src/unreadable.jpg', 'wb') as fixture:
        fixture.write(b'Generated non-image fixture')
    first = job('index')
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1600, 'height':1000}, color_scheme='dark')
    errors=[]
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(base)
    bell=page.get_by_role('button',name=re.compile(r'^Notifications,'))
    panel=page.get_by_role('region',name='Notifications',exact=True)
    expect(bell).to_have_attribute('aria-label','Notifications, 1 unread')
    expect(page.locator('.finished-banner')).to_have_count(0)
    held=[]
    page.route('**/api/v1/notifications/read',lambda route: held.append(route))
    y=page.locator('.gallery-context').bounding_box()['y']
    bell.click()
    expect(panel.get_by_text('Marking notices read…')).to_be_visible()
    assert request.get('/api/v1/notifications/unread').json()['unread']==1
    assert page.locator('.gallery-context').bounding_box()['y']==y
    held.pop().fulfill(status=503,json={'error':'catalog_busy','message':'Generated failure'})
    expect(panel.get_by_role('alert')).to_contain_text('Could not mark notifications read')
    panel.get_by_role('button',name='Retry marking read').click()
    expect(panel.get_by_text('Marking notices read…')).to_be_visible()
    held.pop().abort()
    page.reload()
    expect(bell).to_have_attribute('aria-label','Notifications, 1 unread')
    page.unroute('**/api/v1/notifications/read')
    bell.click()
    expect(bell).to_have_attribute('aria-label','Notifications, 0 unread')
    expect(panel.locator('.notification-item')).to_have_count(1)
    page.keyboard.press('Escape')
    expect(bell).to_be_focused()
    expect(panel).to_have_count(0)
    page.get_by_role('link',name='Logs',exact=True).click()
    expect(bell).to_have_attribute('aria-label','Notifications, 0 unread')
    page.evaluate('localStorage.clear()')
    page.reload()
    expect(bell).to_have_attribute('aria-label','Notifications, 0 unread')
    second=job('copy')
    expect(bell).to_have_attribute('aria-label','Notifications, 1 unread',timeout=15000)
    # Another tab acknowledging an older notice does not mark the new job read.
    assert request.put('/api/v1/notifications/read',data={'run_ids':[first]}).ok
    assert request.get('/api/v1/notifications/unread').json()['unread']==1
    page.route('**/api/v1/notifications',lambda route: route.fulfill(status=503,json={'error':'unavailable','message':'Generated failure'}))
    bell.click()
    expect(panel.get_by_role('alert')).to_contain_text('Could not load notifications')
    page.unroute('**/api/v1/notifications')
    panel.get_by_role('button',name='Retry',exact=True).click()
    expect(panel.locator('.notification-item')).to_have_count(2)
    expect(bell).to_have_attribute('aria-label','Notifications, 0 unread')
    card = panel.locator('.notification-item').first
    links = card.locator('.notification-links')
    links_before = links.bounding_box()
    card.locator('p').first.hover()
    expect(card.locator('.help-content')).to_have_count(0)
    card.locator('summary').click()
    expect(card.locator('details')).to_have_attribute('open', '')
    expect(card.locator('details p')).to_contain_text('Why they failed:')
    assert links.bounding_box() == links_before
    card.get_by_role('link', name='View failures').click(trial=True)
    if os.environ.get('SHOTS'): page.screenshot(path=os.environ['SHOTS']+'/notifications-details.png')
    card.locator('summary').focus()
    page.keyboard.press('Enter')
    expect(card.locator('details')).not_to_have_attribute('open', '')
    if os.environ.get('SHOTS'): page.screenshot(path=os.environ['SHOTS']+'/notifications-dark.png')
    panel.locator('.notification-item').first.get_by_role('link',name='Show these photos',exact=True).click()
    expect(page).to_have_url(re.compile('run='+str(second)))
    expect(panel).to_have_count(0)
    page.goto(base+'/?view=organized')
    checks=page.locator('.card-check input')
    expect(checks).to_have_count(60)
    page.evaluate('document.fonts.ready')
    checks.nth(0).check()
    bar=page.get_by_role('region',name='Selection')
    show=bar.get_by_role('button',name='Show only selected',exact=True)
    reject=bar.get_by_role('button',name=re.compile(r'^Reject'))
    position=(show.bounding_box()['x'],reject.bounding_box()['x'])
    for index in range(1,11):
        checks.nth(index).check()
        expect(reject).to_have_accessible_name(f'Reject ({index+1})…')
        assert (show.bounding_box()['x'],reject.bounding_box()['x'])==position
    page.get_by_role('searchbox', name='Search filenames').fill('photo-000')
    expect(bar.locator('.selection-outside > span').last).to_contain_text('outside this view')
    assert (show.bounding_box()['x'],reject.bounding_box()['x'])==position
    page.get_by_role('searchbox', name='Search filenames').fill('')
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
    if os.environ.get('SHOTS'): page.screenshot(path=os.environ['SHOTS']+'/selection-stable.png')
    bar.get_by_role('button',name='Clear selection').click()
    for mode in ('light','dark'):
        page.evaluate("mode => {localStorage.setItem('ns.theme', mode); window.dispatchEvent(new StorageEvent('storage',{key:'ns.theme',newValue:mode}));}",mode)
        for width,height in [(1600,1000),(800,500),(720,900)]:
            page.set_viewport_size({'width':width,'height':height})
            bell.click()
            expect(panel.locator('.notification-item').first).to_be_visible()
            box=panel.bounding_box()
            assert box['x']>=0 and box['x']+box['width']<=width+1 and box['y']+box['height']<=height+1, box
            expect(panel.get_by_role('button',name='Close notifications')).to_be_in_viewport()
            if os.environ.get('SHOTS'): page.screenshot(path=f"{os.environ['SHOTS']}/notifications-{mode}-{width}.png")
            page.keyboard.press('Escape')
    assert not errors,errors
    browser.close()
print('PASS: notifications read acknowledgment/failure/reload, independent jobs, navigation, links, stable selection and reflow')
