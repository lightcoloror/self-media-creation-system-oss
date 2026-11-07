/* Local HTML-canvas export adapter, following the proton desk's locked-canvas
   screenshot workflow. Uses an isolated offline browser, never a logged-in tab. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
async function main(){
 throw Error('Deprecated experimental outlet: use docs/视频封面多策略多比例正式路由-2026-08-25.md and the existing Remotion Still route. Historical outputs are not approved.');
 const [modulePath,planPath,out]=process.argv.slice(2);if(!out)throw Error('Usage: node publication_cover_export.cjs PLAYWRIGHT PLAN NEW_OUTPUT_DIRECTORY');
 const planBytes=fs.readFileSync(planPath),plan=JSON.parse(planBytes),policyBytes=fs.readFileSync(plan.typography_policy),policy=JSON.parse(policyBytes);
 if(fs.existsSync(out))throw Error('Output exists: refusing overwrite');
 if(plan.candidate_only!==true||plan.manual_publish_only!==true||plan.candidates.length!==3)throw Error('Invalid candidate plan');
 const source=fs.readFileSync(plan.source.path);if(hash(source)!==plan.source.sha256)throw Error('Source hash drift');
 fs.mkdirSync(out,{recursive:true});
 const {chromium}=require(modulePath),browser=await chromium.launch({headless:true});const outputs=[];
 try{
  const page=await browser.newPage({deviceScaleFactor:1});await page.route(/^https?:/,r=>r.abort());
  for(const c of plan.candidates)for(const layout of plan.layouts){
   const profile=policy.profiles[layout.profile],{width:w,height:h}=profile.viewport;
   const min=profile.roles.overlay.min_font_px,font=layout.font_px;
   if(font<min)throw Error('Typography below policy');
   const [px,py,pw,ph,iw,ix,iy]=layout.photo;
   const [tx,ty,tw]=layout.text;
   const lines=c.lines.map(l=>`<div data-role="overlay" class="line">${esc(l)}</div>`).join('');
   const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
   *{box-sizing:border-box}body{margin:0;background:#f7f8f5;font-family:"Noto Sans SC","Microsoft YaHei",sans-serif;color:#243238}.canvas{position:relative;width:${w}px;height:${h}px;overflow:hidden;background:#f7f8f5}.photo{position:absolute;left:${px}px;top:${py}px;width:${pw}px;height:${ph}px;overflow:hidden}.photo img{position:absolute;width:${iw}px;max-width:none;left:${ix}px;top:${iy}px}.copy{position:absolute;left:${tx}px;top:${ty}px;width:${tw}px}.tag{font-size:${profile.roles.structure.min_font_px}px;font-weight:500;line-height:1.3;margin-bottom:${layout.gap}px;color:#59686b}.line{font-size:${font}px;line-height:1.16;font-weight:700;letter-spacing:-.035em;white-space:nowrap}.line:last-child{color:#245b5a}.note{font-size:${profile.roles.promise.min_font_px}px;line-height:1.3;margin-top:${layout.gap}px;color:#59686b}.brand{position:absolute;left:${tx}px;bottom:${layout.footer}px;font-size:${profile.roles.tag.min_font_px}px;color:#59686b;letter-spacing:.12em}
   </style><div class="canvas"><div class="photo"><img src="data:image/jpeg;base64,${source.toString('base64')}"></div><div class="copy"><div data-role="structure" class="tag">${esc(c.kicker)}</div>${lines}<div data-role="promise" class="note">${esc(c.note)}</div></div><div data-role="tag" class="brand">爸比抱抱 · 亲子日常</div></div></html>`;
   await page.setViewportSize({width:w,height:h});await page.setContent(html);await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
   const qa=await page.evaluate(({policy,profile,photo,protectedBox})=>{
    const canvas=document.querySelector('.canvas').getBoundingClientRect();const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};};
    const nodes=[...document.querySelectorAll('[data-role]')].map(e=>{const r=rect(e);return {role:e.dataset.role,text:e.textContent,font:parseFloat(getComputedStyle(e).fontSize),...r,overflow:e.scrollWidth>e.clientWidth+1};});
    const [px,py,pw,ph,iw,ix,iy]=photo;const scale=iw/1080;const [sx,sy,sw,sh]=protectedBox;const face={x:px+ix+sx*scale,y:py+iy+sy*scale,w:sw*scale,h:sh*scale};
    const intersect=(a,b)=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
    const errors=[];for(const n of nodes){if(n.font<policy.profiles[profile].roles[n.role].min_font_px||n.overflow||n.x<0||n.y<0||n.x+n.w>canvas.width+1||n.y+n.h>canvas.height+1)errors.push('type_or_bounds:'+n.text);if(intersect(n,face))errors.push('face_collision:'+n.text);}
    if(face.x<px||face.y<py||face.x+face.w>px+pw||face.y+face.h>py+ph)errors.push('face_crop');
    for(let a=0;a<nodes.length;a++)for(let b=a+1;b<nodes.length;b++)if(intersect(nodes[a],nodes[b]))errors.push('text_collision');
    return {nodes,face,errors,images_loaded:[...document.images].every(i=>i.naturalWidth>0)};
   },{policy,profile:layout.profile,photo:layout.photo,protectedBox:plan.source.protected_face_box});
   if(qa.errors.length||!qa.images_loaded)throw Error(JSON.stringify({candidate:c.id,profile:layout.profile,qa}));
   const file=path.join(out,`${c.id}_${layout.ratio.replace(':','x')}.png`);await page.screenshot({path:file});
   const bytes=fs.readFileSync(file);if(bytes.readUInt32BE(16)!==w||bytes.readUInt32BE(20)!==h)throw Error('PNG dimensions');
   outputs.push({candidate_id:c.id,ratio:layout.ratio,profile:layout.profile,width:w,height:h,path:path.resolve(file),sha256:hash(bytes),qa});
  }
 }finally{await browser.close();}
 const receipt={schema_version:'publication-cover-export.v1',created_at:new Date().toISOString(),plan_sha256:hash(planBytes),policy_sha256:hash(policyBytes),source_sha256:hash(source),outputs,candidate_only:true,manual_publish_only:true,human_visual_review_required:true,published:false};
 fs.writeFileSync(path.join(out,'cover-export-receipt.json'),JSON.stringify(receipt,null,2),{flag:'wx'});
 console.log(JSON.stringify({status:'candidate_rendered',count:outputs.length,output:path.resolve(out)}));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
