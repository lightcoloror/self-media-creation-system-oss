# 采用结果与发布反馈的只读接入

更新：2026-09-12 19:25:37（Asia/Shanghai）。实际工具/模型：Codex / GPT-6 Astra / high。

稳定入口：`scripts/outcome_feedback_link.py`。它输出待审候选，不写真实经营库或 outcome ledger。

## 意图、决策、理由、证据、范围、回滚

- 意图：用 content_id、closure_run_id、account_id 把内容候选、人工采用结果、修改耗时、返工原因和发布观察串起来。
- 决策：只增加自媒体侧适配器。复用 candidate_feedback_batch 的 tracker 输入组装、publication_feedback_tracker 的窗口/指标/信号门、content_operations_cycle 的经营记录和隐私批准门，直接导入跨 Owner 的 outcome_ledger 默认构造、validate 和 review_packet。
- 理由：这些模块已经有独立合同和状态机。本次只补三重身份绑定、时间证据、只读映射与可恢复输出；不复制账本，不移除 synthetic-only 限制。
- 证据：`<workspace>/outputs/content-outcome-feedback-link-20260912-01/acceptance-current.json`。21 项定向测试、四种采用决策、四笔虚构经营操作、真实 CLI 暂停/恢复与重复执行字节/时间戳不变。
- 范围：本入口和本次产物。原 tracker/batch/cycle、outcome_ledger、原生合同集、前项公开候选均保持原 SHA。任务卡称 13 张合同；实际载入的现有原子合同集为 14 张、版本 1.1.0，本次没有改动合同。
- 回滚：停止消费本入口即可。保留历史目录和既存 dirty；不删除账本、候选、回执，不改变共享 Registry 或服务。

## 以后怎样提交人工结果

1. `map-candidate` 读取固定 SHA 的 Content 候选，生成空的 request 和待审包。候选需有 `channels.article.platform_metadata.qrp_candidate_binding.closure_run_id`；隔离虚构输入使用 `outcome_feedback_binding.closure_run_id`。
2. 若提交账号相关结果，`--account-id` 必须已存在于该受审核 Content 版本的 operating_refs。不能给未关联账号的旧候选凭空加账号。本次公开候选尚无账号关联，默认 account_id=null、no_decision/unknown。
3. 人工补齐 request 的 outcome 与本地脱敏证据。每条事件携带同一 content_id/closure_run_id/account_id。decision 支持 adopted、adopted_with_edits、discarded、no_decision；有修改需给 started_at、ended_at、category、reason 及相同内容的 hash-bound 时间证据。修改耗时不等于节省时间，本入口的 time_saved_minutes 必须为空。
4. 人工发布或观察的正式记录仍使用已有 `content_operations_cycle.py record-publication / record-snapshot / build-review`。脱敏经营输入要求既有 privacy_review credential，绑定操作、范围哈希、审核人和时间。适配器不制作批准凭据，不替人批准或执行入库。
5. 可把待录入的原生请求放进 native_requests。适配器调用现有 validator：缺批准凭据显示 privacy_review_required，已通过也只标记 pending_manual_record。它不会据此认定已发布。
6. 发布已由既有记录器登记后，publication 只填写其 store_ref 与 publication_id。适配器只读校验完整 journal、控制文件、内容版本 SHA 与账号，才建立观察窗口。观察放在 observations；缺值保持 unknown/unavailable，缺窗口保留 unknown，不用虚构快照补齐。

示例（在工作区运行；SHA 来自已审核文件，不由适配器猜测）：

```powershell
python -X utf8 -B self-media-creation-system/scripts/outcome_feedback_link.py map-candidate --candidate-ref <workspace-relative-content-item.json> --sha256 <reviewed-sha256> --submitted-at <ISO-time-with-timezone> --output <new-workspace-output-dir>
python -X utf8 -B self-media-creation-system/scripts/outcome_feedback_link.py prepare --input <manual-request.json> --sha256 <reviewed-request-sha256> --output <new-workspace-output-dir>
```

本次公开空白请求可从 `<workspace>/outputs/content-outcome-feedback-link-20260912-01/public-current/request.json` 复制后填写，原文件与原候选保留不覆盖。虚构的完整例子位于 `self-media-creation-system/.runtime/outcome-feedback-link-synthetic-20260912-01/request.json`，不可作为真实经营事件使用。

## 输出与恢复

输出包括 request.json、review-packet.json、outcome-candidate.json 和最终 receipt.json。outcome-candidate 是通过跨 Owner native validator 的送审记录，不是账本追加。复用默认构造时删除了“调用成功/失败”的默认观察及 call_record_hash，改用 candidate_binding_sha256；没有 Provider 调用时不能产生一次失败调用的暗示。

`--stop-after 1` 可注入写入中断；去掉参数用同一输入恢复。全部既存输出先比对，再补写缺失文件；漂移拒绝覆盖。完成消费条件是最终 receipt 存在且重跑校验成功。改代码或改输入使用新目录。scheduled_tasks 始终为空，本入口不创建自动化或提醒。

early 窗口为发布后 48–72 小时，d7 为 156–180 小时，均来自既有 tracker。六层测量保持原合同，播放/点赞/收藏不能进入业务信号。content_no_signal 对应 insufficient-evidence，不表示客户负面或选题失败。未来真实反馈仍需审核；本轮只有明确虚构的操作回归及公开候选只读映射。
