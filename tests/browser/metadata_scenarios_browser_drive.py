"""Read-only acceptance of an indexed/copied metadata-scenario catalog.

Run in the browser image with BASE_URL and a mounted MANIFEST path as arguments.
The generated manifest's written values are expectations; engine_today is not.
This driver does not create catalogs, start jobs or change metadata.
"""
import json
import os
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base, manifest_path = sys.argv[1:3]
manifest = json.loads(Path(manifest_path).read_text())


def date_value(value):
    if re.match(r'^\d{4}:\d{2}:\d{2} ', value):
        value = value[:10].replace(':', '-') + 'T' + value[11:]
    return value[:-1] + '+00:00' if value.endswith('Z') else value


with sync_playwright() as p:
    request = p.request.new_context(base_url=base)

    def get(path):
        response = request.get('/api/v1' + path)
        assert response.ok, (path, response.status)
        return response.json()

    photos = {}
    page_number = 1
    while True:
        rows = get(f'/photos?view=all&page_size=240&page={page_number}')['items']
        if not rows:
            break
        for row in rows:
            detail = get(f"/photos/{row['id']}/inspect")
            photos[detail['source_path'].removeprefix('/data/source/')] = row
        page_number += 1
    cases = {c['case']: c for c in manifest['cases']}
    before = {row['id']: get(f"/photos/{row['id']}/metadata") for row in photos.values()}
    checked = 0
    for case in manifest['cases']:
        if case['group'] not in ('agree', 'conflict'):
            continue
        for photo in case['photos']:
            data = before[photos[photo['path']]['id']]
            for source, recorded in photo.get('sources', {}).items():
                if source not in ('exif', 'embedded_xmp') or 'date' not in recorded:
                    continue
                found = next(s for s in data['sources'] if s['id'] == source)
                expected = date_value(recorded['date']) + recorded.get('offset', '')
                assert found['fields']['date_taken'] == expected, (case['case'], source)
                checked += 1
        for sidecar in case['sidecars']:
            if 'date' not in sidecar['values']:
                continue
            data = before[photos[case['photos'][0]['path']]['id']]
            sidecars = [s for s in data['sources'] if s['kind'] == 'sidecar_xmp']
            assert any(s['fields'].get('date_taken') == date_value(sidecar['values']['date']) for s in sidecars), case['case']
            checked += 1

    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1440, 'height':1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))

    def open_case(name):
        photo = photos[cases[name]['photos'][0]['path']]
        view = 'organized' if photo['status'] == 'Copied' else 'unorganized'
        page.goto(base + f"/?view={view}&photo={photo['id']}&tab=metadata")
        viewer = page.locator('.metadata-sources')
        expect(viewer.get_by_role('tab', name='EXIF', exact=False)).to_be_visible()
        return viewer

    viewer = open_case('all_three_agree')
    viewer.get_by_role('tab', name='Embedded XMP', exact=True).click()
    viewer.get_by_label('Compare with primary', exact=True).check()
    viewer.get_by_label('Show differences only').check()
    expect(viewer).to_contain_text('No differing fields match this filter.')
    viewer = open_case('date_three_way')
    viewer.get_by_role('tab', name='EXIF', exact=True).click()
    viewer.get_by_label('Compare with primary', exact=True).check()
    expect(viewer).to_contain_text('2019-06-15 12:00:00')
    expect(viewer).to_contain_text('2021-08-01 09:30:00')
    viewer.get_by_role('tab', name='Embedded XMP', exact=True).click()
    expect(viewer).to_contain_text('2020-05-01 10:00:00')
    for width, theme in ((1440, 'light'), (720, 'dark')):
        page.evaluate('(theme) => {localStorage.setItem("ns.theme",theme);location.reload()}', theme)
        page.set_viewport_size({'width':width, 'height':1000})
        viewer.get_by_role('tab', name='EXIF', exact=True).click()
        viewer.get_by_label('Compare with primary', exact=True).check()
        viewer.scroll_into_view_if_needed()
        if os.environ.get('SHOTS'):
            page.screenshot(path=os.environ['SHOTS'] + f'/metadata-scenarios-{width}.png')
    viewer = open_case('sidecar_clears_title')
    viewer.get_by_role('tab', name='Embedded XMP', exact=True).click()
    viewer.get_by_label('Compare with primary', exact=True).check()
    expect(viewer).to_contain_text('Empty')
    expect(viewer).to_contain_text('Beach day')
    viewer = open_case('complementary')
    viewer.get_by_role('tab', name='EXIF', exact=True).click()
    viewer.get_by_label('Compare with primary', exact=True).check()
    expect(viewer).to_contain_text('Not recorded')
    viewer = open_case('exif_only')
    viewer.get_by_role('tab', name='XMP Sidecar', exact=True).click()
    expect(viewer).to_contain_text('No metadata recorded for this source.')
    viewer = open_case('malformed_xml')
    page.get_by_role('tab',name='File information',exact=True).click()
    notice=page.get_by_role('region',name='Metadata needs attention',exact=True)
    expect(notice).to_be_visible()
    expect(notice).to_contain_text('not valid XML')
    expect(notice).to_contain_text(cases['malformed_xml']['sidecars'][0]['path'])
    expect(notice).to_contain_text('It and its associated sidecars stay in the source.')
    expect(notice).to_contain_text('Index again')
    expect(notice.get_by_role('link',name='View photo logs')).to_be_visible()
    page.get_by_role('tab',name='Metadata',exact=True).click()
    viewer.get_by_role('tab', name='XMP Sidecar', exact=True).click()
    expect(viewer).to_contain_text('This metadata could not be read. See the issue above or open the photo logs.')
    expect(viewer.get_by_role('link', name='View photo logs')).to_be_visible()
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto(base+'/?view=unorganized')
    sidebar=page.get_by_role('navigation',name='Main')
    attention=sidebar.get_by_role('link',name=re.compile(r'need attention$'))
    attention_count=get('/photos?view=unorganized&reason=attention')['total']
    expect(attention).to_contain_text(str(attention_count))
    # The whole-summary shortcut clears an unrelated search, so it cannot hide holds.
    page.goto(base+'/?view=unorganized&q=no-such-generated-photo')
    show_summary=page.get_by_role('button',name='Show index summary',exact=True)
    if show_summary.is_visible():
        show_summary.click()
    page.get_by_role('link',name=f'View {attention_count} files needing attention',exact=True).click()
    expect(sidebar.get_by_role('link',name=re.compile(r'^Not organized '))).to_have_attribute('aria-current','page')
    expect(page.get_by_role('button',name=re.compile(r'^Needs attention:'))).to_have_attribute('aria-pressed','true')
    expect(page).to_have_url(re.compile(r'reason=attention'))
    assert 'q=' not in page.url
    expect(page.locator('.grid .card')).to_have_count(attention_count)
    page.reload()
    expect(sidebar.get_by_role('link',name=re.compile(r'^Not organized '))).to_have_attribute('aria-current','page')
    expect(page.get_by_role('button',name=re.compile(r'^Needs attention:'))).to_have_attribute('aria-pressed','true')
    sidebar.get_by_role('link',name=re.compile(r'^Library ')).click()
    expect(attention).not_to_have_attribute('aria-disabled','true')
    expect(attention).to_contain_text(str(attention_count))
    assert 'reason=attention' not in page.url
    attention.click()
    expect(sidebar.get_by_role('link',name=re.compile(r'^Not organized '))).to_have_attribute('aria-current','page')
    expect(page.get_by_role('button',name=re.compile(r'^Needs attention:'))).to_have_attribute('aria-pressed','true')
    sidebar.get_by_role('link',name=re.compile(r'^Not organized ')).click()
    expect(page.get_by_role('button',name=re.compile(r'^Needs attention:'))).to_have_attribute('aria-pressed','false')
    attention.click()
    expect(sidebar.get_by_role('link',name=re.compile(r'^Not organized '))).to_have_attribute('aria-current','page')
    expect(page.get_by_role('button',name=re.compile(r'^Needs attention:'))).to_have_attribute('aria-pressed','true')
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.environ['SHOTS']+'/attention-filter.png')
    broken_id=photos[cases['malformed_xml']['photos'][0]['path']]['id']
    marker=page.locator(f'.card[data-id="{broken_id}"]').get_by_role('button',name='Needs attention · Metadata')
    marker.scroll_into_view_if_needed()
    marker.click()
    expect(page.get_by_role('region',name='Metadata needs attention',exact=True)).to_be_visible()
    if os.environ.get('SHOTS'):
        page.get_by_role('region',name='Metadata needs attention',exact=True).screenshot(path=os.environ['SHOTS']+'/metadata-attention.png')
    for width,theme in ((1440,'light'),(720,'dark')):
        page.set_viewport_size({'width':width,'height':1000})
        page.goto(base+'/?view=unorganized&reason=attention')
        page.evaluate('(theme) => {localStorage.setItem("ns.theme",theme);location.reload()}',theme)
        expect(page.get_by_role('button',name=re.compile(r'^Needs attention:'))).to_have_attribute('aria-pressed','true')
        if width < 800:
            page.get_by_role('button',name='Menu',exact=True).click()
        expect(attention).to_be_visible()
        expect(sidebar.get_by_role('link',name=re.compile(r'^Not organized '))).to_have_attribute('aria-current','page')
        expect(attention).to_contain_text(str(attention_count))
        if os.environ.get('SHOTS'):
            page.screenshot(path=os.environ['SHOTS']+f'/attention-filter-{width}.png')
    assert not errors, errors
    for photo_id, data in before.items():
        assert get(f'/photos/{photo_id}/metadata') == data, photo_id
    browser.close()
print(f'PASS: {checked} manifest date assertions; all-source agreement, three-way conflict, empty/missing/unreadable values, reflow; {len(before)} metadata responses unchanged')
