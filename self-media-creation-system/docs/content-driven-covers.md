# 内容驱动的封面方案 × 多比例衍生

更新：2026-09-26，Codex。适用于现有自媒体创作仓库的封面子流程，不新增仓库、渲染器或模型。用户要求的核心是**先选不同的表达方案，再分别制作各比例**，不是同一张底图换几套字体。

## 每次新项目都从这里开始

```powershell
python scripts/self_media_agent.py covers
python scripts/cover_workbench.py doctor
python scripts/cover_workbench.py init --project-id <本项目ID> --title <本项目标题> --output <新brief.json>
# Agent 核对当前视频、用户审核记录、素材和授权，填写 brief；不复制上一条的事实或人物。
python scripts/cover_workbench.py plan --input <brief.json> --output <route-plan.json>
python scripts/cover_workbench.py strategy-init --input <route-plan.json> --output <strategy-request.json>
# Agent 填写下面的内容观察、证据和表达角度。
python scripts/cover_workbench.py strategy-plan --input <strategy-request.json> --output <strategy-plan.json>
python scripts/cover_workbench.py design-init --input <route-plan.json> --strategy-plan <strategy-plan.json> --output <design.json>
# 填充设计卡、每比例布局、当前账号、packaging_ref 和 safe_layout_ref。
python scripts/cover_workbench.py design-build --input <design.json> --output <新design目录>
# 接既有 compile → render → collect，命令见 cover-workbench.md。
python scripts/cover_workbench.py review-init --input <review目录/publication-data.json> --item-id main --output <visual-review.json>
# Agent 必须实际查看原尺寸和手机尺寸图片，再填写逐图及逐对观察；不能批量自动填“通过”。
python scripts/cover_workbench.py review-check --input <visual-review.json> --output <delivery-check.json>
```

`init` 新建 brief 的 `workflow_version=2`。v2 的设计、编译、收图会核对选案计划，不允许跳过选案直接贴“内容驱动”标签。没有该字段的历史输入按 v1 兼容，收图标为 `legacy_selection_unassessed`，不回写旧项目，也不把旧图追认为完成了新审核。

方法检索用 `methods`，风格检索用 `styles --query "插画"`；`plan` 的 `method_plan` 保留来源路径、适用条件及待完成的设计任务。[历史来源清单](cover-method-inventory-2026-09-26.md)、[工作台执行命令](cover-workbench.md)、[7 个非生成式起始配方](generic-cover-design.md) 按需读取。这些索引不代表自动执行第三方 Skill。

## 先理解内容，再选择方法

2026-10-27（Codex，具体模型未独立核验）：从[本篇目的与反馈交接](purpose-continuity.md)读取同源目的、当前正文及最新反馈，再确定角度的编辑优先级。素材/布局差异检查不替代目的取舍；候选完成后用原 `review-integrity check-stage` 引用具体文案或已观看图片的分析锚点。保留自然分行、不同句式与构图选择；编辑建议、作者选定、受众效果分开。

这里的“AI 理解”由执行任务的 Agent 完成；Python 不会自动观看视频、理解童声或判断什么能提高点击率。`content_kind=family` 只影响历史方法的检索范围，不能代替本条视频的分析。

Agent 应先回答四件事：

1. **内容真的发生了什么？** 核对当前成片、已经确认的听写、用户纠正；引用确切来源，不用梗名或标准歌词替代事实。
2. **观众可以从哪些不同角度进入？** 例如人物关系、一个表情、事件过程、语言反差、操作证据。每个角度有自己的承诺和证据，不是三条同义标题。
3. **什么画面最能表达该角度？** 真实瞬间适合一个有信息的画面；先后过程需要有顺序的不同画面；证据路线必须有实际证据图；谐音可用明确标作概念的图文表达。
4. **为什么不用其他方法？** 缺透明主体不等于“不适合抠图”；没有前后关系不能硬做对比；不为了凑满数量造素材、重复同一照片或自动启用生成。

默认展开全部已登记的角度/方法组合，检查内容依据、素材与授权后，每个可执行构图族保留一个互补代表，不预先锁定三套。登记方法库不是所有可能创意的穷举；新增方法应有独立表达机制和执行出口。只有用户明确提出限额时才填写目标数量；不得用换色换字补位。

### 输入记录

`strategy-request.json` 的 `analysis` 包含：

- `synopsis`：只讲本条视频的真实内容。
- `evidence`：每项有 `id / kind / source_ref / observation / confidence / asset_ids / role`。来源 `source_ref={path,sha256}` 必须真实存在；可附 `time_range_s:[开始,结束]`，时间相对于该来源，不能混用原片与候选成片。
- `angles`：每项有 `id / label / hook / signals / evidence_ids / priority`。`priority` 为 1–5 的编辑优先级，不是预测播放量。
- `policy`：默认 `selection_mode:all_applicable, min_angles:2, min_layout_families:2`，不含固定数量。结果 `selection_scope` 记录有依据的组合数、可执行构图族和最终数量。多方案最低差异检查不等于预定产出数量。明确限额时使用 `selection_mode:fixed_count` 和 `target_count`；历史仅含 `target_count` 的计划仍按原规则回放，不追改历史回执。

`kind` 可用 `visual / human_review / transcript`；`confidence` 为 `agent_observed / human_confirmed / asr_candidate`。`human_confirmed` 必须有真正的用户审核依据，不能由 Agent 自签。未经复核的 `asr_candidate` 不可成为封面事实。

`role` 为 `context / reaction / demonstration / outcome / detail / concept`。两张不同哈希的图还不够构成故事：叙事或对照方法需要 `relation={kind:temporal或comparison,evidence_ids:[...],explanation:...}`，且所选画面有至少两种视觉职责。文本记录的角色不充当第二张画面的角色。

角度字段示意（不是可直接执行的项目事实）：

```json
{
  "id": "process",
  "label": "示范与后续反应",
  "hook": "真实过程带来的反差",
  "signals": ["sequence", "reversal"],
  "evidence_ids": ["frame-demonstration", "frame-reaction", "reviewed-context"],
  "priority": 4,
  "relation": {
    "kind": "temporal",
    "evidence_ids": ["frame-demonstration", "frame-reaction"],
    "explanation": "说明两个画面在当前视频中的真实先后关系；不能编造心理活动。"
  }
}
```

## 选案器怎样避免千篇一律

当前有 8 种表达机制，**不是 8 个模型或 8 套必须全部运行的工具**。底层仍复用现有制作路线和方法索引。

| 表达机制 | 有何内容依据才考虑 | 关键输入 |
|---|---|---|
| 真实瞬间 | 关系、发现、情绪、人物、反应 | 该角度引用的真实照片 |
| 前后叙事 | 过程、示范、转折 | 2–3 张不同画面、先后关系及不同视觉职责 |
| 真实对照 | 对照、前后变化 | 两张不同图、真实可比关系，不能暗示虚构效果 |
| 概念与图文反差 | 谐音、比喻、解释、概念反差 | 已复核含义；不冒充拍摄现场 |
| 证据或操作界面 | 结果、操作证据 | 当前项目证据图及核验焦点 |
| 真实主体抠图 | 人物、表情、情绪 | 已审核透明素材，不自动下载模型 |
| 真人与概念装饰 | 谐音、比喻 | 真实照片、装饰图、适用生成授权 |
| AI 概念插画 | 谐音、比喻、解释 | 明确授权；只走现有原生生成出口，不上传家庭照片 |

枚举“角度 × 表达机制”，先检查内容信号、路线开关、该角度关联的素材及关系证据。排序先满足角度和构图族覆盖，再比较显式编辑优先级；同一构图族只保留一个代表。分数只是可解释的本地规则，不是审美模型、观众数据或 CTR 预测。

每个入选项保存角度、制作路线、素材、证据、构图族、入选原因和所需比例。其余项分别记录：`not_applicable`（不适用）、`disabled_route`（未启用）、`missing_inputs`（缺输入/授权）、`redundant_treatment`（重复表达）、`not_selected`（组合取舍）。不以“AI 不擅长”笼统跳过非生图路线。

`ready_for_design` 只代表可以开始设计；`needs_more_evidence_or_revised_policy` 表示仍有缺项。候选 ID、路线、素材身份及比例清单一路绑定到设计和收图；改计划后需重新产生后续产物，不能手改回执。

## 一套方案，分别排各比例

默认目标为 `3:4 / 9:16 / 16:9 / 4:3`；以本项目 brief 为准，不宣称这是所有平台的固定要求。一个方案的竖、横版共享内容承诺，但独立编排图层、标题换行、主次关系与保护区，不能把已排好字的成图拉伸或裁切来凑比例。

当前 v2 同一方案绑定的素材需实际出现在每个比例里。可独立重排同一批素材；如果要换帧、换新裁切/蒙版素材，则回到 brief 和证据重新选案，不允许拿同一 ID 偷换文件。工具不提供自动智能裁切或自动补出缺失人物画面。

通用母版是**可编辑起点**，不是最终审美答案。Agent 必须按内容修改 `profile_layouts`；照片不一定需要色块底，概念不一定需要真实照片。通用入口没有默认调色板；填写 `color_selection` 说明当前内容、情绪、照片和可读性如何决定选色。品牌色只在当前账号/内容明确适用时绑定引用，不将专业账号配色套到其他选题。同一方案的比例衍生共享色板，不同方案可分别选择；换色不算新增方案。字段与历史兼容规则见 [通用设计](generic-cover-design.md#配色选择与账号边界)。

`recipe:null` 表示选中了既有 AI/hybrid 出口，不支持直接交给非生图 `design-build`。使用原来的原生生成/visual-plan 构建入口，并保留同一 `strategy_plan_ref`；不自动降级成某个确定性配方。没有执行授权就保持缺输入。

2026-09-27，Codex 补充：hybrid 的可编辑 `cover_layers` 可接收已批准的 `generated_editorial_visual` 装饰，必须显式声明生成、绑定用户授权，并有可见 AI 标注。生成资产不能以真人主体身份混入；保护区、文字最小字号和逐比例检查不豁免。非生图 `design-build` 仍拒收生成图片；这只是既有图层的受控合成能力，不运行或安装模型。

## 两道差异检查与完整性交付

1. **自动检查实际布局和文件。** 同一照片集合、近乎相同位置/占比的方案，即使名称、文字、字体和颜色不同也拒收；各比例实际素材须对应选案；同一比例不能重复导入完全相同的 PNG。文件须哈希匹配、能解码、尺寸/比例合格。
2. **Agent 查看实际图片。** 自动规则不是感知相似度或审美评判；不同裁切、不同帧但看起来仍相同，也应在逐对视觉审核中退回。逐图检查事实、手机可读性、脸/手等保护区域；每个比例逐对写出方案有何实质差异。不得用 JSON 存在代替看图。

发布页新增“方案 × 比例”矩阵及未采用路线说明，保留原来的单比例 PK、路径和文案复制、合集、人工选择。无图的格子明确标缺项，不拿旧候选填充。选择哪个方案仍由用户决定。

- `rendered_matrix_complete:true` 只证明图片齐全；`complete:false` 持续保留在收图回执中，不能误读为视觉已通过。
- `review-check` 只有逐图和逐对检查全部完成，才生成独立 `complete_candidate_package_pending_human_selection` 回执。收图回执不被覆盖。
- `human_quality_approved:false / publish_authorized:false` 始终保留；Agent 审核不是用户采用，更不是发布许可。

测试脚本为 `tests/test_cover_strategy.py`、`tests/prepare_content_cover_smoke.py`、`tests/content-cover-browser.cjs`。实际运行记录见 [本轮验证](content-driven-covers-verification-2026-09-26.md)。合成测试不证明真实视频理解或封面点击效果。
