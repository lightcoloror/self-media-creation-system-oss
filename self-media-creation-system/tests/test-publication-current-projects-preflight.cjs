'use strict';
// Built-in Node only: no filesystem writes, no shell, no Playwright, no browser.
// Pure tests exercise the actual exported preflight from the candidate module.
const assert=require('node:assert/strict');
const test=require('node:test');
const path=require('node:path');
const {preflight}=require('./publication-current-projects.cjs');

const ROOT=path.resolve('preflight-test-output-root');

function projectRow(projectId){
  return {project_id:projectId,page_ref:{path:'pages/'+projectId+'.html'},current_data_ref:{path:'data/'+projectId+'.json'}};
}
function manifestOf(projectIds){return {projects:projectIds.map(projectRow)};}
function rowWith(overrides){
  return Object.assign({project_id:'valid',page_ref:{path:'pages/valid.html'},current_data_ref:{path:'data/valid.json'}},overrides);
}

test('exports the pure preflight function',()=>{
  assert.equal(typeof preflight,'function');
});

test('accepts multiple projects with Unicode ids and resolves direct-child folders',()=>{
  const ids=['alpha','项目 一','résumé-v2'];
  const plan=preflight(manifestOf(ids),ROOT);
  assert.equal(plan.outputRoot,ROOT);
  assert.deepEqual(plan.projects.map(project=>project.project_id),ids);
  for(const project of plan.projects){
    assert.equal(project.folder,path.join(ROOT,project.project_id));
    assert.equal(path.dirname(project.folder),ROOT);
    assert.equal(path.relative(ROOT,project.folder),project.project_id);
  }
  assert.equal(plan.projects[1].page_path,'pages/项目 一.html');
  assert.equal(plan.projects[1].current_data_path,'data/项目 一.json');
});

test('resolves the supplied output root with path.resolve',()=>{
  const relativeRoot=path.join('relative-root','nested');
  const plan=preflight(manifestOf(['alpha']),relativeRoot);
  assert.equal(plan.outputRoot,path.resolve(relativeRoot));
  assert.equal(plan.projects[0].folder,path.join(path.resolve(relativeRoot),'alpha'));
  assert.equal(path.relative(plan.outputRoot,plan.projects[0].folder),'alpha');
});

test('rejects absent, non-object, non-array or empty projects',()=>{
  for(const manifest of [null,undefined,42,'manifest',[],true]){
    assert.throws(()=>preflight(manifest,ROOT),/manifest must be a non-null object/);
  }
  for(const manifest of [{},{projects:null},{projects:{}},{projects:'alpha'},{projects:42}]){
    assert.throws(()=>preflight(manifest,ROOT),/manifest\.projects must be an array/);
  }
  assert.throws(()=>preflight({projects:[]},ROOT),/manifest\.projects must not be empty/);
});

test('rejects a missing or non-string output directory',()=>{
  for(const outputDirectory of [undefined,'',42,null,{},['out']]){
    assert.throws(()=>preflight(manifestOf(['alpha']),outputDirectory),/output directory must be a non-empty string/);
  }
});

test('rejects malformed project rows',()=>{
  for(const row of [null,undefined,'row',42,true,[projectRow('alpha')]]){
    assert.throws(()=>preflight({projects:[row]},ROOT),/projects\[0\] must be an object/);
  }
});

test('rejects malformed or empty page and current-data references',()=>{
  const badRows=[
    rowWith({page_ref:null}),
    rowWith({page_ref:'pages/valid.html'}),
    rowWith({page_ref:{}}),
    rowWith({page_ref:{path:42}}),
    rowWith({page_ref:{path:''}}),
    rowWith({page_ref:{path:'   '}}),
    rowWith({current_data_ref:null}),
    rowWith({current_data_ref:{}}),
    rowWith({current_data_ref:{path:42}}),
    rowWith({current_data_ref:{path:''}}),
    rowWith({current_data_ref:{path:'   '}})
  ];
  for(const row of badRows){
    assert.throws(()=>preflight({projects:[row]},ROOT),/must be an object|must be a non-empty string/);
  }
});

test('rejects unsafe project ids that could escape or alias the output folder',()=>{
  const cases=[
    ['empty id','',/must be a non-empty string/],
    ['dot','.',/must not be "\." or "\.\."/],
    ['dot dot','..',/must not be "\." or "\.\."/],
    ['forward slash','a/b',/path separators/],
    ['backslash','a\\b',/path separators/],
    ['absolute unix','/escape',/path separators/],
    ['drive path','C:\\escape',/path separators/],
    ['drive relative','C:escape',/path separators/],
    ['UNC path','\\\\server\\share',/path separators/],
    ['NUL character','nul\u0000name',/path separators/],
    ['control character','bad\u0007name',/path separators/],
    ['DEL character','bad\u007Fname',/path separators/],
    ['less-than','bad<name',/path separators/],
    ['greater-than','bad>name',/path separators/],
    ['colon','bad:name',/path separators/],
    ['double quote','bad"name',/path separators/],
    ['pipe','bad|name',/path separators/],
    ['question mark','bad?name',/path separators/],
    ['asterisk','bad*name',/path separators/],
    ['trailing dot','name.',/must not end with a dot or space/],
    ['trailing space','name ',/must not end with a dot or space/]
  ];
  for(const [label,projectId,pattern] of cases){
    assert.throws(()=>preflight({projects:[rowWith({project_id:projectId})]},ROOT),pattern,label);
  }
});

test('rejects Windows reserved device names, including superscript aliases and extensions',()=>{
  const ids=['CON','con','PRN','AUX','NUL','COM1','COM9','LPT1','LPT9','con.txt','CON.json','Com1.tar.gz','NUL.log','COM\u00B9','com\u00B2.txt','LPT\u00B3','lpt\u00B9.log'];
  for(const projectId of ids){
    assert.throws(()=>preflight({projects:[rowWith({project_id:projectId})]},ROOT),/Windows reserved device name/,projectId);
  }
});

test('rejects duplicate project ids and output-folder aliases case-insensitively',()=>{
  assert.throws(()=>preflight(manifestOf(['alpha','alpha']),ROOT),/duplicates another project_id/);
  assert.throws(()=>preflight(manifestOf(['Alpha','alpha']),ROOT),/duplicates another project_id/);
  assert.throws(()=>preflight(manifestOf(['项目','项目']),ROOT),/duplicates another project_id/);
});

test('rejects output-folder escapes and absolute project targets',()=>{
  const ids=['..','../escape','..\\escape','/tmp/escape','C:\\escape','\\\\host\\share'];
  for(const projectId of ids){
    assert.throws(()=>preflight({projects:[rowWith({project_id:projectId})]},ROOT),/must not be|path separators|escapes the output directory/,projectId);
  }
});

test('keeps safely representable Unicode and non-reserved lookalike names',()=>{
  const ids=['中文项目','项目 001','résumé-v2','a.b.c','COM10','CONSOLE','auxiliary','nul_file','.hidden'];
  const plan=preflight(manifestOf(ids),ROOT);
  assert.deepEqual(plan.projects.map(project=>project.project_id),ids);
  assert.equal(new Set(plan.projects.map(project=>project.folder.toLowerCase())).size,ids.length);
});

test('rejects DEL U+007F while keeping non-ASCII ids valid',()=>{
  assert.throws(()=>preflight({projects:[rowWith({project_id:'bad\u007Fname'})]},ROOT),/path separators/);
  const plan=preflight(manifestOf(['中文项目','résumé-v2']),ROOT);
  assert.deepEqual(plan.projects.map(project=>project.project_id),['中文项目','résumé-v2']);
});

test('does not inspect or require page and data paths to exist',()=>{
  const missingPage=path.join(ROOT,'missing-page.html');
  const missingData=path.join(ROOT,'missing-data.json');
  const plan=preflight({projects:[{project_id:'missing-paths',page_ref:{path:missingPage},current_data_ref:{path:missingData}}]},ROOT);
  assert.equal(plan.projects[0].page_path,missingPage);
  assert.equal(plan.projects[0].current_data_path,missingData);
});

test('does not mutate the manifest',()=>{
  const source=manifestOf(['alpha','beta']);
  const before=JSON.parse(JSON.stringify(source));
  preflight(source,ROOT);
  assert.deepEqual(source,before);
});

test('validates every row, not just the first, before returning a plan',()=>{
  assert.throws(()=>preflight({projects:[projectRow('alpha'),rowWith({project_id:'../escape'})]},ROOT),/path separators/);
  assert.throws(()=>preflight({projects:[projectRow('alpha'),rowWith({page_ref:null})]},ROOT),/page_ref must be an object/);
});
