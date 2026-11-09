// Adapted from publication-platform-panels.cjs: consume existing local pages.
// Input manifest and QA downloads stay in a private runtime, not source fixtures.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');

// Pure preflight: validates the whole manifest before any output mkdir, Playwright
// require or browser launch. It does not touch the filesystem and does not resolve
// page/data paths; it only checks their shape for the existing runtime semantics.
const WINDOWS_INVALID_OR_SEPARATOR=/[\u0000-\u001F\u007F<>:"/\\|?*]/;
const WINDOWS_RESERVED_DEVICE_NAMES=new Set([
  'con','prn','aux','nul',
  'com1','com2','com3','com4','com5','com6','com7','com8','com9',
  'com\u00B9','com\u00B2','com\u00B3',
  'lpt1','lpt2','lpt3','lpt4','lpt5','lpt6','lpt7','lpt8','lpt9',
  'lpt\u00B9','lpt\u00B2','lpt\u00B3'
]);

function preflightFailure(message){throw new Error('preflight: '+message);}

function validateProjectId(projectId,index){
  const label='projects['+index+'].project_id';
  if(typeof projectId!=='string'||projectId.length===0) preflightFailure(label+' must be a non-empty string');
  if(projectId==='.'||projectId==='..') preflightFailure(label+' must not be "." or ".."');
  if(WINDOWS_INVALID_OR_SEPARATOR.test(projectId)) preflightFailure(label+' must not contain path separators, control characters or Windows-invalid characters (< > : " | ? *)');
  if(/[. ]$/.test(projectId)) preflightFailure(label+' must not end with a dot or space');
  const deviceName=projectId.split('.')[0].toLowerCase();
  if(WINDOWS_RESERVED_DEVICE_NAMES.has(deviceName)) preflightFailure(label+' must not be a Windows reserved device name');
  return projectId;
}

function preflight(manifest,outputDirectory){
  if(manifest===null||typeof manifest!=='object'||Array.isArray(manifest)) preflightFailure('manifest must be a non-null object');
  if(!Array.isArray(manifest.projects)) preflightFailure('manifest.projects must be an array');
  if(manifest.projects.length===0) preflightFailure('manifest.projects must not be empty');
  if(typeof outputDirectory!=='string'||outputDirectory.length===0) preflightFailure('output directory must be a non-empty string');
  const outputRoot=path.resolve(outputDirectory),projects=[],seenIds=new Set(),seenFolders=new Set();
  manifest.projects.forEach((row,index)=>{
    if(row===null||typeof row!=='object'||Array.isArray(row)) preflightFailure('projects['+index+'] must be an object');
    const projectId=validateProjectId(row.project_id,index);
    const pageRef=row.page_ref,dataRef=row.current_data_ref;
    if(pageRef===null||typeof pageRef!=='object'||Array.isArray(pageRef)) preflightFailure('projects['+index+'].page_ref must be an object');
    if(dataRef===null||typeof dataRef!=='object'||Array.isArray(dataRef)) preflightFailure('projects['+index+'].current_data_ref must be an object');
    if(typeof pageRef.path!=='string'||pageRef.path.trim()==='') preflightFailure('projects['+index+'].page_ref.path must be a non-empty string');
    if(typeof dataRef.path!=='string'||dataRef.path.trim()==='') preflightFailure('projects['+index+'].current_data_ref.path must be a non-empty string');
    const projectKey=projectId.toLowerCase();
    if(seenIds.has(projectKey)) preflightFailure('projects['+index+'].project_id duplicates another project_id (case-insensitive)');
    const folder=path.join(outputRoot,projectId);
    // Lexical confinement only. path.relative proves the target is a direct child of
    // the resolved output root; existing symlinks, junctions, hard links and
    // filesystem races are NOT resolved or sandboxed by this check.
    const relative=path.relative(outputRoot,folder);
    if(relative===''||path.isAbsolute(relative)||relative.split(path.sep).length!==1||relative==='..') preflightFailure('projects['+index+'].project_id escapes the output directory');
    const folderKey=folder.toLowerCase();
    if(seenFolders.has(folderKey)) preflightFailure('projects['+index+'].project_id resolves to a duplicate output folder');
    seenIds.add(projectKey);seenFolders.add(folderKey);
    projects.push({project_id:projectId,page_path:pageRef.path,current_data_path:dataRef.path,folder});
  });
  return {outputRoot,projects};
}

async function run(playwrightModulePath,source,outputDirectory){
  const plan=preflight(source,outputDirectory),out=plan.outputRoot;
  const folders=new Map(plan.projects.map(project=>[project.project_id,project.folder]));
  fs.mkdirSync(out,{recursive:true});
  const {chromium}=require(playwrightModulePath);
  const report={status:'running',projects:[],network:[],errors:[],uploads:false,published:false,human_approval_added:false};
  let browser;
  try{
    browser=await chromium.launch({headless:true,channel:'msedge'});
    for(const row of source.projects){
      const folder=folders.get(row.project_id);fs.mkdirSync(folder,{recursive:true});
      const context=await browser.newContext({acceptDownloads:true,viewport:{width:1280,height:920}});
      await context.route(/^https?:/,r=>{report.network.push(r.request().url());return r.abort();});
      const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
      await page.goto(pathToFileURL(row.page_ref.path).href);
      const data=JSON.parse(await page.locator('#desk-data').textContent());
      const saved=JSON.parse(fs.readFileSync(row.current_data_ref.path,'utf8'));
      assert.deepEqual(data,saved);assert.equal(data.project_id,row.project_id);
      const count=data.items.reduce((n,i)=>n+Object.keys(i.platforms).length,0);
      assert.equal(await page.locator('details.platform-card').count(),count);
      assert.equal(await page.locator('video[controls]').count(),count);
      assert.equal(await page.locator('#delivery-status').getAttribute('data-state'),'draft');
      // A fresh current page must not start out invalidated by its own UI.
      assert.ok(!(await page.locator('#local-preparation').textContent()).includes('通用要求需保存数据后重新检查'));
      await page.getByRole('button',{name:'全部展开',exact:true}).click();
      assert.equal(await page.locator('details.platform-card[open]').count(),count);
      for(const image of await page.locator('img[data-cover-id]').all()){
        await image.scrollIntoViewIfNeeded();
        await image.evaluate(node=>node.decode());
        assert.ok(await image.evaluate(node=>node.naturalWidth>0));
      }
      const panel=page.locator('[data-platform=xiaohongshu]').first();
      const body=panel.getByLabel('简介 / 正文',{exact:true}),original=await body.inputValue();
      await body.fill(original+'\n本地测试修改，不是发布文案。');
      assert.ok((await panel.getByLabel('小红书 整段发布文案',{exact:true}).inputValue()).includes('本地测试修改'));
      assert.ok((await page.locator('#local-preparation').textContent()).includes('通用要求需保存数据后重新检查'));
      const exported=page.waitForEvent('download');await page.getByRole('button',{name:'导出发布数据 JSON',exact:true}).click();
      await(await exported).saveAs(path.join(folder,'edited-test-only.json'));
      const download=page.waitForEvent('download');await page.getByRole('button',{name:'保存当前页面',exact:true}).click();
      const html=path.join(folder,'saved-test-only.html');await(await download).saveAs(html);
      await page.goto(pathToFileURL(html).href);
      assert.equal(await page.locator('[data-platform=xiaohongshu]').first().getByLabel('简介 / 正文',{exact:true}).inputValue(),original+'\n本地测试修改，不是发布文案。');
      assert.ok((await page.locator('#local-preparation').textContent()).includes('通用要求需保存数据后重新检查'));
      assert.equal(await page.locator('#delivery-status').getAttribute('data-state'),'draft');
      await page.getByRole('button',{name:'全部收起',exact:true}).click();
      assert.equal(await page.locator('details.platform-card[open]').count(),0);
      await page.locator('[data-platform=xiaohongshu] summary.platform-head').first().click();
      await page.setViewportSize({width:412,height:915});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      await page.screenshot({path:path.join(folder,'mobile.png'),fullPage:true});
      report.projects.push({project_id:row.project_id,panels:count,status:'passed',tests:['actual-current-data','platform-assets-decode','expand-collapse','copy-updates','requirement-invalidates','export','save-reopen','mobile-layout','draft-boundary']});
      await context.close();
    }
    assert.deepEqual(report.network,[]);assert.deepEqual(report.errors,[]);report.status='passed';
  }catch(e){report.status='failed';report.error=e.stack;process.exitCode=1;}
  finally{
    if(browser)await browser.close();
    fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }
}

async function main(){
  const source=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
  await run(process.argv[2],source,process.argv[4]);
}

if(require.main===module){
  main().catch(error=>{console.error('publication-current-projects.cjs failed: '+(error&&error.stack?error.stack:String(error)));process.exitCode=1;});
}

module.exports={preflight};
