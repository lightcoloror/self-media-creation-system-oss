# 先写稿，再录制：创作入口与升级门禁

2026-10-11，Codex（GPT-6）：聊天式素材提炼、观点访谈和正式提纲先读[material-interview](../skills/material-interview/SKILL.md)。聊天可直接进行，不要求先建录制任务；已有回答优先，提纲追问按缺口选择，材料足够即收口。正式 `interview_guide` 的 handoff 自动加入该 Skill 的路径与哈希，并在复验时重算；普通口播准备不额外加载。

2026-10-10 13:20:00 +08:00，Codex（GPT-6）：拍前先做[本次路由判断](creation-route-selection.md)。口播／采访形态不自动选择故事；必读材料按当前选择加载。未拍结果留作未知；Vlog 独立走旅行体验工作单。

Updated: 2026-09-04 22:04:00 +08:00 | Codex (GPT-5.6 Sol)

## 门禁拦的是什么

试读清楚自然即可保留。录后发现某句话听不清、说错或需要补足必要边界时，先定位句段并局部补录，再核对受影响的字幕、证据和版本绑定。日常衣着、素颜、普通生活背景和轻微停顿在不影响理解、隐私或既定要求时可保留。原有必查项已完成，只剩装饰建议时可结束当前编辑。写作与审核的投入顺序见[观众路径](../structure-route-playbook.md#观众路径)。

门禁限制的是**把未审核的产物当成已完成步骤继续交接**，不控制摄像头，也不禁止写初稿。不得要求“先录完才能写录制稿”。

| 当前阶段 | 可以做什么 | 缺什么才影响下一步 |
|---|---|---|
| 录制前写口播 | 确定目的、事实与待确认项，写正文、结构依据、拍摄备注 | 不得编造本案事实、对白、客户决定；不要求原始音视频 |
| 录制前做采访 | 写开放问题、追问、目的、未知项和录制注意事项 | 不得预写答案并当作真实回答；不要求采访已经发生 |
| 口播稿审核 | 初稿十一门 → 内容/AI痕迹诊断 → 改写或保留 → 作者试读与口吻确认 | 未确认只能继续改稿，不能声称“已确认可交接”；试读不等于正式录制，无需上传录音 |
| 正式录制与素材制作 | 使用录制稿/采访提纲；取得实际采访材料 | 录制同意另行确认；真实回答、声音/人物授权、素材与剪辑引用在这里核对 |
| 成片交付/发布 | 审核最终视频、字幕、封面和说明 | 必须是相同冻结版本，授权、合规和人工发布边界保持 |

`authorization_status` 是当前状态，不要求开始写稿时已经获准公开。未知项可保留为 unknown；可识别敏感材料不得进入通用草稿/fixture。事实尚不明确时先写问题和结构，不把未知写成事实。

拍摄覆盖与画面／声音需求可先填[视频拍前决策卡](../templates/video-preproduction-card.md)。它是人工准备表：口播稿、正式采访提纲及其作者审核仍走下方 `prerecording` 合同；卡上的“拟拍”“拟问”不等于录制同意、事实确认或发布放行。2026-09-23 12:38:49 +08:00，Codex（GPT-6 Astra）。

## 使用既有五流程入口

仍使用 `case_video_candidate`，不新增第二套视频状态机。默认 `creation_phase=production` 保持原有素材制作合同；录制前必须显式选择 `prerecording`：

```powershell
python scripts/self_media_agent.py resolve --request fixtures/agent-entry/prerecord-spoken.request.json
python scripts/self_media_agent.py resolve --request fixtures/agent-entry/prerecord-interview.request.json
```

以上只是合成路由例子，`available_inputs` 不是事实或执行证明。真正 `prepare-step` 仍要提供逐项文件引用、哈希与 context manifest。共享目录中的真实 Skill、调用运行册、事实修订及声纹依据仍须按来源读取；本入口没有自行调用模型。

录制前 handoff 自动带 `required_reading`：来自 canonical registry 的事实卡、Storycraft，以及本地人声 Skill 和调用运行册的精确路径/哈希；漏掉或改变这些引用会被拒绝。它要求 Agent 完整读取并按引用继续加载，不等于程序已经替 Agent 读懂。胶囊记录当前 canonical 路由版本，不再固定写成 1.0.0；旧版本胶囊需重新 resolve。

- `spoken_script`：初稿 `pre_voice=true` → 既有 initial-draft review → 既有 human-voice gate。初稿不填已完成人声回执、不填已冻结 Hook、不伪填八步 passed。正文仍有稳定的修订哈希，不代表通过了审核。
- `interview_guide`：问题草稿 → 绑定具体问题的作者审核。问题与追问、制作备注分开；不提供 answer/transcript 字段。问题审核只确认提纲，不等于录制同意或发布同意。
- 新录制前人声完成步骤必须提供原始 `human-voice-request`、句段绑定的五项语义检查及实际声纹依据哈希。没有词法命中不代表没有表达问题；自然稿可以明确选择 `review_without_rewrite`，不强改。

## 步骤和恢复

```powershell
python scripts/self_media_agent.py prepare-step --capsule <capsule.json> --step-id <step> --context-manifest <context.json> --context-receipt <pack.json> --output <handoff.json> --previous-receipt <previous-output-receipt.json>
python scripts/self_media_agent.py verify-step-output --handoff <handoff.json> --receipt <output-receipt.json>
```

首步不传前置回执；以后必须绑定紧邻前一步。所有 handoff、manifest 和回执保存在同一 run root。录制前后续步骤必须消费前一步的实际文件，不能拿无关旧回执搭配另一份草稿。正文、事实、上下文或回执改动后，从受影响步骤重建并复验；不自动重试。

只想查看后面的步骤时可加 `--inspect-only`。这只是浏览流程，不能作为执行输入或完成证明。业务结果 blocked 时 `ok=false`、CLI 非零退出，不因“文件传输成功”放行。空输出、错合同、漏检查、未完成前序和旧哈希均拒绝推进。

## 验证能证明什么

1. 哈希、步骤顺序、合同字段、输入输出引用和受控词法检查由程序核对。
2. 五项语义检查要求真实句段、判定和理由，并绑定前后版本及声纹来源；不接受只填“已执行 Skill”。
3. 程序仍不能证明 Agent 心里真正理解了 Skill，也不能凭自填 JSON 证明真人身份。真实作者确认不得由 Agent 冒填；真实内容效果仍需要作者和受众验证。
4. 原五流程的通用输出验证明确报告 `transport_and_sequence_only`，不冒充所有 owner 的语义审核；新录制前步骤报告 `prerecord_contract_and_existing_gates`。
5. 历史 fixture/回执不重写；旧人声请求维持原输出哈希，新请求才增加语义审核摘要。旧缺前置回执的 operational handoff 需重建链，不能静默放行。

## 变更依据与回滚

- 意图：修复录制前后顺序颠倒和纸面式完成。
- 决策：扩展既有 case-video 阶段、手工回执与 context handoff；复用 Content Studio 初稿、人声和事实门。
- 理由：写稿需要已知事实与未知问题，不需要先有成片；真正的风险是误当成已审核并继续生产。
- 证据：执行偏差反馈、用户本轮纠正、`test_prerecording_execution.py` 与既有案例/人声专项。
- 生效范围：两个仓库中明确调用该入口的流程，不宣称限制自由聊天或所有 Agent。
- 回滚：仅反向撤销本轮新增阶段、校验分支、schema 扩展及对应测试；保留原生产合同、历史回执、真实稿件和其他并行变化。不得整文件回退到 HEAD。

## 2026-09-11 12:33:23 | 实际时间证据补充 | Codex (GPT-5)

- 录制候选新增 `verify-prerecord-timing`：在人声改写、作者试读和口吻确认之后，用秒表或带时间码的试读记录绑定精确脚本。它仍不要求相机、录音或成片。
- 生产链在视频 Owner 返回成片之后新增 `final-timing`：用定时文本绑定精确脚本和精确成片。真实成片必须由既有 `publication_version_freeze.py` 的 `ffprobe` 能力读取时长；手填时长、成片哈希和时间轴不一致即阻断。
- 两个阶段都核对受众处境、继续观看理由、信息推进、主要回报和实际出现的持续价值承诺。设计卡只证明计划，试读回执只证明录制候选，最终回执只证明所绑定成片；三者不得互相冒充。
- 最终人工发布交接必须消费 `timing-evidence`。正文、脚本、时间输入或成片任一版本改变，都使相应回执失效并要求重测。
- 完整接口与阈值的证据地位见 `docs/short-video-timing-evidence-workflow.md`。
