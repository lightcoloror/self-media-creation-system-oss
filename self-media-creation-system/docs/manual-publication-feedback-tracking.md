# 人工发布后的最小反馈追踪

> Acting tool/model: Codex (GPT-5.6 Sol)
> Updated at: 2026-08-10 18:02:57 +08:00
> Status: synthetic-only, manual-entry-only, no publication or CRM execution

> 2026-08-30 update: 冷启动增长指标、关注诊断率与生产能力记录已经复用现有合同落地，详见 `docs/cold-start-four-week-metrics-recording.md`。

## 目的

这条薄适配器复用现有 `account`、`topic`、`content-item`、`publication-event`、`performance-snapshot` 合同。人工确认一条内容已经发布后，以 `publication-event.occurred_at` 为唯一时间起点，建立两个固定观察窗口：

- `early`：发布后 48–72 小时；合成样例使用 60 小时。
- `d7`：发布后 156–180 小时；合成样例使用 168 小时。

系统不登录账号、不调用平台 API、不抓取实时数据，也不执行发布。当前 importer 只接受完全虚构材料；未来真实记录仍需由用户人工提供最小字段并经过另行审核。

## 六层记录

| 层 | 记录什么 | 不能推导什么 |
|---|---|---|
| 准入 `admission` | 是否正常发布、是否被平台处理 | 不能推导内容质量 |
| 吸引 `attraction` | 曝光、播放、点击、触达 | 不能推导客户意向 |
| 消费 `consumption` | 停留、阅读深度、完播 | 不能推导业务关系 |
| 价值 `value` | 点赞、收藏、分享、评论数量 | 不能自动升级为业务信号 |
| 负反馈 `negative_feedback` | 隐藏、举报、取关等聚合数量 | 不保存原评论和身份信息 |
| 业务 `business` | 明确继续咨询、主动提供必要资料、预约下一步 | 仍需人工确认，不能自动写 CRM |

业务层只接受三个事件类型：

- `continued_consultation`
- `necessary_documents_provided`
- `next_step_booked`

播放、点赞、收藏、分享和评论数量始终属于内容信号。没有观察值时记录 `content_no_signal`，同时保留 `learning_decision=insufficient-evidence`；它不表示客户负面、选题失败或 CRM 状态。

## 稳定命令

在 `<workspace>\self-media-creation-system` 执行：

```powershell
python -B scripts\publication_feedback_tracker.py generate
python -B scripts\publication_feedback_tracker.py validate
python -B scripts\publication_feedback_tracker.py check
```

`check` 同时验证既有五张 Schema、时间窗口、引用关系、信号分层、隐私边界、review packet 和双跑字节幂等。统一总检查入口仍是：

```powershell
python -B scripts\check_self_media_contracts.py
```

## 输入与输出

人工录入模板：

- `templates/manual-publication-feedback-input.v1.synthetic.json`

生成的合成追踪包：

- `fixtures/manual-publication-feedback-v1/publication-events.json`
- `fixtures/manual-publication-feedback-v1/performance-snapshots.json`
- `fixtures/manual-publication-feedback-v1/content-item.json`
- `fixtures/manual-publication-feedback-v1/review-packet.json`
- `fixtures/manual-publication-feedback-v1/manifest.json`

`review-packet.json` 只进入 `vibe-living-pending-acceptance`，`execution_authorized=false`。它不写 vibe-living、CRM 或任何真实业务数据。

## 未来记录真实发布时所需的最小字段

这不是当前 synthetic importer 的授权范围。未来若建立真实记录，用户只需人工提供：

1. 已有 `account_id`、`topic_id`、`content_id`。
2. 平台名称、说明性标题、人工确认的发布时间、登记时间和渠道版本。
3. 48–72 小时与第 7 天各自的 `as_of`、`captured_at`、完整性状态。
4. 各层可见的聚合数值；没有数值就标 unavailable，不猜测。
5. 可选业务事件只记录事件类型、发生时间和脱敏本地引用；仍需人工确认。

不得录入：平台 token/cookie、带追踪参数的链接、客户姓名和联系方式、健康或保单细节、评论/私信原文、可重新识别客户的时间线。

## Fail-closed 负例

提交的负例覆盖：来源 hash 陈旧、缺少第 7 天窗口、重复窗口/快照、重复指标、窗口漂移、观察录入过期、原始评论字段、追踪参数、点赞错误升级为业务信号、手工伪造派生增长率、留存顺序异常、派生指标漂移、重复发布事件，以及把 `content_no_signal` 升级为客户负面结论。

## 候选包到反馈的离线桥接

> Acting tool/model: Codex (GPT-5.6 Sol)
> Updated at: 2026-08-31 10:00:00 +08:00
> Status: synthetic-only verification; it is not a publication log or real-usage proof.

当一个已经通过内容候选门的包需要验证“发布后会怎样记录”时，使用薄适配器而不是再造一套反馈状态机：

```powershell
python -B scripts\candidate_feedback_batch.py check `
  --plan <repository-relative-synthetic-plan.json> `
  --output .runtime\candidate-feedback-batch-check
```

仓库回归不依赖历史 `.runtime` 产物：`tests/test_candidate_feedback_batch.py` 会从已提交的合成内容对象模板构造隔离计划、三个候选及哈希引用，并在测试结束后清理。真实使用时也应生成新的仓库内合成计划，不能把某次运行目录当作可移植 fixture。

该适配器只接受三个明确标记为 `synthetic-only` 的候选，并对候选包、上游 run manifest、review packet 和前序 dispatch receipt 做 SHA-256 绑定。每条链由现有 `publication_feedback_tracker.py` 生成一个稳定的 `publication_event`、`early`（48–72 小时）和 `d7`（156–180 小时）快照以及 review packet。它不登录平台，不发内容，也不会使用真实账号、客户、评论、URL 或 CRM。

额外的批次回执只补足人工边界，而不覆盖既有合同：`manual_action=true`、`synthetic_only=true`、`external_action_performed=false`、冻结内容哈希和人工登记的发布时间。该回执表示“未来真实人工发布时应当怎样记录”，不表示已经发生了人工发布。

本轮三条合成链分别覆盖：

- `policy-inventory`：两个观察窗口均为 `content_no_signal`，业务层仍是 `not-observed`，不产生任何客户负面、选题失败或 CRM 结论。
- `claim-contact`：有合成播放/留存/收藏等内容信号，但没有业务事件；这些数值仍不能推导咨询意向。
- `medical-vs-critical`：只有显式的 `continued_consultation` 才能进入业务层；仍保留 `manual_confirmation_required=true` 和 `crm_write_performed=false`。

未来真实人工录入仍只需要本页上方列出的最小字段。先由人确认内容真的已经发出，再分别在两个窗口人工汇总可见数值；任何真实登录、抓取、发布、客户联系或 CRM 写入都不属于这个命令的权限。
