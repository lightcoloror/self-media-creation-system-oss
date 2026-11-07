# 持续选题发现入口（P0）

更新时间：2026-09-01 19:21:05 +08:00
执行工具／模型：Codex (GPT-5.6 Sol)

## 定位

这是一层追加式输入事件，不是第二套选题状态机。正式主题仍使用：

`docs/content-creation-system/operations/topic.schema.json`

排序继续复用：

`scripts/high_frequency_topic_loop.py`

本入口不会扫描 Obsidian/Logseq，不调用模型，不访问平台，不写稿，不联系客户，不发布。

## 1. 快速记录一条已经脱敏的问题

真实使用前必须自行确认问题文本已经脱敏，并提供一个不可读的独立来源组；同一客户或同一事件重复提到时继续使用同一组。

```powershell
python scripts/topic_discovery_inbox.py capture `
  --question "家里买过几份保险，应该先怎么整理？" `
  --source-lane customer-question `
  --source-ref "manual://deidentified-note-20260901" `
  --independence-group "question-group-opaque-001" `
  --topic-key policy-inventory-first `
  --priority P0 `
  --risk low `
  --fact-dependency low `
  --privacy-passed `
  --counts-toward-frequency `
  --cluster-reviewed
```

只有用户明确确认“这是反复出现的同一类问题”时，才额外添加：

```text
--repeat-confirmed
```

不要把客户姓名、联系方式、保单号、疾病细节或原始聊天复制进命令。

## 2. 生成候选快照和每周 Top 5

```powershell
python scripts/topic_discovery_inbox.py build
```

默认读取：

`research-ledgers/topic-observations.v1.jsonl`

默认输出：

`outputs/draft-only/continuous-topic-discovery/`

输出包括：

- `candidate-source.json`：兼容现有高频问题评分器的候选源；
- `ranked-topics.json`：现有评分逻辑的结果；
- `qualified-topics.json`：把可排序观察与已通过资格门的候选分开；
- `weekly-topics.md`：人工审阅的 Top 5；
- `manifest.json`：输入哈希、输出哈希和 manual-only 边界。

## 3. 验证

```powershell
python scripts/topic_discovery_inbox.py doctor
python scripts/topic_discovery_inbox.py validate-bundle
```

## 当前未启用

- Obsidian/Logseq 白名单增量扫描；
- 发布反馈自动导入；
- web-content-fetcher 归档增量导入；
- AI 语义聚类建议；
- 每日或每周计划任务。

这些属于 P1/P2。启用知识库或平台来源前必须先明确允许的目录、来源和隐私边界。

## 变更依据

- 意图：让真实问题持续进入现有选题排序器。
- 决策：增加 append-only observation ledger 和薄 CLI，不复制 topic 生命周期。
- 理由：把需求频次与事实支持分开，保持来源可追溯、幂等和 fail-closed。
- 证据：现有 `topic.schema.json`、`high_frequency_topic_loop.py`、`content_operations_cycle.py` 与 registered-content-routing 1.1.0。
- 生效范围：仅本地候选发现与 draft-only 周报。
- 回滚：删除本次新增的 schema、CLI、fixture、测试和文档；未修改现有权威合同或历史候选源。
