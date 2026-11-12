"""Check library in a browser (webui-spec 7.6), on generated photos only: the dialog from
Jobs and from the sidebar, the sidebar's library status, the check's findings in Logs,
the Library check review reason, Repair, and the Index notice's inline link and landmark."""
import os
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1]
LIBRARY = Path('/dest/library')


def shot(page, name):
    if os.environ.get('SHOTS'):
        page.screenshot(path=f"{os.environ['SHOTS']}/library-check-{name}.png")


with sync_playwright() as p:
    request = p.request.new_context(base_url=BASE)
    assert request.post('/api/v1/catalog').ok

    def idle():
        for _ in range(600):
            if request.get('/api/v1/jobs/active').json()['active'] is None:
                return
            time.sleep(.1)
        raise AssertionError('Job did not finish')

    for mode in ('index', 'copy'):
        response = request.post('/api/v1/jobs/start', data={'mode': mode})
        assert response.ok, response.text()
        idle()
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 900}, color_scheme='dark')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(BASE)
    # Copied photos keep their originals in the source; the note under Library opens them.
    originals = page.get_by_role('link', name=re.compile(r'^\d+ originals in source$'))
    expect(originals).to_be_visible()
    originals.click()
    expect(page).to_have_url(re.compile(r'view=source.*tree=1|tree=1.*view=source'))
    expect(page.get_by_role('group', name='Show').get_by_role('button', name='Still in source')).to_have_attribute('aria-pressed', 'true')
    shot(page, 'originals')
    page.goto(BASE)
    status = page.get_by_role('region', name='Status', exact=True)
    expect(status.get_by_role('link', name=re.compile('^Source indexed'))).to_be_visible()
    expect(status).to_contain_text('not checked yet')

    # The sidebar offers the dialog; opening it starts nothing.
    status.get_by_role('button', name=re.compile('Check library…$')).click()
    dialog = page.get_by_role('dialog', name='Check library')
    expect(dialog.get_by_role('button', name='Quick check', exact=True)).to_be_focused()
    expect(dialog).to_contain_text('Last checked: not checked yet')
    expect(dialog.get_by_role('button', name='Thorough check', exact=True)).to_be_visible()
    shot(page, 'dialog')
    dialog.get_by_role('button', name='Cancel', exact=True).click()
    expect(dialog).to_have_count(0)
    assert not any(r['mode'] == 'CHECK' for r in request.get('/api/v1/runs').json()['runs'])

    # Jobs › Check library… opens the same dialog; a quick check finds all as recorded.
    page.get_by_role('button', name='Jobs', exact=True).click()
    page.get_by_role('menu', name='Jobs', exact=True).get_by_role('menuitem', name=re.compile('^Check library…')).click()
    page.get_by_role('dialog', name='Check library').get_by_role('button', name='Quick check', exact=True).click()
    idle()
    expect(status).to_contain_text(re.compile(r'checked .*all as recorded'), timeout=10000)
    expect(status.locator('.status-bad, .status-warn')).to_have_count(0)

    # Change the library as other programs would: a photo lost, one moved, unknown files.
    lost = next(LIBRARY.rglob('photo-005.jpg'))
    moved = next(LIBRARY.rglob('photo-006.jpg'))
    lost.unlink()
    Path('/src/photo-005.jpg').unlink()
    (LIBRARY / 'sorted').mkdir(mode=0o777)
    (LIBRARY / 'sorted').chmod(0o777)        # this container runs as root; the app must be able to move files out
    moved.rename(LIBRARY / 'sorted' / 'photo-006.jpg')
    (LIBRARY / 'sorted' / 'notes.txt').write_text('notes')
    (LIBRARY / 'sorted' / '.DS_Store').write_bytes(b'\0')
    renamed = next(LIBRARY.rglob('photo-007.jpg'))
    renamed.rename(renamed.with_name('Garden party.jpg'))                  # a rename in its own folder
    with open(next(LIBRARY.rglob('photo-008.jpg')), 'ab') as edited:      # changed, the same picture
        edited.write(b'edited elsewhere')

    page.get_by_role('button', name='Jobs', exact=True).click()
    page.get_by_role('menu', name='Jobs', exact=True).get_by_role('menuitem', name=re.compile('^Check library…')).click()
    dialog = page.get_by_role('dialog', name='Check library')
    expect(dialog).to_contain_text('Quick · all as recorded')
    dialog.get_by_role('button', name='Thorough check', exact=True).click()
    idle()
    line = status.locator('a.status-bad')
    expect(line).to_contain_text('1 missing', timeout=10000)
    expect(line).to_contain_text('2 need attention')
    shot(page, 'sidebar')

    # The status opens the check's findings in Logs.
    line.click()
    findings = page.get_by_role('region', name='Library check findings', exact=True)
    expect(findings).to_contain_text('Thorough check')
    expect(findings.get_by_role('row').filter(has_text='photo-005.jpg')).to_contain_text('Missing')
    expect(findings.get_by_role('row').filter(has_text='photo-005.jpg')).to_contain_text('no copy was found')
    sixth = findings.get_by_role('row').filter(has_text='photo-006.jpg')
    expect(sixth).to_have_count(1)
    expect(sixth).to_contain_text('Found at a different place in the Library: sorted/photo-006.jpg')
    expect(sixth).to_contain_text('Moved')
    expect(findings).to_contain_text('1 .txt file')
    expect(findings).to_contain_text('from other programs: Mac system files')
    expect(findings).to_contain_text('1 rename you made recorded')
    expect(findings.get_by_role('listitem').filter(has_text='Garden party.jpg')).to_contain_text('photo-007.jpg')
    export = findings.get_by_role('group', name='Export findings', exact=True)
    assert export.get_by_role('link', name='CSV', exact=True).get_attribute('download') is not None
    assert export.get_by_role('link', name='JSON', exact=True).get_attribute('href').endswith('format=json')
    expect(page.locator('.job-head').first).to_contain_text('Library check finished')
    expect(page.locator('.job-head').first).to_contain_text('4 findings')
    shot(page, 'logs')
    for width, size in ((1440, '100%'), (720, '200%')):
        page.set_viewport_size({'width': width, 'height': 900})
        page.locator('html').evaluate('(e,s)=>e.style.fontSize=s', size)
        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1'), width
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.locator('html').evaluate('(e)=>e.style.fontSize="100%"')

    # The three Library photos with a finding carry the Library check reason.
    page.goto(BASE + '/?view=review&reason=library')
    expect(page.get_by_label('Review reason', exact=True)).to_have_value('library')
    cards = page.get_by_role('checkbox', name=re.compile(r'^Select photo-00[568]\.jpg$'))
    expect(cards).to_have_count(3)
    pid = request.get('/api/v1/photos', params={'view': 'review', 'reason': 'library', 'q': 'photo-005'}).json()['items'][0]['id']
    page.goto(BASE + f'/?view=review&reason=library&photo={pid}')
    note = page.get_by_role('region', name='Photo review', exact=True)
    expect(note).to_contain_text('Library check')
    expect(note).to_contain_text('If a backup has it, restore it')
    expect(note.get_by_role('link', name=re.compile(r'^Job #\d+$'))).to_be_visible()
    expect(note.get_by_role('button', name='Remove bookmark')).to_have_count(0)
    shot(page, 'inspector')
    # Repair (webui-spec 7.6): never offered for a photo it can't fix, offered for one it can.
    expect(note.get_by_role('button', name='Repair…')).to_have_count(0)
    six = request.get('/api/v1/photos', params={'view': 'review', 'reason': 'library', 'q': 'photo-006'}).json()['items'][0]['id']
    page.goto(BASE + f'/?view=review&reason=library&photo={six}')
    expect(page.get_by_role('region', name='Photo review', exact=True).get_by_role('button', name='Repair…')).to_be_visible()
    # From a selection of every photo under the reason: two fixes, one it can't make.
    page.goto(BASE + '/?view=review&reason=library')
    page.get_by_role('button', name='Select', exact=True).click()
    page.get_by_role('menu', name='Select').get_by_role('menuitem', name=re.compile('^Select all in this view')).click()
    page.get_by_role('region', name='Selection').get_by_role('button', name='Repair (3)…').click()
    repair = page.get_by_role('dialog', name='Repair 3 photos?')
    expect(repair).to_contain_text('1 photo in the wrong folder → move back to')
    # A kept version is filed by its date; undated, it stays in its Undated year (webui-spec 7.6).
    expect(repair.get_by_role('checkbox', name=re.compile(r'^1 photo changed, looks the same → keep the new version '
                                                           r'\(stays in Undated\/\d{4}\)$'))).to_be_checked()
    expect(repair).to_contain_text('Once it\'s kept, Edit metadata date… in its Inspector gives it a date.')
    expect(repair).to_contain_text("Can't be fixed here (nothing will be done)")
    expect(repair.get_by_role('button', name='Index source', exact=True)).to_be_visible()
    shot(page, 'repair')
    repair.get_by_role('button', name='Repair 2', exact=True).click()
    expect(repair).to_have_count(0)
    idle()
    last = request.get('/api/v1/runs').json()['runs'][0]
    assert last['mode'] == 'REPAIR' and next(LIBRARY.rglob('photo-006.jpg')).parent.name != 'sorted', \
        (last, request.get('/api/v1/operations', params={'run': last['id']}).text()[:2000])
    page.goto(BASE + '/?view=review&reason=library')
    expect(page.get_by_role('checkbox', name=re.compile(r'^Select photo-00[568]\.jpg$'))).to_have_count(1)
    page.goto(BASE + f'/?view=organized&photo={six}')
    page.get_by_role('button', name='View lineage tree').click()
    expect(page.locator('.lineage-timeline')).to_contain_text('Moved back to its date folder')
    page.keyboard.press('Escape')
    eight = request.get('/api/v1/photos', params={'view': 'organized', 'q': 'photo-008'}).json()['items'][0]['id']
    page.goto(BASE + f'/?view=organized&photo={eight}')
    page.get_by_role('button', name='View lineage tree').click()
    expect(page.locator('.lineage-timeline')).to_contain_text('Kept the new version')
    page.keyboard.press('Escape')

    # The recorded rename is in the photo's history, saying how it was found.
    garden = request.get('/api/v1/photos', params={'view': 'organized', 'q': 'Garden party'}).json()['items'][0]['id']
    page.goto(BASE + f'/?view=organized&photo={garden}')
    page.get_by_role('button', name='View lineage tree').click()
    expect(page.locator('.lineage-timeline')).to_contain_text('Renamed outside NegativeSpace')
    shot(page, 'rename-lineage')
    page.keyboard.press('Escape')

    # The Copy/Move notice is a named region, and its link keeps the sentence's line height.
    page.goto(BASE)
    page.get_by_role('button', name='Jobs', exact=True).click()
    page.get_by_role('menu', name='Jobs', exact=True).get_by_role('menuitem', name='Move', exact=True).click()
    page.get_by_role('menu', name='Move', exact=True).get_by_role('menuitem', name=re.compile('^Move all')).click()
    confirm = page.get_by_role('alertdialog')
    notice = confirm.get_by_role('region', name='Index used for preview', exact=True)
    expect(notice).to_contain_text('Based on the Index from')
    link = notice.get_by_role('button', name='Index source', exact=True)
    line_height = notice.locator('p').evaluate('(e)=>parseFloat(getComputedStyle(e).lineHeight)')
    assert link.evaluate('(e)=>getComputedStyle(e).minHeight') == '0px'
    assert link.bounding_box()['height'] <= line_height + 1, (link.bounding_box(), line_height)
    shot(page, 'index-notice')
    confirm.get_by_role('button', name='Cancel', exact=True).click()
    assert not errors, errors
    browser.close()
print('library check browser checks passed')
