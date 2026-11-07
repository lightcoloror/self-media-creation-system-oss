# 创作执行完整性

2026-10-24（Asia/Shanghai），Codex；具体模型变体未独立核验。

本页是现有作者记录、prepare-step、verify-step-output、sequence-status 的补充合同。
不新增工作流目标、问题数据库、发布系统或默认作者样本。Agent 填写证据，用户不需要手填 JSON。

## 接入点与判断

1. 写稿和作者审核的 `prepare-step` 读取现有作者上下文，并要求七项前置决策有效。
2. 写稿输出仍交付主稿和 `author-writing-revision.v1`。输出验证同时查询该版本的编辑记录。缺记录、缺项、必改未关闭，都不能通过该步骤。
3. 作者审核使用同版作者确认。编辑检查不能替代作者确认，也不会把全文收录成表达样本。
4. `sequence-status --require-complete` 仍要求原来所有 Owner 验证；编辑记录齐全不会提升通用 transport 回执的权限。历史步骤回放仅说明当时版本的覆盖，最新写作/审核步骤必须验证当前版本及最新反馈。

`records_complete` 表示九项都有状态；`checks_complete` 表示适用项有可校验的具体证据（可以有问题）；`required_issues_closed` 单独表示必改已处置；`may_advance` 还要求前置准备、适用实际观察、当前作者确认。四者不可互换。`proves_editorial_quality` 和 `publication_authorized` 恒为 false。

## 复用的持久化机制

沿用 author-expression 的同一个追加记录表，新增三种记录类型：`editorial_preflight`、`editorial_review`、`editorial_feedback`。不改变旧记录、不建立第二套数据库。所有记录绑定同一 content_id、作者上下文、真实/合成分类；编辑记录绑定 request_id、实际稿件路径和 SHA-256、作者 revision_id。

旧任务缺这些记录时可以查看历史，但不能声明已经满足新增的完整性门。按实际证据补记，不能批量补“通过”。局部复核仍可引用有效旧证据。

## 本地操作

所有命令从仓库根运行，文件引用用仓库相对路径。真实数据遵守已有授权；测试只用独立 `.test-runtime` 库。命令不调用模型、不联网、不发布。

```powershell
python -B scripts/self_media_agent.py review-integrity preflight --context <author-context.json> --input <preparation.json>
python -B scripts/self_media_agent.py review-integrity record --revision <author-revision.json> --input <review.json>
python -B scripts/self_media_agent.py review-integrity feedback --context <author-context.json> --input <feedback.json>
python -B scripts/self_media_agent.py review-integrity check --revision <author-reviewed-revision.json> --require-complete
python -B scripts/self_media_agent.py review-integrity check-draft --draft <existing-manuscript.md> --require-complete
```

`record` 接受如实的未完成记录；不把命令退出 0 解释为稿件通过。完成声明必须看 `check --require-complete`，该命令在不满足条件时退出 2。正式托管全流程仍须原 `sequence-status --require-complete`，不能拿本命令代替。

### 证据与前置决策

`source` / `evidence[]`：`{path, sha256, quote}`，路径、摘要及原文片段必须一致。引用的材料、分析说明和用户纠正均为实际保存的文本，不允许空引用、只有文件名或泛称“通过”。证据是可复核依据，不是机器认定其内容正确。

前置输入：`route`（expository/story/travel-experience/text）、`actor`、`source`、`items`。七项 id：goal_audience、materials、facts、author_expression、angle、promise、production。每项有 state（ready/not_applicable/missing_input）、reason、evidence。任何缺项或 missing_input 阻止开写；不是要求消除一切未知，reason 应说明材料足够进入本阶段的边界。

### 每版编辑输入

顶层：request_id、draft_ref（path/sha256）、phase（draft/readthrough/final_media）、route、previous_review_id、feedback_ids、changes、checks、issues、actor、source、observations。

九项 checks 的 id 为 C01—C09，分别是目标反馈、事实论证、入口兑现、结构推进、本人表达、AI模式、口播画面、结尾行动、风险权益。每项包含 state、scope、quote、reason、evidence、issue_ids、reuse_from。

状态：unchecked / findings / revised_verified / retained / not_applicable / missing_input。`findings` 要引用问题；`revised_verified` 要有实际 fixed 问题；`retained` 要说明保留依据。C01—C06 和 C08 不允许整个类别不适用；没有发现问题可以保留。写稿阶段 C07/C09 可仅对尚不存在的媒体部分标注不适用，scope 必须为 actual_media，同时 text_review 必须提供文字/安排部分的 quote、reason、evidence；不能把整个类别跳过。成片阶段 C07/C09 的 scope 必须为 final_media，不能不适用。

问题字段：id、first_revision、check_ids、required、state（open/deferred/fixed/retained）、before、after、reason、verification、reopened_by、verified_draft_sha256。稳定 ID 和原始发现不能改，上一轮问题不能删除。必改不能降级为非必改，暂缓不能关闭。关闭必须指向当前稿、具体修改或保留理由、复核证据；固定状态不能用相同 before/after 冒充修改。多项检查引用同一个问题 ID。

### 反馈与有效期

反馈输入：feedback_id、check_ids、issue_ids、reason、source。追加后即使稿件摘要没变，旧检查也不能继续放行。新记录必须承接完整反馈序列；影响已有问题时，reopened_by 引用真实反馈记录。C01 涉及目标或需求时先更新前置决策。C01/C05 反馈晚于原作者确认时，原确认不能放行；需要来自实际新反馈之后、明确范围的新作者确认。

changes 可声明 wording、structure、claims、promise、media、goal。改稿至少复核目标落实、表达、AI模式和衔接；程序识别纯段落重排并额外使结构/承诺/画面/结尾判断失效。其他影响按 Agent 的具体判断声明；程序不声称识别所有语义变化。`reuse_from` 只能指上轮记录，源证据、发现和锚点不变且不在受影响范围时才可复用，reason 要说明本版仍适用。受影响项重新执行；不要每版重访谈、重搜索。

observations 的 readthrough/final_media 为 null 或 `{kind:"observed", artifact:{path,sha256}, source:{path,sha256,quote}}`。实际阶段要求实际录音/视频文件和观察记录；估计时长、脚本文本不算。程序核对存在、类型和绑定，不能证明录像内容或观察真实性；仍沿用原有视频检查器与人审。

## 验收与限制

定向回归：`python -B tests/test_editorial_integrity.py`。现有作者与录制前执行链也有真实入口回归；测试使用独立合成记录。不能用测试夹具填真实作品的通过状态。

本次实施不编辑交接里的 v0.4。OPEN-01、OPEN-02、OPEN-03 及试读、作者确认、实物检查都保留；流程开发完成不会自动关闭它们。

机器能核对结构、摘要、原文锚点、引用、版本和记录链；不能认证人类身份，不能自动证明事实、论证、语气或传播效果。尚未记录进来的用户反馈也无法凭空检测。Agent 必须先追加实际收到的反馈再续办。

`check-draft` 未收到正式作者版本及编辑记录时返回 evidence_not_supplied，检查/确认状态为未知，完成资格为 false；不会把“未提供”说成“从未检查”，也不会写作者库。说明型项目视频可直接使用该入口和作者版本入口，不必伪装成保险案例。现有五个托管目标没有专属通用项目视频目标，本次不增加第六个目标；直接检查不能冒充该视频的托管全链完成。

## 2026-10-27：目的来源与阶段职责补充

执行：Codex；具体运行模型未独立核验。本节补充当前继续执行的条件，保留上文日期和历史归因。只扩展已有前置及 C01 记录，不更改作者 Brief 的原始判断，也不增加目标库、路由或发布许可。

### 当前前置与 C01

`goal_audience` 是每篇内容的必要判断，当前记录不允许 `not_applicable`。信息不足可如实记录 `missing_input`，但 `require_preflight` 只有它为 `ready` 且其他前置没有缺项时才允许继续。体验、娱乐或日常记录也可以有自己的目的，不要求商业转化或教育观众。

当前 C01 不允许用 `not_applicable` 跳过实际产物。为已执行状态（`findings`、`retained`、`revised_verified`）时，除原有产物 `quote`、理由、证据和问题引用外，还要求：

1. `evidence[]` 至少包含一项与 `goal_audience.evidence[]` **相同 path、sha256、quote** 的目的来源。这使当前产物和同一份目的记录相连；不能只引用一个无关、格式正确的文件。
2. `purpose_alignment` 对象填写四项具体说明：

| 字段 | 要说明什么 |
|---|---|
| `stage_duty` | 本阶段对本篇目的承担什么职责 |
| `contribution` | 当前引用的标题、段落或安排怎样贡献；可直接，也可间接 |
| `misunderstanding_risk` | 本阶段可能引入什么期待或误解；没有发现时也说明检查范围 |
| `tradeoff` | 为什么采取这一取舍，保留了什么，接受了哪些限制 |

这四项不能空白或只写“通过”。机器检查字段、引用和记录链，**不判定这些解释在语义上成立**。真正的期待失配仍需编辑者写为具体问题，并按现有必改处置规则处理。目的引用存在不能替代事实、作者判断、权益与制作边界。

目的与表面表达不需要一一重复。数字标题可以吸引目标人群，正文再解释过程；说明和故事可以服务同一目的；环境声、停顿、幽默、审美与生活细节也可承担体验或节奏职责。代码不按目的枚举固定路由，不要求三行封面、固定句式、固定故事结构或强制行动引导。

### 结果、复用与历史

新增 `purpose_continuity_complete` 单独表示：当前目的前置为 `ready`，C01 已执行并具备同源证据和上述职责说明。它不等同于 `proves_editorial_quality`，不证明观众理解、信任或转化。当前 `may_advance` 在原条件之外也要求这一项完成。

原有 `editorial_feedback`、`feedback_ids` 和 `changes` 规则继续生效。C01 反馈先更新前置，再复核受影响判断；不能只复制旧推荐。仅影响 C07 的技术/媒体反馈无需重做仍有效的 C01，但新记录必须承接该反馈。声称 `reuse_from` 时，原 C01 的目的证据与 `purpose_alignment` 也须保持一致；职责或取舍已改变，应记为新评估，而不是暗改复用记录。

`historical=True` 仍可回放缺少本节字段的旧记录，保留当时检查覆盖；缺字段不会被补成新的 `purpose_continuity_complete=true`。历史回放的 `may_advance` 恒为 false，不能用历史查询为当前继续、重剪或发布放行。旧文件、哈希和回执不回写；真正续办时依据当前事实追加记录。

### 五字段变动记录

- **意图**：避免只填写目标、只完成检查记录，就被解释为目的已落实到产物。
- **决策**：复用 `goal_audience` 与 C01，同源目的证据和阶段职责说明成为当前完整性要求；保留旧记录回放与局部复用。
- **理由**：全篇目的共同约束取舍，各阶段可以承担不同职责、选择不同方法；记录完整与语义正确、作者采用、受众效果需要分别判断。
- **证据**：本轮 `P1-目的贯穿覆盖盘点.md` 指出的独立包装推荐与后续评估差异；现有 `editorial_integrity.py` 前置、反馈与版本机制。新增合成测试定义见 `tests/test_editorial_integrity.py`，实际执行结果以本轮独立测试回执为准。
- **生效范围**：当前/新续办的编辑前置和 C01 记录、对应合成测试；不改锁定稿、视频、字幕、作者选择或导出暂停状态。不会将合成通过解释为本案媒体或传播效果已验收。
