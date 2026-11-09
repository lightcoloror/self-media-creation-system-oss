/* Synthetic offline desk only. No user browser, account or publishing. */
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.argv[2]);
(async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const context=await browser.newContext({acceptDownloads:true,viewport:{width:390,height:844}});
    const page=await context.newPage(),errors=[],network=[];
    page.on('pageerror',e=>errors.push(e.message));
    await context.route(/^https?:/,r=>{network.push(r.request().url());return r.abort();});
    const state=()=>page.locator('#cta-review-status').getAttribute('data-state');
    const prepared=pathToFileURL(process.argv[3]).href;
    await page.goto(pathToFileURL(process.argv[4]).href);
    assert.equal(await state(),'pending');
    await page.goto(prepared);
    assert.equal(await state(),'prepared');
    assert.equal(await page.locator('#delivery-status').getAttribute('data-state'),'draft');
    assert.match(await page.locator('.cta-review').textContent(),/互动 · 采用/);
    assert.match(await page.locator('.cta-review').textContent(),/获客 · 不采用/);
    assert.match(await page.locator('.cta-review').textContent(),/发布简介/);
    await page.locator('details.platform-card').evaluate(e=>{e.open=true;});
    await page.getByLabel('简介 / 正文',{exact:true}).fill('Changed copy without the selected question.');
    assert.equal(await state(),'pending');
    const downloadPromise=page.waitForEvent('download');
    await page.getByRole('button',{name:'保存当前页面',exact:true}).click();
    const saved=process.argv[3]+'.saved.html';await(await downloadPromise).saveAs(saved);
    await page.goto(pathToFileURL(saved).href);assert.equal(await state(),'pending');
    await page.goto(prepared);assert.equal(await state(),'prepared');
    await page.locator('input[type=file]').setInputFiles(process.argv[5]);
    assert.equal(await state(),'pending');
    assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
    console.log(JSON.stringify({status:'passed',checks:['missing-plan-pending','copy-prepared-not-delivery','two-independent-decisions','body-location','edit-invalidates','save-reopen-stays-pending','import-invalidates','no-js-errors','no-network']}));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
