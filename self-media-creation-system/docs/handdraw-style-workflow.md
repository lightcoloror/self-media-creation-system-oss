# 编号画风接入自媒体流程

公开适配：2026-11-08，Codex（精确运行模型未独立核验）。第一方通用流程文档，保留原历史署名；源为共享工作快照，不冒充主流程仓库原提交的文件。文中的记录卡和示意内容不代表真实研究、制作、客户授权或发布已完成。

更新时间：2026-10-03 11:32:00 +08:00。执行工具：Codex。

复用 yang0 的 [handraw-style](https://github.com/yang0/handraw-style) 与公开 ContentStudio 的薄适配器。上游图、完整库、模型校准资料和外部 Skill 不随本主流程版分发；使用方应明确提供经过来源、许可与哈希核对的固定上游 checkout，不自动更新。配置记录见[固定来源与权利状态](https://github.com/lightcoloror/content-visual-studio-oss/blob/fabb8b47ea45cf40f248c3300bd5b16647812aeb/config/handdraw-style-library.v1.json)，实际接口见[公开适配器](https://github.com/lightcoloror/content-visual-studio-oss/blob/fabb8b47ea45cf40f248c3300bd5b16647812aeb/scripts/handdraw_style_brief.py)。编号数量以所选版本实际目录为准，元数据不等于素材已获再分发许可。

## 接在哪里

沿用已有流程：稳定母稿 → 确定每张图的用途与视觉路线 → **可选编号画风** → 既有出图/排版入口 → 实际图片与成品审核。选题、对标、结构、情绪和口吻优化仍在母稿阶段完成；画风选择不能充当这些步骤的完成证据。

Agent 复用同一个内容对象、槽位和中央路由卡。仅当配图要表达概念或情境、当前槽位为 `generated-image` 且仍处于 `planned/candidates-ready` 时使用全量 `prompt` 入口。数据图、流程图、条款证据图继续使用对应渲染器。当前全量提示词接口只支持文章槽位；视频配图或社交卡不能仅因库里存在对应版式就声称已接通渲染。

## 怎么调用

用户可以直接说：“打开画风库”“这张配图用 175 号，沿用已有配色”“175 号加 SC-001，主题沿用这张图的用途”。Agent 使用以下已有入口：

```text
content-studio-handdraw gallery --library-root "<pinned-library>" --output-root "<new-gallery-output>"
content-studio-handdraw catalog --library-root "<pinned-library>" --query 175
content-studio-handdraw prompt --library-root "<pinned-library>" --item "<content-item.json>" --target-id "<slot-id>" --request "<request.json>" --output "<new-prompt.json>"
```

请求字段按[公开 prompt 实现](https://github.com/lightcoloror/content-visual-studio-oss/blob/fabb8b47ea45cf40f248c3300bd5b16647812aeb/scripts/handdraw_style_library.py)核对：`style_number`、已确认的 `theme.zh/en`、`frozen_text`，以及按需提供的版式/构图和颜色编号。上面的命令含待替换路径，只是入口说明；本主流程公开版没有附带旧便签样例，不得声称它已运行。真实任务填写已确认主题的中英文表达；指定版式时同时明确构图；默认沿用当前内容配色，只有明确选色时才填写 `color_ids`。`frozen_text` 只放已确认原文，不让提示词工具润色事实或数字。

输出已包含内容哈希、槽位 ID、画风编号、上游提交、参考图路径和哈希。将提示词文件引用记入已有路由卡的视觉说明，不重复抄写元数据，不新建第二张路由卡。参考图只借线条、笔触、媒介和质感，人物、物件、场景及构图以本任务为准。

## 完成状态要分别记录

| 实际进度 | 必须有的证据 | 可以说什么 |
| --- | --- | --- |
| 已选画风 | 编号、适用槽位、选择理由 | 画风已选；未出图 |
| 提示词已生成 | 绑定当前内容哈希的双语提示词文件 | 提示词已准备；未出图 |
| 已出候选图 | 实际图片文件及生成记录 | 候选已生成；待检查 |
| 已完成图片审核 | 当前图片的可读性、事实、配色、参考图误复制检查结果 | 指定图片检查完成；不等于整篇已验收 |
| 已进入成品 | 现有排版/视频产物及相应成品审核 | 按原流程记录成品状态；发布仍按原规则 |

内容或图片变化后，重做受影响的提示词绑定和审核。提示词中写了“不抄构图”不等于实际图片已通过检查；不能以测试样例、提示词文件或图库浏览成功代替实际出图验收。涉及可识别人物时，继续由使用方提供已授权身份参考及其适用合同；不从画风参考中复制人物身份。个人 IP Skill 与身份素材不随本版分发，也不自动安装。

## 历史记录与本次公开范围

原2026-10-03文档记录的图库、提示词与定向测试结果属于本机历史记录；对应输出、临时目录和浏览器记录不随本版分发，本次没有重跑，不能当成本次公开安装或出图验收。原文保存在私有来源快照。

本次仅将现有入口、显式外部库路径、槽位约束和状态区分接入公开方法文档；未下载上游库、出图、启动服务或浏览器、修改渲染器/品牌配置，未改实际稿件。已有路由卡引用提示词和图片证据，仍由原事实、来源、权利、隐私与人工确认流程决定后续状态。
