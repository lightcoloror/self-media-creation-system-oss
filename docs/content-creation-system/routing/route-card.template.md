# 内容路由卡模板

> 这是内容路由卡的唯一主模板；每条内容只维护一张，项目内同名文件仅保留入口。
> Agent 先复用现有任务说明、内容对象和已确认路由，只补缺失或冲突的信息；不让作者重复回答同一个受众、任务或目标问题。
> 按所选 recipe 和适用条件填写本卡，不是把下列所有区块都填一遍。未知项写“待核”；不适用项按路由要求记录理由，不靠 AI 补齐。
> 发布后另建 `publication-event` 与 `performance-snapshot`，不要回头覆盖本卡。

枚举与适用规则以 [中央任务路由器](./task-router.json) 为准；本卡只承载该内容的选择与引用，不新建流程或事实源。受众和读者任务可引用既有 `intent.audience`、`intent.desired_action`、`design_context.communication_job` 等语义一致的信息；发现冲突先核对，不另造一套答案。

交接接口要求的 `evidence_risk`、`voice_visual_route` 分别从第 2 节风险与边界、第 3 节声纹与视觉选择整理；仍须按接口提供必需字段，不再向作者重复询问同一信息。

## 1. 任务定义

2026-10-09 18:50:58 +08:00｜Codex（GPT-6）：以下策略、编辑与复盘说明复用本卡和既有证据，不增加全篇必填表或新的 recipe。

```yaml
route_id: route-YYYYMMDD-short-name
task_type: topic-selection | research | planning | interview | draft | rewrite | title | script | visual-brief | review | retrospective | account-diagnosis
account_ip: cange-risk-diagnosis | cange-growth | dual-account-shared | personal-wechat-moments
content_job: travel-experience | story | mechanism-explanation | tool-or-checklist | case-review | trust-building | collaborator-recruitment | product-demo | question-answer | opinion | business-conversion | account-diagnosis
creation_route: story | travel-experience | expository | technical-rework
creation_route_decision_ref: 本次路由判断；目标、素材或用户约束变化后重新评估
creation_route_context_ref: 本次上下文；含来源、理由与 revision_id
vlog_style: chronological-diary | activity-highlights | practical-guide | experience-review | atmospheric-montage | observational | null
primary_audience: 谁；处于什么情境
primary_goal: experience | personal-memory | entertainment | travel-decision | relationship-touch | search-discovery | understanding | save-for-later | trust | discussion | consultation | collaboration | conversion | learning
structure_route: direct-answer | decision-reframe | scenario-branch | gap-diagnosis | tradeoff-comparison | case-review | mechanism-explanation | tool-action | boundary-map | story-arc | opinion-argument | custom
structure_route_note: 为什么这条路线最符合本篇读者任务；custom 时写展开顺序
format: moments-short-text | graphic-note | short-video-narration | demo-video | interview-video | long-video | live | longform-article
platform: wechat-moments | wechat-groups-wecom | xiaohongshu | wechat-video | douyin | bilibili | wechat-article | zhihu | kuaishou | toutiao | weibo | youtube
```

规则：`primary_goal` 只能选一个。若同时想“建立信任、被收藏、获得咨询”，先选此篇最重要的一个，其余只记为副作用。

`structure_route` 是可选展开路线，不是每篇必套的结构模板。选择方法见 [内容结构路线库与人工改道规则](../../../self-media-creation-system/structure-route-playbook.md)。`content_job` 说明“做什么”，`structure_route` 说明“怎么展开”，`format` 说明“怎么被消费”。

### 1a. 问答型选题的结构分流

仅 `content_job: question-answer` 或 `primary_goal: search-discovery` 时选择问答路线；其他内容可写 `not-applicable`。详细规则见 [问答选题分流与条件式重构操作卡](../../../self-media-creation-system/topic-reframing-playbook.md)。

```yaml
question_structure_route: direct-answer | decision-reframe | not-applicable
audience_entry_question: 普通人实际会问、会搜的话
surface_answer: 先用一句话回应原问题
hidden_assumptions: []
professional_core_question: 专业人士认为真正要回答的问题
client_decision: 读者最终要完成的一个判断或动作
public_value_bridge:
  misconception: 本篇只纠正的一个误区
  distinction: 本篇只拆开的一个关键区别
  action: 本篇只给出的一个立即行动
scope_boundary: 特殊人群、例外和后续问题
backstage_research_refs: []
```

`direct-answer` 只需原问题、直接答案和必要边界，不强制填写真正问题和客户决定。只有 `decision-reframe` 才填写完整字段，并使用“一个误区、一个关键区别、一个行动”。

`question_structure_route` 与 `structure_route` 可以不同：例如原问题本身准确但答案因人而异，可写 `question_structure_route: direct-answer`、`structure_route: scenario-branch`；表面问题需要重构后再查缺口，可写 `decision-reframe` 与 `gap-diagnosis`。

### 1b. 系列规划与人工改道（仅在使用时）

```yaml
planning_scope: single | series
series_question: 整个系列回答的大问题
current_piece_decision: 本篇只解决的一个问题
next_piece_candidates: []
manual_route_override:
  stage: topic | research | outline | draft | review
  from: 原路线
  to: 新路线
  reason: 改道理由
  changed_by: human
```

系列拆解不是单篇正文结构；每一篇仍单独选路线。人工可在任意阶段改动任意环节，不需要统一界面；改道后按操作卡只重跑受影响部分。

策略／系列选择时，在已有说明中写清当前阶段目的（验证传播、建立相应人群的信任、承接已成熟需求或探索方向）、稳定人群与共同问题、各篇分工及服务关联；个人表达可有独立目的，不强加转化比例或咨询 CTA。后续单篇引用该策略，不重复访谈。

有商业目标时，分别记录“需求是否已成为行动／是否来自独立来源的共性需求／能否持续以不同角度连接该需要”的证据或未知。复用既有运营记录和独立来源组，同一人重复提问不算多个需求；对标的成功不能代替自身验证。

### 1c. 角度选择与早期表达设计

选题／提纲阶段就在现有候选中同时试 **人群处境、观看所得、暂定标题、封面文字主张、首句、正文兑现位置**。封面先写主张，不提前制作图片；候选有实质区别即可，不为凑数量反复生成。这属于探索，不提前运行冻结后 Hook、不签发包装通过；正式筛选仍在正文问题关闭和相应作者确认之后。

复用争点对象的 audience_value、hook_hypothesis、evidence_refs、selection_reason。选择理由同时比较当前目标价值、证据准备、参考内容相对其作者近期常态的表现，以及本人新增研究／拍摄／剪辑／交付成本。未知数据写未知；既有排名不是爆款概率。已有半成品纳入取舍，不被新工具自动重置。

写作先引用作者已确认的经历、判断、表达与拒绝原因；材料不足时才追问。观点稿在原提纲中写出主张、强反例和收窄后判断，或解释反例为何不推翻原判断；不强迫普通故事套理论。

## 2. 事实与边界

```yaml
source_basis:
  - user-confirmed-personal-experience | published-final | first-party-record | official-source | ai-draft | candidate
canonical_fact_card_ref:
fact_revision_id:
fact_lock_status: draft | locked_for_draft | superseded
fact_ids_used: []
facts_to_say: []
personal_experience_to_say: []
unknowns_or_pending_checks: []
quantitative_fact_ids: []
quantitative_scope_status: not-applicable | complete | needs-review | blocked
evidence_usage_status: active/background/retired 已在事实卡逐条记录
audience_scope_decision: same-answer | branch-in-piece | split-piece
audience_scope_reason:
privacy_level: none | deidentified | consent-required | blocked
medical_insurance_boundary: 不替代医生决策；不承诺承保或赔付；以合同与实际审核为准
rights_status: original | licensed | pending | blocked
```

返工或已有媒体进入时，在 source_basis／任务说明附“本轮可改范围”：正文可重写、可补录、可补画面、只可剪辑或完全固定；由已有任务推知时不再问。方案受限时收窄承诺、换适合用途或明确暂缓，不用虚构冲突救包装，也不以 AI 流量猜测自动弃稿。

仅所选 recipe 需要研究、`task_type: research` 或 `origin_kind: research-synthesis` 时补充研究引用；已有研究包直接引用，不重写来源台账：

```yaml
research_packet_ref: 本地证据包路径；未建立则留空
discovery_question: 本轮究竟要回答什么
discovery_sources: [peer-post, visible-comment, search-result]
authority_sources: [official-platform, regulator, insurer-disclosure, contract-clause]
claim_status: candidate | conflicted | verified | rejected | unknown
copyright_boundary: 只存问题、短证据摘记和来源引用；不拼接原文、不复用原图
```

## 3. 形式、渠道、声纹与视觉

如需使用情绪共鸣、证据型槽点、受众嘴替或行动型价值认同，复用或补齐
[内容作用机制补充卡](../../../self-media-creation-system/route-card.effect-mechanisms-supplement.md)。机制不是必选项：

```yaml
primary_effect: none | emotional-resonance | evidence-backed-friction | audience-voice | value-alignment
secondary_effect: none | emotional-resonance | evidence-backed-friction | audience-voice | value-alignment
effect_card_ref:
```

```yaml
benchmark_status: not-needed | candidate-only | reviewed-for-structure
benchmark_review_ref: benchmark-visual-grammar-playbook | null
benchmark_refs: []
benchmark_modules_to_adopt: []
benchmark_elements_to_reject: []
facts_imported_from_benchmark: false
visual_role_map_ref:
format_adapter: 对应 format-adapters.json 的 id
platform_overlay: 对应 platform-overlays.json 的 id
voice_route: 本人朋友圈表达 | 灿哥诊风险服务叙事 | 灿哥精进工具表达 | 双号共享项目表达
visual_route: 按主题、受众、阅读任务和使用情境选择；不使用固定账号皮肤
```

规则：对标是可选的结构研究，不是事实来源。每个参考对象必须说明“具体采用什么／明确拒绝什么／用于哪个分镜”；客户原声、医学结论、保险责任和案例事实不得从对标内容导入。

上段为单篇表达对标。账号策略对标另在既有策略说明引用“吸引谁→公开承接→产品／服务→交付→持续内容”的观察与未知；不要求先有单篇事实卡，也不让商业观察倒灌为本案事实。适配边界见同目录 benchmark-visual-grammar-playbook.md。

当配图采用编号画风时，在已有视觉说明中引用 `handdraw_style_brief.py prompt` 的输出文件及所用槽位；编号、源版本、内容哈希由该文件承载，不重复填表。按 [编号画风操作卡](../../../self-media-creation-system/docs/handdraw-style-workflow.md) 分别记录已选画风、已生成提示词、实际候选图和实际图片审核。未用手绘参考时跳过此项，不影响原有视觉路线。接入记录：2026-10-03 11:32:00 +08:00，Codex。

图文内容复用 `visual.article_visual_plan.slots[].purpose`、`media_role` 和 `anchor` 说明每张图承担的读者任务，并引用已有 `visual_role_map_ref`；不另填同义配图矩阵。正文补充解释、条件或意义；替代文字、必要图注、来源和影响判断的限定仍须保留。仅在制作相应视觉时填写，不为纯文字内容创建配图任务。

解释视频中的对象与关系动效，可把 `visual_role_map_ref` 指向既有对象场景 spec／resolved plan，沿用脚本、声音和分镜确认记录。二维对象及轻量三维均属于 `remotion_knowledge_animation`；原件证据继续使用 HyperFrames 聚焦。先根据这一镜头的理解任务选择路线，再选择主题语气与视觉 token。默认选择规则与制作入口见操作者提供的 MVP 视频 owner 材料（该 owner 另行发布并固定于 `tools/public_toolchain.lock.json`；该对象场景操作说明不随本公共版分发），不另建路由卡或审批台账。

### 颜色的用途与作用范围

制作视觉时，在现有 `visual_route` 或其引用的场景计划中说明“品牌色用于哪里；主体和状态颜色依据什么”。没有品牌层时直接记为“本镜头无品牌色”；已有对象／系列颜色表只引用，不另填同义表格。账号、题材或本人旁白不自动选择个人 IP 配色。

个人 IP 配色可用于身份标识、排版、结构和编辑标注：纯文字表格的表头、边框、分组底纹、重点文字，以及照片、软件界面、证据原件上外加的框线、箭头、编号和说明文字均可采用，不要求整张图或整段视频使用品牌模板。

物体按材质和实际情境选色，状态按含义选色，图表按类别／顺序／分歧选色；表格颜色若承担风险、状态或数值等事实含义，也服从相应编码和图例，品牌色只在兼容时采用。照片、软件界面和证据原件保留来源颜色，编辑标注作为独立叠加层，保持对比度，不遮挡关键内容或造成含义误读。标题和背景服务于可读性。跨镜头保持同一对象／类别的颜色含义，并配合文字、形状或线型。详细品牌作用范围以操作者提供的个人 IP 品牌合同（Color Scope）为准；该合同不随本公共版分发，本版仅保留上列可执行边界。允许局部使用品牌色不等于默认给全部内容套个人 IP 配色。

接入记录：2026-10-04 13:22:28 +08:00，Codex（GPT-6）；仅收窄色彩适用范围，复用原卡和场景参数，不新增审批或路由枚举。

边界修正：2026-10-04 15:42:05 +08:00，Codex（GPT-6）；补充文字表格的排版与结构、原件上的独立编辑标注可使用个人 IP 配色；原件与事实编码继续服从内容含义。

## 4. 这次只验证什么（存在明确试验时）

普通成稿不必为了填卡新增试验；需要验证创作假设时再填写。

```yaml
hypothesis: 如果……，那么……；因为……
variable_to_change: 仅一个变量，例如开头、封面承诺、案例节点或图文结构
constants: 其余保持不变的条件
observation_window: 发布后 48–72 小时 / 第 7 天 / 无可观察指标
success_signal: 与 primary_goal 对应的可观察信号
no_signal_meaning: no_signal，不推断为内容无效或关系无效
stop_condition: 何时停止继续改、继续投放或继续拆分
```

## 5. 生成与审核回执

普通稿件也有本轮结束条件：复用同一问题处理表，把问题标为“本版必改／下一条验证／有依据保留”。读者任务、承诺兑现、作者判断和适用事实／隐私／专业门满足后，剩余仅审美偏好或无证据传播猜测时结束本轮编辑。记录预算与结束原因；预算用尽但有实质问题时缩小范围或暂缓，不能放行。此处不新增作者审批，也不以停止润色冒充作者确认或发布许可。

来自上次复盘的决定，引用原 decision 与证据，并注明这次保留／改变什么；正文或包装形成后指向实际差异。无足够证据可以明确维持，不强改。

按所选 recipe 引用已有回执；下列字段展示可能使用的记录，非每篇必跑全部门。`case-video-initial-draft-review.v1` 与故事十一门只用于适用案例/故事链，不能套到所有文章；事实、隐私、专业边界及其他实际适用的检查仍保留。

```yaml
skills_used: []
skill_outputs_accepted: []
skill_outputs_rejected_or_modified: []
initial_draft_review: approved_for_voice_pipeline | return_for_revision | blocked_from_downstream
initial_draft_review_ref: case-video-initial-draft-review.v1 | null
input_fact_card_ref:
correction_invalidation_status: clear | invalidated | revalidated
manual_override_ref: content-item.intent.manual_route_override | null
manual_override_affected_artifacts: []
manual_override_checks_to_rerun: []
manual_override_revalidation_status: not-applicable | invalidated | revalidated
hard_gates: [fact, privacy, medical_insurance, rights, publication]
soft_gates: [topic_structure_fit, audience_appropriate_expertise, format, voice, clear_communication, accessibility]
human_reviewer: 用户本人
freeze_status: draft | reviewed | final-frozen | published
```

## 最小决策树

```text
所选 recipe 要求锁定事实卡，但事实卡未锁定或纠错尚未完成下游失效与重审？ → 先补对应证据，不跨过该事实门；未知项可先列为问题或待核结构，不编成事实。
先确认内容任务和读者任务；再选形式和平台。 → 不把平台当作正文结构。
需要结构分流？ → 从现有路线库选一条主路线；问答或搜索任务另判断直接回答还是条件式重构。
客户、医疗、儿童、理赔？ → 先跑加严质量门。
需要转化？ → 明示为 conversion，才可调用 copywriting；否则不用。
适用案例/故事链的初稿出来了？ → 走该 recipe 的十一门初稿检查；其他内容走自身适用的初稿质量检查，未通过不进入下游。
需要外部参考？ → 事实锁定后再做结构对标；先写采用与拒绝项，再进入脚本和分镜。
已经发出？ → 新建发布回执；不回写“效果好/不好”的主观结论。
怀疑限流？ → 先走 account-diagnosis；官方状态、本人基线和可比窗口不足时不定性。
```

## 2026-08-15 17:53:49 +08:00 | Codex（GPT-5.6 Sol）

- Action: 为每条路由卡增加事实修订版、事实 ID 和纠错失效状态。
- Intent: 让选题与脚本明确绑定同一份事实源。
- Decision: 在原路由卡上扩展，不另建重复模板。
- Reason: 只有正文哈希而没有事实源版本时，旧事实可以被新稿继续引用。
<!-- Private manuscript, case-history or local course-file reference omitted from the public edition. -->
- Effective scope: 所有新建或重做的路由卡。

## 2026-08-17 20:20:43 +08:00 | Codex（GPT-5.6 Sol）

- Intent: 让每次网上对标都有明确用途、拒绝项和事实边界。
- Decision: 在原路由卡的形式与视觉层增加对标状态、引用、采用项、拒绝项和画面职责映射，不新建第二套路由卡。
- Reason: “参考某账号风格”过于模糊，容易造成表现层错配和外部叙事污染本案事实。
- Evidence: `benchmark-visual-grammar-playbook.md`及质子治疗真人小窗口播的实际画面分工。
- Effective scope: 所有使用外部账号、视频、图文或模板作为参考的内容任务。

## 2026-08-20 12:52:09 +08:00 | Codex (GPT-5.6 Sol)

- Intent: 让路由卡能够引用量化口径、特殊受众分流和人工中途修改后的局部重跑结果。
- Decision: 只增加事实卡状态和 QA 引用字段；详细口径仍保存在唯一事实卡，不在路由卡复制数据。
- Reason: 路由必须知道哪些检查失效，但不能成为第二套事实源。
- Evidence: `content-fact-card.v0` 的 `quantitative_scope`、证据用途与权利字段，以及质量门0.8。
- Effective scope: 含量化主张、特殊人群或人工改道的内容任务。

## 2026-09-26 13:25:27 +08:00 | Codex（GPT-6 Astra）

- Intent: 合并重复路由卡，减少重复填报与规则漂移。
- Decision: 本文件作为唯一主模板，吸收项目模板的可选结构、条件问答、系列/人工改道、研究和作用机制区块；枚举由中央 `task-router.json` 定义。项目同名文件改为短入口。
- Reason: 原两份模板分别遗漏研究枚举或事实修订、量化、对标及视觉引用；按任意一份填写都会漏项。已有受众、读者任务和图片用途直接复用，仅补缺失；故事十一门仅按适用 recipe 使用。
- Provenance: 项目模板原记录为 2026-08-13 23:45:18，Codex（GPT-5.6 Sol）；本次迁移保留原语义与本文件既有历史署名，不追改历史归属。
- Effective scope: 后续新建或更新路由卡；不迁移历史内容、不新增流程状态或发布授权。

## 框架决策接入（2026-10-10）

更新：2026-10-10T09:28:29+08:00；Codex（GPT-6）。完整操作见[四种框架决定](../../../self-media-creation-system/topic-reframing-playbook.md#内容框架决定在结构故事和正式包装之前)。

写作前比较每个候选对应的受众、观众所得、具体商业关系、材料兑现和制作成本；不是只给商业关联标高/中/低。使用 `topic-angle-decision.v2`，允许继续、重构、补材料、暂缓，允许全部不选。只有已确认且材料仍有效的继续决定进入结构/故事/初稿。补材料仅通往指定研究或素材准备；重构必须实际改稿并重新评估；暂缓保留材料和恢复条件。已知方向的局部改动可复用仍有效的判断，不重复全面探索。

前置 `dbs-content-value` 诊断与 `dbs-title-cover-intro` 的联合框架探索；正式标题/封面文字/开头仍在正文稳定和适用人工确认后。`title-matrix` 作为同一条标题流程的比较工具；旧 `dbs-hook` / `dbs-xhs-title` 仅兼容，不默认重复调用。新Skill不能代替事实核验、作者决定和改稿。

框架卡字段：当前素材及哈希；单一目标；可改/补录范围；至少3个框架的逐项比较；产品/服务与对象或未知/非本篇目标；四选一结论；整稿/局部改写范围；具体下一步；恢复条件；人工决定与当前稿引用。
