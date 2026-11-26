# 编号画风接入自媒体流程

更新时间：2026-10-03 11:32:00 +08:00。执行工具：Codex。

复用 yang0 的 [handraw-style](https://github.com/yang0/handraw-style) 与现有 Content Studio 适配器。当前本地固定版本提供 280 种画风、136 种版式、36 种配色；具体版本、来源哈希和运行合同以 [库说明](../../content-studio-poc/docs/handdraw-style-library.md) 为准。不要另装一套工具，也不要自动跟随上游更新。

## 接在哪里

沿用已有流程：稳定母稿 → 确定每张图的用途与视觉路线 → **可选编号画风** → 既有出图/排版入口 → 实际图片与成品审核。选题、对标、结构、情绪和口吻优化仍在母稿阶段完成；画风选择不能充当这些步骤的完成证据。

Agent 复用同一个内容对象、槽位和中央路由卡。仅当配图要表达概念或情境、当前槽位为 `generated-image` 且仍处于 `planned/candidates-ready` 时使用全量 `prompt` 入口。数据图、流程图、条款证据图继续使用对应渲染器。当前全量提示词接口只支持文章槽位；视频配图或社交卡不能仅因库里存在对应版式就声称已接通渲染。

## 怎么调用

用户可以直接说：“打开画风库”“这张配图用 175 号，沿用已有配色”“175 号加 SC-001，主题沿用这张图的用途”。Agent 使用以下已有入口：

```powershell
python -B <workspace>/content-studio-poc/scripts/handdraw_style_brief.py gallery
python -B <workspace>/content-studio-poc/scripts/handdraw_style_brief.py catalog --query 175
python -B <workspace>/content-studio-poc/scripts/handdraw_style_brief.py prompt --item <content-item.json> --target-id <slot-id> --request <request.json> --output <new-prompt.json>
```

请求结构复用 [现有样例](../../content-studio-poc/fixtures/handdraw-style-library/prompt-request.json)。该样例的便签、文案和蓝色都是虚构测试输入，不是个人品牌默认值。真实任务填写已确认主题的中英文表达；指定版式时同时明确构图；默认沿用当前内容配色，只有明确选色时才填写 `color_ids`。`frozen_text` 只放已确认原文，不让提示词工具润色事实或数字。

输出已包含内容哈希、槽位 ID、画风编号、上游提交、参考图路径和哈希。将提示词文件引用记入已有路由卡的视觉说明，不重复抄写元数据，不新建第二张路由卡。参考图只借线条、笔触、媒介和质感，人物、物件、场景及构图以本任务为准。

## 完成状态要分别记录

| 实际进度 | 必须有的证据 | 可以说什么 |
| --- | --- | --- |
| 已选画风 | 编号、适用槽位、选择理由 | 画风已选；未出图 |
| 提示词已生成 | 绑定当前内容哈希的双语提示词文件 | 提示词已准备；未出图 |
| 已出候选图 | 实际图片文件及生成记录 | 候选已生成；待检查 |
| 已完成图片审核 | 当前图片的可读性、事实、配色、参考图误复制检查结果 | 指定图片检查完成；不等于整篇已验收 |
| 已进入成品 | 现有排版/视频产物及相应成品审核 | 按原流程记录成品状态；发布仍按原规则 |

内容或图片变化后，重做受影响的提示词绑定和审核。提示词中写了“不抄构图”不等于实际图片已通过检查；不能以测试样例、提示词文件或图库浏览成功代替实际出图验收。涉及本人形象时继续遵循 `lucas-personal-visual-system` 的身份参考规则。

## 本次核验

2026-10-03：`gallery` 入口成功；虚构便签样例 `prompt` 成功，产物见 [提示词包](../../content-studio-poc/outputs/handdraw-workflow-20261003/prompt.json)。全量库 16 项、旧 brief 20 项定向测试通过，覆盖素材与来源哈希、内容绑定、禁止误改路线和未审核状态保留。首次全量库运行有两项遇到沙箱临时目录权限错误；在获工具批准的沙箱外复跑后通过。

本次未生成图片，未重跑浏览器交互或系统剪贴板验收；历史浏览器验收范围保留在库说明中。本次只补齐已有调用入口在自媒体流程中的位置与交付判定，不改动渲染器、品牌配置或历史稿件。

自媒体 `self_media_agent.py doctor` 通过，现有五条 recipe 保持可解析。调用入口放在中央路由卡与 Skill 运行册；未扩展受 100 行/9 KiB 预算约束的 Agent 发现文件。
