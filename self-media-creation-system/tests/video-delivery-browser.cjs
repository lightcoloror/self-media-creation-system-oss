/* Only synthetic local pages; no accounts, network requests or uploads. */
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.argv[2]);
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const context = await browser.newContext({acceptDownloads:true, viewport:{width:390,height:844}});
    const page = await context.newPage();
    const errors=[], network=[];
    page.on('pageerror', e=>errors.push(e.message));
    await context.route(/^https?:/, r=>{network.push(r.request().url());return r.abort();});
    const complete = pathToFileURL(process.argv[3]).href;
    const state=()=>page.locator('#delivery-status').getAttribute('data-state');
    await page.goto(pathToFileURL(process.argv[4]).href);
    assert.equal(await state(),'draft');
    await page.goto(complete);
    assert.equal(await state(),'verified_at_generation');
    const platformCount=Object.keys(JSON.parse(await page.locator('#desk-data').textContent()).items[0].platforms).length;
    assert.equal(await page.getByLabel('合集名称',{exact:true}).count(),platformCount);
    assert.equal(await page.locator('video[controls]').count(),platformCount);
    await page.getByLabel('标题 / 首句',{exact:true}).first().fill('edited synthetic title');
    assert.equal(await state(),'draft');
    const downloadPromise=page.waitForEvent('download');
    await page.getByRole('button',{name:'保存当前页面',exact:true}).click();
    const download=await downloadPromise;
    const saved=process.argv[3]+'.saved.html';
    await download.saveAs(saved);
    await page.goto(pathToFileURL(saved).href);
    assert.equal(await state(),'draft');
    await page.goto(complete);
    await page.locator('input[type=file]').setInputFiles(process.argv[5]);
    assert.equal(await state(),'draft');
    await page.goto(complete);
    // Shared panels expose this platform's cover path; the removed central
    // cover shelf is no longer a real consumer of the current data.
    const cover=page.getByLabel(/^本平台封面 · /).first();
    await cover.fill((await cover.inputValue())+'.changed');
    assert.equal(await state(),'draft');
    await page.goto(complete);
    await page.locator('details.advanced-tools > summary').click();
    await page.getByText('素材搬家：批量更换根目录',{exact:true}).click();
    const migration=page.locator('.migration');
    // Use the exact synthetic video root; no filesystem move occurs.
    const mediaPath=await page.getByLabel(/ 成片文件$/).first().inputValue();
    const root=mediaPath.replaceAll('\\','/').split('/').slice(0,-1).join('/');
    await migration.locator('input').nth(0).fill(root);
    await migration.locator('input').nth(1).fill(root+'-different');
    await page.getByRole('button',{name:'替换路径',exact:true}).click();
    assert.equal(await state(),'draft');
    assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
    console.log(JSON.stringify({status:'browser_delivery_states_passed',checks:['draft','edit','save-reopen','import','platform-cover-edit','migration','platform-collections','platform-media-controls','no-network']}));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
