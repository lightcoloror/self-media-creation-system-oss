# 粗剪、精剪配方与素材要求审核：原片时间区间

更新时间：2026-10-25（Asia/Shanghai）；执行：Codex，运行模型标识未独立核验。
依据：用户本次明确要求将默认行为落实为代码约束。

## 唯一审核入口

```powershell
python scripts/self_media_agent.py video-review policy
python scripts/self_media_agent.py video-review pre-review-audio-audit --timeline <timeline.json> --script <script.md> --identity <identity.json> --output-dir <new-review-dir>
python scripts/self_media_agent.py video-review prepare --purpose rough_cut_recipe --request <request.json> --output-dir <new-review-dir>
```

`--purpose` 允许 `rough_cut_recipe`、`fine_cut_recipe`、`material_requirement`。
输入复用 `self-media-human-review-request-pack.v1`：每项包含原片路径、SHA-256、原片起止秒数、审核问题。顺序即配方审核顺序；时间均为原片时间，不是拼接后的时间。

### 2026-11-22 15:23 +08:00 | Antigravity：审核窗口「所听即最终效果」+ 纯音频 VKP 二次复核分流默认规则

经用户明确指令固化，所有生成 `rough_cut_recipe`（及切口审核类）VKP 原片时间段审核页的 Agent 必须遵守：

1. **交付作者审核页之前，先做「纯音频拼接 + VKP 二次分析 + 切口声学边缘自动检查」**：
   - 当原片有效率较高、不触发中间粗剪视频导出（`source_time_range` 路线，严禁为了检查而渲染 GB 级中间粗剪 MP4）时，**必须按拟定 `cut_in`/`cut_out` 先拼出轻量纯音频 WAV（16 kHz mono，通常仅十几到几十 MB）**，连播送入本地官方 VKP（独立二次 ASR，如 SenseVoice）做全文逐字复核，并逐切口检测首尾 25ms 声学边缘电平：
     - 自动检出并原地修复：吃首字/吞字、截断尾音、漏入相邻废句首字/残音、漏句/漏删重录；
     - 自动修复后须复测切口边缘电平落回静音谷；
   - **只推疑点与关键点进作者审核页**：经 VKP 二次 ASR + 静音边缘双检干净通过的常规切口直接标为 `verified_keep` 过滤掉，**严禁把几十上百条原始切口全量倾倒给作者逐条点听**；作者 VKP 审核页只呈现：自动修复后的复核点、紧切口/二次 ASR 异常点、词级精切/创意硬切点、以及片头/换场/片尾大边界。
2. **只播最终保留效果，不让用户去时间轴找某一秒发生了什么**：`[review_start_seconds, review_end_seconds]` 必须直接锁死在实际剪辑后的切口边缘，严禁把前导长静默或整段拟删废句塞进播放窗口让用户自行听辨“第几秒开始删”。
3. **切入点卡（片头、跳过试录后的正文开头、删废后的接续句）**：`review_start_seconds` 直接等于**最终切入点**（保留首字前安全呼吸点），向后播 3–5 秒最终保留正文；问题只问最终开头效果（起音是否自然、是否吃字、有无前句废音残留）。
4. **切出点卡（词级精切、紧切口、硬切点、换场收尾与片尾）**：`review_end_seconds` 直接等于**最终切出点**（保留尾字后安全尾音点，播到即停），向前给 3–4 秒保留正文；问题只问最终结尾效果（尾音是否完整、有无突兀截断或漏出后句废音）。
5. **短保留整句（≤5 秒）合并单卡**：直接从 `cut_in` 播到 `cut_out`，一次听完首尾效果，不拆成两条重复播放。
6. **例外范围**：仅当某段废句存在“是否包含不可替代的独特信息”等真实语义去留争议、必须让作者听清被删内容本身时，才可单独给出该争议段卡片并写明争议点；常规删废、去静默、去口误一律只呈最终切口效果。

- 变更记录：Intent=零中间大视频前提下自动抓出吞字/漏废字并大幅减轻人工审核负担，让“按下播放即验收最终听感”；Decision=在 `source-time-range-review.md` 与各 Agent 发现入口固化纯音频连播 VKP 二次复核分流 + 最终切口对齐规则；Reason=用户于 2026-11-22 实测指出两项关键改进（不导出大视频也应连播纯音频走 VKP 二次自动检错分流；审核卡片只给最终切口效果）；Evidence=本次会话用户两次直接指令及实测自动捕获修复 5 处吞字/漏废字切口并从 63 条压减至 16 条；Scope=所有调用 VKP 原片时间段审核页的 Agent（文档与规则层，不改历史只读发布包）；Rollback=撤回本节及对应发现入口条目。

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

## 精剪和动效送审前画幅门禁

2026-11-22（Asia/Shanghai），Codex。依据为本期竖拍原片的编码尺寸与实际显示方向不同、动画合成越出画幅的实测回报。

每支片先确定目标画布。用实际原片、动画渲染成品、动画插入后的合成产物核对显示比例。FFprobe 优先读显示矩阵，回退到旋转标签，同时计算像素宽高比。全幅画面比例错、旋转信息无效或产物变更时中止送审。卡片内的原始图片可以有自己的比例，检查其在画布内的合成位置。

在实际合成器里测量花字、字幕、证据卡和动画的可见范围。网页合成器在可见容器上标注 `data-frame-layer`，定格后用 `scripts/video_frame_measurement.mjs` 的 `measureFrameBounds` 采集应用了字号、换行及动画变换的实测边界。测量画布裁切前的范围，覆盖进场、稳定、退场和动画最大位移或缩放的位置。边界越出画布或漏采登记的可见层时中止送审。平台安全区、遮挡和文字可读性沿用原有检查。

检查计划使用 `self-media.video-frame-safety.v1`，包含 `project_id`、`canvas`（宽高）、`duration_seconds`、`composition_ref`、`sources`、`layers`、`sample_times_seconds`、`measurements_ref`。产物引用使用绝对路径和 SHA-256 的 `{path, sha256}`。

- `sources` 每项记录 `stage` 和 `artifact_ref`。阶段为 `program`、`animation_render`、`animation_insert`。实际使用独立动画视频时，渲染和插入的对应产物都要登记。
- `layers` 每项记录稳定的 `id`、`role`、`start_seconds`、`end_seconds`，以及有位移或缩放极值时的 `motion_extrema_seconds`。角色为 `flower`、`subtitle`、`evidence_card`、`animation`。所有检查点按拼接后整期时间轴记录到毫秒。
- `measurements_ref` 指向 `self-media.compositor-frame-measurements.v1`，其 `composition_ref`、`canvas` 与计划一致。每个 `samples` 项包含 `time_seconds` 与 `bounds`，后者按图层 ID 记录实测的 `[left, top, right, bottom]`。
- VKP 精剪请求用 `frame_safety_plan_ref` 引用计划。计划的 `review_payload_sha256` 用 `video_frame_safety.review_payload_hash` 计算，`review_program_starts` 按卡片 ID 记录区间在整期中的起点，用于把原片字幕时间换到整期时间轴。`video-review prepare` 在调用审核页生成器前检查，并在审核包保存 `frame-safety-check.json`。

HyperFrames 等独立合成路线在生成交付审核页前运行以下检查。返回阻断时修正画布或图层再重测。

```powershell
python scripts/self_media_agent.py video-review frame-precheck --plan <plan.json> --output <new-review-frame-check.json>
```

同一份计划随剪辑交付。导出后按原检查点从实际成片抽帧，核对解码画幅，并逐点检查花字、字幕和证据卡是否完整。参见 [视频交付](video-delivery.md)。

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

## 口播粗剪导出后的复查

标准 FFmpeg 粗剪导出会登记实际视频、源时间映射和渲染回执，输出 `rough-cut-registration.json`，并在 `delivery-result.json` 中返回带哈希的 `rough_cut_delivery` 引用。旧手动导出仍可用实际文件走 `video-review post-cut`，它会生成迁移登记。

1. 运行 `video-review post-cut --registration <登记> --candidate <实际粗剪> --timeline <当前时间表> --script <定稿> --identity <项目身份> --output-dir <新目录>`。旧手动导出可省略 `--registration`。可以通过 `--omit` 记录作者确认删句，用 `--vkp-run` 复用同一实际文件的完整本地转写。程序核对脚本、时长、轨道、黑帧、静音和冻结候选。重复／错读有清晰静音边界，且后一次完整贴合定稿，才会删前留后、输出新剪辑和时间映射，并再次调用本地 VKP。
2. 没有疑点时保存机器复核回执。有疑点时，先由 Agent 根据原声、时间和上下文填写 `rough-cut-triage-template.json` 的每一项。用 `verified_keep` 保留已核实的内容，`needs_rework` 要求先修复并换候选，只有 `needs_author_decision` 进入作者审核页。每项填写具体依据。运行 `video-review post-cut-triage --audit <检查> --triage <已处理判断> --output-dir <新目录> --serve --open`。不要把原始差异列表当成作者审核页。
3. 作者在标准 VKP 页面保存后，用 `video-review post-cut-accept --audit <检查> --pack <页面审核包> --decisions <保存决定> --output <新回执>`。在精剪请求中把 `rough_cut_candidate` 设为实际当前视频引用，工作请求的 `current` 绑定 `rough_cut_delivery` 和 `rough_cut_acceptance`。直接调用 `video-review prepare --purpose fine_cut_recipe` 也必须传入 `--rough-cut-delivery` 和 `--rough-cut-acceptance`。
4. 用 `video-delivery rough-cut-bind --input <交付清单> --rough-cut-delivery <登记> --rough-cut-acceptance <复核回执> --output <新交付清单>` 绑定正式交付。登记候选须与交付清单中的 `edited_media` 一致，定稿文件和时间映射也须一致。最终包装仍走原有渲染、字幕、终稿验收。更换作为包装输入的剪辑母版、修改定稿或改变源时间映射，都须复核新版本。
