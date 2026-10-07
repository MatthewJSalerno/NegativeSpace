"""Generated-fixture review flow, first-run choice, persistence, selection and reflow."""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base=sys.argv[1]
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={"width":1440,"height":1000})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    request=p.request.new_context(base_url=base)
    def get(path):
        response=request.get('/api/v1/'+path)
        assert response.ok,response.text()
        return response.json()
    def job(mode, ids=None):
        response=request.post('/api/v1/jobs/start',data={'mode':mode,**({'file_ids':ids} if ids else {})})
        assert response.ok,response.text()
        ident=response.json()['id']
        for _ in range(240):
            result=get(f'runs/{ident}')
            if result['status'] not in ('Preparing','Running','Cancelling') and get('status')['active_job'] is None:
                assert result['status']=='Completed',result
                return
            time.sleep(.25)
        raise AssertionError('job did not settle')
    assert request.post('/api/v1/catalog').ok
    page.goto(base)
    page.get_by_role('button',name='Next',exact=True).click()
    choice=page.get_by_label('Small-image reminders',exact=True)
    expect(choice).to_have_value('')
    page.get_by_role('button',name='Next',exact=True).click()
    expect(page.get_by_text('Choose whether to suggest small images for review.',exact=True)).to_be_visible()
    choice.select_option('on')
    page.get_by_label('Minimum shorter side (pixels)',exact=True).fill('800')
    page.get_by_role('button',name='Next',exact=True).click()
    page.get_by_role('button',name='Next',exact=True).click()
    page.get_by_role('button',name='Save and continue',exact=True).click()
    expect(page.get_by_role('button',name='To organize',exact=False).first).to_have_attribute('aria-pressed','true')
    assert get('settings')['small_image_min']['value']==800
    job('index')
    job('copy')
    page.reload()
    # Explicit To organize survives refresh, even though default is now Library.
    expect(page.get_by_role('button',name='To organize',exact=False).first).to_have_attribute('aria-pressed','true')
    page.goto(base+'/?view=organized')
    cards=page.locator('.card')
    expect(cards.first).to_be_visible()
    first=int(cards.first.get_attribute('data-id'))
    cards.first.get_by_role('checkbox').check()
    page.get_by_role('button',name='Needs review',exact=False).first.click()
    expect(page.get_by_role('group',name='Review reason')).to_be_visible()
    expect(page.locator(f'.card[data-id="{first}"] input')).to_be_checked()
    page.get_by_role('button',name='Small images',exact=False).first.click()
    card=page.locator(f'.card[data-id="{first}"]')
    if os.environ.get('SHOTS'): page.screenshot(path=os.environ['SHOTS']+'/review-inbox.png',full_page=True)
    card.get_by_role('button',name='Review photo',exact=True).click()
    workspace=page.get_by_role('dialog',name='Review photos',exact=True)
    expect(workspace).to_be_visible()
    expect(workspace.get_by_text('Location: Library',exact=True)).to_be_visible()
    page.wait_for_function("[...document.querySelectorAll('.review-photo img')].some(i => i.complete && i.naturalWidth > 0)")
    if os.environ.get('SHOTS'): workspace.screenshot(path=os.environ['SHOTS']+'/review-workspace.png')
    # Next is a skip, not a saved answer; Previous returns to the same photo.
    workspace.get_by_role('button',name='Next photo',exact=True).click()
    expect(workspace.locator('.workspace-step')).to_contain_text('Photo 2 of')
    assert [n['reason'] for n in get(f'photos/{first}/review')['reasons']]==['small']
    workspace.get_by_role('button',name='Previous photo',exact=True).click()
    expect(workspace.locator('.workspace-step')).to_contain_text('Photo 1 of')
    page.set_viewport_size({'width':720,'height':500})
    expect(workspace.get_by_role('button',name='Back to gallery',exact=False)).to_be_visible()
    assert workspace.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
    if os.environ.get('SHOTS'): workspace.screenshot(path=os.environ['SHOTS']+'/review-workspace-reflow.png')
    page.set_viewport_size({'width':1440,'height':1000})
    workspace.get_by_role('button',name='Review later',exact=True).click()
    workspace.get_by_label('Optional note',exact=True).fill('Only surviving small copy')
    workspace.get_by_role('button',name='Save reminder',exact=True).click()
    expect(workspace.get_by_text('Added to Review later.',exact=True)).to_be_visible()
    # A refused save cannot dismiss the reminder; retry retains the same decision.
    page.route(f'**/api/v1/photos/{first}/review', lambda route: route.fulfill(status=503,json={'error':{'code':'review_unavailable','message':'Generated refusal'}}) if route.request.method=='POST' else route.continue_())
    workspace.get_by_role('button',name='Mark reviewed',exact=True).click()
    expect(workspace.get_by_role('button',name='Retry saving',exact=True)).to_be_visible()
    assert 'small' in [n['reason'] for n in get(f'photos/{first}/review')['reasons']]
    page.unroute(f'**/api/v1/photos/{first}/review')
    workspace.get_by_role('button',name='Retry saving',exact=True).click()
    expect(workspace.get_by_text('Size reviewed. The photo stays in your library.',exact=True)).to_be_visible()
    expect(workspace.get_by_role('button',name='Mark reviewed',exact=True)).to_be_enabled()
    workspace.get_by_role('button',name='Back to gallery',exact=False).click()
    detail=get(f'photos/{first}/review')
    assert [n['reason'] for n in detail['reasons']]==['later'],detail
    page.get_by_role('button',name='Review later (',exact=False).first.click()
    expect(page.locator(f'.card[data-id="{first}"]')).to_be_visible()
    page.reload()
    expect(page.locator(f'.card[data-id="{first}"]')).to_be_visible()
    page.locator(f'.card[data-id="{first}"]').get_by_role('button',name='Review photo',exact=True).click()
    workspace.get_by_role('button',name='Done',exact=True).click()
    expect(workspace.get_by_text('Review later reminder cleared.',exact=True)).to_be_visible()
    workspace.get_by_role('button',name='Back to gallery',exact=False).click()
    assert not get(f'photos/{first}/review')['reasons']
    job('index')
    assert not get(f'photos/{first}/review')['reasons'],'Index resurrected review'
    # Reject is the existing confirmed engine workflow, not a catalog-only dismissal.
    page.goto(base+'/?view=review&reason=small')
    expect(page.locator('.card').first).to_be_visible()
    rejected=int(page.locator('.card').first.get_attribute('data-id'))
    page.locator('.card').first.get_by_role('button',name='Review photo',exact=True).click()
    workspace.get_by_role('button',name='Reject…',exact=True).click()
    page.get_by_role('alertdialog').get_by_role('button',name='Reject',exact=True).click()
    expect(workspace.get_by_text('Photo moved to Rejects.',exact=True)).to_be_visible(timeout=60000)
    assert get(f'photos/{rejected}/inspect')['status']=='Rejected_Copied'
    assert not get(f'photos/{rejected}/review')['reasons']
    workspace.get_by_role('button',name='Back to gallery',exact=False).click()
    page.goto(base+'/?view=organized&suspicious=1&undated=1')
    page.get_by_role('button',name='Clear filters',exact=True).click()
    expect(page.get_by_role('button',name='Library (',exact=False).first).to_have_attribute('aria-pressed','true')
    page.get_by_role('button',name='Needs review (',exact=False).first.click()
    page.get_by_role('button',name='Small images (',exact=False).first.click()
    page.get_by_role('button',name='Change in Settings',exact=True).click()
    dialog=page.get_by_role('dialog',name='Settings',exact=True)
    expect(dialog.get_by_role('tab',name='Files',exact=True)).to_have_attribute('aria-selected','true')
    dialog.get_by_label('Small-image reminders',exact=True).select_option('off')
    dialog.get_by_role('button',name='Save settings',exact=True).click()
    expect(dialog.get_by_text('Saved.',exact=True)).to_be_visible()
    dialog.get_by_role('button',name='Close settings',exact=True).click()
    expect(page.get_by_role('button',name='Small images (0)',exact=True)).to_be_visible()
    page.goto(base+'/?view=organized')
    page.get_by_role('button',name='Has similar photos',exact=False).first.click()
    page.get_by_role('button',name='No capture date',exact=False).first.click()
    expect(page.get_by_role('button',name='Has similar photos',exact=False).first).to_have_attribute('aria-pressed','true')
    expect(page.get_by_role('button',name='No capture date',exact=False).first).to_have_attribute('aria-pressed','true')
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.environ['SHOTS']+'/review-desktop.png',full_page=True)
    page.set_viewport_size({'width':720,'height':500})
    expect(page.get_by_role('button',name='Needs review',exact=False).first).to_be_visible()
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.environ['SHOTS']+'/review-reflow.png',full_page=True)
    assert not errors,errors
    print('PASS: first-run choice, place default, review persistence, independent reasons, selection, re-index, chips and Settings route')
    browser.close()
