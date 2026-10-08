"""Reference sets with generated files and an explicit A–B–C–D chain."""
import os
import json
from urllib.parse import urlsplit, parse_qs
import re
import sqlite3
import sys
import time
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    created = request.post('/api/v1/catalog')
    assert created.ok, created.text()
    def wait(run):
        for _ in range(600):
            result = request.get(f'/api/v1/runs/{run}').json()
            if (result['status'] not in ('Preparing','Running','Cancelling')
                    and request.get('/api/v1/jobs/active').json()['active'] is None):
                assert result['status'] == 'Completed', result
                return
            time.sleep(.2)
        raise AssertionError('Job did not finish')
    for mode in ('index','copy'):
        response = request.post('/api/v1/jobs/start',data={'mode':mode})
        assert response.ok, response.text()
        wait(response.json()['id'])
    with sqlite3.connect('/catalog/db/ns_sqlite.db') as conn:
        records=conn.execute("SELECT id,sha1_hash FROM photos WHERE status='Copied' ORDER BY id LIMIT 5").fetchall()
        a,b,c,d,large=[r[0] for r in records]
        hashes=['0000000000000000','000000000000003f','0000000000000fff','000000000003ffff']
        conn.execute("UPDATE contents SET phash='ffffffffffffffff',phash_state='ok'")
        for (_,digest),h in zip(records,hashes):
            conn.execute('UPDATE contents SET phash=? WHERE digest=?',(h,digest))
        conn.execute('DELETE FROM content_similarity')
        conn.execute('DELETE FROM similarity_hashes')
        for h in [*hashes,'ffffffffffffffff']:
            conn.execute('INSERT INTO similarity_hashes VALUES(?)',(h,))
        for i,h in enumerate(hashes):
            for other in hashes[i+1:]:
                distance=(int(h,16)^int(other,16)).bit_count()
                if distance<=16:
                    conn.execute('INSERT INTO content_similarity VALUES(?,?,?)',(h,other,distance))
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    def shot(name):
        if os.environ.get('SHOTS'):
            page.screenshot(path=os.path.join(os.environ['SHOTS'],name+'.png'))
    page.goto(sys.argv[1]+'/?view=similar')
    sort = page.get_by_role('combobox', name='Sort', exact=True)
    group = page.get_by_role('checkbox', name='Group similar photos', exact=True)
    expect(sort).to_have_value('matches')
    threshold = page.get_by_role('combobox', name='Gallery match threshold')
    expect(threshold).to_have_value('90')
    threshold.select_option('85')
    page.reload()
    expect(threshold).to_have_value('85')
    page.goto(sys.argv[1]+'/?view=similar')
    expect(threshold).to_have_value('85')
    page.goto(sys.argv[1]+'/?view=similar&match_min=95')
    expect(threshold).to_have_value('95')
    page.goto(sys.argv[1]+'/?view=similar')
    expect(threshold).to_have_value('85')  # Opening a link does not change preferences.
    threshold.select_option('90')
    expect(group).to_be_checked()
    sort.select_option('oldest')
    group.uncheck()
    page.get_by_role('button', name=re.compile('^Has similar photos')).click()
    sort.select_option('largest')
    page.get_by_role('button', name=re.compile('^Has similar photos')).click()
    expect(sort).to_have_value('oldest')
    expect(group).not_to_be_checked()
    page.reload()
    expect(sort).to_have_value('oldest')
    expect(group).not_to_be_checked()
    page.goto(sys.argv[1]+'/?view=similar')
    expect(sort).to_have_value('oldest')
    page.goto(sys.argv[1]+'/?view=similar&sort=newest')
    expect(sort).to_have_value('newest')
    page.reload()
    expect(sort).to_have_value('newest')
    page.get_by_role('button', name=re.compile('^Has similar photos')).click()
    expect(sort).to_have_value('largest')
    page.goto(sys.argv[1]+'/?view=similar&match_min=90&sort=name')
    expect(sort).to_have_value('name')  # Explicit links win over saved defaults.
    group.check()
    group=page.get_by_role('checkbox',name='Group similar photos',exact=True)
    expect(group).to_be_checked()
    group.check()
    expect(page.locator('.card')).to_have_count(5)
    expect(page.locator('.gallery-summary')).to_contain_text('5 sets')
    photo_count = request.get('/api/v1/photos?view=similar&match_min=90').json()['total']
    expect(page.get_by_role('button', name=re.compile('^Has similar photos'))).to_have_text(
        f'Has similar photos ({photo_count})')
    expect(page.get_by_text('trip / day 1', exact=True)).to_be_visible()  # Hidden members remain filterable.
    page.wait_for_load_state('networkidle')
    grouping_requests = []
    def record_grouping_request(request):
        grouping_requests.append(urlsplit(request.url).path)
    page.on('request', record_grouping_request)
    group.uncheck()
    expect(page.locator('.card')).to_have_count(60)
    page.wait_for_load_state('networkidle')
    group.check()
    expect(page.locator('.card')).to_have_count(5)
    page.wait_for_load_state('networkidle')
    page.remove_listener('request', record_grouping_request)
    assert not any(path in ('/api/v1/photos/timeline', '/api/v1/photos/types',
                            '/api/v1/photos/folders') for path in grouping_requests), grouping_requests

    card=page.locator(f'.card[data-id="{a}"]')
    expect(card.get_by_text('Reference set · 2 photos',exact=True)).to_be_visible()
    card.locator('.card-check input').check()
    shot('reference-set-gallery')
    card.get_by_role('button',name='Explore related sets',exact=True).click()
    dialog=page.get_by_role('dialog',name='Explore reference sets',exact=True)
    expect(dialog.locator('[data-member-id]')).to_have_count(2)
    expect(dialog.locator(f'[data-related-id="{b}"]')).to_contain_text('1 additional match outside the starting set')
    dialog.locator(f'[data-related-id="{b}"] input').check()
    dialog.get_by_role('button',name='Show together',exact=True).click()
    expect(dialog.locator('[data-member-id]')).to_have_count(3)
    expect(dialog.locator(f'[data-member-id="{c}"]')).to_contain_text('Related through')
    expect(dialog.locator(f'[data-member-id="{c}"]')).to_contain_text('no direct match recorded at 90%')
    expect(dialog.locator(f'[data-member-id="{d}"]')).to_have_count(0)
    shot('reference-sets-combined')
    # Indirect photos compare against their actual supporting reference, not A.
    dialog.locator(f'[data-member-id="{c}"]').get_by_role('button',name=re.compile('^Compare with')).click()
    review=page.get_by_role('dialog',name='Review photo match',exact=True)
    expect(review).to_be_visible()
    expect(review.locator('.review-score')).to_contain_text('90.62%')
    review.get_by_role('button',name='Back to gallery',exact=True).click()
    expect(dialog).to_be_visible()
    expect(dialog.locator('[data-member-id]')).to_have_count(3)
    expect(card.locator('.card-check input')).to_be_checked()
    # A threshold change resets selected expansions and recomputes all memberships.
    dialog.get_by_role('combobox',name='Set match threshold').select_option('95')
    expect(dialog.locator('[data-member-id]')).to_have_count(1)
    expect(dialog.get_by_text('0 related sets chosen',exact=True)).to_be_visible()
    dialog.get_by_role('combobox',name='Set match threshold').select_option('90')
    expect(dialog.locator('[data-member-id]')).to_have_count(2)
    page.set_viewport_size({'width':700,'height':844})
    assert dialog.locator('.reference-sets').evaluate('e => e.scrollWidth <= e.clientWidth+1'), 'set dialog overflow'
    shot('reference-sets-narrow')
    dialog.get_by_role('button',name='Back to gallery',exact=True).click()
    page.set_viewport_size({'width':1440,'height':1000})
    # Review from the tile opens the ordinary direct-match workspace.
    card.get_by_role('button',name='Review this set',exact=True).click()
    expect(review).to_be_visible()
    expect(review.locator('.review-score')).to_contain_text('90.62%')
    review.get_by_role('button',name='Back to gallery',exact=True).click()
    # Browse neighboring distinct sets using the active gallery order.
    card.get_by_role('button',name='Review this set',exact=True).click()
    position=request.post('/api/v1/photos/position',data={'photo_id':a,'view':'similar',
        'sort':'name','group_sets':True,'match_min':90,'page_size':60}).json()
    next_id=position['next_id']
    assert next_id is not None
    expect(review.get_by_role('button',name='Next set',exact=True)).to_be_enabled()
    review.get_by_role('button',name='Next set',exact=True).click()
    page.wait_for_function('(id) => JSON.parse(new URLSearchParams(location.search).get("review"))?.origin === id',arg=next_id)
    expect(review.get_by_role('button',name='Previous set',exact=True)).to_be_enabled()
    review.get_by_role('button',name='Previous set',exact=True).click()
    page.wait_for_function('(id) => JSON.parse(new URLSearchParams(location.search).get("review"))?.origin === id',arg=a)
    review.get_by_role('button',name='Rotate reference right',exact=True).click()
    # LAN HTTP commonly lacks clipboard access; offer a usable manual link.
    page.evaluate('Object.defineProperty(navigator, "clipboard", {configurable:true, value:undefined})')
    review.get_by_role('button',name='Copy review link',exact=True).click()
    manual=review.get_by_role('textbox',name='Review link',exact=True)
    expect(manual).to_be_visible()
    page.set_viewport_size({'width':700,'height':844})
    assert review.evaluate('e => e.scrollWidth <= e.clientWidth+1')
    shot('review-actions-narrow')
    page.set_viewport_size({'width':1440,'height':1000})
    copied=manual.input_value()
    bookmark=json.loads(parse_qs(urlsplit(copied).query)['review'][0])
    assert bookmark['origin']==a and bookmark['reference']==a
    assert bookmark['views'][str(a)]['rotation']==90
    # Successful clipboard writes report success, too.
    page.evaluate('Object.defineProperty(navigator, "clipboard", {configurable:true, value:{writeText: async text => {window.copiedReview = text}}})')
    review.get_by_role('button',name='Copy review link',exact=True).click()
    expect(review.get_by_text('Review link copied.',exact=False)).to_be_visible()
    assert page.evaluate('window.copiedReview') == copied
    shot('review-actions')
    review.get_by_role('button',name='Show this set in gallery',exact=True).click()
    expect(review).to_have_count(0)
    expect(page.locator('.card')).to_have_count(2)
    expect(page.locator(f'.card[data-id="{a}"] .card-check input')).to_be_checked()
    expect(page.locator(f'.card[data-id="{b}"] .card-check input')).not_to_be_checked()
    page.locator('.focus-head').get_by_role('button',name='Back to results',exact=True).click()
    expect(page.locator('.card')).to_have_count(5)
    # Copied links restore the comparison without replaying writes.
    page.goto(copied)
    expect(review).to_be_visible()
    expect(review.locator('.review-score')).to_contain_text('90.62%')
    review.get_by_role('button',name='Back to gallery',exact=True).click()
    # Failure has an explicit retry; successful retry restores the same set.
    page.route('**/api/v1/similar/*/sets?*',lambda route: route.fulfill(status=503,json={'message':'Fixture temporary failure'}))
    card.get_by_role('button',name='Explore related sets',exact=True).click()
    expect(dialog.get_by_role('alert')).to_be_visible()
    page.unroute('**/api/v1/similar/*/sets?*')
    dialog.get_by_role('button',name='Retry sets',exact=True).click()
    expect(dialog.locator('[data-member-id]')).to_have_count(2)
    dialog.get_by_role('button',name='Back to gallery',exact=True).click()
    # A dense same-hash bucket remains paged and explicit expansion is capped.
    # Explore from the unfiltered set tile: searching intentionally ungroups.
    page.locator(f'.card[data-id="{large}"]').get_by_role('button',name='Explore related sets',exact=True).click()
    expect(dialog.locator('[data-member-id]')).to_have_count(12)
    for checkbox in dialog.locator('[data-related-id] input').all()[:6]: checkbox.check()
    expect(dialog.locator('[data-related-id] input').nth(6)).to_be_disabled()
    dialog.get_by_role('button',name='Show together',exact=True).click()
    expect(dialog.locator('[data-member-id]')).to_have_count(12)
    expect(dialog.get_by_role('region',name='Displayed sets')).to_contain_text('126 distinct photos')
    dialog.get_by_role('button',name='Next photos',exact=True).click()
    expect(dialog.get_by_role('navigation',name='Set photo pages')).to_contain_text('Page 2 of 11')
    dialog.get_by_role('button',name='Next sets',exact=True).click()
    expect(dialog.get_by_role('navigation',name='Related set pages')).to_contain_text('Page 2 of 11')
    dialog.get_by_role('button',name='Show this set in gallery',exact=True).first.click()
    expect(dialog).to_have_count(0)
    expect(page.locator('.gallery-summary')).to_contain_text('126 photos')
    expect(page.locator('.card')).to_have_count(60)
    page.get_by_role('button',name='Next page',exact=True).click()
    expect(page.locator('.pager button[aria-current="page"]')).to_have_text('2')
    shot('set-members-gallery')
    page.locator('.focus-head').get_by_role('button',name='Back to results',exact=True).click()
    page.reload()
    expect(group).to_be_checked()
    expect(dialog).to_have_count(0)
    # Needs review exposes the same grouping, threshold, sort and set controls.
    setting=request.get('/api/v1/settings').json()['small_image_min']
    assert request.put('/api/v1/settings',data={'values':{'small_image_min':800},
        'revisions':{'small_image_min':setting['revision']}}).ok
    page.goto(sys.argv[1]+'/?view=review&similar=1&match_min=90&group_sets=1&sort=matches')
    expect(group).to_be_checked()
    expect(threshold).to_have_value('90')
    expect(sort).to_have_value('matches')
    expect(page.get_by_role('button',name='Review this set',exact=True).first).to_be_visible()
    expect(page.get_by_role('button',name='Explore related sets',exact=True).first).to_be_visible()
    shot('needs-review-grouping')
    # Filters ungroup without changing the explicit saved preference or selection.
    page.locator('.card input[type=checkbox]').first.check()
    for label in ('Suspicious dates','No capture date','Small images','Review later'):
        chip=page.get_by_role('group',name='Review reason').get_by_role('button',name=re.compile('^'+label))
        chip.click()
        expect(group).not_to_be_checked()
        expect(group).to_be_disabled()
        page.reload()
        expect(group).not_to_be_checked()
        expect(group).to_be_disabled()
        assert page.evaluate("localStorage.getItem('ns.groupSets')") != 'false'
        chip.click()
        expect(group).to_be_checked()
        expect(group).to_be_enabled()
    for query in ('q=photo', 'type=jpg', 'date=2023', 'folder=.'):
        page.goto(sys.argv[1]+'/?view=review&similar=1&group_sets=1&'+query)
        expect(group).not_to_be_checked()
        expect(group).to_be_disabled()
        expect(page.get_by_text('Showing every photo that matches all active filters. Clear the other filters to group similar photos.',exact=True)).to_be_visible()
    # Combined restrictions show only the matching individual, not its full set.
    large_name=request.get(f'/api/v1/photos/{large}/inspect').json()['filename']
    page.goto(sys.argv[1]+'/?view=review&similar=1&group_sets=1&type=jpg&q='+large_name)
    expect(page.locator('.card')).to_have_count(1)
    expect(page.locator(f'.card[data-id="{large}"]')).to_be_visible()
    shot('needs-review-filtered-photos')
    page.goto(sys.argv[1]+'/?view=review&similar=1&group_sets=1')
    expect(group).to_be_checked()
    page.get_by_role('button',name=re.compile(r'^Library \(')).first.click()
    expect(group).to_be_checked()
    expect(page.get_by_role('button',name='Review this set',exact=True).first).to_be_visible()
    page.get_by_role('button',name=re.compile(r'^Needs review \(')).first.click()
    expect(group).to_be_checked()
    group.uncheck()
    page.reload()
    expect(group).not_to_be_checked()
    group.check()
    expect(page.locator('.card')).to_have_count(5)
    expect(page.locator('.gallery-summary')).to_contain_text('5 sets')
    page.set_viewport_size({'width':1000,'height':700})
    expect(group).to_be_visible()
    shot('needs-review-grouping-reflow')
    page.set_viewport_size({'width':1440,'height':1000})
    # Failed hash recovery has a per-file log, not just a job count.
    with sqlite3.connect('/catalog/db/ns_sqlite.db') as conn:
        digest=conn.execute('SELECT sha1_hash FROM photos WHERE id=?',(a,)).fetchone()[0]
        conn.execute("UPDATE photos SET dest_path='/data/dest/fixture-missing.jpg' WHERE id=?",(a,))
        conn.execute("UPDATE file_states SET current_path='/data/dest/fixture-missing.jpg' WHERE sha1_hash=? AND location_role='destination'",(digest,))
        conn.execute("UPDATE contents SET phash=NULL,phash_state='error' WHERE digest=?",(digest,))
    repair=request.post('/api/v1/similar/recovery',data={'scope':'missing','photo_id':a})
    assert repair.ok,repair.text()
    run=repair.json()['id']
    wait(run)
    page.goto(sys.argv[1]+f'/logs?run={run}')
    expect(page.locator('.message').filter(has_text='[repair_missing]')).to_be_visible()
    expect(page.locator('.message').filter(has_text='The destination file is missing')).to_be_visible()
    shot('recovery-failure-details')
    assert not errors,errors
    browser.close()
print('Reference set browser checks passed')
