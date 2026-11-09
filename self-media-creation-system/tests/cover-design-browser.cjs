/* Existing publication desk, generic synthetic cover smoke; no logged-in browser. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {pathToFileURL}=require('node:url');
const [pw,browserPath,reviewDir]=process.argv.slice(2);
(async()=>{
 const {chromium}=require(pw);
 const browser=await chromium.launch({headless:true,executablePath:browserPath});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
  const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
  await context.route(/^https?:/,r=>{external.push(r.request().url());return r.abort()});
  await page.goto(pathToFileURL(path.join(reviewDir,'封面比较与发布辅助页.html')).href);
  assert.equal(await page.locator('.pk-card').count(),7);
  for(const ratio of ['3:4','16:9']){
   await page.getByLabel('封面 PK 比例').selectOption(ratio);
   assert.equal(await page.locator('.pk-card img').count(),7);
   await page.locator('.pk-card img').evaluateAll(async imgs=>Promise.all(imgs.map(i=>i.decode())));
   const expected=ratio==='3:4'?.75:16/9;
   assert.ok(await page.locator('.pk-card img').evaluateAll((imgs,r)=>imgs.every(i=>Math.abs(i.naturalWidth/i.naturalHeight-r)<.002),expected));
   await page.locator('.cover-pk').screenshot({path:path.join(reviewDir,'smoke-'+ratio.replace(':','x')+'.png')});
  }
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert.equal(await page.getByLabel('合集名称',{exact:true}).count(),6);
  const data=JSON.parse(fs.readFileSync(path.join(reviewDir,'publication-data.json'),'utf8'));
  assert.equal(data.items[0].cover_pk.selected,null);
  assert.ok(data.items[0].cover_pk.candidates.every(c=>c.design_method&&c.generative_model_used===false));
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('PASS: 14 PNGs decode in 7 generic recipe candidates, two ratios; provenance retained; no auto-selection, mobile overflow or external requests');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
