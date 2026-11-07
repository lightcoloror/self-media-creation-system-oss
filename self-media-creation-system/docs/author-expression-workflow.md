# 作者表达、判断与改稿积累

创作入口补充：先用[每次路由判断](creation-route-selection.md)选择故事、独立 Vlog 或说明，再进入对应写作／声音工作流。写作 handoff 必须附当前 context 和 decision；不因口播形态而默认加载故事框架。2026-10-10 13:20:00 +08:00，Codex（GPT-6）。

更新时间：2026-09-26 11:59:39 +08:00

执行者：Codex (GPT-6 Astra)

这是现有创作流程的实现说明。沿用五个目标；朋友圈、图文、案例口播及录制前脚本/采访提纲接入作者上下文。发布反馈和只改技术参数的视频返工不新增写稿环节。样本不是事实来源，记录也不授予发布权限。

## 用户如何使用

2026-10-09 18:50:58 +08:00｜Codex（GPT-6）：选题时先从既有作者上下文识别持续表达来源：亲历的选择、反复被问的问题、愿意继续研究的疑惑、有根据的不同判断。候选在原 brief／判断说明注明本人的事实或解释增量；材料不足才追问，不重复做整套访谈，不把表达意愿当市场需求证据。用一次实际短稿检验可讲性，后续依实际完成记录判断是否能持续，不新增素材数据库。

照常描述事情和自己的看法即可，Agent 负责本地记录和命令，不要求用户手填 JSON。每次创作先读取当前账号已确认的表达片段、拒绝表达及其原因，再保留本次判断。首次没有样本时继续使用现有 `voice_profile_ref`（朋友圈语气配置/表达画像）；明确样本数为零，不编造旧稿，不将旧画像自动升级为已确认正文。

用户说“这句像我”“这里改成……”“别写得像讲课”时，记录其具体文本与本次消息来源，只积累明确确认的范围。“可以”若只针对标题，不扩成全稿认可；仅确认事实不等于确认语气。无法判定范围时保留候选，不加入写前参考。一次写作可以只增加一句。已确认样本撤回后停止供新稿检索。

## 三类记录

1. **表达片段**：账号、体裁、原文、日期（系统记录时间）、来源、来源类型、精确确认范围。正样本指导表达，负样本附实际拒绝原因。AI 初稿只能作为候选；用户明确确认某个片段后才可作为参考。跨体裁样本仅参考措辞和语气，不照搬长短结构。最多读取五条，避免一次装入整库。
2. **本次判断**：原话、对象、立场、强度、依据和不确定处。用户未说明的字段如实写“未说明”，不推断成既定立场；没有观点的内容允许明确 `judgments: []`。同一 content_id 的原始记录不可覆盖。用户主动改变判断时以新 content_id 建立新的来源记录，并在来源处引用旧记录。
3. **逐轮改稿**：完整 before/after、文本校验值、自动差异、上一版引用、修改原因和原因的实际提供者。AI 的理由标为 assistant；用户没解释时不编造其动机，可记录“用户替换了此句，原因未说明”。每版均追加保存，最终稿不会自动变成整篇风格样本。

## 判断如何受保护

先写忠实表达用户判断的正文。事实疑点、隐私、法律、安全或措辞建议另存 risk_notes，指出具体句子及原因；不以“风险较大”为由悄悄替用户改立场。涉及立场、对象、归因、强度和不确定性的变化时，向用户展示原话、改稿和变化建议。实际不能协助的部分明确解释，不能伪装为作者观点。

代码发现原话不在改后稿中会标记 `needs_author_confirmation`；原话仍在也只说明字符串存在，不能证明没有反讽、否定或语义转移。沿用现有最终作者确认环节，对每条判断记录 `preserved`（含作者认可的忠实转述）或 `accepted_change`。没有明确用户决定则不自填 author 确认。每份确认绑定具体版本，新稿不能套用旧确认。命令验证的是来源声明和版本绑定，不认证真人身份，也不宣称自动理解全部语义。

## 本地入口

在 `<workspace>/self-media-creation-system` 运行。默认私有库为 `.runtime/author-expression/store.sqlite3`，已被现有 `.gitignore` 排除；真实数据只应是非敏感或已脱敏的作者表达。数据库采用事务和追加记录，候选/确认、真实/合成、账号均隔离。系统不上传、不读取整个知识库。

```powershell
python scripts/self_media_agent.py authoring
python scripts/author_expression_store.py status
python scripts/author_expression_store.py recall --account-id lucas --genre moments
python scripts/author_expression_store.py sample --input <sample-input.json>
python scripts/author_expression_store.py retract --input <retraction-input.json>
python scripts/author_writing_context.py prepare --input <brief-input.json> --request-id <current-request-id> --output <new-context.json>
python scripts/author_writing_context.py revision --context <context.json> --draft <actual-draft.md> --input <revision-input.json> --output <new-revision.json>
python scripts/author_writing_context.py review --revision <revision.json> --input <author-decisions.json> --output <new-reviewed-revision.json>
python scripts/author_writing_context.py check --revision <reviewed-revision.json> --require-review
```

存储库和桥接所绑定的文件必须位于本仓库内；核心 sample 等命令可读取用户授权的其他本地输入。真实工作记录放 `.runtime/author-expression/` 下。输出使用新文件名，不覆盖旧证据。测试加 `--store .test-runtime/<run>/store.sqlite3`，不得向默认库写合成样本。可从 `templates/author-writing/` 的**合成示例**理解字段，不能把示例当作用户确认。

## 接入现有执行器

- `prepare-step` 中写稿步骤必需 `author-writing-context`，以 manifest 的 `source_role` 标明；`role` 用 `user_correction`，`load_mode` 为 `inline` 或 `reference`，必须绑定 `expected_sha256`。正文与个人原话只能放授权范围内的上下文；reference 模式需读取指定文件。
- 创作请求须明确 `author_identity.account_id` 与 `genre`，由 Agent 根据用户账号和本次任务填写。体裁为 `moments`、`graphic_note`、`spoken_script`、`interview_guide`；执行器检查与流程及作者上下文一致。已有账号 JSON 声明 account_id 时也要一致；自由文本画像不会被猜成账号标识。
- 作者/包装审核步骤还必需 `author-revision-review`，内容是含 `review_ref` 的 `author-writing-revision.v1` 文件。确认稿必须与现有 `moments-candidate`、`frozen-body` 或 `interview-guide` 对应实际文件一致。
- 写稿输出增加 `author-writing-revision.v1`，同一 receipt.outputs 同时列出实际正文。校验会打开正式主稿并与持久化 after 比对，不能另塞一份无关附件充数。JSON 原生支持案例分段口播、采访问题、content-item 的完整母稿和渠道正文、body/text/markdown/body_markdown；只有朋友圈允许以完整 .md/.txt 正文作为正式输出，其他体裁保持原有 JSON 契约。摘要不能代替全稿，引用正文改变后须重新记录版本。
- 复验 handoff 和输出时再次校验。缺失作者记录、引用损坏、撤回样本、改动原始判断记录、确认错版本均停止相应步骤。`--inspect-only` 仅用于查看说明，不能替代执行通过。
- 改稿结束后，依据用户的具体反馈调用 sample 收录精确片段；没有认可则仅保存版本。下一次 prepare 自动读取已确认片段，实现跨对话积累。无需新增第六个 workflow_goal。

## 范围与回退

新增模块为 `author_expression_store.py` 和 `author_writing_context.py`；复用稳定 self_media_agent 入口、原有上下文/人审步骤、hash 绑定和隐私规则。保留历史脚本、原始文件和原有草稿画像。无法读取私有库时停止使用该上下文并给出错误，不能声称已回忆作者风格。代码级撤销需连同 recipe 角色和入口校验一起回退；保留私库及历史版本，不删除学习记录。


2026-10-24 | Codex（具体模型变体未独立核验）：前置准备、九项逐版审稿、问题承接及反馈失效已接入原作者存储和执行入口。见 [执行完整性合同](editorial-execution-integrity.md)。检查完成、问题关闭和作者确认分别判断；不得以合成验收代替实际稿件审核。
