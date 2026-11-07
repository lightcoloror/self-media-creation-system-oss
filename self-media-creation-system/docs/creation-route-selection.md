# 创作阶段：判断表达形式

更新：2026-10-10 13:20:00（Asia/Shanghai）｜Codex（GPT-6）

入口层级澄清：2026-10-25 21:34:37 +08:00｜Codex（GPT-6）。尚不清楚本次该进入哪条流程时，先用原有 `self_media_agent.py resolve` 选择交付入口，见[任务入口指南](workflow-entry-selection.md)。本页只判断创作表达形式；仅审核原片、做发布页、比较标题／封面、记录平台数据或维护代码，不需要重新开始本创作判断。

适用：新建、重写、重新策划脚本或剪辑方案。AI 阅读本次用户目标、纠正、素材证据和交付形式，先判断主路由，再写脚本、筛选镜头和安排声音。沿用同一项目时也核对当前目标和证据；新增素材、改变观看任务或用户纠正后重新生成判断。不把历史脚本、账号、平台、片长或“旅游”关键词当作路由结论。

## 判断顺序

目的延续补充（2026-10-27，Codex）：沿用[目的贯穿交接](purpose-continuity.md)中同一 Brief 来源与当前反馈；`primary_intent` 不代替本篇受众与预期变化。阶段职责决定本阶段贡献，现有四条路线及局部组合保持自由；只改技术内容不因此重新策划。

1. 从已有上下文提取本次观看任务：记录行程、看刺激动作、获取攻略、听真实体验判断、感受环境、观察人与地方，或理解真实因果变化。能判断就执行，仅关键偏好缺失时才提问。
2. 阅读素材的画面、动作、声音、反应、信息和覆盖缺口；未拍项目读取意图和预计覆盖。因果变化必须引用证据；未知现场结果不得预写为事实。
3. 选一条主路线并记录理由、替代路线和未决项。故事与旅行体验平行。技术修改若涉及方向、脚本或素材取舍变化，需要重新评估创作路由。
4. Vlog 根据目标选一种主形态，允许组合局部表现手法。局部真实因果变化成立且有表达必要时可单独设计故事章节；音乐高潮、速度变化或镜头峰值本身不是人物故事证据。
5. 给用户一段可核对的说明：路由、形态、选择依据、其他路线为什么不优先、素材缺口、下一步，再进入相应指南。

| 路由 | 进入依据 | 工作内容 |
| --- | --- | --- |
| `story` | 主表达对象是真实因果变化，且有相应证据 | 原有故事设计卡、行动与反馈、事实支持的转折和变化 |
| `travel-experience` | 行程、动作、攻略、体验、氛围或观察是首要任务 | 形式选择、覆盖清单、镜头与声音日志、分段方案、EDL；无需冲突—转折—高潮或故事卡 |
| `expository` | 首要任务是解释、回答或提供工具信息 | 现有说明、问答等结构；故事手法按适用性选用 |
| `technical-rework` | 方向不变，仅指定技术修改 | 现有修改区间与审核；不得以此绕过新脚本判断 |

Vlog 六种形态见[旅行／体验指南](travel-experience-vlog-workflow.md)。动作、感官、实用信息和互动镜头按各自用途筛选，不因缺少故事推进而统一低分。所有路由共享完整素材分析：源清单、画面、声音、事件导航、精彩候选与未使用理由。轻量或短片只减少成片长度及制作复杂度。

## 本地入口

```text
python scripts/self_media_agent.py creation-route
python scripts/self_media_agent.py creation-route resolve --input <current-context.json> --output <decision.json>
python scripts/self_media_agent.py creation-route check --decision <decision.json> --current-context <current-context.json>
```

输入遵循 `schemas/creation-route-context.v1.schema.json`。可复制 `fixtures/creation-route-v1/same-day-activity-highlights.context.json` 的形状，替换任务和依据。字段是 AI 语义评估；CLI 不读取影片、不预测效果、不调用模型。`causal_change.status=supported` 必须有来源；通过只说明评估自洽，不证明素材或事实已被人工核实。

输出包含路由、形态、理由、替代路线、质量重点、共享分析范围和输入／策略哈希。`ready` 进入指南；`needs-context` 先完善已有信息；`needs-evidence` 补证据或按真实素材改选方向。原有因果故事可以继续选故事路线，旅游题材也不禁止有依据的故事表达。

五个 managed recipe 的写作步骤，以及拍前准备各步，在 `prepare-step` 和 `validate_step_handoff` 需要上下文清单中各一项 `source_role=creation-route-context` 与 `source_role=creation-route-decision`。采用 `role=source_manifest`，均记录文件 `expected_sha256`。工具复算判断、核对任务及当前上下文；拍前必读和后续审核保持同一所选路线。Vlog 不交给案例／图文 recipe，应进入独立工作单；五个固定 recipe 没有被冒充成旅行渲染器。

Vlog 工作单先执行 `creation-route check`，再将分段用途和源时间码交给现有 VKP／NLE／MVP。素材分析、渲染与精确审核沿用各自入口。本次没有增加模型、视频分析器、渲染器或发布接口。

## 依据

- 用户要求：旅行 Vlog 与原有讲故事流程分开，每次由 AI 判断。
- [Adobe 旅行视频流程](https://www.adobe.com/learn/premiere-pro/web/create-travel-video)：分镜、覆盖、筛选和剪辑提供制作工具。
- [Xu 等对 B 站旅行 Vlog 的研究](https://researchonline.jcu.edu.au/67811/7/JCU_67811_Xu_et_al_2021.pdf)：体验、审美、剪辑、幽默与互动共同构成内容；样本有限，不证明通用最佳形式。
- [旅行 Vlog 叙事维度研究](https://journals.sagepub.com/doi/abs/10.1177/00472875241312178)：连贯、信息、视听和真实性维度可参考；其美食旅行范围不意味着所有活动 Vlog 必选戏剧框架。

路线类型和选择规则是本地操作性综合，由用户要求及上述研究启发；没有固定时长比例或平台效果承诺。
