# CTA 选择、位置与实际落地复核

2026-10-29｜Codex（当前运行模型的具体版本未独立核实）。适用于现有脚本审核、发布辅助页和视频交付入口。

必须作出选择，不是必须添加 CTA。互动与获客分别判断；`not_used` 加理由是有效结果，不能因“不获客”直接跳过互动选择。具体内容、表达方式和位置继续服从本条内容的目的，不固定结尾、不限制为同一种句式。

## 一份选择记录，沿原流程消费

复用 `scripts/cta_review.py` 的轻量校验适配器、现有文件哈希引用和最终人审记录；不增加发布器、生成器或内容分类模型。

1. **脚本审核**：现有 `review-prerecord-draft` 要求 `cta-plan`，绑定本版脚本。互动可用于邀请观众回答、分享或参与讨论；获客用于服务咨询、线索或联系转化。分别记录采用/不采用及理由。采用时逐处记录具体文案、位置和选择该位置的理由；获客同时明确服务边界。不能把一句自我反思或叙事中的疑问自动判成互动 CTA。
2. **录制前与剪辑前复核**：`verify-prerecord-timing` 检查当前脚本绑定；口播 CTA 必须在脚本实际口播正文中。脚本或选择改变时重审，不能复用旧通过记录。录制前不强求最终时间码；进入 `video-delivery preflight` 后，片内位置必须有有效起止秒数。
3. **发布文案检查**：各发布条目与交付 manifest 引用同一 `cta_plan_ref`。发布台 `check` 核对目标平台、字段以及已选文案是否真的存在于对应字段；放在简介不能冒充片内或置顶评论。生成草稿仍允许缺项，但显示待复核。修改文案或引用后，网页状态失效，保存并重跑原检查。
4. **成片验收**：原有 `video-delivery check / deliver` 的人审环节要求 `acceptance.cta_landing`。绑定本版计划、最终视频和原有完整输入指纹，核对片内实际听到/看到的文字、时间与位置、观察证据，以及当前发布文案。未采用也须确认实际没有未计划的 CTA，不能只用计划或勾选待办冒充落地。

支持的位置：`video_spoken`（视频口播）、`video_overlay`（片内文字）、`publication_body`（平台简介/正文）、`pinned_comment`（准备的置顶评论）。片内位置用时间码，可在中段或结尾；发布文案位置用平台与字段。其他载体应先适配实际消费端，不用错误位置凑通过。

## 初始化与绑定

```text
python scripts/self_media_agent.py video-delivery cta-init --project-id <项目ID> --script <本版脚本> --output <新的cta-plan.json>
python scripts/self_media_agent.py video-delivery cta-bind --input <交付manifest.json> --plan <已复核的cta-plan.json> --output <新的manifest.json>
```

初始化为 `undecided`，不会自动同意添加或省略。绑定仅验证并保存新 manifest，清除旧最终验收引用，不会修改视频或发布。把同一个计划的 `path`、`sha256` 引用登记到发布数据各相应条目的 `cta_plan_ref`，再按原流程核验。

计划最小示例（仅说明结构，哈希须来自真实文件；不能照抄为项目审批）：

```json
{
  "schema": "self-media.cta-plan.v1",
  "project_id": "example",
  "script_ref": {"path": "<本版脚本绝对路径>", "sha256": "<真实SHA256>"},
  "decisions": {
    "interaction": {
      "decision": "use",
      "reason": "邀请观众表达自己的判断困难，服务本条讨论目的",
      "placements": [{
        "id": "audience-question",
        "location": "publication_body",
        "platform": "douyin",
        "text": "你在选择时最想弄清楚的是什么？",
        "reason": "保留片内叙事的自然收束，在正文承接讨论"
      }]
    },
    "acquisition": {
      "decision": "not_used",
      "reason": "本条分享经历，不安排服务咨询或线索转化",
      "placements": []
    }
  }
}
```

如果两类都不采用，两类都填写 `not_used`、具体理由和空 `placements`，同样可以通过。若采用获客，添加 `service_boundary`。若改为片内位置，移除 `platform`，添加 `start_seconds` 和 `end_seconds`；口播文案与当前实际脚本一致。

## 最终验收记录

在原有完整人审 acceptance 内新增如下字段，保留原来的审核人、日期、完整观看和输入指纹等要求：

```json
{
  "cta_landing": {
    "plan_sha256": "<本版计划真实SHA256>",
    "video_sha256": "<最终成片真实SHA256>",
    "prepared_copy_reviewed": true,
    "unplanned_cta_absent": true,
    "notes": "<实际看听成片并检查各平台已准备文案后的观察，包含未采用项>",
    "observations": [{
      "id": "<计划中片内位置ID>",
      "location": "video_overlay",
      "text": "<实际看到的文字>",
      "start_seconds": 117.0,
      "end_seconds": 120.0,
      "evidence_ref": {"path": "<观察证据文件>", "sha256": "<真实SHA256>"},
      "evidence_note": "<如何在本版最终成片对应窗口核验，不能只描述制作计划>"
    }]
  }
}
```

片内每个位置都须覆盖，不能多、少或重复；文案、载体必须相同，观察时间与计划相差不超过 0.25 秒且不超片长。这是编辑定位容差，不是强制观众停留时长。片内没有 CTA 时 `observations` 为空，仍需要真实观察和文案复核。审核发现未计划的互动或获客内容，应修改选择记录或内容并重审；不能勾选“没有”掩盖差异。

代码验证文件版本、字段匹配、观察记录完整性和时间位置；它不声称自动理解全部画面/音频语义，不能单靠哈希证明文字可读或人物确实说过。实际看听和语义复核沿用现有人审。发布台核验的是**已准备的本地文案**；置顶评论是否在线发布仍须按原发布状态/账号操作流程记录。

## 迁移与边界

旧工程与旧发布页可继续读取、显示草稿。下一次请求当前完整验收时，补齐选择记录和实际落地复核；不回填假审批，也不追溯修改已发布的成片。本次改变后续流程和校验，不追溯修改已发布项目。

## 变动依据

| 变动 | 意图 | 决策 | 理由 | 证据 | 生效范围 |
|---|---|---|---|---|---|
| 两类选择与位置记录 | 防止非获客等同于无互动、漏掉取舍 | 复用版本绑定；两类独立 use/not_used 与理由 | 用户明确要求可省略但须说明 | `cta_review.py`、`tests/test_cta_review.py` | 采用记录，不强制生成 CTA |
| 脚本/朗读节点接入 | 在录制前发现漏选与脚本漂移 | 原配方增加 `cta-plan` 输入并验证当前脚本 | 发布阶段才决定可能来不及口播 | `prerecording_validation.py`、配方和原执行测试 | 现有案例脚本录制前路径；共用视频交付仍覆盖其他视频路径 |
| 发布台核验 | 区分片内、简介与评论 | 校验本平台实际字段、显示选择，输入变化失效 | 计划、准备和在线发布是不同状态 | `publication_desk.py`、共享模板、浏览器回归 | 重新生成/检查的本地发布页 |
| 最终落地验收 | 防止只验计划不验实际成片 | 计划/视频哈希、完整观察、时间、文案核对 | 本次已发布案例暴露载体复核缺口 | `video_delivery.py`、真实合成媒体回归 | 后续完整交付；原人审和资源保护保留 |
| 入口与测试适配 | 保持可发现且不放松已有校验 | 历史长说明保留到详细文档；合成视频补实际 AI 标识 | 发现入口原超长，测试素材缺少现行标识要求 | 原始文件快照、回归记录 | 发现入口及合成测试，不改真实项目 |

当前测试结果和修改清单见 [实施与验证记录](cta-workflow-implementation-20261029.md)。
