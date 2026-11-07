# 选题、平台与通用文章的现有入口连接

2026-10-29，Codex；具体运行模型未独立核验。

## 先发现当前入口

```powershell
& <workspace>/scripts/local-tools.ps1 discover content-creation-system
```

运行返回的 `contract.cli.self_media_resolve`，替换请求和输出路径。源码目录不等于当前执行目录；当前注册 launcher、Python 路径及固定运行副本以本次 discover 为准。不要从旧笔记复制开发目录命令，也不要执行注册表全部命令。

`resolve` 仍是只读选择器，不生成正文、写作者确认或发布。每完成一个实际步骤后，将产物引用及哈希放进原 `work_request.current`，重新 resolve。它读取现有作者存储，不新增状态库。不要重放旧的 next_action。

## 选题来路与采用依据

在已有 `context_manifest.editorial_context.topic_selection` 写入：

```json
{
  "topic": "当前内容具体要回答的问题",
  "origin": "user_assigned",
  "origin_source": {"artifact_id": "request-source", "quote": "已保存的提出选题原文"},
  "adoption": "selected",
  "adoption_basis": "说明为何本次采用，或引用用户已明确指派的范围",
  "adoption_source": {"artifact_id": "request-source", "quote": "已保存的采用依据原文"}
}
```

这不是可伪造通过的模板。`request-source` 必须是同一 manifest 的真实 artifact，含原路径和 SHA256；两处引用均核对原文字节。`origin` 支持 `user_assigned / agent_proposed / tool_trial / existing_topic`；`adoption` 支持 `selected / candidate / deferred`。候选、暂缓不会进入写稿。

已有用户指派或既有决定可复用，不要求每次额外询问。Agent 提议与工具试用不得冒充用户原选题。采用选题不等于作者认可稿件，更不等于发布授权。程序验证绑定，不认证自然语言真伪或人工身份。

如果已有选题框架决定，使用 `current.topic_decision={path,sha256}` 传递原 `topic-angle-decision.v2`，并用 `topic_selection.decision_artifact_id` 指向 manifest 中同一决定文件。两边必须匹配，继续调用原四结果检查；不能把 pending 改为 confirmed，也不能忽略已声明的框架决定。明确固定范围的任务可沿用现有选题依据，不强制重造多套角度。

## 形态与平台分开

原工作请求分别填写 `content_format` 和 `platform`，理由仍记在 `selection_basis`。平台从当前 canonical overlays 选择；缺少时返回可用选项，不从形态反推。

- `article` 对应 `longform-article`，可选 `wechat-article / zhihu / toutiao` 等既有兼容平台。
- `graphic_note` 对应 `graphic-note`，只有明确小红书才选小红书配方；知乎等平台走既有文体与平台 overlay。
- `short_post` 对应旧名 `moments-short-text`，这个历史文体名不再表示一定发朋友圈。只有明确 `wechat-moments` 才进入朋友圈配方，微博等走对应 overlay。
- 其他脚本/视频明确其既有文体；平台与文体不兼容时报冲突，不能偷偷改成另一个平台。技术返工和已有交付审核不因此重开选题。

## 通用文章的实际消费者

1. `current.author_context` 引用现有 `author-writing-context.v1`。没有时提示现有 `author_writing_context.py prepare`，先查已有记录，不另建作者库。
2. 现有七项 preflight 加 `entry_binding`，复制本次选择器计算的值。该值绑定选题及依据、目标/受众来源、反馈、创作决定和形态/平台。只有目的等实际条件变化才需要重新核对；稿件正常新增、切换阶段不单独触发该绑定失效。
3. 复用或真正写好正文后，现有 `author_writing_context.py revision` 登记同版作者版本。`current.author_revision` 绑定这个结果，purpose manifest 的 current_body 绑定同一稿件，不能拿另一个文件代替。
4. 选择器实际调用原 `editorial_integrity.check_draft/status`。缺 C01-C09、必改未关闭、当前准备不足时，返回原 `review-integrity record`；要先实际检查/修改，不得仅补通过记录。有效历史检查按原机制复用。
5. 检查完整后返回 `article_review_package`，包含当前稿、版本、选题、形态/平台和编辑状态。没有作者确认时是 `awaiting_author`，next_action 为 `human_review`，不会输出代填确认命令。
6. 这个包仅是编辑审核入口，不是排版成品。平台排版、实际渲染检查和人工发布分别列为剩余步骤；公众号继续复用 Content Studio 的 `wechat_article_format_adapter.py` 和已有公开审核稿模式，不自动执行或冒称完成。

所有 JSON 引用先验哈希；现有作者路径和数据库限制保持原样。不能将原开发库或另一作品的上下文直接改标签移入当前副本。需要迁移时保留原证据并按原迁移机制办理。

## 变动依据

- 意图：让已有流程的选题、形态/平台和编辑验收真正相连。
- 决策：扩展原 context/work_request，复用 purpose anchors、canonical overlays、作者存储及编辑校验；五个受管目标不变。
- 理由：文档顺序和指南链接不等于当前产物已被消费者核验；不增加新编排系统。
- 证据：`tests/test_editorial_connections.py` 与原入口/目的/编辑回归；实际运行结果记在本轮本地交付记录。
- 生效范围：本地注册运行副本的新创作选择和通用文章审核；旧结果、基线、开发目录、线程设置与发布边界不变。
# 2026-10-29 后续连接：排版与同版成品审核

当前 `resolve` 在编辑记录齐备后同时返回 `article_review_package` 和下一步。
作者未决定仍为 `awaiting_author`，但 `production_next_action` 提供可另行执行的候选排版准备；它不是作者确认，也不授予预览服务器权限。

1. 执行 `self_media_agent.py article-delivery prepare --request CURRENT_REQUEST --output NEW_ITEM.json`。
   自动从当前稿生成既有 Content Studio 对象，不改正文。默认内容门全为 needs-review、作者为 required，公开材料标签为空。已有同版内容对象可由 `current.article_source_item` 引用，保留其来源、门和作者状态，不复造证据。
2. 根据真实材料完成适用的公开材料声明/隐私检查，再把对象 path/SHA 写入 `current.article_item`。不得为了运行而自动填 pass 或 approved。resolve 调用原渲染器的输入校验；只支持已实现的公众号 public-review 文本范围，其他平台明确报告尚无制作器。
3. 沿 resolve 返回的 `wechat_article_format_adapter.py render --mode public-review ...` 命令生成全新目录，把原 `manifest.json` 引用放入 `current.article_render_manifest`。旧目录和旧结果保留。
4. resolve 验证正文、内容对象、三个 HTML 和原 render-receipt 的绑定，再返回桌面、移动、暗色三项观察模板。实际查看对应预览后记录观察和截图哈希，放入 `current.article_visual_review`。不得把测试图片/模板填充当作实际视觉验收。
5. `resolve` 或 `article-delivery check --request CURRENT_REQUEST --output NEW_PACKAGE.json` 汇总现有稿件、选题、作者记录、排版和视觉观察为同一个作者审核包。不用视频发布台伪装文章项目。

`check` 退出码 0 只表示检查命令完成并输出当前包，必须读取其中 status/remaining_steps；它不宣称业务完成。输出中的 `rendered_artifacts_verified` 是文件与回执一致性，visual review 是记录校验，不独立证明判断正确或手机/后台显示。`final_media_verified` 不被本桥接提升；作者、平台后台及人工发布仍独立。

旧受管请求也须与当前 request_id 相同，并带 resolve 返回的 entry_binding。无绑定或绑定过期只返回新请求模板，禁止先执行旧请求再补登记；旧文件不覆盖。旧配方的直接历史接口仍可读，本约束用于新的父子交接。

意图：闭合已审稿与现有制作/验收消费者；决策：增加薄适配，不建新流程系统；理由：防止重复编辑检查或串任务；证据：`test_flow_connections.py`、`test_research_delivery_connection.py`；范围：注册入口、公开文本候选、同版文件/观察绑定，不创建任何确认或发布。Codex，精确模型未独立核验。此前说明保留；本节补充其后续制作与验收连接。

