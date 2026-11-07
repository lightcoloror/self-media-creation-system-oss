# Handoff

## Header

- Message-ID: `SMALL-MODEL-CONTENT-CANDIDATE-LOOP-20260827-01`
- From: `content-creation-self-media-owner`
- To: `fresh-gpt-5.6-luna-low`
- Date: `2026-08-28T01:16:15+08:00`
- Subject: 用一条稳定命令完成合成证据到候选内容与平台变体闭环
- References: `小模型自主闭环优化派发包-2026-08-27.md`

## Body

只读取 `AGENT_DISCOVERY.md` 和 `fixtures/small-model-content-loop-v1/compact-handoff.v1.json`。先运行 doctor，再运行正向闭环；随后在另一个 run-root 暂停到 candidate 并显式 resume；最后按 `negative-cases.json` 验证至少五种错误会以零重试方式阻断。

不要读源码、测试、聊天记录或真实资料。不要改输入夹具，不要调用模型、网络、平台账号或发布功能。成功只表示生成 `candidate_only / review_required / manual-only` 的本地候选，不表示内容已经审核或可以发布。

## Attachments

- `fixtures/small-model-content-loop-v1/compact-handoff.v1.json`
- `fixtures/small-model-content-loop-v1/input.valid.json`
- `fixtures/small-model-content-loop-v1/negative-cases.json`

## Status

`pending`

## Recovery

暂停后只能使用 handoff 中的 `resume` 命令。出现 hash、route、privacy、fact、human-voice 或 finalize 错误时停止；`automatic_retries` 必须为 `0`。

Metadata: Codex (GPT-5.6 Sol), 2026-08-28 01:16:15 +08:00.
