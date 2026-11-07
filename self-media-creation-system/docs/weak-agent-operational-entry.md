# 小上下文 Agent 的自媒体流程入口

> 更新时间：2026-08-27 09:16:56 +08:00
> 执行者：Codex（GPT-5.6 Sol）
> 状态：local operational consumer ready
> 边界：只发现、解析和交接候选任务；不调用 Provider、不发布、不发送、不联系客户、不写 CRM 或知识库。

## 要解决的问题

原系统的事实、路由、Skill、格式、平台、发布和反馈合同已经较完整，但入口分散。能力较弱或上下文较小的 Agent 容易出现四种错误：读完整仓库后仍选错路线；把旧 snapshot 和 Registered 路由混搭；为了补齐缺失输入而编造事实；把 `publish-ready` 当成发布授权。

本次没有新建路由器或内容状态机，而是在既有 canonical 路由之上增加一个 metadata-only 的窄入口：

```text
agent-tool-manifest.v1.json
  → AGENT_DISCOVERY.md
  → 显式 workflow_goal
  → 5 条固定 Recipe 之一
  → ≤8 KiB task capsule
  → 既有 CLI / bounded agent task / human gate
  → 短回执或单一恢复动作
```

## 为什么不用自然语言自动分类

当前只有 5 条高频、可回归的真实工作路径。请求必须显式选择 `workflow_goal`；入口只做精确映射，不从模糊文本猜测第六条路线。这减少了路由 token，也让错误可被 schema 直接阻断。新路线必须先进入 canonical 合同，再增加 Recipe 和冷启动 fixture。

“已经发布／现在有多少播放／收到平台提示”等不是第六条内容工作流，而是直接运营事件。遇到这类人工报告，先运行`python scripts/self_media_agent.py operations`发现现有追加式记录器；记录完成且需要复盘时，才选择下面的`publication_feedback_review`。

## 五条固定路径

1. `moments_short_post`：一个真实观察 → 朋友圈候选 → 朗读与作者确认 → 人工发布交接。
2. `xhs_evidence_graphic`：高频问题 → 研究 Owner → 证据型母稿与图文计划 → 标题／封面／承诺一致性审核。系列可以一次全部剪完，但每条发布前单独复核包装；标题和封面不得标“第几集／期”，顺序只留在内部日历或 manifest。
3. `case_video_candidate`：已核案例 → 脱敏脚本 sidecar → human voice 三段门 → 现有视频 Owner 候选交接。
4. `publication_feedback_review`：已有私有运营库 → 六层内容与经营复盘草稿 → 人工复核。
5. `context_efficient_rework`：源素材与决策单 → 代理审片／变更窗口 → Owner 回执 → 完整候选最终人工 QA。

## 上下文预算

- task capsule 上限：8192 bytes；当前最大合成样本约 4.7 KiB。
- tool receipt 上限：1500 bytes。
- `always_load` 只含入口、请求和必要绑定。
- 大文件、完整日志、全量网页、原始访谈与视频只允许 hash-bound reference。
- `on_demand` 只在当前步骤需要时加载；失败时才展开相关日志窗口。

这不是删掉质量信息。事实、用户修正、授权、隐私、医疗保险边界、标题承诺、最终视听 QA 和人工发布门均不可降级。

## 稳定命令

```powershell
python scripts/self_media_agent.py doctor
python scripts/self_media_agent.py capabilities
python scripts/self_media_agent.py operations
python scripts/self_media_agent.py run-example --recipe xhs-evidence-graphic
python scripts/self_media_agent.py resolve --request fixtures/agent-entry/xhs-evidence-graphic.request.json
```

错误恢复只接受登记过的 `error_code`：

```powershell
python scripts/self_media_agent.py resume --receipt <error-receipt.json>
```

它只返回一个人工恢复动作，`automatic_retry` 永远为 `false`。未知错误不得猜测或循环重试。

## 安全与正确性门

- canonical route 必须整套加载；canonical 缺失、hash 漂移、mixed roots 都 fail-closed。
- 输入引用必须是仓库内相对路径并绑定 SHA-256；路径逃逸、缺失、重复角色和 hash 漂移均阻断。
- 缺少普通输入时返回 `blocked_missing_inputs`，不生成占位事实。
- 每条 Recipe 的最后一步必须是 `human_gate`。
- CLI 步骤不得含发布、上传或发送动作。
- publication=`manual-only`；Provider、外发、客户联系、CRM 和知识库写入均不授权。
- `content_no_signal` 保持中性，不变成客户或业务结论。

## 变更依据

- 意图：让较弱、较短上下文的 Agent 在不读完整仓库的情况下发现并正确使用流程。
- 决策：在 self-media operational consumer 增加 manifest、短 discovery、5 条 Recipe、task capsule 和薄 CLI；路由仍归 Registered content-creation-system。
- 理由：最大风险不是模型“不够聪明”，而是入口过多、隐含选择过多、上下文无界和授权语义不清。
- 证据：现有 canonical routing binding、context efficiency 工具、publication feedback tracker、case-video/human-voice gates 及各 Owner 稳定入口。
- 生效范围：后续朋友圈、小红书图文、案例视频候选、发布反馈和视频局部返工的 Agent 冷启动。
- 回滚：删除本次 manifest、discovery、Recipe、三个 schema、入口脚本、fixtures、tests 与 README 指针，并移除总 checker 中的 Agent doctor 调用；不影响既有路由、内容、发布和经营数据。

## 剩余限制

该入口证明的是本地合同和合成冷启动，不证明真实使用效果、事实通过、作者认可、当前在线、视频完成或发布授权。连续回放真实任务后，才应根据失败分布调整 Recipe；不能因为想进一步省 token 就放宽证据和人工门。
