# 可复用的多路线封面工作台

更新：2026-09-26，Codex（GPT-6 Astra）。属于现有视频封面子流程，不是新 workflow，也不是新渲染器。

## 入口

2026-09-26 内容选案补强（Codex）：新项目默认走 [内容分析 → 方案选择 → 视觉差异审核 → 全比例交付](content-driven-covers.md)。不是把所有路线固定各跑一张；先以内容证据选互补方案，缺输入、重复、不适用分别解释。

2026-09-26 通用母版补充（Codex）：新增 `design-recipes / design-init / design-build`，详见 [通用封面设计](generic-cover-design.md)。适用于不同项目和账号，包含非生成式图层、7 个起始构图配方和可编辑 JSON 母版；输出仍接本页既有 compile/render/collect，不安装第二套编辑器。

```powershell
python scripts/self_media_agent.py covers
python scripts/cover_workbench.py catalog
python scripts/cover_workbench.py methods
python scripts/cover_workbench.py styles --query "插画"
python scripts/cover_workbench.py styles --source bitblanket-cover-prompt-forge --query "竖版"
python scripts/cover_workbench.py doctor
python scripts/cover_workbench.py init --project-id new-video --title "本条视频" --output <private-run>/brief.json
python scripts/cover_workbench.py plan --input <private-run>/brief.json --output <private-run>/route-plan.json
```

`doctor` 只检查文件和可发现的程序，不会启动服务、下载模型或把“文件在”写成运行成功。首次空 brief 故意不能进入 plan：Agent 要先填本项目真实内容，而不是拿上一条改标题。

## 样片和终稿分别验收

2026-11-18，Codex。本轮根据作者反馈，把画幅数量和成图文字核对接入封面校验。成片的角标和平台发布申明继续使用各自的检查入口。

1. `init` 默认生成 `cover_stage=preview`。每个风格出 1–2 个画幅，用现有比较页看构图、手机小图、脸和道具，以及所有可见文字。`review-check` 通过后只记为 `preview_reviewed`。
2. 作者定风格后，在新 brief 写 `cover_stage=final`，把 `requested_ratios` 设为 `3:4`、`9:16`、`4:3`、`16:9`。`style_choice` 记 `candidate_id`、`user_confirmation`（作者原话）和已核对的 `preview_package_ref`（绝对路径和 SHA-256）。`strategy-init` 在这阶段只选作者指定的候选。每个画幅独立重排。少一个、换成别的风格或重复用一个画幅都不能通过终稿检查。
3. `approved_cover_labels` 默认为空。标题以当前封面文案为准。确实需要放来源说明、道具上的文字、账号署名或 AI 字样时，逐条填写「确切用词 → 本期用途」。核对当前选择和实际素材，发现错误、重复或多余的字先修。素材元数据中的账号、来源、生成过程不进入封面文字清单。封面标题本身讨论 AI 时，照常保留题目里的 AI。另有平台或项目要求的披露应先确认适用位置与字样。
4. `compile` 和 `collect` 检查写入合成计划的文字。`review-init` 在每张已渲染 PNG 的记录里提供 `visible_text`。Agent 要看大图和手机小图，把实际看到的文字抄进记录，包含生成图、账单或截图里烘焙的字。标题跨行时合成一条。`review-check` 对照本期批准文字，拒绝多余字样、漏题和图片换版。记录人工或 Agent 逐张核对的结果，不宣称自动 OCR。

本地 HTML 或其他现有渲染出口的 PNG 使用同一套 `package-check`。输入为 `self-media.cover-package-review.v1`，填写 `project_id`、`stage`、`reviewer` 和 `candidates`。每个候选记录 `id`、`style_id`、`headline`、`approved_labels` 和以比例为键的 `images`。每张图填 `image_ref={path,sha256}`、`visual_passed=true` 和实际看到的 `visible_text`。预览以各风格 1–2 张建立记录；终稿只保留一个候选，加上步骤 2 的 `style_choice`。`style_id` 同一风格跨比例保持一致；工作台使用候选的显式 `style_id`，或沿用 `design_method`/`route`。引用的预览包会重新核对。

```powershell
python scripts/cover_workbench.py package-check --input <private-run>/cover-final-review.json --output <private-run>/cover-final-check.json
```

只有当前四张成图与选定风格都通过才得到 `final_cover_package_complete`。旧封面数据仍可读取，历史核对结果不能充当新的四画幅终稿回执。封面验收回执不授予发布权限。

## 历史 Skill 复用入口（2026-09-26 补全）

`methods` 读取 `config/cover-methods.v1.json`，逐次检查本地文件并计算哈希，区分已安装技能、研究副本和仅历史提及。已登记 20 项，运行时查询实际本地命中数。详见 [历史技能补查](cover-method-inventory-2026-09-26.md)。`poses --query "正面"` 可查已选姿势的来源和视角元数据；目录原图另行目视核对和授权。

brief 可填 `content_kind`：`generic/family/tutorial/product/article/case/lucas_brand`；不填兼容旧计划为 generic。`method_ids` 可明确增加方法 ID；拼错会报错，超出默认适用场景会警告，源文件缺失会标为 `blocked_missing_source`，不自动替代路线。

`plan` 新增 `method_plan`：按内容与所选路线列出参考方法、精确源码路径/哈希、采用理由、所需设计产物和不采纳边界。**这是设计任务，不是设计完成证据，也不是源 Skill 的自动调用。** Agent 按需完整读取选用的 SKILL 和相关参考，再将交付字段落实到候选设计卡；不得一口气执行所有第三方工作流。新方法索引不改旧 visual plan 或渲染合同。

`styles --query "插画"` / `styles --template-id <实际ID>` 跨来源检索 GPT Image、atutun、gbro、Baoyu 和 BitBlanket。可用 `--source <方法 ID>` 限定来源。新增条目保留来源文件、哈希和行号，源文件缺失的条目不出现在匹配中；GPT Image 的原有案例字段继续可用。模板、构图、质感和设计手法分别标明类型。

## Agent 操作配方（每个新项目复用）

1. 读当前用户要求、审核记录、现有标题封面计划；冻结 `promise/facts/forbidden_claims`。不要把旁白、笑话、比喻变成新事实。
2. 查素材，图像先看再设计。每个 asset 填 `id/kind/artifact={path,sha256}/local_use_approved/privacy_reviewed`。kind 用 `photo/evidence/reviewed_cutout/generated_decoration`。文件必须是当前私有目录的绝对路径。原件不改，照片上传默认不允许。
3. 用 `strategy-init / strategy-plan` 绑定内容观察和表达角度。默认 `all_applicable`：每个有内容依据且输入齐全的不同构图族保留一个代表，不预设三套；按当前策略检查角度和构图族覆盖，不足不凑数。`routes` 可列全部试用，`plan` 返回各路缺项。抠图需透明且复核过的衍生图；没有则保持缺输入。
4. 为每个候选写设计卡：`id/name/route/hypothesis/composition/strength/risk`。`composition` 写“何种真实瞬间、视线、主次、留白/景深/文字关系”，不是仅填风格名。检查是否只换了背景色。方法参考来自 [研究报告](cover-open-source-research-2026-09-26.md)，不是多个外部 SKILL 同时强制执行。
5. 确定性路线写现有 `lucas.case_cover_visual_plan.v1`（schema 名称为兼容保留，不代表给家庭视频套保险品牌），绑定真实 account、已审核 title plan、safe layout 和素材哈希。通用母版没有默认青红色板；按内容/情绪/素材选择 `color_selection`，同方案各比例沿用该方案颜色，不同方案可分别选色。品牌色仅在当前账号和内容明确适用时绑定引用；详见 [配色选择与账号边界](generic-cover-design.md#配色选择与账号边界)。手工可编辑 visual-plan 也在候选与计划同时附上选色对象，compile/collect 核对实际图层。摄影负空间可用 `local.photo_editorial_cover.v1`，该旧协议不声称已执行逐图层配色核对。不要把家庭账号假装成“灿哥精进”以绕过某个 recipe 的适用边界。其他既有 recipe 仅在适用账户/素材下使用。
6. AI 是可选 Agent 步骤。brief 中 `ai_authorization={allowed:true,user_quote:原始明确授权}` 只记录范围。完整提示词先存文件，Agent 按授权用原生工具。无参考图概念生成走 `ai-illustration`，真人原图与 AI 非人物装饰走 `hybrid`，有参考图的生成走 `ai-reference`。
7. 比例独立排版。每个 profile 都有 layout 与 safe zone；不要为了补齐比例缩小标题、切脸或硬裁已经排好文字的海报。底稿不适合横版就换构图或明确缺输入。
8. `compile` → 已有 Still 出图 → `collect` → `review-init / review-check`。在每个比例的输出图上看中文字、眼睛、嘴、手、主视觉、字幕残留、脸部遮挡，再按 270px 竖版/360px 横版看小图并逐对检查差异。图片齐全不等于审核完成，更不产生人类通过。
9. 在已有发布辅助页选候选。缺失比例的平台封面为空并提示；不会写 undefined 路径或沿用上一组。保留合集字段。没有人工选择前不把编辑推荐变成人工采用。

## Build 合同

`self-media.cover-build.v1`：

```json
{
  "schema":"self-media.cover-build.v1",
  "project_id":"new-video",
  "route_plan_ref":{"path":"<private-run>/route-plan.json","sha256":"文件实际哈希"},
  "strategy_plan_ref":{"path":"<private-run>/strategy-plan.json","sha256":"文件实际哈希"},
  "safe_layout_ref":{"path":"<private-run>/safe-layout.json","sha256":"文件实际哈希"},
  "packaging_ref":{"path":"<private-run>/packaging.json","sha256":"文件实际哈希"},
  "candidates":[{
    "id":"real-memory","name":"真实瞬间","route":"photo-editorial",
    "hypothesis":"当前项目的真实点击理由","composition":"具体素材与空间关系",
    "strength":"为什么适合这条内容","risk":"会丢失什么信息",
    "visual_plan_ref":{"path":"<private-run>/real-memory.json","sha256":"文件实际哈希"}
  }],
  "platform_ratios":{"xiaohongshu":["3:4"],"bilibili":["16:9","4:3"]}
}
```

上述只是字段示例，不可执行，不能把“文件实际哈希”当值。`platform_ratios` 是当前项目的人工准备需求，不是工具宣称的平台强制规则。

原生 AI 候选填写 `prompt_ref`、`reference_uploads:[]` 和 `outputs:[{ratio,artifact:{path,sha256}}]`。导入时检查实际 PNG、分辨率、比例和哈希。工作台只导入已完成的输出，保留 Agent 的执行来源。

`ai-reference` 在 brief 的 assets 为每份参考填写 `kind: generation_reference`、`local_use_approved: true`、`privacy_reviewed: true`、`generation_use_approved: true` 及 `reference_role`（identity、character、object、pose、costume、composition、style、material 或 lighting）。真人 identity 额外记录 `subject_scope`（self 或 authorized_other）、`consent_quote` 和 `use_boundary`，授权原话留在私有 brief。参考文件必须能解码。可记录 `source`、`pinned_commit`、`reference_id`、`angle` 和 `use_boundary`。选案绑定参考 ID，收图总回执、候选数据及复核输入展示其哈希、角色和适用范围。`reference_uploads` 在该路线可省略，沿用上传字段时须为空。参考资料传给模型须在实际授权范围内。

混合选案的 `design-init` 将本地可编辑配方放在 `candidates`，原生 AI 或另行制作的 hybrid 放在 `external_candidates`。前者填写版式，后者补齐提示词和已出图文件或 hybrid 视觉计划。两组通过 `design-build` 合成同一 build；`compile` 只出本地 Still，`collect` 将两组收在同一候选包中。

## 执行

```powershell
python scripts/cover_workbench.py compile --input <private-run>/build.json --output <private-run>/build-01 --runtime-source <已登记Remotion源码> --skill-root <已登记Remotion技能源码>
python scripts/cover_workbench.py render --input <private-run>/build-01/remotion/remotion-project-manifest.json --runtime-source <同一源码> --browser <已验证浏览器>
python scripts/cover_workbench.py collect --input <private-run>/build.json --receipt <private-run>/build-01/remotion/remotion-cover-run-receipt.json --desk <private-run>/publication-data.json --item-id main --output <private-run>/review-01
```

编译生成同一正式 Remotion 项目。已有受控运行时依赖须按原 renderer 流程安装/复用，工具不隐式 npm install。不要绕过 renderer 的运行时版本、资源检查或回执。编译不是出图；出图不是视觉审核。

正式发布包在 `runtime_dependencies/cover-mvp` 固定封面后端的源码与入口，纳入发布清单哈希。默认封面入口使用该版本；发布前在同一包上运行封面回归。

`collect` 校验既有正式回执、源 manifest、精确 visual plan、真实 PNG，合并进既有发布包，保存旧候选历史、文案和发布记录；输出 JSON、HTML 和汇总回执。所有输出只新建，不覆盖已有版本。发布仍全部人工。

## 支持与不支持

现在可执行：本地确定性 visual plan 编译/出图；无上传的 AI 图接入；多路线同页比较；缺失比例检查；哈希绑定；现有发布包无损合并。Agent 仍负责选帧与设计，不是“一句话自动生成最佳封面”的承诺。

目前不做：自动云端登录/收费、人物图上传、模型安装、伪造人类批准、自动预测 CTR、自动发布。rembg、Polotno 等后端是否可用必须另做真实 doctor/试跑，不能因为出现在研究表就显示为已集成。

本轮实际执行范围及回执见 [2026-09-26 验收记录](cover-workbench-verification-2026-09-26.md)。
