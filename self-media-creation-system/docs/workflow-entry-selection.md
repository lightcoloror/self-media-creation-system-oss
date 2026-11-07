# 自媒体任务从哪个入口继续

更新：2026-10-25 21:34:37 +08:00｜工具／模型：Codex（GPT-6）

先确定本次交付和已有进度，再进入现有流程。Agent 不需要先猜 `workflow_goal`，也不应把流程名称交给用户选择。入口仍是原来的 `self_media_agent.py resolve`，没有增加另一套工作流引擎、项目状态库或模型调用。

## 一个入口，按需进入原有模块

```text
用户本次交付 + 已保存的当前输入
→ resolve（self-media-work-request.v1）
→ 唯一 primary_entry + next_action + 必要的 missing_inputs
→ 当前产物子流程／原有进度恢复／创作形式判断
→ 适用的现有配方或指南
```

| 层级 | 职责 | 不应混同的对象 |
| --- | --- | --- |
| 任务入口 | 本次要交付什么、从哪一步继续 | 不写脚本、不制作媒体 |
| 创作形式 | 故事、体验／Vlog、说明、技术返工 | 不是发布页、封面或审片流程 |
| 受管配方 | 五条有步骤、handoff 与回执的执行序列 | 不代表全部自媒体任务，不把 Vlog 塞进案例配方 |
| 共用子流程 | 作者表达、封面、原片审核、发布页、交付、运营、归档 | 可直接进入，不必重跑整条创作链 |
| 质量检查 | 所选流程在相应阶段检查产物 | 不作为另一条竞争工作流 |
| Owner | 工具维护与专业归属 | 当前用户直接指派不自动转发其他线程 |
| 历史兼容 | 旧命名、别名与来源证据 | 不与 canonical 当前规则并列供选择 |

## 调用方法

2026-10-29｜Codex（精确模型未独立核验）：日常调用先执行 `<workspace>/scripts/local-tools.ps1 discover content-creation-system`，使用返回的 `contract.cli.self_media_resolve`。下文仓库内命令表示子命令参数，不替代当前注册 launcher。新增创作连接见 [选题、平台与文章编辑](article-editorial-connection.md)：选题依据用现有 context anchors；形态和平台独立选择；通用文章实际消费作者版本和编辑记录，不再只返回文体指南。当前 `awaiting_author` 表示检查包可供作者审核，不等于已确认或已发布。

Agent 从用户原话与当前上下文提取 `requested_output`、`selection_basis`，附上当前 JSON 产物的绝对路径和 SHA-256。不读取整个项目来猜最新文件，不自行补写“已完成”或“已授权”。例如：

```json
{
  "schema_version": "self-media-work-request.v1",
  "request_id": "current-content-20261025",
  "requested_output": "fine_cut_review",
  "selection_basis": "用户要求继续精剪字幕审核，原片和已保存审核要求在当前项目中"
}
```

```text
python scripts/self_media_agent.py resolve --request <task.json> --output <selection.json>
```

输入定义见 [self-media-work-request.v1.schema.json](../schemas/self-media-work-request.v1.schema.json)。旧 `self-media-agent-request.v1` 继续用于已选定的受管配方；保存的 capsule、handoff 和回执格式保持兼容。若其绑定的配方或规则版本已变，原有漂移校验仍会阻止继续；按 `resume` 返回的恢复说明比较影响范围，保留旧证据，不能改旧哈希或把旧回执挂到新 capsule 上，也不能因此自动重剪。

通用脚本／视频如已知为 Demo、长视频、直播等，可提供 `content_format`。允许值和适配器 ID 取自当前 canonical `format-adapters`；未确定时返回具体缺项，不能一律认作短视频口播。Agent 优先从已知交付形式补齐。

输出的 `next_action` 只有一个：现有 CLI 参数列表、现有指南，或当前稿的 `human_review`。`selected` 表示入口已选择，不表示已执行、质检通过或交付完成。`needs_context` 返回非零退出码和具体缺项；Agent 先从当前记录恢复缺项，仅缺少决定性信息时询问用户。`awaiting_author` 也返回非零退出码，但表示需要作者审核，不是业务执行失败。配方模板故意标为不完整，不能将模板当成可执行合同。

## 常见任务如何走

| 本次要求 | requested_output | 现有消费者与继续方式 |
| --- | --- | --- |
| 审核粗剪／精剪配方／某段素材 | rough_cut_review / fine_cut_review / material_review | video-review → targeted-review；原片时间区间跳转，不生成审核视频 |
| 补齐发布辅助页 | publication_page | publication-desk；旧数据先 upgrade，当前数据先 preparation 检查，再生成页面 |
| 做封面方案与各平台比例 | cover_options | covers；复用同一封面候选与比例合同，不能把四个比例冒充四种创意 |
| 比较标题、封面文字与开头 | title_options | dbs-title-cover-intro 协调入口；仅做本次文案，不擅自扩展为整段脚本或封面图 |
| 已发布、定时或提供平台数据 | publication_record | operations；先记录实际事件，不直接启动表现复盘 |
| 分析已记录的表现 | performance_review | publication_feedback_review；依原合同准备运营存储等输入 |
| 修改流程代码或修复入口 | workflow_repair | 当前任务维护；doctor 是检查入口，不是自动转发指令 |
| 新写文章或继续原稿编辑 | article | 核对选题依据、长文形态及独立平台选择，复用现有作者版本与编辑验收，按缺项继续；完整检查包仍待作者决定 |
| 新写脚本、图文、视频方案 | script / graphic_note / video_plan | creation-route 核对本次形式，再选既有配方／文体指南；拍前案例脚本进入 prerecording，不索要尚未拍摄的视频 |
| 已锁定方案要求实际成片 | finished_video | 已有 delivery_manifest 则检查现有交付；否则进入适用制作流程，导出仍依据用户的实际授权 |
| “继续” | continue | 现有 capsule 与有序回执调用 sequence-status；错误回执走 resume；唯一当前发布数据或交付合同恢复对应消费者 |
| 制作归档计划 | archive_plan | artifact_lifecycle；计划不授权删除 |

“继续”无法由现有证据确定时返回一个明确缺项，不按文件修改时间重启流程。明确交付优先于无关的旧 capsule。只有创作或重新策划需要 `creation-route`；仅做发布页、标题、封面、审核或技术维护不触发一次新的故事判断。

## 复用、去重与校验

- canonical 路由继续由 `routing-binding.v1.json` 整组绑定。过期快照不作为回退来源。
- 同一 skill ID 的多个适用阶段保留在 `applicability_fragments`，归为一个调用目标。`dbs-hook` 等旧别名解析到现有目标；不要把多个片段当成多个完整工作流，也不要把所有阶段的前提合成一张无条件清单。
- `creation_context` 与 `creation_decision` 必须属于当前任务并相互匹配。内容改变后旧判断不能继续通过。
- 当前元数据引用必须有匹配的文件哈希。孤立回执、损坏文件、未知字段和冲突的已选配方失败关闭。
- 受管流程继续由 `prepare-step`、`verify-step-output`、`sequence-status` 执行与验收。新选择结果不替代它们，也不提供媒体导出、发布、跨线程发送或知识库写入授权。

## 能力边界

2026-10-27（Codex，具体模型未独立核验）：创作、独立标题/封面和适用审核入口通过 `current.context_manifest` 复用[本篇目的与反馈](purpose-continuity.md)。缺项保留原入口并返回 needs_context；不重启整套配方。阶段职责不限制表达方法，输出另做实际锚点复核；仅有选择结果仍不代表完成。

这是已有入口里的确定性选择逻辑。它依据 Agent 提交的任务判断及当前元数据选择消费者，不自行理解任意聊天、不读取影片，也不能证明语义判断正确。公共入口和消费者可阻止无效输入；完全绕过这些工具手写产物的 Agent 仍可能违反流程。验收应落到生成器及实际产物检查，不能只看选择结果。

## 按阶段调用的原有命令

从短发现页迁来，避免新 Agent 被大量平行入口淹没。按所选步骤加载，不是每个任务全跑一遍。参数与前置要求继续读取原模块帮助及当前 handoff。

```text
python scripts/story_material_inbox.py check
python scripts/story_material_inbox.py evaluate --input fixtures/story-material-observation-v1/synthetic.input.json
python scripts/topic_angle_decision.py check
python scripts/story_five_question_adapter.py check
python scripts/story_design_gate.py check
python scripts/short_video_timing_evidence.py check
python scripts/serious_content_translation_gate.py check
python scripts/science_popularization_gate.py check
python scripts/cross_platform_fact_consistency_gate.py check
python scripts/production_run_lock.py create --spec <spec.json> --workspace-root <workspace> --output <production-run-lock.json>
python scripts/production_run_lock.py verify --lock <production-run-lock.json> --workspace-root <workspace> --output <verification.json>
python scripts/privacy_redaction_binding.py --binding <binding.json> --workspace-root <media-workspace> --mvp-root <mvp-video-pipeline> --output <receipt.json>
```
# 口播净剪交付分流补充

2026-10-26 08:33:27｜Codex（运行模型未独立核验）：已有口播配方使用 `current.spoken_edit_plan`，交付需求使用 `current.spoken_delivery_request`。`rough_cut_review` 进入原片审核，`rough_cut_video` 进入显式净剪导出，`editable_project` 按明确 editor 选择剪映或 Premiere。已有配方的 `finished_video` 先选净剪出口，后续包装和最终交付仍需完成。旧配方指向剪映不再构成选路依据，缺编辑器不能擅自选择。

入口继续为 `self_media_agent.py resolve`，实际调用 MVP 原 `spoken_rough_cut.py select-delivery / prepare-delivery / render-delivery`；没有另建任务分发器。配方和请求仍按 path/sha256 绑定，准备审核页不会触发视频导出。
