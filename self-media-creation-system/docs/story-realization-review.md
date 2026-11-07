# 故事设计到正文的验收

2026-11-02 20:20:00 +08:00 | Codex (gpt-6.1-sol)

新录制前故事路线在既有门禁中绑定当前 Story Design Card，不新增发布状态。解释路线保持自身检查；故事卡通过不能替代正文审查。

1. `draft-prerecord-case` 的 context manifest 追加 `source_role=story-design-card`，指向当前有效卡。故事脚本写入 `structure_route=story-arc`；门禁核对卡片、事实修订及 content_id。故事卡缺失不能完成草稿步骤。
2. 用既有 initial-draft review template 命令加 `--structure-route story-arc --story-card <card.json>` 生成待审核模板。直接解释用 `--structure-route direct-answer`，不提交故事卡。
3. 在原审核回执的 `story_realization` 中逐项填目标、场景、激励事件、期望落差、压力、选择、每个转折、高潮、结局及情绪动作依据。每项注明真实 `segment_id`、`spoken_span`、该段和卡片共有的 `fact_refs` 及具体判断。缺材料使用 `material_gap`，需修改使用 `needs_revision`，沿用 `return_for_revision`。模板不自动通过。
4. 对白、潜台词与人物声音逐项判断适用性。没有原话时说明 `not_applicable`，不编造对白。故事必要要素不得用不适用跳过；不能把同一句话粘贴到所有项目证明完整故事。
5. initial-draft validate 同样传路线与故事卡。声纹改写请求的 `semantic_review.story_realization` 必须针对改后正文重新审核，human_voice_gate 加 `--story-card`。卡片、事实或正文变化使旧审核失效。
6. 后续录制前时间证据仍须使用同一故事路线和卡片。正文变更不能仅复用旧故事卡审核，故事卡并不冻结正文。

该检查保证句段、引用、覆盖和版本一致，不能证明填报者的语义判断正确，更不能证明观众共鸣。保留作者复核、真实反馈和人工发布边界。历史回执可供检查，新执行必须补当前证据。

实现：`content-studio-poc/scripts/narrative_realization.py`、`initial_draft_quality_gate.py`、`human_voice_gate.py` 与本项目 `scripts/prerecording_validation.py`。

## 图文、朋友圈和普通文本

既有作者编辑记录的 `route=story` 时，在 C04 结构推进检查里提供 `story_card_ref`（path/sha256）和 `story_realization`。纯文本按非空行依次使用 `text-0001`、`text-0002` 作为句段编号；`input_body_sha256` 是既有 `draft_text` 输出 UTF-8 文本的 SHA-256。其余要素合同复用同一匹配器；事实含义仍由 C02 和编辑者核对。缺故事证据可以记录为未完成，但 `story_realization_complete=false`、`may_advance=false`；重排或改稿后不能复用旧判断。历史记录可回放，不自动升级。
