const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.argv[2]);
const logic=require('../templates/publication-desk/manual-desk.js');
(async()=>{
  const browser=await chromium.launch({headless:true});
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'publication-desk-'));
  try{
    const context=await browser.newContext({acceptDownloads:true,viewport:{width:1360,height:950}});
    const page=await context.newPage();const errors=[],network=[];
    page.on('pageerror',e=>errors.push(e.message));
    await context.route(/^https?:/,r=>{network.push(r.request().url());return r.abort();});
    await page.goto(pathToFileURL(process.argv[3]).href);
    assert.equal(await page.locator('.platform-card').count(),6);
    assert.equal(await page.locator('.collection-overview').count(),1);
    assert.equal(await page.getByLabel('合集名称',{exact:true}).count(),6);
    assert.equal(await page.getByLabel('合集简介',{exact:true}).count(),6);
    assert.equal(await page.locator('.platform-gates').count(),6);
    assert.equal(await page.locator('.schedule .meta-table tr').count(),7);
    assert.ok((await page.locator('body').innerText()).includes('内容依据与禁止扩写'));
    assert.ok((await page.locator('body').innerText()).includes('待核验'));
    const hasPK=await page.locator('.cover-pk').count();
    if(hasPK){
      assert.equal(await page.locator('.pk-card').count(),3);
      for(const r of ['3:4','9:16','16:9','4:3']){await page.getByLabel('封面 PK 比例').selectOption(r);assert.equal(await page.locator('.pk-card img').count(),3);assert.ok((await page.locator('.pk-card img').first().getAttribute('alt')).includes(r));}
      await page.getByRole('button',{name:'选用 B 组封面',exact:true}).click();
      assert.ok((await page.locator('.cover-pk').innerText()).includes('当前人工选择 B'));
    }
    const text='保存后还能读到 </script> & 中文';
    await page.getByLabel('标题 / 首句',{exact:true}).first().fill(text);
    await page.getByLabel('合集名称',{exact:true}).first().fill('测试合集，仅测试');
    assert.ok((await page.locator('.field-count').first().innerText()).startsWith(Array.from(text).length+' 字符'));
    await page.locator('.record summary').first().click();
    await page.locator('.record select').first().selectOption('scheduled');
    assert.equal(await page.locator('.schedule tr').nth(1).locator('td').nth(2).innerText(),'已提交定时');
    await page.getByLabel('平台已设置的定时日期 / 时间',{exact:true}).first().fill('2026-10-01');
    const jsonEvent=page.waitForEvent('download');await page.getByRole('button',{name:'导出发布数据 JSON',exact:true}).click();
    const jsonFile=path.join(temp,'edited.json');await(await jsonEvent).saveAs(jsonFile);
    const saved=JSON.parse(fs.readFileSync(jsonFile,'utf8'));logic.validate(saved);
    assert.equal(saved.items[0].platforms.douyin.fields.title,text);
    assert.equal(saved.items[0].platforms.douyin.fields.collection_name,'测试合集，仅测试');
    assert.equal(saved.items[0].platforms.douyin.record.status,'scheduled');
    assert.equal(saved.items[0].platforms.douyin.record.published_at,'');
    if(hasPK){assert.equal(saved.items[0].cover_pk.selected,'B');assert.ok(saved.items[0].platforms.bilibili.cover_ids.every(id=>id.startsWith('B_')));}
    const htmlEvent=page.waitForEvent('download');await page.getByRole('button',{name:'保存当前页面',exact:true}).click();
    const htmlFile=path.join(temp,'saved.html');await(await htmlEvent).saveAs(htmlFile);
    const secondText=text+' · 保存后继续编辑';
    await page.getByLabel('标题 / 首句',{exact:true}).first().fill(secondText);
    await page.getByLabel('平台已设置的定时日期 / 时间',{exact:true}).first().fill('2026-10-02');
    const againJsonEvent=page.waitForEvent('download');await page.getByRole('button',{name:'导出发布数据 JSON',exact:true}).click();
    const againJsonFile=path.join(temp,'edited-again.json');await(await againJsonEvent).saveAs(againJsonFile);
    const againData=JSON.parse(fs.readFileSync(againJsonFile,'utf8'));
    assert.equal(againData.items[0].platforms.douyin.fields.title,secondText);
    assert.equal(againData.items[0].platforms.douyin.record.scheduled_for,'2026-10-02');
    const againHtmlEvent=page.waitForEvent('download');await page.getByRole('button',{name:'保存当前页面',exact:true}).click();
    const againHtmlFile=path.join(temp,'saved-again.html');await(await againHtmlEvent).saveAs(againHtmlFile);
    await page.goto(pathToFileURL(againHtmlFile).href);
    assert.equal(await page.getByLabel('标题 / 首句',{exact:true}).first().inputValue(),secondText);
    assert.equal(await page.getByLabel('平台已设置的定时日期 / 时间',{exact:true}).first().inputValue(),'2026-10-02');
    if(hasPK)assert.ok((await page.locator('.cover-pk').innerText()).includes('当前人工选择 B'));
    await page.goto(pathToFileURL(htmlFile).href);
    assert.equal(await page.getByLabel('标题 / 首句',{exact:true}).first().inputValue(),text);
    assert.equal(await page.locator('.record select').first().inputValue(),'scheduled');
    await page.getByLabel('标题 / 首句',{exact:true}).first().fill('temporary edit');
    const importDialog=page.waitForEvent('dialog');
    await page.locator('input[type=file]').setInputFiles(jsonFile);
    await(await importDialog).accept();
    await page.waitForFunction(expected=>{const label=[...document.querySelectorAll('label')].find(l=>l.textContent==='标题 / 首句');return label&&document.getElementById(label.htmlFor)?.value===expected;},text);
    assert.equal(await page.getByLabel('标题 / 首句',{exact:true}).first().inputValue(),text);
    const asset=saved.items[0].video;asset.path='D:/media2/file.mp4';
    assert.equal(logic.remap(saved,'D:/media','E:/archive'),0);
    asset.path='D:/media/file.mp4';const hash=asset.sha256;
    assert.equal(logic.remap(saved,'D:/media','E:/archive'),1);assert.equal(asset.path,'E:/archive/file.mp4');assert.equal(asset.sha256,hash);
    assert.equal(logic.localUrl('https://example.com/video.mp4'),'');
    assert.equal(logic.quoted('D:/my files/片.mp4'),'"D:\\my files\\片.mp4"');
    assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
    if(process.argv[4])await page.screenshot({path:process.argv[4],fullPage:false});
    if(process.argv[5]){
      await page.goto(pathToFileURL(process.argv[5]).href);
      assert.equal(await page.locator('article.item').count(),8);
      assert.equal(await page.locator('.platform-card').count(),40);
      assert.equal(await page.getByLabel('短标题',{exact:true}).count(),8);
      assert.equal(await page.getByLabel('置顶评论',{exact:true}).count(),40);
      assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
    }
    console.log('PASS: real-browser edit, JSON export/import, saved HTML reopen, scheduled state, path boundaries, no external requests');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
