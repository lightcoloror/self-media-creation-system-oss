# Agent 流程顺序与完成声明门

更新时间：2026-09-05 21:33:11 +08:00
执行工具／模型：Codex (GPT-6 Astra)

## 问题

任务胶囊已经列出步骤，`prepare-step` 也会验证直接前置回执，但 Agent 仍可能绕开入口直接写稿，或在只完成部分步骤时口头宣称“完整流程已走完”。另一个风险是把通用回执的哈希和传输成功误当成 Owner 已完成事实、合规、人声或人工审核。

## 唯一流程游标

本仓不增加第二套状态机。`sequence-status` 只根据当前 capsule 和按 `step_index` 顺序提供的真实回执，重新验证整条前缀并派生唯一下一步：

```text
python scripts/self_media_agent.py sequence-status --capsule <capsule.json>
python scripts/self_media_agent.py sequence-status --capsule <capsule.json> --receipt <step-1-receipt.json> --receipt <step-2-receipt.json>
python scripts/self_media_agent.py sequence-status --capsule <capsule.json> --receipt <ordered-receipts...> --require-complete
```

执行规则：

1. 每完成一步，先运行 `verify-step-output`，再把该回执追加到 `sequence-status`。
2. 只执行返回值中的一个 `next_step`，不凭记忆选择后续步骤。
3. 回执缺失、重复、乱序、跨 capsule、哈希漂移或前一步 blocked 均失败关闭。
4. 交付前必须执行 `--require-complete`。步骤虽齐全但只有 `transport_and_sequence_only` 的，返回 `owner_semantics_pending`，不能宣称“完整受管流程完成”。
5. 人工门仍必须由真人完成；流程游标不能证明真人身份、真实阅读或真实创作效果，也不授予发布权限。

## 状态语义

- `next_step_required`：只允许准备返回的下一步。
- `blocked`：停止，不得绕行。
- `sequence_complete_owner_semantics_pending`：形式步骤齐全，但仍欠 Owner 语义证据。
- `sequence_complete`：步骤与已有 Owner 语义校验均齐全；仍只表示受管候选链完成，不等于已发布。

## 变更依据

- 意图：让弱 Agent 不靠长上下文记忆流程，并阻止漏步骤后的虚假完成声明。
- 决策：在现有 capsule、handoff 和 receipt 上增加只读派生游标，不持久化平行状态。
- 理由：单靠说明文档和“请记得”无法执行阻断；直接 状态机又会造成双重真值。
- 证据：现有 `_validate_previous_step` 已能递归验前缀，但此前没有面向 Agent 的唯一下一步与收口命令；通用回执明确只证明 `transport_and_sequence_only`。
- 生效范围：由 `self_media_agent.py` 管理的五条 recipe 及录制前变体；自由聊天和未进入胶囊的稿件不能冒充受管流程产物。
- 回滚：移除 sequence schema、CLI、测试和文档，并回退 manifest/catalog 小版本；不得改写历史任务回执或删除业务产物。
