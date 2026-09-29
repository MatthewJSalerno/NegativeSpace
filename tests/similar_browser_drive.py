"""Gallery/Inspector similarity review using generated photos and real Index/Copy."""
import os
import re
import sys
import time

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok

    def run_job(mode):
        run = request.post('/api/v1/jobs/start', data={'mode': mode}).json()['id']
        for _ in range(600):
            outcome = request.get(f'/api/v1/runs/{run}').json()
            if outcome['status'] not in ('Preparing', 'Running', 'Cancelling'):
                break
            time.sleep(.2)
        assert outcome['status'] == 'Completed', outcome

    def shot(name):
        if os.environ.get('SHOTS'):
            page.screenshot(path=os.path.join(os.environ['SHOTS'], name + '.png'))

    run_job('index')
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(sys.argv[1])
    expect(page.get_by_role('link', name='Similar', exact=True)).to_have_count(0)
    page.get_by_role('button', name=re.compile('^Has similar photos')).click()
    expect(page.locator('.card')).to_have_count(0)
    expect(page.get_by_text('Copy or Move indexed photos to the destination first.', exact=False)).to_be_visible()
    # Only generated fixtures are copied in this isolated test catalog.
    run_job('copy')
    page.reload()
    expect(page.locator('.card').first).to_be_visible()
    gallery_photo = page.locator('.card').first
    reference = int(gallery_photo.get_attribute('data-id'))
    gallery_photo.get_by_role('checkbox').check()
    gallery_photo.get_by_role('button', name=re.compile('^Open ')).click()
    inspector = page.get_by_role('region', name='Photo details', exact=True)
    information_tab = inspector.get_by_role('tab', name='Photo information', exact=True)
    similar_tab = inspector.get_by_role('tab', name='Similar photos', exact=True)
    expect(information_tab).to_have_attribute('aria-selected', 'true')
    expect(inspector.locator('.photo-matches')).to_have_count(0)
    information_tab.focus()
    page.keyboard.press('ArrowRight')
    expect(similar_tab).to_be_focused()
    expect(similar_tab).to_have_attribute('aria-selected', 'true')
    assert f'photo={reference}' in page.url
    summary = inspector.get_by_role('region', name='Similar photos', exact=True)
    counts = request.get(f'/api/v1/similar/{reference}/counts').json()['counts']
    assert len(counts) == 6
    for c in counts:
        label = f'{c["threshold"]}% or higher: {c["count"]} matches'
        expect(summary.get_by_role('button', name=label, exact=True)).to_be_visible()
    # Make room for the grid using the existing preview divider; the reference
    # remains visible while the match panel scrolls independently.
    preview_divider = inspector.get_by_role('separator', name='Resize photo preview')
    preview_divider.focus()
    page.keyboard.press('Home')
    expect(preview_divider).to_have_attribute('aria-valuenow', '20')
    expect(inspector.get_by_role('button', name='Enlarge the photo')).to_be_in_viewport()
    shot('gallery-match-counts')
    assert summary.locator('.inspector-match-list').evaluate('e => getComputedStyle(e).gridTemplateColumns.split(" ").length') >= 2
    gallery_ids = page.locator('.card').evaluate_all('els => els.map(e => e.dataset.id)')
    summary.get_by_role('button', name=re.compile('^75% or higher:')).click()
    matches = summary.get_by_role('region', name='Matches for this photo', exact=True)
    expect(matches.locator('.inspector-match')).to_have_count(12)
    expect(page).to_have_url(re.compile('match=75'))
    matches.get_by_role('button', name='Next matches', exact=True).click()
    expect(inspector.get_by_role('button', name='Enlarge the photo')).to_be_in_viewport()
    expect(page).to_have_url(re.compile('match_page=2'))
    expect(matches.get_by_text('Page 2 of', exact=False)).to_be_visible()
    assert page.locator('.card').evaluate_all('els => els.map(e => e.dataset.id)') == gallery_ids
    expect(page.locator(f'.card[data-id="{reference}"] input')).to_be_checked()
    shot('gallery-inspector-matches')
    page.set_viewport_size({'width': 1920, 'height': 1000})
    inspector_divider = page.get_by_role('separator', name='Resize the photo panel')
    page.wait_for_function("Number(document.querySelector('[aria-label=\"Resize the photo panel\"]').getAttribute('aria-valuemax')) > 1000")
    inspector_divider.focus()
    for _ in range(12):
        before_width = int(inspector_divider.get_attribute('aria-valuenow'))
        max_width = int(inspector_divider.get_attribute('aria-valuemax'))
        page.keyboard.press('ArrowLeft')
        expect(inspector_divider).to_have_attribute('aria-valuenow', str(min(max_width, before_width + 40)))
    expect(inspector.locator('.inspector-main')).to_have_attribute('data-wide', 'true')
    inspector.get_by_role('tabpanel', name='Similar photos', exact=True).evaluate('e => e.scrollTop = 0')
    expect(inspector.get_by_role('button', name='Enlarge the photo')).to_be_in_viewport()
    assert matches.locator('.inspector-match-list').evaluate('e => getComputedStyle(e).gridTemplateColumns.split(" ").length') >= 2
    shot('inspector-matches-expanded')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    information_tab.click()
    expect(inspector.get_by_role('tabpanel', name='Photo information')).to_be_visible()
    expect(matches).to_have_count(0)
    page.reload()
    expect(information_tab).to_have_attribute('aria-selected', 'true')
    similar_tab.click()
    expect(matches.get_by_text('Page 2 of', exact=False)).to_be_visible()
    expect(summary.get_by_role('button', name=re.compile('^75% or higher:'))).to_have_attribute('aria-pressed', 'true')
    matches.get_by_role('button', name=re.compile('^Review side by side:')).first.click()
    dialog = page.get_by_role('dialog', name='Review photo match', exact=True)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text('Different bytes (different SHA-1).', exact=False)).to_be_visible()
    dialog.get_by_role('slider', name='Zoom both previews', exact=True).fill('2')
    dialog.get_by_role('slider', name='Horizontal position', exact=True).fill('75')
    transforms = dialog.locator('.review-zoom').evaluate_all('els => els.map(e => ({transform:e.style.transform, origin:e.style.transformOrigin}))')
    assert len(transforms) == 2 and transforms[0] == transforms[1] and transforms[0]['transform'] == 'scale(2)', transforms
    dialog.get_by_role('button', name='Related photograph', exact=True).click()
    expect(dialog.get_by_role('status')).to_contain_text('Saved: Related photograph')
    shot('match-review-desktop')
    dialog.get_by_role('button', name='Close review', exact=True).click()
    expect(matches.get_by_role('button', name=re.compile('^Review side by side:')).first).to_be_focused()
    page.reload()
    matches.get_by_role('button', name=re.compile('^Review side by side:')).first.click()
    expect(dialog.get_by_role('button', name='Related photograph', exact=True)).to_have_attribute('aria-pressed', 'true')
    page.set_viewport_size({'width': 700, 'height': 844})
    assert dialog.evaluate('e => e.scrollWidth <= e.clientWidth + 1'), 'review overflow at narrow width'
    page.set_viewport_size({'width': 1440, 'height': 1000})
    dialog.get_by_role('button', name='Close review', exact=True).click()
    # Threshold changes are local to the Inspector; a failed request has a retry.
    page.route('**/api/v1/similar/*?*', lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
    summary.get_by_role('button', name=re.compile('^100% or higher:')).click()
    expect(matches.get_by_role('alert')).to_be_visible()
    page.unroute('**/api/v1/similar/*?*')
    matches.get_by_role('button', name='Retry matches', exact=True).click()
    expect(matches.locator('.inspector-match')).to_have_count(12)
    expect(page).not_to_have_url(re.compile('match_page='))
    summary.get_by_text('Validation and performance', exact=True).click()
    diagnostics = summary.get_by_role('region', name='Matching diagnostics', exact=True)
    expect(diagnostics.get_by_text('Related photograph judgments', exact=True).locator('+ dd')).to_have_text('1')
    summary.get_by_text('Validation and performance', exact=True).click()
    # Back from another screen restores the reference, threshold and gallery view.
    page.get_by_role('link', name='Logs', exact=True).click()
    page.go_back()
    expect(summary.get_by_role('button', name=re.compile('^100% or higher:'))).to_have_attribute('aria-pressed', 'true')
    expect(page.get_by_role('button', name=re.compile('^Has similar photos'))).to_have_attribute('aria-pressed', 'true')
    # A failed count load must not fabricate zeros or lose the selected threshold.
    page.route('**/api/v1/similar/*/counts', lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
    page.reload()
    expect(summary.get_by_role('button', name='Retry match counts')).to_be_visible()
    expect(summary.locator('.match-thresholds')).to_have_count(0)
    page.unroute('**/api/v1/similar/*/counts')
    summary.get_by_role('button', name='Retry match counts').click()
    expect(summary.locator('.match-thresholds button')).to_have_count(6)
    # Narrow Inspector and nested comparison use shared modal/focus behavior.
    page.set_viewport_size({'width': 700, 'height': 844})
    expect(page.get_by_role('dialog', name='Photo details', exact=True)).to_be_visible()
    expect(summary.locator('.match-thresholds button')).to_have_count(6)
    assert summary.evaluate('e => e.scrollWidth <= e.clientWidth + 1'), 'Inspector matches overflow'
    matches.get_by_role('button', name=re.compile('^Review side by side:')).first.click()
    expect(dialog).to_be_visible()
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(page.get_by_role('dialog', name='Photo details', exact=True)).to_be_visible()
    shot('gallery-matches-narrow')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    # Browsing photos retains the tab and threshold, with match paging reset.
    old_title = inspector.locator('.inspector-head h2').inner_text()
    inspector.get_by_role('button', name='Next photo', exact=True).click()
    expect(inspector.locator('.inspector-head h2')).not_to_have_text(old_title)
    expect(similar_tab).to_have_attribute('aria-selected', 'true')
    expect(summary.get_by_role('button', name=re.compile('^100% or higher:'))).to_have_attribute('aria-pressed', 'true')
    expect(page).not_to_have_url(re.compile('match_page='))
    # Old standalone/exact-mode bookmarks redirect into the same gallery workflow.
    page.goto(f'{sys.argv[1]}/similar?mode=exact&photo={reference}&threshold=85')
    expect(page).to_have_url(re.compile(r'/\?view=similar&photo=\d+&tab=similar&match=85'))
    expect(summary.get_by_role('button', name=re.compile('^85% or higher:'))).to_have_attribute('aria-pressed', 'true')
    expect(matches.locator('.inspector-match')).to_have_count(12)
    # A saved page beyond the remaining candidates returns to the last valid page.
    page.goto(page.url + '&match_page=999')
    expect(page).not_to_have_url(re.compile('match_page=999'))
    expect(matches.locator('.inspector-match').first).to_be_visible()
    matches.get_by_role('button', name='Hide matches', exact=True).click()
    expect(matches).to_have_count(0)
    expect(page).not_to_have_url(re.compile('match='))
    page.reload()
    expect(summary.locator('.match-thresholds button')).to_have_count(6)
    expect(matches).to_have_count(0)
    assert not errors, errors
    browser.close()
    print('Gallery similarity browser checks passed')
