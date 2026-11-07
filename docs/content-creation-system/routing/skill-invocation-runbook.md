# Skill 调用运行册：谁能做什么，谁不能越界

> 规则优先级：用户本轮明确要求 > 用户确认事实与最终修改 > 账号/IP > 本人声纹与视觉 > 事实/隐私/合规/版权 > 形式 > 平台 > Skill > 公式。

| 场景 | 可以调用 | 交付物 | 不得替代 |
|---|---|---|---|
| 聊天式素材访谈、观点提炼、正式采访提纲 | [material-interview](../../../self-media-creation-system/skills/material-interview/SKILL.md) | 复用已有回答、按关键缺口追问、足够材料时收口；正式提纲沿用原合同 | 招聘面试、预设答案、固定情绪/金句清单、录制或发布许可 |
| 内容支柱、栏目、渠道角色、内容组合 | `content-strategy` | 受众—问题—内容目标的策略候选 | 本人声纹、医疗保险事实、固定发帖频率 |
| 账号策略与商业方向对标 | `content-strategy`＋`content-benchmark-workflow` 整号模式；`dbs-benchmark`仅经本地适配补充 | 受众—需要—公开承接—交付—持续内容的观察、未知与可执行性 | 以估算利润作硬门、排除真实资源与表达意愿、照搬人设；不能证明对方盈利或本人的业务成立 |
| 素材提炼、跨平台再利用 | `social-content` | 可改编角度与形式清单 | 中国平台规则、推荐机制、批量发布或私信 |
| 明确商业承接页/服务说明 | `copywriting` | 转化文案候选 | 朋友圈、个人叙事、医疗理赔案例的默认文体 |
| 公众号/长文结构 | `blog-writer`、`wechat-article` | 章节与资料缺口 | 来源核验、最终微信排版、个人口吻 |
| 正文稳定后的跨平台标题生成、诊断、比较与复盘 | `title-matrix`（本地适配） | 实际标题候选、原题/改后、正文兑现位置及推荐取舍 | 上游故事/情绪修改、事实核验、作者确认和发布许可；未确认正文只能标记探索候选 |
| 选题／提纲阶段共同试框架与包装 | 本地路由卡候选；需要标题方法时可用 `title-matrix` 探索 | 人群处境、观看所得、暂定标题／封面主张／首句及支撑位置 | 正式 Hook、完整封面制作、包装通过、作者确认；无法兑现时回到角度而非放大措辞 |
| 平台文字标题、封面标题文字或配套开头 | `dbs-title-cover-intro`；已有 `title-matrix` 结果时复用 | 按需交付标题、封面文字及换行、开头与正文兑现位置 | 封面图片、正文事实、医疗/保险结论、作者确认；不重复整轮生成 |
| 口播开头和说话顺畅度 | `dbs-title-cover-intro` 的开头子任务 | 冻结且作者确认正文之后的开场候选、接入正文位置及待听看片段 | 恐惧钩子、完整脚本、伪造已拍原话；不得越过适用初稿与作者确认门 |
| 明确指定旧 Skill 或旧版对照 | `dbs-hook` / `dbs-xhs-title`，仅按用户指定 | 旧版候选与比较 | 默认推荐、自动降级；仍遵守同一事实与审核边界 |
| 同一事实的多框架观察角度 | `local-evidence-synthesis`＋`perspective-angle-candidates.v1` | 1–5 个类型化候选、来源要求、适配说明和误引风险 | 模拟名人发言、伪造引语/立场、增加事实；框架应用必须写成分析镜头 |
| 公众号 HTML 候选排版 | Content Studio `wechat_article_format_adapter.py` | inline HTML、普通/暗色预览和 hash-bound 回执；支持 synthetic 与显式 public-review | 不写作、不自动打开/上传/发布。public-review 要求公开声明、隐私通过、无 blocked 门、正文哈希一致；保留待作者确认，不要求伪造 approved |
| 成稿诊断 | `dbs-content`、`dbs-ai-check` | 已通过结构闸门稿件的清晰度、套路化、表达效率问题清单 | 修复缺失事实、缺失服务因果、擅自改写为陌生声纹、事实核验 |
| 叙事型自媒体：短视频、公众号、访谈、个人品牌与真实服务案例 | 本地 `insurance-content-storycraft` | 最小故事单元、场景、因果转变、采访证据、跨媒介适配；敏感案例另含服务动作、五锚点和初稿质量闸门 | 医疗决策、虚构场景/对话/心理、承保或赔付承诺、把单一案例当普遍证据 |
| 本人风格 | 本地 `voice-profile` 与已确认语料 | 删除 AI 腔、匹配对应 IP 的表达建议 | 把所有内容写成慢/稳/克制一种气质 |
| AI 采访式图文 | 素材提问先读 `material-interview`（上方链接），后续沿用本地 `AI图文流程` | 采访问题、初稿、卡片任务、制图 Brief | 自动发布、替用户判断、把一句提示词说成自动创作 |
| 选题级对标、补对标、根据对标改稿 | `content-benchmark-workflow`＋本地对标操作卡；检索按既有WCF／agent-reach入口，`dbs-benchmark`补充筛选 | 实读内容与证据状态、账号基线或缺口、逐篇采用／拒绝、改稿前后审计和视觉职责映射 | 本案事实、专业结论、涨粉／盈利归因、第三方素材或原话复制；不能仅凭账号名单交付 |
| 查当前平台规则或规格 | `agent-reach` / 官方入口 | 带来源、检查日期、置信状态的易变信息 | 固定权重、永久最佳时间、绕过风控 |

## DBS 新版调用约定

2026-11-02 15:52:11 +08:00｜Codex（GPT-6）：选题发现和对标采集复用[平台采集与恢复](../../../self-media-creation-system/docs/research-capture-execution.md)。注册入口 `self_media_research_capture` 提供原网页账本前检与组件验收；实际采集继续使用现有 WCF、wechat-tools、bili-cli和当前获授权浏览器工具。每平台分阶段留证，连接最多30秒；元数据、正文、图页、字幕分别判断。WCF优先，Jina只在不适用／不可用且说明原因后备选。登录／验证码不能通过换工具绕过，历史子任务看不到浏览器不构成模型能力结论。

2026-10-10 09:22:33 +08:00，Codex：采用已安装的 DBS v2.18.47 新入口。沿用当前路线卡和证据记录，不新建生产链。

- 先识别文字发布标题、封面标题文字、视频开头中的实际所需项；只要一项就只做一项。封面文字不包含画面设计、图片生成或渲染权限。
- `title-matrix` 负责现有标题生成、诊断、比较与复盘；交给 `dbs-title-cover-intro` 时携带已选主线、正文版本、标题候选和证据边界，只补缺失的表面。不重复角度发现、重复标题生成或重复要求已给出的确认。
- 选题／提纲阶段仍可联合试标题、封面主张和首句，但只能标记 `exploratory-candidate`、兑现缺口与版本；不得签发正式 Hook、成品、作者确认或发布通过。未选主线且确需重新开发角度时才按新版方法展开，已有明确主线或局部措辞修改走快捷路径。
- 正式标题／封面／开头仍须正文问题关闭及相应作者确认；正式口播开头沿用适用初稿质量门、作者试读与正文冻结要求。新版的“草稿足够就继续”不覆盖本地审核要求；缺事实、作者确认或可靠时间码时如实保留缺口。
- 已拍素材只使用可定位原话与画面；新写句子须明确标为补拍候选。只看字幕不得声称已验收听感或镜头连续性。正文或开头变更后仅复核受影响的承诺、衔接和审核，不借旧版本回执放行。
- 不把安装更新当作医疗／保险事实核验、数据采集、模型调用、制作或发布授权；现有事实、隐私、合规、版权和人工发布边界不变。平台默认字数和跨平台复用规则只是候选，实际平台与本篇要求优先。
- `dbs-hook`、`dbs-xhs-title` 仅供用户明确指定或旧版对照，不因旧文档提及就默认调用。原有硬门说明中的旧 Hook 同时约束新入口的正式开头子任务。

意图：让自媒体实际调用跟随已更新 Skill。决策：新入口默认、旧入口显式兼容、主线和标题只处理一次。理由：上游已弃用两个旧默认入口，但本地内容边界仍有效。证据：安装版 Skill、`skill-registry.json` 和本轮定向测试。生效范围：本地创作调用与候选审核，不含发布或历史产物重算。

## 每次调用的最小输入

2026-09-17 21:32:40｜Codex（GPT-6 Astra）：所有创作调用同时遵守[质量门的完成判定](../../../self-media-creation-system/quality-gate-playbook.md#完成判定检查修改与优化分开)。Skill已读、检查表已填、机器回执passed不等于优化；发现的问题须绑定正文的改前/改后及逐项复核，或给出有证据的保留理由。结构/情绪缺陷未关闭时退回上游，不先进入试读、Hook或宣称全流程完成。仅修改口吻须如实说明，不冒称结构优化。

在调用任何写作 Skill 前，先附上：

```text
账号/IP：
本篇唯一目标：
形式与平台：
目标受众：
证据状态和禁止说法：
唯一事实卡修订版与状态：
本稿允许使用的事实 ID：
声纹/视觉路线：
外部对标状态、采用项与拒绝项：
本次只需要 Skill 做的子任务：
```

这样 Skill 才是专门工具，而不是不受约束的“代笔者”。

如果开头所需的数据、案例、结果或权威依据不在事实卡和冻结正文中，只能输出问题或 `needs_source`；禁止采用通用 Hook Skill 的“主动增补素材”指令。正文变化后，旧开头失效并重跑。

## 高风险升级

- 医疗、保险、理赔、儿童、客户或家属：先建立唯一事实卡，锁定修订版并记录隐私边界，再写稿。
- 涉及当前平台规定、工具版本、价格、产品能力：先查官方或一手来源，登记检查日期。
- 涉及真实客户：没有匿名化或公开授权，Skill 只能处理抽象结构，不能接收可识别材料。

## 外部对标调用顺序

2026-10-09 18:50:58 +08:00｜Codex（GPT-6）：先区分账号策略研究与单篇表达研究。策略对标复用 content-strategy 与 dbs-benchmark 的商业链、能力／成本分析；只采用这些方法，**不采用估算十倍利润硬门、忽略本人资源／长期表达意愿、所有不一致都必须改成一致**。公开材料看不到的收入、归因和复购写 unknown；学习结构不搬运表达或替换本人判断。策略结论供多篇引用，不逐篇重做。

下列顺序用于单篇。记录采用／拒绝后，在提纲里联合试框架、标题、封面文字主张和首句，再形成正文。早期设计不等于提前正式过门；禁止越过初稿门执行正式开头子任务的规则同时适用于 dbs-title-cover-intro 与显式旧版 dbs-hook。普通稿件的编辑结束条件及材料可改范围见主路由卡，不再增加一轮重复提问。

2026-09-17 18:59:44 | Codex（GPT-6 Astra）：选题级对标按 [现有操作卡的完整执行入口](benchmark-visual-grammar-playbook.md#选题级对标的完整执行入口) 接入。用户明确要求时不可跳过；已采资料先复用。研究报告分别标明内容可用范围、表现证据和未完成项。正文形成后必须追加 `keep/change/reject/insufficient-evidence` 差异审计，随后继续故事、情绪、初稿、人声及本人试读门，不能以对标报告代替这些检查。

`唯一事实卡锁定 → 明确受众、目标和内容任务 → 选定内容形态 → content-benchmark-workflow复用／补查并拆解 → 记录采用／拒绝及证据状态 → 形成结构与视觉职责映射 → 初稿与差异审计 → 后续文案和制作门`

- 对标只解决“怎样表达和展示”，不能回答“本案发生了什么”。
- 同一个参考对象不必整套照搬；可以分别学习证据呈现、克制解释、竖屏卡片和同行业承接。
- 没有后台数据时，不判断对标账号是否盈利，也不把播放量等同于获客成功。
- 涉及医疗和保险时，外部视频中的结论必须回到正式事实与来源流程重新核验。
- 第三方视频只用于内部分析；成片默认使用自制卡片、自有采访和已授权原件。

## 真实案例的强制初稿闸门

只有 `content-fact-card` 已标记 `locked_for_draft`，`insurance-content-storycraft` 才能形成第一版完整正文。正文形成后，必须先按以下顺序审核，不能直接进入 `dbs-content`、`dbs-ai-check`、去 AI 味改写、Hook、试拍或发布：

1. 事实与证据；
2. 单条任务；
3. 服务因果；
4. 采访完整性；
5. 分发合规：内容分类、现行/未来规则、公司审核、账号授权、广告与AI标识；
6. 医疗与保险边界；
7. 隐私与授权；
8. 标题、开头、正文、CTA 一致；
9. 初步口语与 AI 痕迹；
10. CTA 与服务产品边界；
11. 制作可行性与相邻选题重叠。

其中“服务因果”必须做反向测试：删除创作者的具体动作后，如果故事仍然完整、结果不变，则获客稿退回重写。客户感受和夸奖只能作旁证，不能代替创作者做了什么、带来了什么变化、当时不能保证什么。

闸门只有三种结果：`approved_for_voice_pipeline`、`return_for_revision`、`blocked_from_downstream`。只有第一种可以继续；审核结果必须同时绑定当前正文哈希和事实卡引用，任一变化后自动失效。

## 缺失的正式适配器

目前没有必要立刻再造通用 Skill。先通过格式剧本和质量门完成以下五类真实任务，积累你自己的样本后再固化：

1. 采访视频；2. 产品 Demo；3. 长视频；4. 直播；5. 平台规格复核。

## 2026-07-25 14:11:38 | Codex（GPT-5.6 Sol）

- Action: converted the skill registry from a capability list into an invocation and boundary runbook.
- Summary: generic writing skills now remain subordinate to user-confirmed facts, voice, format and safety gates.

## 2026-08-14 18:55:26 | Codex (GPT-5.6 Sol)

- 意图：把“初稿出来后检查什么”变成所有真实案例脚本的固定阻断步骤。
- 决策：Storycraft 初稿后先过十一项结构与分发合规闸门，再允许内容诊断、去 AI 味、Hook 和试拍。
- 理由：语言工具只能改善表达，不能补回缺失的服务因果、证据、授权或系列分工。
- 证据：`case-video-initial-draft-review.v1`、`initial_draft_quality_gate.py` 及配套回归测试已经实现相同状态合同。
- 生效范围：医疗、保险、理赔、客户采访等真实服务案例；最终发布仍需人工高风险审核。

## 2026-08-14 21:59:17 | Codex (GPT-5.6 Sol)

- 意图：把本地已有六道合规门和成片版本绑定流程接回 Skill 路由。
- 决策：初稿十一门后，稳定脚本再做六道合规审核；视频、字幕、封面和发布文案完成后，再做精确成片合规门，最后才允许人工发布。
- 理由：内容诊断、去AI味、Hook、脚本审核和客户采访同意都不能替代账号授权、机构审核或最终成片确认。
- 证据：`case-video-review-receipt.v1`、`case-video-final-cut-compliance-review.v1`、本地六道门合规资料和聚焦回归测试。
- 生效范围：保险、医疗、理赔、客户采访和服务案例；普通内容按风险适用，发布仍为人工。

## 2026-08-15 17:53:49 +08:00 | Codex（GPT-5.6 Sol）

- Intent: Prevent writing Skills from receiving an unversioned mixture of facts, old drafts, and machine summaries.
- Decision: Require a locked fact revision and an explicit fact-ID allowlist before any writing Skill; bind the initial review to both body and fact card.
- Reason: Language tools cannot detect that an upstream chronology or action label has already been corrected elsewhere.
- Evidence: `content-fact-card` update, `case-video-initial-draft-review.v1` binding, and proton-case corrections.
- Effective scope: All writing Skill calls; full rule for high-risk content.

## 2026-08-17 20:20:43 +08:00 | Codex（GPT-5.6 Sol）

- Intent: 让外部案例研究成为可追溯的工具调用，而不是创作者或AI凭印象模仿。
- Decision: 增加`agent-reach → dbs-benchmark → 对标操作卡 → 视觉职责映射`的固定顺序。
- Reason: 搜索负责找到样本，诊断负责拆结构，两者都不能替代事实卡、授权、合规或人工判断。
- Evidence: 本轮网上实例核对与`benchmark-visual-grammar-playbook.md`。
- Effective scope: 所有需要网上对标、形式参考、镜头参考或视觉Brief的自媒体任务。

## 2026-09-03 14:00:56 +08:00 | Codex (GPT-5.6 Sol)

- 意图：把已完成 BookWiki 处理的叙事原文接入现有 Skill 路由，而不是另建重复流程。
- 决策：`insurance-content-storycraft` 同时承担短视频、公众号、访谈和个人品牌的叙事结构；只有 `story-arc` 才启用故事卡，事实解释类内容不强套故事。
- 证据：BookWiki 主题包 `内容创作与自媒体经营`、跨书指南及 0.96 审阅结果；Skill 内的 `bookwiki-source-map.md` 和 `cross-media-storytelling.md`。
- 生效范围：叙事选材、策划、写作、改写和诊断；事实、隐私、版权、合规与人工发布边界不变。


## 2026-10-03T20:00:56+08:00 | Codex（GPT-6）

将 title-matrix 接入已有标题环节；适配边界、调用方式与实稿演练见 [接入记录](../../../self-media-creation-system/docs/title-matrix-integration.md)。正文问题先实际修复并关闭，标题保留原题/改后与正文版本，诊断完成不等于优化完成。已有路线卡和包装/复盘记录继续作为证据入口。

## 框架决策接入（2026-10-10）

更新：2026-10-10T09:28:29+08:00；Codex（GPT-6）。完整操作见[四种框架决定](../../../self-media-creation-system/topic-reframing-playbook.md#内容框架决定在结构故事和正式包装之前)。

写作前比较每个候选对应的受众、观众所得、具体商业关系、材料兑现和制作成本；不是只给商业关联标高/中/低。使用 `topic-angle-decision.v2`，允许继续、重构、补材料、暂缓，允许全部不选。只有已确认且材料仍有效的继续决定进入结构/故事/初稿。补材料仅通往指定研究或素材准备；重构必须实际改稿并重新评估；暂缓保留材料和恢复条件。已知方向的局部改动可复用仍有效的判断，不重复全面探索。

前置 `dbs-content-value` 诊断与 `dbs-title-cover-intro` 的联合框架探索；正式标题/封面文字/开头仍在正文稳定和适用人工确认后。`title-matrix` 作为同一条标题流程的比较工具；旧 `dbs-hook` / `dbs-xhs-title` 仅兼容，不默认重复调用。新Skill不能代替事实核验、作者决定和改稿。


## 逐版执行完整性（2026-10-24）

Codex（具体模型变体未独立核验）：技能执行不得以阅读过说明或有报告文件代替。现有写稿与作者审核入口已接入[执行完整性合同](../../../self-media-creation-system/docs/editorial-execution-integrity.md)：前置七项、逐版 C01—C09、稳定问题 ID、反馈重开、受影响证据复核，均沿用作者记录表。脚本只核对可追溯的记录与版本，不能证明文案质量。本人表达与 AI 模式分别记录；部分完成、必改未闭、作者未确认和实际媒体未检查分别返回，不能统称全部通过。
