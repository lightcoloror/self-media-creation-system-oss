/* Headless regression of the real local comparison page, no uploads/network. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.argv[2]);
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.argv[4]});
  try{
    const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:1040}});
    const page=await context.newPage();const errors=[],external=[];
    page.on('pageerror',e=>errors.push(e.message));
    await context.route(/^https?:/,r=>{external.push(r.request().url());return r.abort();});
    await page.goto(pathToFileURL(process.argv[3]).href);
    assert.equal(await page.locator('.pk-card').count(),6);
    assert.equal(await page.locator('.pk-card img').count(),6);
    await page.locator('.pk-card img').evaluateAll(async imgs=>Promise.all(imgs.map(i=>i.decode())));
    assert.ok(await page.locator('.pk-card img').evaluateAll(imgs=>imgs.every(i=>i.naturalWidth>=480)));
    await page.locator('.cover-pk').scrollIntoViewIfNeeded();
    await page.screenshot({path:process.argv[5],fullPage:false});
    await page.getByLabel('封面 PK 比例').selectOption('16:9');
    assert.equal(await page.locator('.missing-ratio').count(),6);
    assert.equal(await page.locator('.pk-card img').count(),0);
    await page.getByRole('button',{name:'选用 E-real-contrast 组封面',exact:true}).click();
    const wait=page.waitForEvent('download');
    await page.getByRole('button',{name:'导出发布数据 JSON',exact:true}).click();
    const download=await wait;const content=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
    assert.deepEqual(content.items[0].platforms.bilibili.cover_ids,[]);
    assert.deepEqual(content.items[0].platforms.xiaohongshu.cover_ids,['E-real-contrast_3x4']);
    assert.deepEqual(content.items[0].platforms.douyin.cover_ids,[]);
    assert.equal(content.items[0].platforms.bilibili.record.status,'prepared');
    assert.equal(await page.getByLabel('合集名称',{exact:true}).count(),6);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    console.log('PASS: six real PNGs decoded; missing ratios visible; incomplete platform cleared; complete ratio assigned; no publish; no external requests');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
