# 故事素材候选入口

更新时间：2026-09-03 18:00:00 +08:00
执行工具／模型：Codex (GPT-5.6 Sol)

## 定位

`story-material-observation.v1` 是追加式、已脱敏的故事瞬间候选，不是第二套内容状态机。它只回答：这段真实材料是否已经具备进入现有 `story-design-card.v1` 的最小信息。

它不写稿、不读取知识库、不访问平台、不联系客户，也不授予发布权。`ready-for-story-design` 仍必须经过事实卡、故事设计、医疗保险、隐私、人声和人工发布门。

## 收集字段

- 来源模式、授权状态、身份处理和证据状态；
- 主角目标、原有平衡、触发事件；
- 第一次行动和现实反馈；
- 最难的选择、结果与代价；
- 可选的感官细节；
- 观众可能理解的意义；
- 已确认原话、明确标注的转述，或不使用引语。

感官细节不是必填项。没有证据时应写 `unknown`，不能为了画面感补写。

## 稳定命令

```powershell
python scripts/story_material_inbox.py check
python scripts/story_material_inbox.py evaluate --input fixtures/story-material-observation-v1/synthetic.input.json
```

人工确认已脱敏后，才可以显式追加：

```powershell
python scripts/story_material_inbox.py capture `
  --input path/to/deidentified-story-material-input.json
```

默认账本是 `research-ledgers/story-material-observations.v1.jsonl`。相同材料重复提交返回 `already-recorded`；相同 ID 不同哈希会阻断。

## 进入故事设计的条件

除感官细节外，核心字段必须齐全；证据状态必须是 `user-confirmed` 或 `verified-source`；隐私必须通过；采访和可识别身份必须有确认授权。未满足时保留为 `incomplete`，不会自动升级为故事、稿件或发布候选。

## 变更依据

- 意图：把日常真实瞬间稳定积累为可审计故事候选。
- 决策：增加 append-only 观察对象和薄 CLI，继续复用既有事实卡与故事设计门。
- 理由：素材发现和成稿应分开；不完整材料应保留未知项而不是被模型补齐。
- 证据：本地故事方法笔记、`insurance-content-storycraft` 和 `story-design-card.v1`。
- 生效范围：本地、候选态、人工脱敏后的故事素材收集。
- 回滚：删除本 Schema、fixture、CLI、测试和文档，并从统一 checker 移除 doctor；不改动历史事实卡、内容对象或发布记录。
