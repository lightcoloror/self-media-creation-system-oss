# vibe-living 全虚构内容闭环 fixture 消费说明

更新时间：2026-08-05 12:00:00 +08:00
执行者：Codex（GPT-5.6）

## 唯一消费入口

`fixtures/vibe-living-synthetic-loop-v1/consumer-manifest.json`

这是一个离线、只读、`synthetic_only` 的消费清单。它不是 CRM 导入文件，也不授权发布、联系客户或写入任何业务系统。

## 复用的权威合同

- `question-research-poc/schemas/research-output.v1.schema.json`
- `docs/content-creation-system/content-item.schema.json`
- `docs/content-creation-system/operations/account.schema.json`
- `docs/content-creation-system/operations/topic.schema.json`
- `docs/content-creation-system/operations/publication-event.schema.json`
- `docs/content-creation-system/operations/performance-snapshot.schema.json`
- `content-studio-poc/schemas/content-video-brief.v1.schema.json`

没有新增 topic、material、content、publication 或 performance 的平行 Schema。由于这些生产合同使用 `additionalProperties: false`，`synthetic_only=true` 由消费清单、每个清单条目、发布/快照 envelope 和 feedback handoff 共同携带；不能把这个标记硬塞进生产对象。

## 五个问题如何读取

`questions[]` 中每项都给出：

- `research_output_ref`：合成证据、claim、review 与 source 状态；
- `topic_ref`：现有 `topic.schema.json` 对象；
- `material_ref`：统一 `content-item` 的 `candidate` 快照；
- `content_draft_ref`：同一 `content_id` 的 `draft` 快照；
- `article_ref`：现有 research-output adapter 生成的 draft-only Markdown；
- `video_brief_ref`：现有 adapter 生成的 draft-only 视频简报。

`synthetic_frequency_count` 只是 fixture 输入，用来检验排序和引用，不证明现实世界中问题的频率。

## 三组发布与反馈如何读取

`publication_feedback_cases[]` 中每项都给出：

- `publication_events_ref`：两条现有 publication-event 合同事件；
- `performance_snapshots_ref`：48–72 小时和第 7 天的现有 performance-snapshot 合同快照；
- `feedback_handoff_ref`：沿用《insurance-client-action-recording-decision-2026-06-22》的信号分层字段。

判定规则：

1. `content_no_signal` 永远只进入 `content_observation`。
2. 播放、点赞、收藏只是内容指标，不自动生成 `relationship_signal` 或 `crm_candidate`。
3. 只有 `continued_consultation`、`necessary_documents_provided`、`next_step_booked` 三类明确事件可以形成 `crm_candidate`。
4. `crm_candidate` 必须保持 `pending_human_confirmation`、`confirmed=false`、`manual_confirmation_required=true`。
5. 所有记录固定 `analysis_only=true`、`execution_allowed=false`、`do_not_auto_contact=true`。

## 验证命令

```powershell
python -B scripts\vibe_living_synthetic_fixture_pack.py validate
python -B scripts\vibe_living_synthetic_fixture_pack.py check
python -B scripts\check_self_media_contracts.py --no-tests
python -B -m unittest tests.test_vibe_living_synthetic_fixture_pack -v
```

`check` 会进行 schema、引用、信号边界、六个负例和双跑字节级幂等检查。

## vibe-living 消费边界

vibe-living 只能把本清单作为 UI/导入兼容测试的只读输入：

- 可以显示 synthetic topic、draft、publication observation 和待人工确认候选；
- 不得把任何记录写成真实客户、真实机会、客户下一步或正式 CRM 数据；
- 不得把合成计数用于业务判断；
- 不得自动联系任何人；
- 不得发布任何草稿。

## 回滚

删除本次新增的 seed、生成目录、生成/验证脚本、测试和本说明，并从 `scripts/check_self_media_contracts.py` 移除 `VIBE_FIXTURE` 导入及验证调用即可；现有生产 Schema 和既有 fixture 不需要回滚。
