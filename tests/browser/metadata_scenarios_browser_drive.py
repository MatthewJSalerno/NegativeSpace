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
        page.goto(base + f"/?view={view}&photo={photo['id']}")
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
    viewer.get_by_role('tab', name='XMP Sidecar', exact=True).click()
    expect(viewer).to_contain_text('This source could not be interpreted.')
    expect(viewer.get_by_role('link', name='View photo logs')).to_be_visible()
    assert not errors, errors
    for photo_id, data in before.items():
        assert get(f'/photos/{photo_id}/metadata') == data, photo_id
    browser.close()
print(f'PASS: {checked} manifest date assertions; all-source agreement, three-way conflict, empty/missing/unreadable values, reflow; {len(before)} metadata responses unchanged')
