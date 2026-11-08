# 内容作用机制补充卡

公开适配：2026-11-08，Codex（精确运行模型未独立核验）。第一方通用流程文档，保留原历史署名；源为共享工作快照，不冒充主流程仓库原提交的文件。文中的记录卡和示意内容不代表真实研究、制作、客户授权或发布已完成。

> 仅在需要“共鸣、槽点、嘴替、价值认同”时填写。没有充分证据就选 `none`。
> 规则详见 [内容作用机制](./content-effect-mechanisms.md)。

## A. 机制选择

```yaml
primary_effect: none | emotional-resonance | evidence-backed-friction | audience-voice | value-alignment
secondary_effect: none | emotional-resonance | evidence-backed-friction | audience-voice | value-alignment
why_this_effect_matches_primary_goal:
effect_evidence_confidence: high | medium | low | assumption
```

规则：

- 主机制只能选一个；辅机制最多一个。
- `assumption` 只能进入采访、选题验证或草稿，不得写成“用户都这样想”。
- 机制与首要目标不匹配时，保留清晰表达，选择 `none`。

## B. 受众证据

```yaml
audience_evidence:
  source_type: original-question | standardized-real-question | comment | search-log | interview | published-feedback | colleague-retelling | ai-draft | author-assumption
  evidence_refs: []
  quote_status: verbatim-cleared | standardized-paraphrase | not-quotable
  trigger_context:
  user_task_or_goal:
  evidence_gap:
```

## C. 只填写被选中的机制

```yaml
emotional_resonance:
  observable_detail:
  human_tension:
  felt_response:
  reader_bridge:
  disclosure_boundary:
  ending_mode: action | discovery | open-space | none

evidence_backed_friction:
  common_assumption:
  observed_mismatch:
  affected_party_and_cost:
  evidence_refs: []
  corrected_model_or_action:
  strawman_check: pass | fail
  hostility_check: pass | fail

audience_voice:
  source_phrase:
  source_phrase_status: verbatim | standardized | hypothesis
  surface_question:
  underlying_user_task:
  public_paraphrase:
  invented_quote_check: pass | fail

value_alignment:
  decision_point:
  reasonable_alternatives: []
  constraints_and_tradeoff:
  chosen_action:
  cost_or_consequence:
  implied_principle:
  moral_superiority_check: pass | fail
```

## D. 验证

```yaml
mechanism_hypothesis: 如果使用……，目标受众会更容易……
single_variable:
direct_content_signal:
platform_observable:
business_signal_separate: true
observation_window: 48–72h | day-7 | no-observable-metric
no_signal_meaning: no_signal
retire_or_revise_condition:
```

## 最小否决

```text
需要补造引语/冲突/情绪？ → 不用该机制。
真实问题未复核？ → 只能标 standardized 或 hypothesis。
槽点没有证据和修正模型？ → 改为普通问题说明。
价值观没有实际选择与代价？ → 删除价值升华。
敏感题材靠恐惧、羞辱或敌我成立？ → 阻断。
```
