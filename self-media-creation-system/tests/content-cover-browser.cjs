/* Real local PNG/desk verification; isolated browser, no account or network. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const [pw,bin,dir]=process.argv.slice(2);
(async()=>{
 const {chromium}=require(pw),browser=await chromium.launch({headless:true,executablePath:bin});
 try{
  const ctx=await browser.newContext({viewport:{width:1440,height:1100},acceptDownloads:true}),page=await ctx.newPage();
  const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
  await ctx.route(/^https?:/,r=>{external.push(r.request().url());return r.abort()});
  await page.goto(pathToFileURL(path.join(dir,'封面比较与发布辅助页.html')).href);
  assert.equal(await page.locator('.cover-matrix tbody tr').count(),3);
  assert.equal(await page.locator('.cover-matrix img').count(),12);
  await page.locator('.cover-matrix img').evaluateAll(xs=>Promise.all(xs.map(x=>x.decode())));
  for(const ratio of ['3:4','9:16','16:9','4:3']){
   await page.getByLabel('封面 PK 比例').selectOption(ratio);
   await page.locator('.pk-card img').evaluateAll(xs=>Promise.all(xs.map(x=>x.decode())));
   const [a,b]=ratio.split(':').map(Number);
   assert.ok(await page.locator('.pk-card img').evaluateAll((xs,r)=>xs.length===3&&xs.every(x=>Math.abs(x.naturalWidth/x.naturalHeight-r)<.002),a/b));
  }
  assert.equal(await page.locator('.strategy-dispositions').count(),1);
  assert.equal(await page.getByLabel('合集名称',{exact:true}).count(),6);
  await page.locator('.cover-delivery').screenshot({path:path.join(dir,'content-matrix-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  const matrixWrap=page.locator('.cover-delivery .table-wrap');
  assert.ok(await matrixWrap.evaluate(e=>e.scrollWidth>e.clientWidth));
  assert.ok(await matrixWrap.evaluate(e=>{e.scrollLeft=300;return e.scrollLeft>0}));
  await matrixWrap.evaluate(e=>{e.scrollLeft=0});
  await page.evaluate(()=>{const section=document.querySelector('.cover-delivery'),head=document.querySelector('.top');window.scrollTo(0,section.getBoundingClientRect().top+scrollY-head.getBoundingClientRect().height-12)});
  await page.screenshot({path:path.join(dir,'content-matrix-mobile.png')});
  const data=JSON.parse(fs.readFileSync(path.join(dir,'publication-data.json'),'utf8'));
  assert.equal(data.items[0].cover_pk.selected,null);
  assert.equal(data.items[0].platforms.douyin.fields.body,'Preserve synthetic publication copy');
  assert.equal(data.items[0].cover_pk.delivery.rendered_matrix_complete,true);
  assert.equal(data.items[0].cover_pk.delivery.complete,false);
  assert.ok(data.items[0].cover_pk.candidates.every(c=>c.selection_reason&&c.angle&&c.evidence_ids.length));
  // Exercise existing human-selection and editable-page persistence with the
  // new matrix present. Synthetic browser actions are not actual user approval.
  await page.setViewportSize({width:1440,height:1100});
  const chosen=data.items[0].cover_pk.candidates[0].id;
  await page.getByRole('button',{name:'选用 '+chosen+' 组封面',exact:true}).click();
  const edited='Synthetic edited title <not markup>';
  await page.getByLabel('标题 / 首句',{exact:true}).first().fill(edited);
  let download=page.waitForEvent('download');await page.getByRole('button',{name:'保存当前页面',exact:true}).click();
  const savedPage=path.join(dir,'synthetic-saved-page.html');await(await download).saveAs(savedPage);
  await page.goto(pathToFileURL(savedPage).href);
  assert.equal(await page.getByLabel('标题 / 首句',{exact:true}).first().inputValue(),edited);
  assert.equal(await page.locator('.cover-matrix img').count(),12);
  assert.ok((await page.locator('.cover-pk').innerText()).includes('当前人工选择 '+chosen));
  // Missing one ratio is visible, never filled using the previous candidate.
  const partial=JSON.parse(JSON.stringify(data));delete partial.items[0].cover_pk.candidates[0].cover_by_ratio['4:3'];
  await page.locator('input[type=file]').setInputFiles({name:'synthetic-partial.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(partial))});
  await page.locator('.cover-matrix .missing-ratio').waitFor();
  assert.equal(await page.locator('.cover-matrix .missing-ratio').count(),1);
  assert.equal(await page.locator('.cover-matrix img').count(),11);
  await page.getByLabel('封面 PK 比例').selectOption('4:3');
  assert.equal(await page.locator('.pk-card img').count(),2);
  assert.equal(await page.locator('.pk-card .missing-ratio').count(),1);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  fs.writeFileSync(path.join(dir,'content-browser-verification.json'),JSON.stringify({status:'passed',images:12,ratios:4,concepts:3,decoded:true,mobile_width:390,horizontal_matrix_scroll:true,publication_copy_preserved:true,save_reopen:true,missing_ratio_visible:true,synthetic_selection_test_only:true,human_approved:false,external_requests:external,page_errors:errors},null,2),{flag:'wx'});
  console.log('PASS: 3 concepts x 4 ratios, 12 actual PNGs; selection reasons, rejected routes, fields/save/reopen, missing ratio, local-only desktop/mobile UI.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
