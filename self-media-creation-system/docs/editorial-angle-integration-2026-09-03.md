# 素材—争点—议程—选题与故事五问接入说明

- 状态：local operational extension
- Acting tool/model：Codex (GPT-5.6 Sol)
- 更新时间：2026-09-03 20:39:37 +08:00
- 派发：`SELF-MEDIA-EDITORIAL-ANGLE-INTEGRATION-20260903-01`

## 决策

现有内容主链不变：`topic-observation.v1` 仍负责保存脱敏观察，`story-design-card.v1` 仍是故事设计权威合同，content item 与人工发布状态也没有变化。

本次只在两处补薄层：

```text
topic-observation.v1
→ topic-angle-decision.v1（至少三个争点＋一个议程一致的提议）
→ 人工确认争点
→ 原有研究／写稿／包装／发布审核

故事五问
→ story-five-question-adapter.v1（一致性视图）
→ story-design-card.v1（唯一故事权威）
```

## 为什么需要这一层

素材只是发生了什么，同一素材通常能产生多个切入角度。选题必须同时说明：面向谁、解决什么、希望受众思考什么、以什么方式理解、哪些角度没有采用，以及为什么。传播潜力和新颖度只能是待验证假设，不能覆盖账号定位、证据与风险。

`topic-angle-decision.v1` 因此不自动打普适分数，也不保存“平台权重”。它要求至少三个争点，显式拒绝偏离议程、无证据冲突、伪造客户案例、评论冒充事实和情绪操控。

每个候选显式记录 `audience_question`、`evidence_readiness`、`trust_value`、`business_relevance`、`compliance_risk` 与 `novelty_or_timeliness`。这样小模型可以直接读取判断依据，不必从散文描述里自行猜测。

## 来源采用边界

采用为 `candidate_experience` 的本地二次整理材料：

<!-- Private manuscript, case-history or local course-file reference omitted from the public edition. -->
<!-- Private manuscript, case-history or local course-file reference omitted from the public edition. -->

吸收：素材与选题分离、同一素材多争点、议程包含 what/how、传播与议程需要共同考虑、故事简化五问。

拒绝晋级为事实：播放量与成交量、1—3 分公式、百万播放预测、平台偏好、泛流量/精准流量的绝对判断，以及材料中的个案与权威表述。它们不能进入事实卡或作为平台规则。

实现复用仓库已有 `jsonschema` 校验、topic observation、Story Design Card、recipe/task capsule、人审门和 manual-only 发布边界；没有引入新开源依赖或第二套状态机。

## 稳定入口

```text
python scripts/topic_angle_decision.py check
python scripts/story_five_question_adapter.py check
python scripts/self_media_agent.py run-example --recipe moments-short-post
python scripts/self_media_agent.py run-example --recipe xhs-evidence-graphic
```

Luna low 或其他小上下文 Agent 只需读取 `AGENT_DISCOVERY.md`、任务请求和 `self_media_agent.py` 生成的紧凑 capsule。它可以提出候选争点，但不能替人完成 `confirm-editorial-angle`。

## 失败关闭

- 少于三个争点；
- 高传播假设但偏离议程的角度被选中；
- 冲突或反差在正文和证据中都不存在；
- 未确认客户案例、评论、帖子或搜索问题被当作事实；
- 经验分值被声明为平台真值；
- topic observation、evidence 或 Story Design Card 哈希漂移；
- 五问答案不在绑定的 Story Design Card 中；
- 任何自动发布、外发、客户联系或知识库写入权限出现。

## 变更依据

- 意图：让选题阶段先比较争点与议程，不再把素材直接写成标题。
- 决策：增加一个候选决策合同和一个 Story Card 视图适配器；人工选题确认仍是硬门。
- 理由：把经验变成可检查字段，同时避免把经验数字或简化问法升级为平台事实和新状态机。
- 证据：现有 Schema、两份本地二次整理材料、合成正负 fixture、幂等测试和任务胶囊回归。
- 生效范围：朋友圈、小红书图文在写稿前使用；案例视频消费上游回执，故事五问按需使用。
- 回滚：删除新增 Schema、脚本、fixtures 与 tests，移除 recipe/manifest/binding/discovery 中对应引用；原有 topic、story、content 与 publication 合同继续有效。
