"""Metadata setup/settings, frozen real jobs and stable live notice geometry."""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    request=p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(sys.argv[1]);page.get_by_role('button',name='Next',exact=True).click()
    page.get_by_label('Small-image reminders',exact=False).select_option('off')
    page.get_by_role('button',name='Next',exact=True).click()
    expect(page.locator('.settings-step')).to_have_text('Step 3 of 6 Metadata')
    association=page.get_by_label('When an XMP sidecar matches multiple photos',exact=False)
    expect(association).to_have_value('');expect(association).to_have_attribute('required','')
    page.get_by_role('button',name='Next',exact=True).click()
    expect(page.get_by_text('Choose how to associate a shared XMP sidecar.',exact=True)).to_be_visible()
    expect(association).to_be_focused()
    expect(page.get_by_label('RAW photos',exact=True)).to_have_value('xmp')
    expect(page.get_by_label('Other photo formats',exact=True)).to_have_value('embedded')
    expect(page.get_by_label('RAW photos',exact=True).locator('option[value=embedded]')).to_be_disabled()
    association.select_option('raw_only')
    page.get_by_role('button',name='Next',exact=True).click()
    page.get_by_role('button',name='Back',exact=True).click()
    expect(association).to_have_value('raw_only')
    association.select_option('ask')
    page.get_by_label('Other photo formats',exact=True).select_option('xmp')
    # Nothing saved until the final step. Explicit Ask me is still a saved decision.
    original=request.get('/api/v1/settings').json()
    assert original['xmp_association']['revision']==0
    assert original['metadata_write_non_raw']['value']=='embedded'
    metadata=page.get_by_role('region',name='Metadata preferences',exact=True)
    expect(metadata).to_contain_text('If a field is missing, NegativeSpace checks the next source.')
    for width,zoom in ((1440,1),(1440,2),(640,1)):
        # Browser zoom reduces the CSS viewport; CSS zoom alone does not resize vh.
        page.set_viewport_size({'width':round(width/zoom),'height':round(1000/zoom)})
        association.scroll_into_view_if_needed()
        assert page.locator('.settings-page').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/metadata-setup-{width}-{zoom}.png")
    page.set_viewport_size({'width':1440,'height':1000})
    for _ in range(3):page.get_by_role('button',name='Next',exact=True).click()
    page.get_by_role('button',name='Save and continue',exact=True).click()
    expect(page.get_by_role('button',name='Index source',exact=True)).to_be_visible()
    saved=request.get('/api/v1/settings').json()
    assert saved['xmp_association']['value']=='ask' and saved['xmp_association']['revision']==1
    assert saved['metadata_write_non_raw']['value']=='xmp'
    def wait(run):
        for _ in range(600):
            state=request.get(f'/api/v1/runs/{run}').json()
            if state['status'] not in ('Preparing','Running','Cancelling') and request.get('/api/v1/jobs/active').json()['active'] is None:
                assert state['status']=='Completed',state
                return
            time.sleep(.1)
        raise AssertionError('Job did not finish')
    def start(mode):
        response=request.post('/api/v1/jobs/start',data={'mode':mode})
        assert response.ok,response.text()
        return response.json()['id']
    wait(start('index'));page.reload()
    page.get_by_role('button',name='Settings',exact=True).click()
    dialog=page.get_by_role('dialog',name='Settings',exact=True)
    dialog.get_by_role('tab',name='Metadata',exact=True).click()
    expect(association).to_have_value('ask')
    association.select_option('non_raw_only')
    expect(dialog.get_by_role('tab',name='Metadata')).to_contain_text('Metadata')
    expect(dialog.get_by_role('tab',name='Metadata').get_by_role('img',name='unsaved changes')).to_be_visible()
    dialog.get_by_role('tab',name='Performance',exact=True).click()
    dialog.get_by_role('tab',name='Metadata').click()
    expect(association).to_have_value('non_raw_only')
    dialog.get_by_role('button',name='Reset',exact=True).click()
    expect(association).to_have_value('ask')
    expect(dialog.get_by_role('img',name='unsaved changes')).to_have_count(0)
    # Another tab wins: revisions prevent silently replacing its choice.
    association.select_option('raw_only')
    current=request.get('/api/v1/settings').json()['xmp_association']
    assert request.put('/api/v1/settings',data={'values':{'xmp_association':'non_raw_only'},'revisions':{'xmp_association':current['revision']}}).ok
    dialog.get_by_role('button',name='Save settings',exact=True).click()
    expect(dialog.get_by_role('alert')).to_contain_text('changed elsewhere')
    expect(association).to_have_value('non_raw_only')
    # Run starts while Settings is open. Draft and geometry must survive both edges.
    gate=Path('/src/.hold-settings-job');gate.write_text('hold generated Copy')
    # Locate the actual catalog filename rather than asserting a deployment convention.
    db=next(path for path in Path('/catalog').rglob('*.db') if not path.name.endswith('-shm'))
    def snapshot(run):
        with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as conn:
            return json.loads(conn.execute('SELECT effective_config_json FROM run_configs WHERE run_id=?',(run,)).fetchone()[0])
    notice=dialog.get_by_role('status',name='When settings apply',exact=True)
    def visible_notice():return notice.locator('div:not([aria-hidden=true])')
    def top():return dialog.locator('.settings-tabs').evaluate('(e)=>e.getBoundingClientRect().top-e.closest(".settings").getBoundingClientRect().top+e.closest(".settings").scrollTop')
    try:
        for width,zoom in ((1440,1),(1440,2),(640,1)):
            page.set_viewport_size({'width':round(width/zoom),'height':round(1000/zoom)})
            dialog.get_by_role('tab',name='Metadata',exact=True).click()
            association.select_option('all')
            page.get_by_label('Other photo formats',exact=True).select_option('embedded')
            dialog.get_by_role('tab',name='Appearance',exact=True).click()
            page.evaluate('document.fonts.ready')
            baseline=top()
            run=start('copy')
            frozen=snapshot(run)
            expect(visible_notice()).to_contain_text('A job is running.')
            assert abs(top()-baseline)<=1,(top(),baseline)
            dialog.get_by_role('tab',name='Metadata').click()
            expect(association).to_have_value('all')
            expect(visible_notice()).to_contain_text('not this one')
            if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/metadata-active-{width}-{zoom}.png")
            if width==1440 and zoom==1:
                dialog.get_by_role('button',name='Save settings',exact=True).click()
                expect(dialog.get_by_text('Saved. The running job keeps its existing settings; changes apply to future jobs.',exact=True)).to_be_visible()
                assert request.get('/api/v1/settings').json()['xmp_association']['value']=='all'
                assert frozen['xmp_association']=='non_raw_only' and frozen['metadata_write_non_raw']=='xmp'
            assert snapshot(run)==frozen
            dialog.get_by_role('tab',name='Appearance',exact=True).click()
            baseline=top();gate.unlink();wait(run)
            expect(visible_notice()).to_contain_text('Processing settings apply to future jobs.')
            expect(visible_notice()).not_to_contain_text('A job is running.')
            assert abs(top()-baseline)<=1,(top(),baseline)
            gate.write_text('hold generated Copy')
        page.set_viewport_size({'width':1440,'height':1000})
        dialog.get_by_role('tab',name='Metadata').click()
        expect(association).to_have_value('all')
        dialog.get_by_role('button',name='Close settings',exact=True).click()
        gate.unlink();next_run=start('index');wait(next_run)
        assert snapshot(next_run)['xmp_association']=='all'
        assert snapshot(next_run)['metadata_write_non_raw']=='embedded'
    finally:
        gate.unlink(missing_ok=True)
    assert not errors,errors
    browser.close()
    print('PASS: required XMP choice, preferences/reset/conflict, frozen real job, later-job settings, stable notice and narrow/200% layout')
