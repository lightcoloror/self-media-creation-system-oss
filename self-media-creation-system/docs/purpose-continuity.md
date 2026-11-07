# 本篇目的贯穿与反馈传递

2026-10-27（Asia/Shanghai），Codex；运行模型变体未独立核验。

复用 `resolve → context manifest → prepare-step → 输出复核` 和现有 C01/反馈记录。没有新增路由、目标数据库、自动评分器或发布权限。内容目的不同于 `workflow_goal`；后者只表示交付流程。

## 同源目的，阶段分工

沿用本篇已经确认的 Brief、锁定记录或目标说明作为真源。把原文和哈希放入现有 `context-input-manifest.v1`，新增的 `editorial_context.version=1` 只是引用适配层，不是另写一份目标让各模块自由改。

目的决定取舍；阶段职责描述当前部分贡献什么；结构、句式、行数、音乐和节奏仍按素材与现有路由选择。标题可以用投入数字吸引相应受众，正文交代真实过程，结尾体现判断；生活细节、气口、留白和审美体验也可有间接作用。不要求每句话重复主旨，不强制升华或转化。

`editorial_context` 字段：

- `version:1`、`content_id`：同一内容身份，跨步骤不暗换。
- `purpose`、`audience`：各为 `{artifact_id,quote}`，引用现有 artifacts 的真实原文；可以来自同一个 Brief。
- `stage_duty`：本阶段职责，具体自由文字；不使用目标枚举选择表达路线。
- `current_body_artifact_id`：当前正文的 artifact_id；独立标题/封面必须提供。正文还未产生的前期步骤可为 null，不伪造正文。
- `feedback`：`[{artifact_id,quote,check_ids}]`，C01—C09 的影响范围由 Agent 如实判断。
- `feedback_note`：已收到哪些反馈、未知什么；空列表必须说明当前未提供或确无已知反馈，不能将未知写成没有。

上述引用必须有 `expected_sha256`，不得采用 `load_mode:on_failure`。所有路径沿用原 context manifest 的相对路径边界；不复制媒体进上下文、不读取整个知识库。目的、受众、反馈与正文文本读取上限为 2 MB，实际视频沿用媒体消费者。

普通 manifest v1 仍可按原合同读取；本扩展有独立版本。新执行 `prepare-step` 除纯 `verify-canonical-route` 发现节点外要求目的上下文；旧手写记录没有新证据不能宣称完成了新门。`--inspect-only` 和历史回放保留，但不构成新执行许可。不要手改旧 JSON、旧回执或哈希来让它通过。

## 独立入口与局部修改

`self-media-work-request.v1.current.context_manifest={path,sha256}` 指向同一个清单。`resolve` 仍返回原来的标题、封面、创作或审核入口；没有目的上下文时增加具体 `missing_inputs` 并返回 `needs_context`，不把标题任务变成完整脚本配方。实际选入 `context_efficient_rework` 的 `technical_only` 请求不要求重做创作判断；标题/封面不能靠这个标签豁免目的和正文。若提供目的上下文仍会核对其版本。

各新受管步骤的 `execution_brief.purpose_context` 包含读取后的目的锚点、受众、职责、正文及反馈摘要，重新验证时会重读源文件并核对。下一步骤必须承接上一项已知反馈。同一序列改变目的或受众必须有新增 C01 决策依据；工具不能认证这份依据是否出自真人，Agent 对用户立场仍不得擅改。

## 后续反馈怎样进入下一步

先把收到的反馈按现有 `review-integrity feedback` 记入原作者记录；已有作者上下文时，传递清单必须携带该内容全部已登记反馈的来源锚点及不缩减的检查范围。已知作者库不得在下一步被省略或换成独立快照；已有前置记录时，清单目的必须与当前 `goal_audience` 至少一条证据同路径、哈希和引文，接通 C01 的同源链。没有正式作者上下文的独立包装可直接引用真实反馈文档，在 `feedback_note` 明确这是显式提供的快照，不能声称已扫描全项目或找到所有反馈。

新增反馈时生成新清单/新阶段复核，保留旧清单；旧复核绑定的是旧清单，不能用于新的当前输入。清单里 `source_role=editorial-feedback...` 或原有 `role=user_correction` 的已声明文件不能从反馈列表遗漏。检查范围可重排或扩增，不能缩减、丢失旧来源。禁止依赖文件修改时间猜“最新”。未来输入若仍故意提交旧清单且没有作者记录或新反馈来源，工具无法知道未提供的信息；Agent 续办时必须先恢复当前用户指令和已知反馈。

反馈的影响范围沿用 C01—C09、`changes` 和已有问题关闭机制。只改包装排序不自动撤销全文音频确认；只改字幕错字不自动重访谈或重搜选题。作者改变目的、受众或立场时更新相关决定，不把旧确认搬到新目标上。

## 对实际产物复核

沿用原入口：

```text
python scripts/self_media_agent.py review-integrity check-stage --context <当前清单.json>
python scripts/self_media_agent.py review-integrity check-stage --context <当前清单.json> --review <阶段复核.json> --output <新结果.json>
```

仅检查 context 返回 `context_bound`，不代表产物已审核。阶段复核 `schema_version=self-media-stage-purpose-review.v1`，包含：

- `context_ref`、`artifact_ref`：复核文件所在目录内的相对路径及 SHA-256；产物可以是标题候选 JSON、脚本或镜头分析文本，视频观感仍须实际审片。
- `quote`：实际产物中能找到的锚点。
- `purpose_alignment`：`stage_duty/contribution/misunderstanding_risk/tradeoff` 四项具体说明，职责与交接相同。
- `feedback_resolutions`：每条已提供反馈的 `{artifact_id,resolution}`，说明采用、保留或待解决的处置。
- `disposition`：`retained/needs_revision/needs_input`；发现偏离则如实保留问题，后两者退出 2。
- `reason`：具体编辑判断。不能以“已读/通过”替代分析。

受管输出回执沿用原 `outputs`，多带一份上述阶段复核，引用同一 outputs 中的实际产物。缺复核、错版本、漏反馈或仍需修改，不能完成当前步骤。写稿/作者审核继续保留 C01—C09、问题关闭与作者确认，不拿阶段桥接替代它们。实际修改的 `revised_verified` 由原版本与问题关闭机制证明，阶段桥接不单独签发“优化完成”。

机器通过只说明来源、版本、锚点和反馈记录完整；`editorial_quality_verified/author_selection_verified/audience_effect_verified/publication_authorized/media_export_authorized` 均为 false。即使记录完整，编辑判断仍可错误，真实受众效果仍需反馈验证。

## 本次变动记录

| 意图 | 决策 | 理由 | 证据 | 生效范围 |
|---|---|---|---|---|
| 目的在独立包装不再丢失 | 扩展既有 context manifest，并由 resolve 与新 handoff 消费 | 已有目标不应另建真源 | P1 盘点；本案 C03/C06 后评差异 | 当前新交接，不改历史 JSON |
| 产物判断有具体依据 | C01 同源目的证据与阶段职责；原 review-integrity 下补阶段桥接 | 格式、悬念或事实正确不能代替目的适配 | 具体产物引文与四项取舍说明 | 记录完整性，不宣称语义认证 |
| 反馈不能被旧排序遮盖 | 版本绑定、前序反馈承接、已有作者记录对照 | 后评必须被当前消费者看见 | 当前上下文与阶段复核哈希 | 受影响步骤；不改变作者选择 |
| 保留自由与历史 | 职责不映射方法；技术入口保留；旧证据不改写 | 同目的可采用多种表达 | 现有 creation-route 和局部复用规则 | 不改稿件、媒体或导出状态 |

回退时仅撤销本次代码和文档改动，保留所有新增复核证据及历史文件；不得重置无关 dirty 改动或删除作者库。
