/* Shared offline desk. No platform calls; saved HTML embeds edited project data. */
(function () {
  'use strict';
  const schema = 'local-publication-desk.v2';
  const statuses = {prepared:'待发布', planned:'计划发布', scheduled:'已提交定时', published:'人工确认已发布'};
  const labels = {douyin:'抖音',xiaohongshu:'小红书',weixin_channels:'微信视频号',kuaishou:'快手',bilibili:'哔哩哔哩',weibo:'微博'};
  const fieldLabels = {title:'标题 / 首句',body:'简介 / 正文',tags:'话题 / 标签',short_title:'短标题',collection_name:'合集名称',collection_description:'合集简介',pinned_comment:'置顶评论'};
  function validate(data) {
    if (!data || data.schema_version !== schema || typeof data.project_id !== 'string' || !data.project_id || typeof data.title !== 'string' || !Array.isArray(data.items) || !data.items.length || data.items.length > 200) throw Error('发布包格式不正确');
    const ids = new Set();
    const terms=data.editorial_context?.forbidden_public_phrases||[];
    if(!Array.isArray(terms)||terms.some(t=>typeof t!=='string'||!t.trim()))throw Error('禁止提前透露的文字列表格式不正确');
    for (const i of data.items) {
      if (typeof i.id !== 'string' || ids.has(i.id) || typeof i.title !== 'string' || !Array.isArray(i.covers) || !i.platforms || typeof i.platforms !== 'object' || !Object.keys(i.platforms).length) throw Error('视频条目格式不正确');
      ids.add(i.id);
      const pk=i.cover_pk;
      if(pk!==undefined){
        if(!pk||typeof pk!=='object'||Array.isArray(pk)||('requested'in pk&&typeof pk.requested!=='boolean')||!Array.isArray(pk.candidates||[])||(pk.candidates||[]).some(c=>!c||typeof c.id!=='string'||!c.cover_by_ratio||typeof c.cover_by_ratio!=='object'||Array.isArray(c.cover_by_ratio)))throw Error('封面比较数据格式不正确');
        if(!Array.isArray(pk.required_ratios||[])||(pk.required_ratios||[]).some(r=>!['3:4','4:3','9:16','16:9','1:1'].includes(r)))throw Error('封面比例格式不正确');
        if(!['single','parallel_test'].includes(pk.selection_mode||'single')||!Array.isArray(pk.test_candidate_ids||[])||(pk.test_candidate_ids||[]).some(id=>typeof id!=='string'))throw Error('封面使用方式格式不正确');
      }
      const coverIds = new Set();
      for (const c of i.covers) { if (typeof c.id !== 'string' || coverIds.has(c.id)) throw Error('封面编号重复'); coverIds.add(c.id); }
      for (const a of [i.video,...i.covers]) {
        if (!a || typeof a.path !== 'string' || a.path.length > 4096 || (a.sha256 && !/^[a-f0-9]{64}$/i.test(a.sha256))) throw Error('素材路径或哈希格式不正确');
      }
      for (const [key,p] of Object.entries(i.platforms)) {
        if(p.cover_test!==undefined&&(!p.cover_test||typeof p.cover_test!=='object'||Array.isArray(p.cover_test)||typeof(p.cover_test.requested??false)!=='boolean'))throw Error('平台封面测试格式不正确');
        if (!Object.hasOwn(labels,key)) throw Error('未知平台：'+key);
        if (key!=='weixin_channels' && Object.hasOwn(p.fields||{},'short_title')) throw Error('短标题仅适用于视频号，请先修正平台字段：'+key);
        if (!p.fields || !(['kuaishou','weixin_channels'].includes(key)?['body','tags']:['title','body','tags']).every(k => typeof p.fields[k] === 'string') || !Object.values(p.fields).every(v => typeof v === 'string' && v.length <= 20000) || !p.record || !Object.hasOwn(statuses,p.record.status)) throw Error('平台文案或记录格式不正确');
        if (!Array.isArray(p.cover_ids) || p.cover_ids.some(k => !coverIds.has(k))) throw Error('平台封面引用不存在');
        if(p.cover_test?.main_cover_id!==undefined&&(typeof p.cover_test.main_cover_id!=='string'||(p.cover_test.main_cover_id&&!coverIds.has(p.cover_test.main_cover_id))))throw Error('主封面引用不存在');
        for (const k of ['account','planned_at','scheduled_for','published_at','url','notes']) if (p.record[k] !== undefined && typeof p.record[k] !== 'string') throw Error('发布记录格式不正确');
      }
    }
    if (data.rules !== undefined && !Array.isArray(data.rules)) throw Error('平台规则格式不正确');
    return data;
  }
  function pathNorm(value) { return value.trim().replace(/^"|"$/g,'').replaceAll('\\','/').replace(/\/+$/,''); }
  function quoted(value) { return value.trim() ? '"' + pathNorm(value).replaceAll('/','\\') + '"' : ''; }
  function localUrl(path) {
    const p=pathNorm(path);
    if (/^[a-z]:\//i.test(p)) return 'file:///' + p.slice(0,2) + p.slice(2).split('/').map(encodeURIComponent).join('/');
    if (p.startsWith('/') && !p.startsWith('//')) return 'file://' + p.split('/').map(encodeURIComponent).join('/');
    return '';
  }
  function remap(data, oldRoot, newRoot) {
    const old=pathNorm(oldRoot), next=pathNorm(newRoot);
    if (!localUrl(old) || !localUrl(next)) throw Error('请输入完整的本地素材根目录');
    let count=0;
    for (const item of data.items) for (const asset of [item.video,...item.covers]) {
      const p=pathNorm(asset.path), a=p.toLowerCase(), b=old.toLowerCase();
      if (a===b || a.startsWith(b+'/')) { asset.path=next+p.slice(old.length); count++; }
    }
    return count;
  }
  function serialized(data) { validate(data); return JSON.stringify(data,null,2).replaceAll('<','\\u003c').replaceAll('>','\\u003e').replaceAll('&','\\u0026'); }
  function platformCoverIds(item,key){const p=item.platforms[key],main=p.cover_test?.requested&&p.cover_test.main_cover_id;return [...new Set([...(main?[main]:[]),...p.cover_ids])];}
  function checkPolicyBasis(key,name,policy){
    const profile=policy.platforms[key];let keys=[];
    if(name==='current_specs')keys=Object.keys(profile);
    else if(['crop_preview','cover_slots','cover_pk'].includes(name))keys=['cover_mode','cover_ratios','native_cover_test'];
    else if(['short_title_rules','title_restored','submission','disclosure'].includes(name))keys=['field_limits','short_title','short_title_allowed_symbols','separate_title','copy_mode'];
    else if(['schedule','schedule_change'].includes(name))keys=['historical_notes'];
    const result={description:profile.checks?.[name]??policy.common_checks[name],dependencies:policy.check_dependencies[name],profile:Object.fromEntries(keys.filter(k=>k in profile).map(k=>[k,profile[k]]))};
    if(['crop_preview','cover_slots','cover_pk','current_specs'].includes(name))result.ratio_tolerance=policy.ratio_tolerance;
    return result;
  }
  function platformCheckSnapshot(item,key,name,policy){
    const p=item.platforms[key],f=p.fields,r=p.record;
    const candidates=JSON.parse(JSON.stringify(item.cover_pk||{}));if(p.cover_test)candidates.platform_cover_test=JSON.parse(JSON.stringify(p.cover_test));
    const values={account:r.account||'',video:item.video,copy:f,covers:platformCoverIds(item,key).map(id=>item.covers.find(c=>c.id===id)),
      tags:f.tags||'',title:f.title||'',short_title:f.short_title||'',
      collection:Object.fromEntries(['collection_name','collection_description'].map(k=>[k,f[k]||''])),
      schedule:Object.fromEntries(['planned_at','scheduled_for'].map(k=>[k,r[k]||''])),cover_candidates:candidates};
    return JSON.parse(JSON.stringify({policy_version:policy.version,platform:key,policy_basis:checkPolicyBasis(key,name,policy),inputs:Object.fromEntries(policy.check_dependencies[name].map(k=>[k,values[k]]))}));
  }
  function stableJson(value){return JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);}
  function coverTestPlan(item,key,policy){
    const p=item.platforms[key],pk=item.cover_pk||{},test=p.cover_test||{};if(!test.requested)return null;
    if(pk.selection_mode!=='parallel_test'||pk.selected)throw Error('并行测试不能预先选定胜者');
    const ids=test.candidate_ids||[],selected=pk.test_candidate_ids||[],candidates=new Map((pk.candidates||[]).map(c=>[c.id,c]));
    const profile=policy.platforms[key],native=profile.native_cover_test||{},minimum=native.min_candidates||2,ratios=test.ratios||[];
    if(!Array.isArray(ids)||ids.length<minimum||new Set(ids).size!==ids.length||ids.some(id=>!candidates.has(id)||!selected.includes(id)))throw Error('请保留至少 '+minimum+' 个不同的PK候选');
    if(native.max_candidates&&ids.length>native.max_candidates)throw Error('PK候选最多 '+native.max_candidates+' 张，主封面另计');
    if(!Array.isArray(ratios)||!ratios.length||new Set(ratios).size!==ratios.length||ratios.some(r=>!profile.cover_ratios.includes(r)))throw Error('封面测试比例未正确配置');
    if(profile.cover_mode==='one'&&ratios.length!==1)throw Error('每个测试方案应使用同一比例，不能把不同比例当不同创意');
    if(profile.cover_mode==='all'&&(profile.cover_ratios.length!==ratios.length||profile.cover_ratios.some(r=>!ratios.includes(r))))throw Error('每个测试方案均需配齐比例槽位');
    const assets=new Set(item.covers.map(a=>a.id)),expected=[];
    const variants=ids.map(id=>{const c=candidates.get(id),covers=Object.fromEntries(ratios.map(r=>[r,c.cover_by_ratio[r]]));if(Object.values(covers).some(id=>!assets.has(id)))throw Error('测试方案缺少实际封面：'+id);expected.push(...Object.values(covers));return {candidate_id:id,name:c.name||id,covers};});
    if(new Set(expected).size!==expected.length||JSON.stringify(expected)!==JSON.stringify(p.cover_ids))throw Error('封面测试的方案与上传路径不一致');
    const result={candidate_ids:ids,ratios,variants,interface_status:test.interface_status||'pending'};
    if(native.layout==='main_plus_candidates'){
      const main=test.main_cover_id,asset=item.covers.find(a=>a.id===main);
      if(main&&!asset)throw Error('主封面文件不存在');
      if(main&&(expected.includes(main)||expected.some(id=>asset.sha256&&asset.sha256===item.covers.find(a=>a.id===id).sha256)))throw Error('主封面不能同时作为PK候选');
      Object.assign(result,{layout:native.layout,main_cover_id:main||null,max_candidates:native.max_candidates,total_cover_count:expected.length+(main?1:0)});
    }
    return result;
  }
  function applyCoverTestSelection(item,ids,policy,onlyKey=null){
    const pk=item.cover_pk,candidates=new Map((pk.candidates||[]).map(c=>[c.id,c]));
    const minimum=policy.platforms[onlyKey]?.native_cover_test?.min_candidates||2;
    if(ids.length<minimum||new Set(ids).size!==ids.length||ids.some(id=>!candidates.has(id)))throw Error('请保留至少 '+minimum+' 个不同方案参与测试');
    if(onlyKey&&(!item.platforms[onlyKey]||ids.some(id=>!(pk.test_candidate_ids||[]).includes(id))))throw Error('平台方案必须来自当前测试组');
    const next=JSON.parse(JSON.stringify(item));next.cover_pk.selection_mode='parallel_test';next.cover_pk.selected=null;delete next.cover_pk.selected_at;if(!onlyKey)next.cover_pk.test_candidate_ids=ids.slice();
    for(const [key,p]of Object.entries(next.platforms)){
      if(onlyKey&&key!==onlyKey)continue;
      const profile=policy.platforms[key],assigned=pk.platform_ratios?.[key],ratios=assigned?.length?assigned:(profile.cover_mode==='one'?[profile.cover_ratios.includes('3:4')?'3:4':profile.cover_ratios[0]]:profile.cover_ratios.slice());
      p.cover_test={interface_status:'pending',interface_evidence:'',checked_at:'',...(p.cover_test||{}),requested:true,candidate_ids:ids.slice(),ratios:ratios.slice()};
      p.cover_ids=ids.flatMap(id=>ratios.map(r=>candidates.get(id).cover_by_ratio[r]));coverTestPlan(next,key,policy);
    }
    Object.assign(pk,next.cover_pk);delete pk.selected_at;for(const [key,p]of Object.entries(item.platforms)){if(onlyKey&&key!==onlyKey)continue;p.cover_test=next.platforms[key].cover_test;p.cover_ids=next.platforms[key].cover_ids;}
    return item;
  }
  function invalidateChangedChecks(data,policy){
    let count=0;
    for(const item of data.items)for(const [key,p]of Object.entries(item.platforms))for(const [name,check]of Object.entries(p.platform_checks||{})){
      if(!['confirmed','not_applicable'].includes(check.status)||!policy.check_dependencies[name])continue;
      if(stableJson(check.input_snapshot)!==stableJson(platformCheckSnapshot(item,key,name,policy))){
        const {previous_evidence,...previous}=check;
        check.previous_evidence=[...(previous_evidence||[]),previous];
        check.status='pending';delete check.input_snapshot;
        check.invalidated_reason='相关输入或规则已变化，旧核验仅保留为历史';count++;
      }
    }
    return count;
  }
  function preparationIssues(data, policy, geometry={}) {
    const issues=[];
    for(const item of data.items){
      const add=(key,text)=>issues.push({item_id:item.id,platform:key,detail:text});
      if(!data.target_platforms?.length)add('*','本次平台集合尚未确认，请升级项目数据');
      else if(data.target_platforms.some(k=>!item.platforms[k])||Object.keys(item.platforms).some(k=>!data.target_platforms.includes(k)))add('*','当前平台卡片与本次平台集合不一致');
      for(const [key,p] of Object.entries(item.platforms)){
        const profile=policy.platforms[key];
        const testing=p.cover_test?.requested===true;
        if(testing)try{const plan=coverTestPlan(item,key,policy),limit=p.cover_test.confirmed_candidate_limit,minimum=profile.native_cover_test?.min_candidates||2;if(limit!==undefined&&limit!==null&&(!Number.isInteger(limit)||limit<minimum||plan.candidate_ids.length>limit))add(key,'计划候选数超过已核对名额，或名额记录无效');if(profile.native_cover_test?.main_required&&!plan.main_cover_id)add(key,'主封面待指定；主封面不占3张PK候选名额');}catch(error){add(key,error.message);}
        if(profile.separate_title===false&&p.fields.title)add(key,'旧普通标题需迁移，不是本平台输入框');
        if(!profile.short_title&&Object.hasOwn(p.fields,'short_title'))add(key,'短标题只适用于视频号');
        for(const f of [...(profile.separate_title===false?['body','tags']:['title','body','tags']),...(profile.short_title?['short_title']:[])])if(!p.fields[f]?.trim())add(key,(fieldLabels[f]||f)+'待补齐');
        for(const [f,n] of Object.entries(profile.field_limits||{}))if(Array.from(p.fields[f]||'').length>n)add(key,(fieldLabels[f]||f)+'超过已记录适配基线');
        if(profile.short_title_allowed_symbols&&Array.from(p.fields.short_title||'').some(c=>!/[\p{L}\p{N}\s]/u.test(c)&&!profile.short_title_allowed_symbols.includes(c)))add(key,'短标题含不适用符号');
        const found=[];
        for(const id of platformCoverIds(item,key)){
          const asset=item.covers.find(c=>c.id===id),dim=asset&&geometry[asset.path];
          if(!dim){add(key,'封面尚未成功显示：'+id);continue;}
          const ratio=profile.cover_ratios.find(r=>{const [a,b]=r.split(':').map(Number);return Math.abs((dim.width/dim.height)/(a/b)-1)<=policy.ratio_tolerance;});
          if(ratio)found.push(ratio);else add(key,'封面实际比例不适用：'+id);
        }
        if(profile.cover_mode==='all'&&profile.cover_ratios.some(r=>!found.includes(r)))add(key,'封面槽位未配齐：'+profile.cover_ratios.filter(r=>!found.includes(r)).join('、'));
        if(profile.cover_mode==='one'&&!testing&&p.cover_ids.length!==1)add(key,'需选择一张适用封面');
        if(profile.cover_mode==='unverified')add(key,'本平台封面规格待核准');
        for(const term of data.editorial_context?.forbidden_public_phrases||[])if(term&&Object.values(p.fields).some(v=>v.includes(term)))add(key,'发布文案出现已禁止提前透露的文字');
      }
      const pk=item.cover_pk;
      if(!pk||(pk.requested===false&&!pk.not_requested_reason?.trim()))add('*','尚未明确封面多方案比较范围');
      if(pk?.requested!==false&&(!pk?.candidates||pk.candidates.length<2))add('*','多方案对比待补齐；多个比例不代表多个创意');
      const hashes=new Map();
      const needed=Object.keys(item.platforms).flatMap(k=>policy.platforms[k].cover_mode==='all'?policy.platforms[k].cover_ratios:[]);
      if(pk?.candidates?.length&&(!pk.required_ratios?.length||needed.some(r=>!pk.required_ratios.includes(r))))add('*','候选比较缺少目标平台比例');
      for(const c of pk?.candidates||[]){
        if(!c.title||!(c.hypothesis||c.selection_reason))add('*','封面候选缺标题或比较理由：'+c.id);
        for(const r of pk.required_ratios||[]){
          const asset=item.covers.find(a=>a.id===c.cover_by_ratio?.[r]),dim=asset&&geometry[asset.path];
          if(!asset||!dim){add('*','候选封面未显示：'+c.id+' / '+r);continue;}
          const [a,b]=r.split(':').map(Number);
          if(Math.abs(dim.width/dim.height-a/b)>.002)add('*','候选实际比例不符：'+c.id+' / '+r);
          const identity=r+':'+asset.sha256;
          if(asset.sha256&&hashes.has(identity)&&hashes.get(identity)!==c.id)add('*','不同候选复用了同一张图');
          hashes.set(identity,c.id);
        }
        for(const term of data.editorial_context?.forbidden_public_phrases||[])if(term&&c.title?.includes(term))add('*','候选标题出现已禁止提前透露的文字：'+c.id);
      }
    }
    return issues;
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports={validate,remap,quoted,localUrl,serialized,preparationIssues,platformCheckSnapshot,invalidateChangedChecks,coverTestPlan,applyCoverTestSelection,platformCoverIds}; return; }
  let data=validate(JSON.parse(document.getElementById('desk-data').textContent));
  if(data.publication_summary?.status==='user_reported_published')statuses.prepared='发布记录待核对';
  const policy=JSON.parse(document.getElementById('platform-policy').textContent);
  const coverPreviews=JSON.parse(document.getElementById('cover-previews')?.textContent||'{}');
  const buildDocument=JSON.parse(document.getElementById('desk-build')?.textContent||'{}');
  const ctaBuild=buildDocument.cta,requirementBuild=buildDocument.requirement_report;
  function requirementBuildCurrent(){const current=Object.fromEntries(Object.entries(data).filter(([key])=>!['revision','modified_at','ui_state'].includes(key)));return !!requirementBuild?.input_snapshot&&stableJson(current)===stableJson(requirementBuild.input_snapshot);}
  function ctaBuildCurrent(){return !!ctaBuild&&JSON.stringify(ctaBuild.input_snapshot)===JSON.stringify(data.items.map(i=>({id:i.id,plan_ref:i.cta_plan_ref??null,video:i.video,fields:Object.fromEntries(Object.entries(i.platforms).map(([k,p])=>[k,p.fields]))})));}
  const geometry={};
  const imageBindings=new Map();
  const videoBindings=new Map();
  function coverUrl(cover){const cached=coverPreviews[cover.path];return cached&&(!cover.sha256||cached.sha256===cover.sha256.toLowerCase())?cached.data_url:localUrl(cover.path);}
  function bindCover(img,cover){
    imageBindings.set(img,cover);
    img.dataset.coverId=cover.id;
    const path=cover.path;
    img.onload=()=>{if(cover.path!==path)return;geometry[path]={width:img.naturalWidth,height:img.naturalHeight};img.dataset.loaded='true';refreshPreparation();};
    img.onerror=()=>{if(cover.path!==path)return;delete geometry[path];img.dataset.loaded='false';refreshPreparation();};
    img.src=coverUrl(cover)||'';
  }
  function refreshPreparation(){
    const box=document.getElementById('local-preparation');if(!box)return;
    const issues=preparationIssues(data,policy,geometry);
    if(requirementBuild?.status==='checked_structural'&&!requirementBuildCurrent())issues.push({platform:'*',detail:'当前文案或素材已变化，通用要求需保存数据后重新检查；旧检查不自动沿用。'});
    box.replaceChildren();box.dataset.state=issues.length?'needs_attention':'ready';
    box.append(el('h2',issues.length?'本地发布准备：'+issues.length+' 项待补齐':'本地文案与封面预览已配齐'));
    box.append(el('p','页面修订 '+(data.revision||1)+'；实际平台投稿、封面审美及成片审核分别记录。'));
    if(issues.length){const list=el('ul');for(const row of issues)list.append(el('li',(labels[row.platform]||'内容包装')+'：'+row.detail));box.append(list);}
  }
  function coverShelf(parent,item){
    const shelf=el('section',undefined,'package-meta');shelf.append(el('h2','本次封面 · 比例与平台对应'),el('p','已核验的图片内置在此页；上传复制每张图下方的原文件路径。换图后需要重新核对。'));
    const grid=el('div',undefined,'cover-shelf');
    for(const cover of item.covers){
      const card=el('section');card.append(el('h3',cover.target_ratio||cover.label||cover.id));
      const img=el('img');bindCover(img,cover);img.alt=cover.label||cover.id;card.append(img);
      const platforms=Object.entries(item.platforms).filter(([k,p])=>p.cover_ids.includes(cover.id)).map(([k])=>labels[k]);
      card.append(el('p',platforms.length?'用于：'+platforms.join('、'):'备用比例 · 本次未分配上传槽位'));
      field(card,'复制此封面路径',cover.path,v=>{cover.path=v;},true,cover);grid.append(card);
    }
    shelf.append(grid);parent.append(shelf);
  }
  let dirty=false;
  const root=document.getElementById('desk');
  let message;
  let fieldNumber=0;
  let assetInputs=new WeakMap();
  const readyCopies=[];
  const coverBatches=[];
  const checkControls=new Map();
  function readyText(key,p){
    const mode=policy.platforms[key].copy_mode;
    return (mode==='title_body_tags'?[p.fields.title,p.fields.body,p.fields.tags]:[p.fields.body,p.fields.tags]).filter(Boolean).join('\n\n');
  }
  function readyCopy(parent,key,p){
    if(policy.platforms[key].copy_mode==='separate')return;
    const box=el('details',undefined,'ready-copy');box.append(el('summary','整段复制 · '+(policy.platforms[key].copy_mode==='title_body_tags'?'描述与话题':'正文与话题')));
    const input=el('textarea');input.readOnly=true;input.value=readyText(key,p);input.setAttribute('aria-label',(labels[key]||key)+' 整段发布文案');
    box.append(input,button('复制整段',()=>copy(readyText(key,p),input,box.lastChild)));parent.append(box);readyCopies.push({key,p,input});
  }
  function el(tag,text,cls) { const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e; }
  function notice(text) { if(message)message.textContent=text; }
  function invalidateDelivery() { const b=document.getElementById('delivery-status');if(b){b.dataset.state='draft';b.textContent='草稿预览 · 页面或数据已变更，请导出 JSON 并重新运行本地 video-delivery 检查；旧审核不能用于当前版本。本页不执行投稿，已有发布事实与当前编辑分别记录。';}const c=document.getElementById('cta-review-status');if(c){c.dataset.state='pending';c.textContent='CTA：页面已修改，请保存数据后重新核对选择、位置和实际文案；原落地记录不能自动沿用。';} }
  function changed() { invalidateChangedChecks(data,policy);for(const [check,control]of checkControls){control.select.value=check.status;control.reason.textContent=check.invalidated_reason||'';}for(const r of readyCopies)r.input.value=readyText(r.key,r.p);for(const batch of coverBatches)batch.input.value=batch.ids.map(id=>quoted(batch.item.covers.find(c=>c.id===id).path)).join(' ');dirty=true; invalidateDelivery();refreshPreparation();notice('有未保存修改：点击“保存当前页面”即可保留并继续使用。');let n=0;for(const i of data.items)for(const p of Object.values(i.platforms)){const row=document.querySelectorAll('.schedule .meta-table tr')[++n];if(row){row.cells[2].textContent=statuses[p.record.status];row.cells[3].textContent=p.record.planned_at||'待安排';row.cells[4].textContent=p.record.published_at||'尚未确认发布';}} }
  function button(label,fn) { const b=el('button',label); b.type='button'; b.addEventListener('click',fn); return b; }
  async function copy(value,source,b) {
    let copied=false;
    if(navigator.clipboard && window.isSecureContext)try{await navigator.clipboard.writeText(value);copied=true;}catch(_){}
    if(!copied){source.focus();source.select();try{copied=document.execCommand('copy');}catch(_){}}
    b.textContent=copied?'已复制':'请按 Ctrl+C'; setTimeout(()=>{b.textContent='复制';},1500);
  }
  function field(parent,label,value,update,path=false,asset=null) {
    const caption=el('label',label); parent.append(caption);
    const row=el('div',undefined,'copy-row'+(path?' path-row':label.includes('简介')||label.includes('正文')?' tall':''));
    const input=el('textarea'); input.id='field-'+(++fieldNumber);caption.htmlFor=input.id;input.value=path?quoted(value):value; input.spellcheck=false;
    if(asset){if(!assetInputs.has(asset))assetInputs.set(asset,[]);assetInputs.get(asset).push(input);}
    input.addEventListener('input',()=>{const previous=asset?.path;update(path?pathNorm(input.value):input.value);if(asset){delete geometry[previous];for(const other of assetInputs.get(asset))if(other!==input)other.value=quoted(asset.path);for(const [img,a]of imageBindings)if(a===asset){bindCover(img,asset);const link=img.closest('a');if(link)link.href=localUrl(asset.path);}for(const [video,a]of videoBindings)if(a===asset){video.src=localUrl(asset.path)||'';}}changed();});
    const b=button('复制',()=>copy(path?quoted(input.value):input.value,input,b)); row.append(input,b);parent.append(row);
    if(!path){const count=el('small',undefined,'field-count');const refresh=()=>{count.textContent=Array.from(input.value).length+' 字符（含标点与空格）'+(label.includes('标题')?' · 平台计数方式及上限待发布界面核验':'');};refresh();input.addEventListener('input',refresh);parent.append(count);}
  }
  // Guidance is an upload checklist, not a claim about current platform capabilities.
  const guidance={
    douyin:'检查推荐流与主页封面的裁切；话题粘贴后确认匹配项；合集和定时以当前账号可见入口为准。',
    xiaohongshu:'检查笔记封面和列表预览；正文中的话题需确认已识别；检查标题是否截断，合集入口以账号界面为准。',
    weixin_channels:'分别检查描述与短标题；封面在信息流中复核；话题需确认识别，定时与合集以当前账号入口为准。',
    kuaishou:'按上传页实际可选封面比例择一，不能把多张候选当成必须全部上传；核对话题及合集入口。',
    bilibili:'核对分区、转载/自制选项和标签；预览横版列表封面；合集与定时能力以当前账号界面为准。',
    weibo:'核对正文、话题和视频封面；检查公开范围；合集或定时未出现时按不适用或手动发布处理。'
  };
  function readable(parent,value){
    if(value===undefined||value===null||value===''){parent.append(el('p','待准备 / 待核验'));return;}
    if(Array.isArray(value)){const ul=el('ul');for(const v of value){const li=el('li');readable(li,v);ul.append(li);}parent.append(ul);}
    else if(typeof value==='object'){const dl=el('dl');for(const [k,v]of Object.entries(value)){dl.append(el('dt',fieldLabels[k]||({common_name:'通用合集名称',common_description:'通用合集简介',feature_status:'功能状态',fallback:'不可用时处理',strategy:'排期策略',measurement_windows:'观察窗口',timing_basis:'时间依据',source:'依据',story:'正片事实',outro:'片尾说明',do_not_infer:'本条禁止扩写',copy_policy:'文案边界'}[k])||k));const dd=el('dd');readable(dd,v);dl.append(dd);}parent.append(dl);}
    else parent.append(el('span',String(value)));
  }
  function overview(main){
    const boundary=el('section',undefined,'package-meta boundary');boundary.append(el('h2','内容依据与禁止扩写（不属于发布文案）'));readable(boundary,data.editorial_context||data.source_snapshot?.publication_boundary||'待补充内容依据；不得自行推断人物动机或扩写事实。');main.append(boundary);
    const collection=el('section',undefined,'package-meta collection-overview');collection.append(el('h2','合集（固定模块，可留空）'));readable(collection,data.collection||data.source_snapshot?.collection||'未设置合集。下方每个平台均保留可编辑的合集名称和简介；不需要合集时留空，按单条发布。');main.append(collection);
    const schedule=el('section',undefined,'package-meta schedule');schedule.append(el('h2','发布计划与观察窗口'),el('p','以下是人工计划，不代表已在平台提交定时。具体时间在各平台“发布记录”中填写，保存后保留。'));
    const table=el('table',undefined,'meta-table');const tr=el('tr');for(const s of ['视频','平台','状态','计划时间','实际发布'])tr.append(el('th',s));table.append(tr);
    for(const i of data.items)for(const [key,p]of Object.entries(i.platforms)){const row=el('tr');for(const v of [i.title,labels[key]||key,statuses[p.record.status],p.record.planned_at||'待安排',p.record.published_at||'尚未确认发布'])row.append(el('td',v));table.append(row);}const wrap=el('div',undefined,'table-wrap');wrap.append(table);schedule.append(wrap);
    readable(schedule,data.publishing_schedule||data.source_snapshot?.publishing_schedule||{strategy:'暂无账号数据支持最佳发布时间，先按可人工检查的时间安排；不自动定时。',measurement_windows:'24 小时检查上线、声音字幕、告警并作临时观察；正式 early 为发布后 48–72 小时，d7 为 156–180 小时（第 7 天附近）。24 小时数据为 provisional，不替代正式快照，不要求三轮完整复盘。',timing_basis:'待积累本人账号数据；先核对来源可信度、分母、窗口与可比性。小样本或低曝光可继续观察，不直接判断选题无效。'});main.append(schedule);
  }
  function platformChecks(parent,key,p){
    const item=data.items.find(i=>i.platforms[key]===p);
    const profile=policy.platforms[key], box=el('details',undefined,'platform-requirements');
    box.append(el('summary','上传时操作与核验记录（展开）'),el('p','封面：'+profile.cover_ratios.join('、')+'；'+(profile.cover_mode==='all'?'各比例分别准备':profile.cover_mode==='one'?'二选一':'规格待核准')),el('p','规则版本 '+policy.version+' · '+policy.source+'；历史限制须当日账号界面复核。'));
    box.append(el('p',guidance[key]||''));if(p.preparation)readable(box,p.preparation);
    for(const note of profile.historical_notes)box.append(el('p',note));
    p.platform_checks??={};
    for(const [name,text]of Object.entries({...policy.common_checks,...profile.checks})){
      const check=p.platform_checks[name]??={status:'pending',evidence:'',checked_at:''};
      const row=el('section');row.append(el('p',text));
      const select=el('select');select.setAttribute('aria-label',(labels[key]||key)+' '+name+' 核验状态');
      for(const [value,label]of Object.entries({pending:'待核验',confirmed:'已核验',...(policy.optional_checks.includes(name)?{not_applicable:'不适用'}:{})})){
        const option=el('option',label);option.value=value;select.append(option);
      }
      select.value=check.status;select.addEventListener('change',()=>{check.status=select.value;if(check.status!=='pending'){check.input_snapshot=platformCheckSnapshot(item,key,name,policy);delete check.invalidated_reason;}changed();});row.append(select);
      const reason=el('small',check.invalidated_reason||'');row.append(reason);checkControls.set(check,{select,reason});
      field(row,'核验依据 / 不适用原因',check.evidence,v=>{check.evidence=v;});
      field(row,'核验日期 YYYY-MM-DD',check.checked_at,v=>{check.checked_at=v;});box.append(row);
    }
    parent.append(box);
  }
  function coverMatrix(parent,item){
    const pk=item.cover_pk;if(!pk?.strategy_plan_ref)return;
    const section=el('section',undefined,'cover-delivery');section.append(el('h3','内容方案 × 比例衍生'),el('p','每行一个内容方案，每列一个目标比例。窄屏可在表格内横向滑动，或在下方切换单一比例比较。图片齐全不等于视觉审核通过；最终采用仍由你决定。'));
    const wrap=el('div',undefined,'table-wrap');wrap.tabIndex=0;wrap.setAttribute('aria-label','封面方案与比例矩阵，可横向滚动');
    const table=el('table',undefined,'meta-table cover-matrix'),thead=el('thead'),head=el('tr');
    for(const name of ['内容方案',...pk.required_ratios])head.append(el('th',name));thead.append(head);table.append(thead);
    const body=el('tbody');
    for(const c of pk.candidates){
      const row=el('tr'),label=el('th');label.scope='row';label.append(el('strong',c.angle||c.name),el('p',c.selection_reason||'选案依据待补充'));row.append(label);
      for(const ratio of pk.required_ratios){
        const cell=el('td'),cover=item.covers.find(a=>a.id===c.cover_by_ratio[ratio]),url=cover&&localUrl(cover.path);
        if(url){const link=el('a');link.href=url;link.target='_blank';link.rel='noopener';const img=el('img');bindCover(img,cover);img.alt=c.id+' '+ratio+' 比例衍生';img.loading='lazy';link.append(img);cell.append(link,el('small','视觉审核状态见回执'));}
        else cell.append(el('p','待制作','missing-ratio'));row.append(cell);
      }
      body.append(row);
    }
    table.append(body);wrap.append(table);section.append(wrap);
    if(pk.strategy_dispositions?.length){const detail=el('details',undefined,'strategy-dispositions');detail.append(el('summary','未采用、重复、不适用或缺输入的路线'));
      const names={not_applicable:'不适用',disabled_route:'本项目未启用',missing_inputs:'缺输入',redundant_treatment:'同类方案去重',not_selected:'未入选'};
      for(const d of pk.strategy_dispositions)detail.append(el('p',d.angle_id+' / '+d.strategy_id+' · '+(names[d.status]||d.status)+'：'+d.reason+(d.missing?.length?'（'+d.missing.join('、')+'）':'')));
      section.append(detail);
    }
    parent.append(section);
  }
  function coverPK(main,item){
    const pk=item.cover_pk;if(!pk?.candidates?.length){if(pk?.requested){const box=el('section',undefined,'package-meta cover-pk');box.append(el('h2','封面标题方案比较'),el('p','已要求多种方案；当前尚未配齐可比较的候选。同一设计的不同比例不算多个创意方案。'));main.append(box);}return;}
    const parallel=pk.selection_mode==='parallel_test';
    const box=el('section',undefined,'package-meta cover-pk');box.append(el('h2',parallel?'首发多封面测试 · 并列候选':'封面候选 PK · 多路线比较'),el('p',parallel?'首发计划同时测试 '+(pk.test_candidate_ids||[]).length+' 个方案；尚未产生测试胜者。每个方案的不同比例是同一方案的适配文件，不计作额外创意。平台原生测试入口和名额在投稿界面核对。':'编辑推荐 '+pk.recommended+'；'+(pk.selected?'当前人工选择 '+pk.selected:'尚未人工选择')+'。这是内容包装比较，不是线上点击率测试。缺少的比例标为待制作，不会硬裁或假装完成。选择只替换已完成的封面路径，不改发布标题或发布状态。'));
    const modeLabel=el('label','首发封面使用方式'),mode=el('select');mode.setAttribute('aria-label','首发封面使用方式');
    for(const [v,t]of [['single','单组选用'],['parallel_test','首发同时测试多组']]){const o=el('option',t);o.value=v;mode.append(o);}mode.value=parallel?'parallel_test':'single';
    mode.addEventListener('change',()=>{try{if(mode.value==='parallel_test')applyCoverTestSelection(item,pk.test_candidate_ids?.length>=2?pk.test_candidate_ids:pk.candidates.map(c=>c.id),policy);else{pk.selection_mode='single';pk.selected=null;for(const p of Object.values(item.platforms)){if(p.cover_test)p.cover_test.requested=false;p.cover_ids=[];}}changed();show();notice('已更新本地封面使用方式，请保存；未提交平台。');}catch(e){show();notice(e.message);}});modeLabel.append(mode);box.append(modeLabel);
    coverMatrix(box,item);
    const ratio=el('select');ratio.setAttribute('aria-label','封面 PK 比例');for(const r of (pk.required_ratios||['3:4','9:16','16:9','4:3'])){const o=el('option',r);o.value=r;ratio.append(o);}box.append(ratio);
    const grid=el('div',undefined,'pk-grid');
    const draw=()=>{grid.replaceChildren();for(const c of pk.candidates){const card=el('section',undefined,'pk-card');card.append(el('h3',c.id+' · '+c.name));const cover=item.covers.find(a=>a.id===c.cover_by_ratio[ratio.value]);if(cover){const a=el('a');a.href=localUrl(cover.path);a.target='_blank';a.rel='noopener';const img=el('img');bindCover(img,cover);img.alt=c.id+' '+ratio.value+' 封面';a.append(img);card.append(a);field(card,'此比例 PNG 路径',cover.path,v=>{cover.path=v;},true,cover);}
      if(!cover)card.append(el('p','此比例待制作 · 不自动裁切','missing-ratio'));
      if(c.route)card.append(el('p','制作路线：'+c.route));
      if(c.selection_reason)card.append(el('p','内容角度：'+c.angle),el('p','选择依据：'+c.selection_reason));
      if(c.color_selection)card.append(el('p','配色依据：'+c.color_selection.rationale,'color-rationale'));
      card.append(el('p','配套标题候选：'+c.title),el('p','点击理由：'+c.hypothesis),el('p','优势：'+c.strength),el('p','取舍：'+c.risk));
      if(parallel){const label=el('label'),check=el('input');check.type='checkbox';check.checked=(pk.test_candidate_ids||[]).includes(c.id);check.setAttribute('aria-label','首发测试 '+c.name);check.dataset.testCandidateId=c.id;check.addEventListener('change',()=>{try{const ids=pk.candidates.filter(x=>x.id===c.id?check.checked:(pk.test_candidate_ids||[]).includes(x.id)).map(x=>x.id);applyCoverTestSelection(item,ids,policy);changed();show();notice('已更新首发测试候选及各平台路径；没有选定胜者。请保存当前页面。');}catch(e){show();notice(e.message);}});label.append(check,document.createTextNode(' 参与首发封面测试'));card.append(label);}
      else card.append(button('选用 '+c.id+' 组封面',()=>{pk.selection_mode='single';pk.selected=c.id;pk.selected_at=new Date().toISOString();const missing=[];for(const [key,p]of Object.entries(item.platforms)){if(p.cover_test)p.cover_test.requested=false;const ratios=pk.platform_ratios?.[key]||['3:4'];const wanted=ratios.map(r=>c.cover_by_ratio[r]);if(wanted.some(id=>!id||!item.covers.some(a=>a.id===id))){p.cover_ids=[];missing.push(labels[key]||key);}else p.cover_ids=wanted;}dirty=true;show();notice('已选择 '+c.id+'；'+(missing.length?'缺少比例的平台未分配封面：'+missing.join('、')+'。':'已完成比例的路径已同步。')+'请保存当前页面。未更改发布标题，也未上传或发布。');}));grid.append(card);}};
    ratio.addEventListener('change',draw);draw();box.append(grid);main.append(box);
  }
  function mainCoverPanel(parent,item,key,p){
    const box=el('section',undefined,'main-cover-panel');box.append(el('h5','主封面 · 1张'),el('p','主封面单独上传，不占下方最多3张PK候选名额。'));
    const main=()=>item.covers.find(c=>c.id===p.cover_test.main_cover_id);
    const choose=el('select');choose.setAttribute('aria-label',labels[key]+' 主封面选用');
    const empty=el('option','主封面待指定');empty.value='';choose.append(empty);
    const candidates=new Set(p.cover_ids);
    for(const cover of item.covers){if(candidates.has(cover.id))continue;const dim=coverPreviews[cover.path]||cover;if(dim.width&&dim.height&&!policy.platforms[key].cover_ratios.some(r=>{const [a,b]=r.split(':').map(Number);return Math.abs(dim.width/dim.height/(a/b)-1)<=policy.ratio_tolerance;}))continue;const option=el('option',cover.label||cover.id);option.value=cover.id;choose.append(option);}
    const custom=el('option','填写其他本地图片路径');custom.value='__custom__';choose.append(custom);choose.value=p.cover_test.main_cover_id||'';
    const ensureCustom=()=>{const id=item.id+'-'+key+'-custom-main';let asset=item.covers.find(a=>a.id===id);if(!asset){asset={id,label:labels[key]+' 自选主封面',path:'',sha256:''};item.covers.push(asset);}p.cover_test.main_cover_id=id;return asset;};
    choose.addEventListener('change',()=>{if(choose.value==='__custom__')ensureCustom();else p.cover_test.main_cover_id=choose.value;changed();show();});box.append(choose);
    const img=el('img',undefined,'cover-preview main-cover-preview');img.alt=labels[key]+' 主封面';const refresh=()=>{const asset=main();img.hidden=!asset?.path;if(asset?.path)bindCover(img,asset);};refresh();box.append(img);
    field(box,labels[key]+' 主封面图片路径',main()?.path||'',value=>{const asset=main()||ensureCustom();if(asset.path!==value)asset.sha256='';asset.path=value;refresh();},true,main()||null);
    if(!main()?.path)box.append(el('p','尚未指定主封面；下方PK候选保持不变。','main-cover-pending'));parent.append(box);
  }
  function coverTestPanel(parent,item,key,p){
    const section=el('section',undefined,'platform-gates cover-test-plan');section.dataset.coverTestPlatform=key;
    let plan;try{plan=coverTestPlan(item,key,policy);}catch(e){section.append(el('p',e.message,'boundary'));parent.append(section);return;}
    const test=p.cover_test,native=plan.layout==='main_plus_candidates';
    section.append(el('h5',native?'封面 · 1张主封面＋'+plan.candidate_ids.length+'张PK候选':'首发封面测试 · '+plan.candidate_ids.length+' 个方案'));
    if(native){mainCoverPanel(section,item,key,p);section.append(el('p','以下是与主封面PK的候选，最多3张；支持自主上传或通过平台智能推荐添加。'));}
    else section.append(el('p','同一条视频、标题与文案，按本平台比例分别上传测试封面。'));
    const choices=el('div');for(const c of item.cover_pk.candidates.filter(c=>(item.cover_pk.test_candidate_ids||[]).includes(c.id))){const label=el('label'),check=el('input');check.type='checkbox';check.checked=plan.candidate_ids.includes(c.id);check.setAttribute('aria-label',(labels[key]||key)+' 测试 '+c.name);check.addEventListener('change',()=>{try{const ids=item.cover_pk.test_candidate_ids.filter(id=>id===c.id?check.checked:plan.candidate_ids.includes(id));applyCoverTestSelection(item,ids,policy,key);changed();show();notice('已更新本平台测试候选，请保存。');}catch(e){show();notice(e.message);}});label.append(check,document.createTextNode(' '+c.name+' '));choices.append(label);}section.append(choices);
    const cards=el('div',undefined,'platform-cover-grid');for(const variant of plan.variants){const group=el('section',undefined,'cover-test-variant');group.dataset.candidateId=variant.candidate_id;group.append(el('h5',variant.name));for(const [ratio,id]of Object.entries(variant.covers)){const cover=item.covers.find(a=>a.id===id),img=el('img',undefined,'cover-preview');img.alt=labels[key]+' '+variant.name+' '+ratio;bindCover(img,cover);group.append(img);field(group,(native?'PK候选 ':'测试候选 ')+variant.name+' · '+ratio,cover.path,v=>{cover.path=v;},true,cover);}cards.append(group);}section.append(cards);
    for(const ratio of plan.ratios){const ids=plan.variants.map(v=>v.covers[ratio]),input=el('textarea');input.readOnly=true;input.value=ids.map(id=>quoted(item.covers.find(c=>c.id===id).path)).join(' ');input.setAttribute('aria-label',(labels[key]||key)+' 同比例批量选择 '+ratio);const row=el('div',undefined,'copy-row');const b=button('复制这 '+ids.length+' 张路径',()=>copy(input.value,input,b));row.append(input,b);section.append(el('p',ratio+' · 同时选择 '+ids.length+' 张测试封面'),row);coverBatches.push({item,ids,input});}
    const detail=el('details');detail.append(el('summary','投稿时核对原生测试入口与名额'),el('p','这里记录本次账号界面的实际情况；本地素材齐全不代表平台已经开通测试。没有原生入口时保留待处理，不自动改成重复发帖或替作者选一张。'));
    const status=el('select');status.setAttribute('aria-label',(labels[key]||key)+' 原生封面测试入口');for(const [v,t]of [['pending','待投稿界面核对'],['confirmed','已核对原生入口可用'],['unavailable','当前账号未见可用入口']]){const o=el('option',t);o.value=v;status.append(o);}status.value=test.interface_status||'pending';status.addEventListener('change',()=>{test.interface_status=status.value;changed();});detail.append(status);
    field(detail,(labels[key]||key)+' 测试入口与数量依据',test.interface_evidence||'',v=>{test.interface_evidence=v;});field(detail,(labels[key]||key)+' 测试入口核对日期 YYYY-MM-DD',test.checked_at||'',v=>{test.checked_at=v;});
    const limitLabel=el('label',native?'PK候选名额（主封面另计；最多3张）':'当前账号允许的候选数（未核对留空）'),limit=el('input');limit.type='number';limit.min=String(policy.platforms[key].native_cover_test?.min_candidates||2);if(native)limit.max=String(plan.max_candidates);limit.step='1';limit.value=test.confirmed_candidate_limit??'';limit.setAttribute('aria-label',(labels[key]||key)+' 封面测试候选名额');limit.addEventListener('input',()=>{if(limit.value==='')delete test.confirmed_candidate_limit;else test.confirmed_candidate_limit=Number(limit.value);changed();});limitLabel.append(limit);detail.append(limitLabel);section.append(detail);parent.append(section);
  }
  function download(text,name,type) { const a=el('a');const u=URL.createObjectURL(new Blob([text],{type}));a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000); }
  function stamp() { return new Date().toISOString().replaceAll(':','-').replace(/\.\d+Z$/,'Z'); }
  function rememberPlatformPanels(){data.ui_state??={};data.ui_state.platform_panels??={};for(const panel of root.querySelectorAll('details.platform-card'))data.ui_state.platform_panels[panel.dataset.panelKey]=panel.open;}
  function setPlatformPanels(open){for(const panel of root.querySelectorAll('details.platform-card'))panel.open=open;rememberPlatformPanels();}
  function snapshot() { rememberPlatformPanels();const out=JSON.parse(JSON.stringify(data));out.revision=(Number(out.revision)||0)+1;out.modified_at=new Date().toISOString();return out; }
  function saveHtml() {
    invalidateDelivery();
    const out=snapshot();const json=serialized(out), clone=document.documentElement.cloneNode(true);
    clone.querySelector('#desk-data').textContent=json;clone.querySelector('#desk').replaceChildren();
    download('<!doctype html>\n'+clone.outerHTML, '发布辅助页-'+stamp()+'.html','text/html;charset=utf-8');
    // Keep item/asset references used by existing input listeners after saving.
    data.revision=out.revision;data.modified_at=out.modified_at;
    dirty=false;notice('已下载包含全部修改的页面；下次打开下载的新版即可继续。');
  }
  function recordPanel(parent,p) {
    const d=el('details',undefined,'record');d.append(el('summary','发布记录 · '+statuses[p.record.status]));
    const select=el('select');for(const [value,label]of Object.entries(statuses)){const o=el('option',label);o.value=value;select.append(o);}select.value=p.record.status;
    select.addEventListener('change',()=>{p.record.status=select.value;d.querySelector('summary').textContent='发布记录 · '+statuses[select.value];changed();});d.append(select);
    for(const [key,label]of Object.entries({account:'账号备注',planned_at:'计划日期 / 时间',scheduled_for:'平台已设置的定时日期 / 时间',published_at:'实际上线时间（含时区，如 2026-09-26T20:30:00+08:00）',url:'作品链接',notes:'备注 / 证据位置'})){
      const l=el('label',label),input=el('input');input.value=p.record[key]||'';input.addEventListener('input',()=>{p.record[key]=input.value;changed();});l.append(input);d.append(l);
    }
    d.append(el('p','只填写已知时间。定时成功保留为“已提交定时”；作品实际上线后再记录“已发布”。'));parent.append(d);
  }
  function show() {
    if(invalidateChangedChecks(data,policy))dirty=true;
    checkControls.clear();
    readyCopies.length=0;
    coverBatches.length=0;
    imageBindings.clear();
    videoBindings.clear();
    for(const key of Object.keys(geometry))delete geometry[key];
    if(dirty)invalidateDelivery();
    fieldNumber=0;assetInputs=new WeakMap();
    const pageTitle=data.title.endsWith('发布辅助页')?data.title:data.title+' · 发布辅助页';
    root.replaceChildren();document.title=pageTitle;
    const head=el('header',undefined,'top');head.append(el('h1',pageTitle));
    const toolbar=el('div',undefined,'toolbar');toolbar.append(button('全部收起',()=>setPlatformPanels(false)),button('全部展开',()=>setPlatformPanels(true)),button('保存当前页面',saveHtml),button('导出发布数据 JSON',()=>{download(serialized(snapshot()),'发布数据-'+stamp()+'.json','application/json');notice('已导出 JSON；可载入此页或用本地工具重新生成页面。');}));
    const importInput=el('input');importInput.type='file';importInput.accept='.json,application/json';importInput.hidden=true;
    importInput.addEventListener('change',async()=>{try{if(!importInput.files[0])return;if(importInput.files[0].size>8*1024*1024)throw Error('文件超过 8 MB');const incoming=validate(JSON.parse(await importInput.files[0].text()));if(dirty&&!window.confirm('当前修改尚未保存，是否载入另一份发布数据？'))return;data=incoming;dirty=false;invalidateDelivery();show();notice('已载入发布数据');}catch(e){notice(e.message);}});
    toolbar.append(button('载入发布数据 JSON',()=>importInput.click()),importInput,button('刷新素材预览',()=>show()));head.append(toolbar);
    message=el('div',dirty?'有未保存修改':'修改后保存当前页面，下次直接打开新版。','message');message.setAttribute('role','status');head.append(message);
    const nav=el('nav',undefined,'nav');data.items.forEach((i,n)=>{const a=el('a',String(n+1)+' · '+i.title);a.href='#item-'+n;nav.append(a);});if(data.items.length>1)head.append(nav);root.append(head);
    const main=el('main'),advanced=el('details',undefined,'package-meta advanced-tools');advanced.append(el('summary','准备检查与素材工具（可选）'));
    const preparation=el('section');preparation.id='local-preparation';preparation.setAttribute('aria-live','polite');advanced.append(preparation);
    const migration=el('details',undefined,'package-meta migration');migration.append(el('summary','素材搬家：批量更换根目录'));
    const old=el('input'),next=el('input');old.placeholder='旧根目录，如 D:\\项目素材';next.placeholder='新根目录，如 E:\\归档素材';
    migration.append(el('p','仅替换匹配目录内的素材路径；保留素材哈希。搬家后可用本地工具 check 核验文件。'),old,next,
      button('替换路径',()=>{try{const count=remap(data,old.value,next.value);if(count){dirty=true;show();}notice('已替换 '+count+' 个素材路径');}catch(e){notice(e.message);}}));advanced.append(migration);
    data.items.forEach((item,index)=>{
      const section=el('article',undefined,'item');section.id='item-'+index;section.append(el('h2',item.title));
      const platforms=el('div',undefined,'platforms');
      for(const [position,[key,p]]of Object.entries(item.platforms).entries()){
        const card=el('details',undefined,'platform-card'),h=el('summary',undefined,'platform-head');
        const panelKey=item.id+'::'+key;card.dataset.panelKey=panelKey;card.dataset.platform=key;
        card.open=data.ui_state?.platform_panels?.[panelKey]??position===0;
        h.append(el('h4',labels[key]||key),el('small','视频 · 封面 · 标题与文案'),el('span','展开 / 收起','panel-action'));card.append(h);
        card.addEventListener('toggle',()=>{if(root.contains(card)){data.ui_state??={};data.ui_state.platform_panels??={};data.ui_state.platform_panels[panelKey]=card.open;}});
        const stack=el('div',undefined,'copy-stack');
        const media=el('section',undefined,'platform-video');media.append(el('h5','视频文件'));
        field(media,labels[key]+' 成片文件',item.video.path,v=>{item.video.path=v;},true,item.video);
        const preview=el('details',undefined,'media-preview');preview.append(el('summary','预览本平台成片'));const video=el('video');video.controls=true;video.preload='none';const videoURL=localUrl(item.video.path);if(videoURL)video.src=videoURL;videoBindings.set(video,item.video);preview.append(video);media.append(preview);stack.append(media);
        const limits=policy.platforms[key].field_limits||{};
        if(Object.keys(limits).length)stack.append(el('p','已记录的适配基线：'+Object.entries(limits).map(([k,v])=>(fieldLabels[k]||k)+' ≤ '+v+' 字').join('；')+'。本地按Unicode码点计数，平台实际计数以界面为准。'));
        if(p.cover_test?.requested)coverTestPanel(stack,item,key,p);
        else{if(!p.cover_ids.length)stack.append(el('p','封面待准备，尚未分配素材。','boundary'));
          for(const id of p.cover_ids){const cover=item.covers.find(c=>c.id===id),url=localUrl(cover.path);if(url){const a=el('a');a.href=url;a.target='_blank';a.rel='noopener';const img=el('img',undefined,'cover-preview');bindCover(img,cover);img.alt=cover.label||id;img.loading='lazy';a.append(img);stack.append(a);}}
          for(const id of p.cover_ids){const cover=item.covers.find(c=>c.id===id);field(stack,'本平台封面 · '+(cover.label||id),cover.path,v=>{cover.path=v;},true,cover);}}
        if(policy.platforms[key].separate_title===false && p.fields.title)stack.append(el('p','旧数据含普通标题：本平台不适用，请修正后重新生成。','boundary'));
        for(const [name,value]of Object.entries(p.fields))if(!['collection_name','collection_description','pinned_comment'].includes(name)&&!(policy.platforms[key].separate_title===false&&name==='title'))field(stack,key==='kuaishou'&&name==='body'?'作品描述 / 文案':fieldLabels[name]||name,value,v=>{p.fields[name]=v;});
        readyCopy(stack,key,p);
        const collectionFields=el('details',undefined,'collection-fields');collectionFields.append(el('summary','合集与置顶评论（可选）'));
        for(const name of ['collection_name','collection_description'])field(collectionFields,fieldLabels[name],p.fields[name]||'',v=>{p.fields[name]=v;});stack.append(collectionFields);
        if(Object.hasOwn(p.fields,'pinned_comment'))field(collectionFields,fieldLabels.pinned_comment,p.fields.pinned_comment,v=>{p.fields.pinned_comment=v;});
        const optionalFields=key==='weixin_channels'?['short_title','pinned_comment']:['pinned_comment'];
        if(optionalFields.some(name=>!Object.hasOwn(p.fields,name)))collectionFields.append(button(key==='weixin_channels'?'添加短标题 / 置顶评论':'添加置顶评论',()=>{for(const k of optionalFields)if(!Object.hasOwn(p.fields,k))p.fields[k]='';changed();show();}));
        stack.append(el('p','话题粘贴后按平台提示选择。','topic-note'));platformChecks(stack,key,p);recordPanel(stack,p);card.append(stack);platforms.append(card);
      }
      section.append(platforms);main.append(section);
    });
    if(!data.rules?.length)advanced.append(el('p','尚未登记当前账号规则核验结果。'));
    if(data.rules?.length){const rules=el('details',undefined,'package-meta');rules.append(el('summary','平台规则与核验来源'));
      for(const rule of data.rules){rules.append(el('h3',labels[rule.platform]||rule.platform),el('p','核验日期：'+(rule.checked_at||'未提供')+' · '+(rule.scope||'待复核')),el('p','来源：'+(rule.source||'未提供')));const detail=el('details');detail.append(el('summary','查看历史规则（本页不据此自动裁切或定时）'),el('pre',JSON.stringify(rule.values,null,2)));rules.append(detail);}advanced.append(rules);}
    main.append(advanced);
    root.append(main,el('footer','复制文案与上传路径后，在平台完成上传和发布。发布记录随保存的页面和 JSON 一起保留。'));
    // Archived ratio variants still participate in local checks without a visible global gallery.
    for(const item of data.items)for(const cover of item.covers)if(cover.path&&![...imageBindings.values()].some(a=>a===cover)){const probe=el('img');bindCover(probe,cover);}
    refreshPreparation();
  }
  show();
})();
