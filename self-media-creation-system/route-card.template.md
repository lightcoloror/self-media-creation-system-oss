# 内容路由卡模板

> 每条内容只填一张；不确定项写“待核”，不靠 AI 补齐。
> 发布后另建 `publication-event` 与 `performance-snapshot`，不要回头覆盖本卡。
> 更新时间：2026-08-13 23:45:18
> 执行者：Codex（GPT-5.6 Sol）

## 1. 任务定义

```yaml
route_id: route-YYYYMMDD-short-name
task_type: topic-selection | research | planning | interview | draft | rewrite | title | script | visual-brief | review | retrospective
account_ip: cange-risk-diagnosis | cange-growth | dual-account-shared | personal-wechat-moments
content_job: story | mechanism-explanation | tool-or-checklist | case-review | trust-building | collaborator-recruitment | product-demo | question-answer | opinion | business-conversion
primary_audience: 谁；处于什么情境
primary_goal: relationship-touch | search-discovery | understanding | save-for-later | trust | discussion | consultation | collaboration | conversion | learning
structure_route: direct-answer | decision-reframe | scenario-branch | gap-diagnosis | tradeoff-comparison | case-review | mechanism-explanation | tool-action | boundary-map | story-arc | opinion-argument | custom
structure_route_note: 为什么这条路线最符合本篇读者任务；custom 时写展开顺序
format: moments-short-text | graphic-note | short-video-narration | demo-video | interview-video | long-video | live | longform-article
platform: wechat-moments | xiaohongshu | wechat-video | douyin | bilibili | wechat-article
```

规则：`primary_goal` 只能选一个。若同时想“建立信任、被收藏、获得咨询”，先选此篇最重要的一个，其余只记为副作用。

`structure_route` 是可选展开路线，不是每篇必套的结构模板。选择方法见 [内容结构路线库与人工改道规则](./structure-route-playbook.md)。`content_job` 说明“做什么”，`structure_route` 说明“怎么展开”，`format` 说明“怎么被消费”。

### 1a. 问答型选题的结构分流

问答型内容先选择路线；案例、故事、工具、机制、观点等可写 `not-applicable`。详细规则见 [问答选题分流与条件式重构操作卡](./topic-reframing-playbook.md)。

```yaml
question_structure_route: direct-answer | decision-reframe | not-applicable
audience_entry_question: 普通人实际会问、会搜的话
surface_answer: 先用一句话回应原问题
hidden_assumptions: []
professional_core_question: 专业人士认为真正要回答的问题
client_decision: 读者最终要完成的一个判断或动作
public_value_bridge:
  misconception: 本篇只纠正的一个误区
  distinction: 本篇只拆开的一个关键区别
  action: 本篇只给出的一个立即行动
scope_boundary: 特殊人群、例外和后续问题
backstage_research_refs: []
```

`direct-answer` 只需原问题、直接答案和必要边界，不强制填写真正问题和客户决定。只有 `decision-reframe` 才填写完整字段，并使用“一个误区、一个关键区别、一个行动”。

`question_structure_route` 与 `structure_route` 可以不同：例如原问题本身准确但答案因人而异，可写 `question_structure_route: direct-answer`、`structure_route: scenario-branch`；表面问题需要重构后再查缺口，可写 `decision-reframe` 与 `gap-diagnosis`。

### 1b. 系列规划与人工改道（仅在使用时）

```yaml
planning_scope: single | series
series_question: 整个系列回答的大问题
current_piece_decision: 本篇只解决的一个问题
next_piece_candidates: []
manual_route_override:
  stage: topic | research | outline | draft | review
  from: 原路线
  to: 新路线
  reason: 改道理由
  changed_by: human
```

系列拆解不是单篇正文结构；每一篇仍单独选路线。人工可在任意阶段改动任意环节，不需要统一界面；改道后按操作卡只重跑受影响部分。

## 2. 事实与边界

```yaml
source_basis:
  - user-confirmed-personal-experience | published-final | first-party-record | official-source | ai-draft | candidate
facts_to_say: []
personal_experience_to_say: []
unknowns_or_pending_checks: []
privacy_level: none | deidentified | consent-required | blocked
medical_insurance_boundary: 不替代医生决策；不承诺承保或赔付；以合同与实际审核为准
rights_status: original | licensed | pending | blocked
```

只有 `task_type: research` 或 `origin_kind: research-synthesis` 时补充：

```yaml
research_packet_ref: 本地证据包路径；未建立则留空
discovery_question: 本轮究竟要回答什么
discovery_sources: [peer-post, visible-comment, search-result]
authority_sources: [official-platform, regulator, insurer-disclosure, contract-clause]
claim_status: candidate | conflicted | verified | rejected | unknown
copyright_boundary: 只存问题、短证据摘记和来源引用；不拼接原文、不复用原图
```

## 3. 形式、渠道、声纹与视觉

如需使用情绪共鸣、证据型槽点、受众嘴替或行动型价值认同，先填写
[内容作用机制补充卡](./route-card.effect-mechanisms-supplement.md)。机制不是必选项：

```yaml
primary_effect: none | emotional-resonance | evidence-backed-friction | audience-voice | value-alignment
secondary_effect: none | emotional-resonance | evidence-backed-friction | audience-voice | value-alignment
effect_card_ref:
```

```yaml
format_adapter: 对应 format-adapters.json 的 id
platform_overlay: 对应 platform-overlays.json 的 id
voice_route: 本人朋友圈表达 | 灿哥诊风险服务叙事 | 灿哥精进工具表达 | 双号共享项目表达
visual_route: 按主题、受众、阅读任务和使用情境选择；不使用固定账号皮肤
```

## 4. 这次只验证什么

```yaml
hypothesis: 如果……，那么……；因为……
variable_to_change: 仅一个变量，例如开头、封面承诺、案例节点或图文结构
constants: 其余保持不变的条件
observation_window: 发布后 48–72 小时 / 第 7 天 / 无可观察指标
success_signal: 与 primary_goal 对应的可观察信号
no_signal_meaning: no_signal，不推断为内容无效或关系无效
stop_condition: 何时停止继续改、继续投放或继续拆分
```

## 5. 生成与审核回执

```yaml
skills_used: []
skill_outputs_accepted: []
skill_outputs_rejected_or_modified: []
hard_gates: [fact, privacy, medical_insurance, rights, publication]
soft_gates: [topic_structure_fit, audience_appropriate_expertise, format, voice, clear_communication, accessibility]
human_reviewer: 用户本人
freeze_status: draft | reviewed | final-frozen | published
```

## 最小决策树

```text
事实或授权不清？ → 停在研究/采访，不成稿。
内容要怎样展开？ → 从可选路线库选一条主路线；都不贴合时用 custom。
问答型真实问题？ → 另判断直接回答还是条件式重构；其他题材不套问答结构。
先选形式；再选平台。 → 不要先说“写一篇小红书”。
客户、医疗、儿童、理赔？ → 先跑加严质量门。
需要转化？ → 明示为 conversion，才可调用 copywriting；否则不用。
已经发出？ → 新建发布回执；不回写“效果好/不好”的主观结论。
```
