"""Palette persistence, theme contrast and narrow targets against the real UI."""
import os
import sys
import time
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    run = request.post('/api/v1/jobs/start', data={'mode':'index'}).json()['id']
    for _ in range(600):
        if (request.get(f'/api/v1/runs/{run}').json()['status'] not in ('Preparing', 'Running', 'Cancelling')
                and request.get('/api/v1/jobs/active').json()['active'] is None):
            break
        time.sleep(.2)
    else:
        raise AssertionError('Index timed out')
    context = browser.new_context(viewport={'width':1600,'height':1100})
    page = context.new_page()
    writes, errors = [], []
    page.on('request', lambda r: writes.append(r.url) if r.method in ('POST','PATCH','PUT') else None)
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(sys.argv[1])
    expect(page.locator('.card').first).to_be_visible()
    page.evaluate('document.fonts.ready')
    assert page.evaluate('document.fonts.check("14px Inter")')

    def shot(name):
        if os.environ.get('SHOTS'):
            page.screenshot(path=f"{os.environ['SHOTS']}/appearance-{name}.png")

    for mode in ('light','dark'):
        page.emulate_media(color_scheme=mode)
        for palette in ('cool','warm'):
            page.get_by_role('button', name='Settings', exact=True).click()
            panel = page.locator('.modal-shell > .settings')
            expect(panel.locator('section').first).to_have_class('appearance-settings')
            # In a short window the Files tab, the tallest, scrolls: a cue says there is more
            # below, then above.
            page.set_viewport_size({'width':1600,'height':600})
            page.get_by_role('tab', name='Files').click()
            expect(page.locator('.modal-scroll-cue.below')).to_be_visible()
            expect(page.locator('.modal-scroll-cue.above')).to_have_count(0)
            panel.evaluate('(el) => el.scrollTop = el.scrollHeight')
            expect(page.locator('.modal-scroll-cue.below')).to_have_count(0)
            expect(page.locator('.modal-scroll-cue.above')).to_be_visible()
            panel.evaluate('(el) => el.scrollTop = 0')
            expect(page.locator('.modal-scroll-cue.above')).to_have_count(0)
            expect(page.locator('.modal-scroll-cue.below')).to_be_visible()
            page.set_viewport_size({'width':1600,'height':1100})
            page.get_by_role('tab', name='Appearance').click()
            choice = page.get_by_label('Color palette', exact=True)
            choice.select_option(palette)
            expect(page.locator('html')).to_have_attribute('data-palette',palette)
            choice.scroll_into_view_if_needed()
            shot(f'{palette}-{mode}-settings')
            page.get_by_role('button', name='Close settings').click()
            # All enabled text colors against each neutral surface, including hover.
            ratios = page.evaluate('''() => {
                const style = getComputedStyle(document.documentElement);
                const rgb = name => {
                    const value = style.getPropertyValue(name).trim();
                    const hex = value.slice(1);
                    return (hex.length===3 ? [...hex].map(c=>c+c) : hex.match(/../g)).map(c=>parseInt(c,16)/255);
                };
                const lum = name => rgb(name).map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4).reduce((n,c,i)=>n+c*[.2126,.7152,.0722][i],0);
                const contrast = (a,b) => (Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
                const text = ['--text','--muted','--accent','--good','--warn','--bad'].flatMap(a=>['--bg','--surface','--surface-2'].map(b=>contrast(a,b)));
                return {text, accent:contrast('--accent','--accent-text'), danger:contrast('--danger-bg','--danger-text'), input:contrast('--control-border','--surface')};
            }''')
            assert min(ratios['text']) >= 4.5, (mode,palette,ratios)
            assert ratios['accent'] >= 4.5 and ratios['danger'] >= 4.5
            assert ratios['input'] >= 3
            page.reload()
            expect(page.locator('html')).to_have_attribute('data-palette',palette)
            expect(page.locator('.card').first).to_be_visible()
            page.locator('.card-image').first.click()
            expect(page.locator('.inspector .info')).not_to_have_count(0)
            shot(f'{palette}-{mode}-library')
            page.get_by_role('link',name='Logs',exact=True).click()
            expect(page.locator('.logs')).to_be_visible()
            shot(f'{palette}-{mode}-logs')
            page.goto(sys.argv[1]+'/stats')
            expect(page.locator('.stat-tile').first).to_be_visible()
            shot(f'{palette}-{mode}-stats')
            page.goto(sys.argv[1])
    assert not writes, 'Appearance changes wrote server settings'
    # A second tab sees palette changes.
    other = context.new_page()
    other.goto(sys.argv[1])
    expect(other.locator('html')).to_have_attribute('data-palette','warm')
    page.get_by_role('button',name='Settings',exact=True).click()
    page.get_by_label('Color palette',exact=True).select_option('cool')
    expect(other.locator('html')).to_have_attribute('data-palette','cool')
    page.get_by_role('button',name='Close settings').click()
    for width in (800,390,320):
        page.set_viewport_size({'width':width,'height':900})
        page.goto(sys.argv[1])
        expect(page.locator('.card').first).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        for name in ('Settings','Browse'):
            box = page.get_by_role('button',name=name,exact=True).bounding_box()
            assert box and box['height'] >= 44 and box['width'] >= 44, (name,box)
        card_target = page.locator('.card-check').first.bounding_box()
        assert card_target['height'] >= 44 and card_target['width'] >= 44
        page.get_by_role('button',name='Browse',exact=True).click()
        check = page.locator('.side-panel input[type=checkbox]').first
        expect(check).to_be_visible()
        box = check.bounding_box()
        assert box['height'] >= 44 and box['width'] >= 44
        # Start Settings from its normal closed-sidebar state on narrow screens.
        page.goto(sys.argv[1])
        page.get_by_role('button',name='Settings',exact=True).click()
        box = page.get_by_label('Color palette',exact=True).bounding_box()
        assert box and box['height'] >= 44
        page.get_by_role('button',name='Close settings').click()
    isolated = browser.new_context()
    denied = isolated.new_page()
    denied.add_init_script("Storage.prototype.getItem = () => {throw new Error('blocked')}; Storage.prototype.setItem = () => {throw new Error('blocked')}")
    denied.goto(sys.argv[1])
    expect(denied.locator('.card').first).to_be_visible()
    denied.get_by_role('button',name='Settings',exact=True).click()
    denied.get_by_label('Color palette',exact=True).select_option('warm')
    expect(denied.locator('html')).to_have_attribute('data-palette','warm')
    assert not errors, errors
    browser.close()
print('Both palettes in both modes: contrast, local persistence, cross-tab updates, self-hosted font and narrow controls passed')
