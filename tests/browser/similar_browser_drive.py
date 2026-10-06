"""Gallery/Inspector similarity review using generated photos and real Index/Copy."""
import os
import json
from urllib.parse import parse_qs, urlsplit
import re
import sys
import time

from playwright.sync_api import expect, sync_playwright

def gallery_context(url):
    return {k:v for k,v in parse_qs(urlsplit(url).query).items() if k != 'review'}

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
    gallery_sort = page.get_by_role('combobox', name='Sort', exact=True)
    gallery_threshold = page.get_by_role('combobox', name='Gallery match threshold', exact=True)
    page.get_by_role('button', name='Most matches first', exact=True).click()
    expect(gallery_sort).to_have_value('matches')
    gallery_threshold.select_option('95')
    expect(page).to_have_url(re.compile('match_min=95'))
    expected = request.get('/api/v1/photos?view=similar&sort=matches&match_min=95').json()
    expect(page.locator('.card').first).to_have_attribute('data-id', str(expected['items'][0]['id']))
    expect(page.locator('.card').first.locator('.card-match-count')).to_have_attribute('title', f"{expected['items'][0]['similar_count']} matches at or above 95%")
    page.locator('.card').first.get_by_role('checkbox').check()
    gallery_threshold.select_option('90')
    expect(page.locator('.card').first.get_by_role('checkbox')).to_be_checked()
    page.locator('.card').first.get_by_role('button', name=re.compile('^Open ')).click()
    expect(page.get_by_role('tab', name='Similar photos', exact=True)).to_have_attribute('aria-selected', 'true')
    expect(page.get_by_role('button', name=re.compile('^90% or higher:'))).to_have_attribute('aria-pressed', 'true')
    page.reload()
    expect(gallery_sort).to_have_value('matches')
    expect(gallery_threshold).to_have_value('90')
    expect(page.get_by_role('button', name=re.compile('^90% or higher:'))).to_have_attribute('aria-pressed', 'true')
    page.get_by_role('link', name='Logs', exact=True).click()
    page.go_back()
    expect(gallery_sort).to_have_value('matches')
    expect(gallery_threshold).to_have_value('90')
    expect(page.locator('.card').first.locator('.card-match-count')).to_have_attribute('title', re.compile('matches at or above 90%'))
    shot('gallery-match-sort')
    page.set_viewport_size({'width':700,'height':844})
    # Close the narrow Inspector before exercising gallery controls.
    page.get_by_role('tab', name='Photo information', exact=True).click()
    page.get_by_role('dialog', name='Photo details', exact=True).get_by_role('button', name='Close', exact=True).click()
    expect(gallery_threshold).to_be_visible()
    assert page.locator('.browse-search').evaluate('e => e.scrollWidth <= e.clientWidth + 1')
    shot('gallery-match-sort-narrow')
    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_role('button', name=re.compile('^All photos')).click()
    expect(gallery_sort).to_have_value('newest')
    expect(gallery_threshold).to_have_count(0)
    page.get_by_role('button', name=re.compile('^Has similar photos')).click()
    gallery_threshold.select_option('75')
    gallery_photo = page.locator('.card').first
    expected_group = request.get('/api/v1/photos?view=similar&group_sets=true&match_min=75&sort=matches').json()['items'][0]
    expect(gallery_photo).to_have_attribute('data-id', str(expected_group['id']))
    reference = expected_group['id']
    gallery_photo.get_by_role('checkbox').check()
    gallery_photo.get_by_role('button', name=re.compile('^Open ')).click()
    inspector = page.get_by_role('region', name='Photo details', exact=True)
    information_tab = inspector.get_by_role('tab', name='Photo information', exact=True)
    similar_tab = inspector.get_by_role('tab', name='Similar photos', exact=True)
    expect(similar_tab).to_have_attribute('aria-selected', 'true')
    information_tab.click()
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
    reference_preview = dialog.get_by_role('figure', name='Reference preview')
    candidate_preview = dialog.get_by_role('figure', name='Candidate preview')
    dialog.get_by_role('button', name='Rotate reference right', exact=True).click()
    dialog.get_by_role('button', name='Rotate candidate left', exact=True).click()
    expect(reference_preview).to_contain_text('Viewing rotation: 90°')
    expect(candidate_preview).to_contain_text('Viewing rotation: 270°')
    expect(reference_preview).to_contain_text('Displayed: 240 × 320')
    expect(candidate_preview).to_contain_text('Displayed: 240 × 320')
    dialog.get_by_role('button', name='Rotate reference right', exact=True).click()
    expect(reference_preview).to_contain_text('Displayed: 320 × 240')
    dialog.get_by_role('button', name='Rotate reference left', exact=True).click()
    dialog.get_by_role('slider', name='Zoom reference', exact=True).fill('2')
    expect(dialog.get_by_role('slider', name='Zoom candidate', exact=True)).to_have_value('1')
    dialog.get_by_role('checkbox', name='Link zoom and position').check()
    expect(dialog.get_by_role('slider', name='Zoom candidate', exact=True)).to_have_value('2')
    dialog.get_by_role('slider', name='Reference horizontal position', exact=True).fill('75')
    expect(dialog.get_by_role('slider', name='Candidate horizontal position', exact=True)).to_have_value('75')
    expect(candidate_preview).to_contain_text('Viewing rotation: 270°')
    # The address records current-pair transforms and navigation, not file edits.
    page.wait_for_function("""() => {
        const review = JSON.parse(new URLSearchParams(location.search).get('review'));
        return review?.views[review.candidate]?.rotation === 270
            && review.views[review.candidate]?.x === 75 && review.views[review.reference]?.x === 75;
    }""")
    saved_workspace = parse_qs(urlsplit(page.url).query)['review'][0]
    page.reload()
    expect(dialog).to_be_visible()
    expect(reference_preview).to_contain_text('Viewing rotation: 90°')
    expect(candidate_preview).to_contain_text('Viewing rotation: 270°')
    expect(dialog.get_by_role('slider', name='Candidate horizontal position', exact=True)).to_have_value('75')
    assert json.loads(parse_qs(urlsplit(page.url).query)['review'][0]) == json.loads(saved_workspace)
    shot('comparison-restored')
    # Expanded pan controls and details grow the comparison rather than creating
    # a second vertical scroll area inside the review window.
    def full_comparison():
        assert dialog.locator('.review-previews, .review-comparison').evaluate_all('''els => els.every(e => {
            const bounds = e.getBoundingClientRect();
            return e.scrollHeight <= e.clientHeight + 1 && [...e.querySelectorAll('.review-preview-controls, .review-pair-options')].every(child =>
                child.getBoundingClientRect().bottom <= bounds.bottom + 1);
        })'''), 'Photo controls or details are clipped inside the comparison'
    for height in (700, 1000):
        page.set_viewport_size({'width': 1440, 'height': height})
        full_comparison()
        dialog.get_by_role('checkbox', name='Link zoom and position').scroll_into_view_if_needed()
        expect(dialog.get_by_role('checkbox', name='Link zoom and position')).to_be_in_viewport()
        assert dialog.locator('.review-previews').evaluate('e => e.scrollTop') == 0
        assert dialog.locator('.match-review-dialog').evaluate('e => e.scrollTop') > 0
    dialog.get_by_role('button', name='Next candidate', exact=True).click()
    expect(candidate_preview).not_to_contain_text('Viewing rotation:')
    expect(reference_preview).to_contain_text('Viewing rotation: 90°')
    dialog.get_by_role('button', name='Previous candidate', exact=True).click()
    expect(candidate_preview).to_contain_text('Viewing rotation: 270°')
    # The workspace frame: the header stays in view while the window scrolls, names the
    # position, and ← → step through candidates, stopping at the first one.
    expect(dialog.locator('.workspace-header')).to_be_in_viewport()
    # It opens where the Inspector was (here its second page), so read the start.
    position = dialog.locator('.workspace-step span')
    expect(position).to_have_text(re.compile(r'^Candidate \d+ of \d+$'))
    start = int(re.match(r'Candidate (\d+)', position.inner_text()).group(1))
    at = lambda n: re.compile(rf'^Candidate {n} of ')
    dialog.get_by_role('button', name='Next candidate', exact=True).focus()
    page.keyboard.press('ArrowRight')
    expect(position).to_have_text(at(start + 1))
    page.keyboard.press('ArrowLeft')
    expect(position).to_have_text(at(start))
    # Controls that use the arrows keep them: on the divider, ← → resize, not step.
    divider = dialog.get_by_role('separator', name='Resize comparison and information')
    divider.focus()
    page.keyboard.press('ArrowRight')
    expect(divider).to_have_attribute('aria-valuenow', '74')
    expect(position).to_have_text(at(start))
    page.keyboard.press('ArrowLeft')
    expect(divider).to_have_attribute('aria-valuenow', '72')
    expect(candidate_preview).to_contain_text('Viewing rotation: 270°')
    metadata = dialog.get_by_role('region', name='Metadata comparison')
    file_table = metadata.get_by_role('table', name='File and image properties', exact=True)
    expect(file_table.get_by_role('columnheader', name='Reference', exact=True)).to_be_visible()
    # Recorded formats and dimensions describe image properties, not inferred
    # winners. Compare exact byte counts before rounding the displayed size.
    property_case = 'different'
    def inspect_properties(route):
        response = route.fetch()
        data = response.json()
        is_reference = data['id'] == reference
        if property_case == 'different':
            data.update(width=6000 if is_reference else 9000, height=4000 if is_reference else 6000,
                        file_size=25000000 if is_reference else 25000001,
                        metadata=[['FileType', 'NEF' if is_reference else 'JPEG']])
        else:
            data.update(width=None, height=None, file_size=None, metadata=[],
                        filename='unknown' if is_reference else 'candidate.NEF')
        route.fulfill(response=response, json=data)
    page.route('**/api/v1/photos/*/inspect', inspect_properties)
    dialog.get_by_role('button', name='Refresh comparison', exact=True).click()
    expect(file_table.get_by_role('row', name=re.compile('^Format'))).to_contain_text('NEF')
    expect(file_table.get_by_role('row', name=re.compile('^Format'))).to_contain_text('JPEG')
    expect(file_table.get_by_role('row', name=re.compile('^Megapixels'))).to_contain_text('24 MP')
    expect(file_table.get_by_role('row', name=re.compile('^Megapixels'))).to_contain_text('54 MP')
    size_row = file_table.get_by_role('row', name=re.compile('^File size'))
    expect(size_row).to_have_attribute('data-different', 'true')
    expect(size_row).to_contain_text('25,000,001 bytes')
    expect(file_table.get_by_role('row', name=re.compile('^Aspect ratio'))).to_contain_text('3:2')
    metadata.get_by_role('checkbox', name='Differences only').check()
    expect(file_table.get_by_role('row', name=re.compile('^Aspect ratio'))).to_have_count(0)
    expect(file_table.get_by_role('row', name=re.compile('^Pixel dimensions'))).to_be_visible()
    shot('file-image-differences')
    metadata.get_by_role('checkbox', name='Differences only').uncheck()
    property_case = 'missing'
    dialog.get_by_role('button', name='Refresh comparison', exact=True).click()
    expect(file_table.get_by_role('row', name=re.compile('^Format'))).to_contain_text('NEF (extension only)')
    expect(file_table.get_by_role('row', name=re.compile('^Pixel dimensions')).get_by_role('cell').first).to_have_text('Not recorded')
    expect(file_table.get_by_role('row', name=re.compile('^Aspect ratio')).get_by_role('cell').last).to_have_text('Not recorded')
    page.unroute('**/api/v1/photos/*/inspect', inspect_properties)
    dialog.get_by_role('button', name='Refresh comparison', exact=True).click()
    expect(file_table.get_by_role('row', name=re.compile('^Format'))).to_contain_text('JPEG')
    metadata.get_by_role('checkbox', name='All recorded tags').check()
    expect(file_table.get_by_role('row', name=re.compile('^Pixel dimensions')).get_by_role('cell').first).to_have_text('320 × 240')
    # Column context remains visible while scrolling each section. In narrow
    # reflow the containing review window takes over scrolling from the pane.
    def sticky_headings(table, scroll_selector):
        result = table.evaluate('''async (table, selector) => {
            const scroller = table.closest(selector), head = table.querySelector('thead');
            scroller.scrollTop = 0;
            scroller.scrollTop = head.getBoundingClientRect().top - scroller.getBoundingClientRect().top + 40;
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            return {delta: head.getBoundingClientRect().top - scroller.getBoundingClientRect().top - parseFloat(getComputedStyle(scroller).paddingTop),
                scroll: scroller.scrollTop, background: getComputedStyle(head).backgroundColor};
        }''', scroll_selector)
        assert result['scroll'] > 0 and abs(result['delta']) < 2, result
        assert result['background'] != 'rgba(0, 0, 0, 0)', result
        expect(table.get_by_role('columnheader', name='Candidate', exact=True)).to_be_in_viewport()
    tags_table = metadata.get_by_role('table', name='All recorded metadata', exact=True)
    for table in (file_table, metadata.get_by_role('table', name='Capture information', exact=True), tags_table):
        sticky_headings(table, '.review-information')
    shot('sticky-metadata-headings')
    page.set_viewport_size({'width': 700, 'height': 844})
    sticky_headings(tags_table, '.match-review-dialog')
    shot('sticky-metadata-headings-narrow')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    dialog.locator('.review-information, .match-review-dialog').evaluate_all('els => els.forEach(e => e.scrollTop = 0)')
    metadata.get_by_role('searchbox', name='Find metadata field').fill('ImageWidth')
    tags_table = metadata.get_by_role('table', name='All recorded metadata', exact=True)
    expect(tags_table.locator('tbody tr').first).to_contain_text('ImageWidth')
    metadata.get_by_role('checkbox', name='Differences only').check()
    expect(tags_table.locator('tbody tr')).to_have_count(0)
    expect(tags_table.locator('..').get_by_text('No fields match these filters.')).to_be_visible()
    metadata.get_by_role('checkbox', name='Differences only').uncheck()
    metadata.get_by_role('checkbox', name='All recorded tags').uncheck()
    # Keyboard resizing and view-only transforms never navigate the main gallery.
    before_url = page.url
    resize = dialog.get_by_role('separator', name='Resize comparison and information')
    resize.focus()
    page.keyboard.press('ArrowLeft')
    expect(resize).to_have_attribute('aria-valuenow', '70')
    assert gallery_context(page.url) == gallery_context(before_url)
    dialog.get_by_role('button', name='Reset reference view').click()
    dialog.get_by_role('button', name='Reset candidate view').click()
    full_comparison()
    dialog.locator('.review-filmstrip').scroll_into_view_if_needed()
    expect(dialog.get_by_role('button', name='Next candidate', exact=True)).to_be_in_viewport()
    assert dialog.locator('.review-previews').evaluate('e => e.scrollTop') == 0
    dialog.locator('.match-review-dialog').evaluate('e => e.scrollTop = 0')
    page.wait_for_function("[...document.querySelectorAll('.review-rotation img')].length === 2 && [...document.querySelectorAll('.review-rotation img')].every(e => e.complete && e.naturalWidth > 0)")
    shot('match-review-desktop')
    dialog.get_by_role('button', name='Back to gallery', exact=True).click()
    expect(matches.get_by_role('button', name=re.compile('^Review side by side:')).first).to_be_focused()
    page.reload()
    # Explicit selections are in-memory; establish one after the reload before
    # checking that reference promotion leaves it intact.
    page.locator(f'.card[data-id="{reference}"] input').check()
    matches.get_by_role('button', name=re.compile('^Review side by side:')).first.click()
    expect(dialog.get_by_role('slider', name='Zoom reference', exact=True)).to_have_value('1')
    # Failed loads remain errors, not empty metadata or an empty match set.
    page.route('**/api/v1/photos/*/inspect', lambda route: route.fulfill(status=503, json={'detail': {'message': 'Metadata temporarily unavailable'}}))
    dialog.get_by_role('button', name='Refresh comparison', exact=True).click()
    expect(metadata.get_by_role('alert')).to_be_visible()
    page.unroute('**/api/v1/photos/*/inspect')
    metadata.get_by_role('button', name='Retry metadata').click()
    expect(file_table).to_be_visible()
    page.route('**/api/v1/similar/*?*', lambda route: route.fulfill(status=503, json={'detail': {'message': 'Candidates temporarily unavailable'}}))
    dialog.get_by_role('button', name='Refresh comparison', exact=True).click()
    candidates = dialog.get_by_role('region', name='Candidate photos')
    expect(candidates.get_by_role('alert')).to_be_visible()
    page.unroute('**/api/v1/similar/*?*')
    candidates.get_by_role('button', name='Retry candidates').click()
    expect(dialog.locator('.review-filmstrip button')).to_have_count(12)
    # A pair that cannot be loaded says so and offers a retry.
    page.route('**/api/v1/similar/*/pair/*', lambda route: route.fulfill(
        status=409, json={'detail': {'message': 'The photo content changed. Refresh the comparison.'}}))
    dialog.get_by_role('button', name='Refresh comparison', exact=True).click()
    expect(dialog.get_by_role('alert')).to_be_visible()
    page.unroute('**/api/v1/similar/*/pair/*')
    dialog.get_by_role('button', name='Retry comparison').click()
    expect(dialog.get_by_role('alert')).to_have_count(0)
    # Promoting a candidate queries its direct matches, keeps its viewing rotation,
    # and leaves the gallery context untouched.
    original_url = page.url
    original_name = reference_preview.locator('.review-photo-name > span').inner_text()
    promoted_name = candidate_preview.locator('.review-photo-name > span').inner_text()
    promoted = request.get(f'/api/v1/similar/{reference}?threshold=75&page=2&page_size=12').json()['items'][0]['id']
    dialog.get_by_role('button', name='Rotate candidate left', exact=True).click()
    with page.expect_response(lambda r: f'/api/v1/similar/{promoted}?' in r.url):
        dialog.get_by_role('button', name='Use as reference', exact=True).click()
    expect(reference_preview.locator('.review-photo-name > span')).to_have_text(promoted_name)
    expect(reference_preview).to_contain_text('Viewing rotation: 270°')
    expect(reference_preview).to_be_focused()
    expect(candidate_preview.locator('.review-photo-name > span')).to_have_text(original_name)
    expect(dialog.get_by_role('combobox', name='Minimum similarity')).to_have_value('75')
    expected = request.get(f'/api/v1/similar/{promoted}?threshold=75&page_size=12').json()['items']
    expect(dialog.locator('.review-filmstrip button')).to_have_count(len(expected))
    assert dialog.locator('.review-filmstrip button').evaluate_all('els => els.map(e => e.getAttribute("aria-label"))') == [f'Compare {p["filename"]}' for p in expected]
    assert gallery_context(page.url) == gallery_context(original_url)
    expect(page.locator(f'.card[data-id="{reference}"] input')).to_be_checked()
    page.reload()
    expect(reference_preview.locator('.review-photo-name > span')).to_have_text(promoted_name)
    expect(candidate_preview.locator('.review-photo-name > span')).to_have_text(original_name)
    expect(reference_preview).to_contain_text('Viewing rotation: 270°')
    shot('match-new-reference')
    dialog.get_by_role('button', name='Back to gallery', exact=True).click()
    expect(inspector.locator('.inspector-head h2')).to_have_text(original_name)
    expect(page).not_to_have_url(re.compile("review="))
    assert gallery_context(page.url) == gallery_context(original_url)
    # Explicit gallery selection is session-only and is not part of the bookmark.
    expect(page.locator(f'.card[data-id="{reference}"] input')).not_to_be_checked()
    matches.get_by_role('button', name=re.compile('^Review side by side:')).first.click()
    expect(reference_preview.locator('.review-photo-name > span')).to_have_text(original_name)
    page.set_viewport_size({'width': 700, 'height': 844})
    dialog.get_by_role('button', name='Rotate reference right', exact=True).click()
    expect(reference_preview).to_contain_text('Viewing rotation: 90°')
    full_comparison()
    assert dialog.evaluate('e => e.scrollWidth <= e.clientWidth + 1'), 'review overflow at narrow width'
    shot('match-review-narrow')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    # Esc in a workspace returns to the gallery, as Back to gallery does.
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    # Focus returns to a real control, so the keyboard carries on (Immich once lost
    # keyboard scrolling after its viewer): the opener while it still exists, otherwise the
    # Inspector's selected tab (Inspector closeComparison) or the shared fallback, since the
    # match list may reload as the comparison closes
    # (ui-design.md: "restores the opener on close (or a logical surviving control)").
    page.wait_for_function("""() => {
        const el = document.activeElement;
        return el && el !== document.body && (
            (el.getAttribute('aria-label') || '').startsWith('Review side by side:')
            || el.matches('[role="tab"][aria-selected="true"], [data-focus-home], .actions-menu > button'));
    }""")
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
    expect(diagnostics.get_by_text('Stored pairs of different hashes', exact=True)).to_be_visible()
    expect(diagnostics).not_to_contain_text('judgment')
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
    # This fixture is one identical set. Ungroup before stepping between photos.
    page.get_by_role('checkbox', name='Group similar photos', exact=True).uncheck()
    expect(page.locator('.card')).to_have_count(60)
    # Browsing photos retains the tab and threshold, with match paging reset.
    old_title = inspector.locator('.inspector-head h2').inner_text()
    inspector.get_by_role('button', name='Next photo', exact=True).click()
    expect(inspector.locator('.inspector-head h2')).not_to_have_text(old_title)
    expect(similar_tab).to_have_attribute('aria-selected', 'true')
    expect(summary.get_by_role('button', name=re.compile('^100% or higher:'))).to_have_attribute('aria-pressed', 'true')
    expect(page).not_to_have_url(re.compile('match_page='))
    # Old standalone/exact-mode bookmarks redirect into the same gallery workflow.
    page.goto(f'{sys.argv[1]}/similar?mode=exact&photo={reference}&threshold=85')
    expect(page).to_have_url(re.compile(r'/\?view=similar&sort=matches&match_min=75&photo=\d+&tab=similar&match=85'))
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
    # Invalid bookmarks cannot open an unrelated or malformed comparison.
    page.goto(page.url + '&review=%7B%22origin%22%3A-1%7D')
    expect(dialog).to_have_count(0)
    expect(page).not_to_have_url(re.compile('review='))
    assert not errors, errors
    browser.close()
    print('Gallery similarity browser checks passed')
