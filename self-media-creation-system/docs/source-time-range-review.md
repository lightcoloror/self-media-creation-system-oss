# 粗剪、精剪配方与素材要求审核：原片时间区间

更新时间：2026-10-25（Asia/Shanghai）；执行：Codex，运行模型标识未独立核验。
依据：用户本次明确要求将默认行为落实为代码约束。

## 唯一审核入口

```powershell
python scripts/self_media_agent.py video-review policy
python scripts/self_media_agent.py video-review prepare --purpose rough_cut_recipe --request <request.json> --output-dir <new-review-dir>
```

`--purpose` 允许 `rough_cut_recipe`、`fine_cut_recipe`、`material_requirement`。
输入复用 `self-media-human-review-request-pack.v1`：每项包含原片路径、SHA-256、原片起止秒数、审核问题。顺序即配方审核顺序；时间均为原片时间，不是拼接后的时间。

命令直接调用现有 VKP `prepare_targeted_review_pack`。输出原来的 `targeted-review.html`、`targeted-review-pack.json` 和审核决定文件，不复制、剪辑、转码、拼接、导出视频或音频。打开页面仍使用 VKP 原有 loopback `serve`。页面入口不可用时明确失败，不回退导出片段。

```powershell
$env:PYTHONPATH='<VKP>/src'
python -m video_knowledge_pipeline.targeted_review serve <new-review-dir> --host 127.0.0.1 --port 0
```

## 代码约束

- `video_review_delivery.py` 校验用途、输入字段、`source_time_range`，拒绝未知导出字段、`independent_clip` 和预先写入通过状态；无 `--force` 或导出权限开关。
- VKP 对源哈希、存在性、有限时间边界、审核范围、问题和页面合同继续做原有校验。用户决定仍保存在原来的审核决定文件中。
- MVP 粗剪工作区默认 `script_aligned_source_time_ranges`；不能将旧独立片段策略重新计算哈希后作为新工作区通过。
- 旧技术审片计划不再要求代理视频，`proxy_first=false`、`proxy_profile.enabled=false`；审核回执必须引用同一路径、同一哈希的原片。技术 QA 仍可读取原片向 null 出口检测并保存日志，不生成审核视频。
- 执行器拒绝重新封装的代理计划或独立片段请求，且在调用 FFmpeg 前拒绝；禁止接入导出片段的审核回执。

## 审核与实际制作分开

### 2026-10-25 20:52:50 | Codex：精剪文字和动效不能只写在说明里

`fine_cut_recipe` 输入必须声明 `presentation_requirements`，包括 `required_layers`（dialogue/age/context）、`animated_speakers`（child/father/neutral）和适用理由 `style_reason`。粗剪与纯素材检查可不适用；不能把萌娃可爱风格强加给所有项目。

每个区间用 `expected_dialogue` 记录已知对白的原片时间、说话人和显示文本。确实没有对白时用空数组及 `no_dialogue_reason`；个别对白不加字幕须给 `omission_reason`。已有人工修订与可信定位直接使用，不要求用户重新输入已确认信息。这份清单不是自动听写，也不能证明未登记的对白全被发现。

代码检查清单中的对白确实出现在 `subtitle_cues`，所需文字层未丢失，明确要求的说话人没有漏动画，字号使用现有 MVP `typography-gates.v1.json` 的下限。同人字号变化需要 `emphasis_reason`；播放器基础颜色不再随不同动画种类任意变化，显式强调才能改变。强调原因随 canonical pack 保存。

生成后重新读取实际 `targeted-review-pack.json`，核对全部指定字幕属性，时间仅允许生成器已有的毫秒舍入。写出绑定原请求及审核包哈希的 `presentation-check.json`；丢字段直接失败，不把“输入写过动效”当成页面已应用。

门禁通过仍只表示结构和已知要求传到播放器。实际字体加载、播放/暂停/跳时动画、手机可读、遮挡及导出效果须在对应产物检查；报告始终不自动设置人审通过。

用户说“审核粗剪结果”“审核精剪配方”“这个片段合不合适”“放到精确审核页”，均不构成实际导出请求。
只有本次原生用户消息明确要求实际成片或独立片段时，才另走已有生产入口。审核通过、AI 填写 `user_approved=true`、历史授权或任务模板不能替代该请求。生产入口不会从本审核命令自动触发。

已有代理视频合同和旧片段策略保持原文件不动，但不能用于当前执行；需基于原片重新生成计划。旧 v1 粗剪工作区仍可只读解析，不因此取得导出权限。

## 验收与限制

测试应覆盖三种用途、准确保留时间范围和顺序、独立片段/代理/伪批准/未知字段被拒绝、失败前不调用执行器、源哈希漂移、同内容复制文件不能替代原片、技术 QA 缓存复用。

约束适用于这些已接入的流程入口，不是操作系统沙箱，也不鉴别一段任意文本是否确实来自用户。具有任意终端权限的 Agent 理论上仍能绕开入口；发现此类行为应视为违反用户指令，而不能宣称本地 JSON 字段可提供密码学授权证明。

生效范围：审核路由、粗剪工作区默认值、上游审片计划及回执、技术执行器。没有新增播放器、ASR、渲染器、发布入口；不改永久资源策略，不覆盖原片和已有审核决定。

### 本次验证记录（2026-10-25，Codex）

- self-media：入口 30 项、上下文审片合同 20 项、原片审核交付 7 项通过。
- MVP：粗剪工作区 10 项、技术执行器 10 项、素材 CLI 1 项、发布粗剪门禁 1 项通过。
- 真实方案 B 请求通过新入口准备：3 个原片、3 个区间，`media_copies_created=0`；输出目录仅有 HTML 和两个 JSON。未据此宣称内容已经人工审核通过。
- 单独运行旧 `test_context_manifest_consumer.py` 仍失败：其夹具请求已经不存在的 `execute-owner-task` 步骤（`step_unresolved`）。这是跨工具旧夹具与现行配方不一致，未放宽步骤校验绕过；该项不计入上述 79 项通过测试。完整仓库测试未运行。
