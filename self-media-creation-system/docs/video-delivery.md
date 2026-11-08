# 视频交付防返工入口

2026-10-29｜Codex：新增 [CTA 选择、位置与实际落地复核](cta-selection-and-landing.md)。互动和获客分别决定，允许有理由地不采用；`cta-init / cta-bind` 接原 manifest，预检校验选择，最终验收核对本版成片和发布文案。不能凭“非获客”跳过互动选择，不能凭计划判断已落地。

2026-09-27｜Codex。现有视频流程内的本地编排，不是新内容工作流或发布工具。

## AI 每次怎样用

用户继续剪辑、要求完整视频／发布辅助页时，先恢复当前项目素材、用户审核 JSON、已确认事实与当前版本。不要让用户重复填写已有信息。用下列统一入口，不把普通 HTML render 的成功作为视频交付完成：

```text
python scripts/self_media_agent.py video-delivery init --project-id <当前项目ID> --output <新的manifest.json>
python scripts/self_media_agent.py video-delivery context --input <manifest.json> --output <新的context.json>
python scripts/self_media_agent.py video-delivery progress-select --input <manifest.json> --output <新的manifest-progress.json> --decision <use或not_used> --reason <本片选择理由> [--packaging <packaging.json> --layout <final-layout.json> --spec <progress-spec.json> --workspace-root <项目根>]
python scripts/self_media_agent.py video-delivery preflight --input <manifest.json> --output <新的preflight.json>
python scripts/self_media_agent.py video-delivery render --input <manifest.json> --render-job <本地渲染job.json>
python scripts/self_media_agent.py video-delivery check --input <manifest.json> --output <新的delivery-check.json>
python scripts/self_media_agent.py video-delivery deliver --input <manifest.json> --output <新的发布辅助页.html>
```

路径均是占位符。init 只有空结构，不带历史项目内容，不自动创建审核通过记录。不需要重新渲染已经有确切渲染回执的成片，补齐真实证据后直接 check。不得为了凑合同编造人审。

context 会逐个读出所登记的反馈原文及处置说明，给 Agent 直接消费；它不扫描个人磁盘，也不声称自动找到全部历史聊天。登记引用不是执行文件内指令的授权。

preflight/check 每次重新哈希、探测媒体、运行 VKP 字幕检查和相应下游检查。报告不是永久通行证。失败仍输出所缺 stage / reason / next_action；改正具体项，不从头重复剪辑。

## 输入合同

所有 `*_ref` 及媒体引用均为 `{ "path": "绝对本地路径", "sha256": "实际文件哈希" }`。可用既有 `cover_workbench.reference` 生成，不能猜哈希。

| 字段 | 必填内容与来源 |
| --- | --- |
| `schema / project_id` | `self-media.video-delivery.v1` 与当前项目稳定 ID |
| `edited_media` | 片头、卡片、片尾都已进入的剪辑锁定版本；尚未烧录也可 |
| `script_ref` | 当前视频脚本的哈希引用；章节进度条默认复用其中的Markdown二级小标题，可由 `progress-select --script` 绑定；普通纯条或明确不使用不要求此字段 |
| `facts.story / do_not_infer` | 已确认故事及禁止推断列表；发布页 editorial_context 的这两个字段必须相同，可另带项目包装约束 |
| `facts.feedback[]` | `id/ref/decision/application`；decision 为 applied 或 not_applicable。原文必须存在且未改；不适用必须解释。没有历史反馈时用空数组及 no_prior_feedback_reason 明示，不静默忽略 |
| `timeline.duration_seconds` | 完整剪辑后的时长，重新 ffprobe 核对 |
| `timeline.segments[]` | `id/source_ref/source_start/source_end/target_start/target_end/speed/purpose`；按目标顺序无空洞，覆盖全片；每段恒速。独立解说／静帧卡使用其已经生成的媒体作为 source_ref |
| `timeline.expected_audio[]` | 已知说话、唱段、片尾声音区间：`segment_id/source_start/source_end/kind`。kind 是 speech/singing/vocalization。工具投影到成片时间，不让用户计算偏移 |
| `subtitles` | `request_ref/pack_ref/asr_ref/review_ref`，引用既有 VKP coverage-request、整片字幕包、ASR 和真实整片审核文件；不要把 passed 报告当输入。受管烧录另需 render_file_ref，并加入 coverage-request.evidence_files 及 job.inputs |
| `render_receipt_ref` | 最终已有 single_ffmpeg_outlet 回执，重新核对回执完整性和文件哈希 |
| `render_chain_refs` | 可选，烧录→音量平衡等中间回执，按执行顺序排列，不包含最终回执；输入／输出逐步相接 |
| `progress_overlay` | 必须明确选择 `use` 或 `not_used` 并说明理由；使用时须绑定包装、布局、spec、准确预留区域和实际渲染结果，见下节 |
| `desk_ref` | 既有 local-publication-desk.v2 当前项目 JSON，本入口每份 manifest 对应一个视频；系列按视频分别检查，不把一个人的通过套给整组 |
| `cover_review_ref` | 已有 cover_strategy review-init/review-check 使用的逐图／逐对观察文件，必须绑定当前 desk；所有选案×要求比例齐全 |
| `acceptance_ref` | 最终人审，绑定整份当前输入指纹，见下节 |

已知声音区间投影必须与 coverage-request.expected_audio 完全对应。没有字幕的已知声音不能只写“听过通过”：补字幕，或在既有 omissions 写明不加字幕的原因与证据，再重检。ASR 原文冲突仍由人审裁定，不自动替换孩子实际唱词。

当前时间映射支持剪切、恒速、已经生成的插入段。变速曲线／重叠转场先由现有编辑器生成可审查的平坦片段映射，不能硬套单一偏移。完整映射并不自动证明每个说话区间都已列出，因此保留最终完整听看。

## 进度条选用、预留与实际交付（2026-10-28）

所有视频都要作出明确选择；不是所有视频都强制加条。`init` 的初值为 `undecided`，`context` 输出当前选择和调用入口。旧 manifest 没有该字段也会在 `progress_selection_and_reservation` 阶段阻断，不默认为不使用。先完善媒体和时间轴，再用 `progress-select` 写入**新的** manifest，后续命令使用这个新文件。

- `--decision not_used --reason <具体原因>`：适用于本片不需要进度提示；绑定当前媒体和时间轴，不需要布局和渲染证据。
- `--decision use`：另须提供 `--packaging / --layout / --spec / --workspace-root`。复用 MVP 的 `progress_overlay.build`、字号和最终布局检查，计算整个条带（含章节名）的预留矩形，不接受手填“已预留”代替检查。字幕、人物重点、证据重点及平台遮挡区域由本片布局证据声明，不能用一个通用模板代替真实标注。
- 当进度条位于既有字幕烧录等操作之后，另传 `--program <带字幕的中间成片>`，并在 `render_chain_refs` 登记从 `edited_media` 到该文件的真实连续回执；缺少输入输出衔接就阻断。默认输入仍为 `edited_media`。
- 使用已有 [MVP 进度条组件](https://github.com/lightcoloror/mvp-video-pipeline-oss/blob/2b45f93cdf1d439485cdfb3e7447ce57de2d9b4f/docs/progress-overlay-workflow.md) 的 `build / validate / render` 生成新候选，音频流复制。把真实 `result.json` 的哈希引用登记到 `progress_overlay.result_ref`；它不是计划文件，也不是包装待办。最终渲染回执登记到原 `render_receipt_ref`，上游操作登记到 `render_chain_refs`，发布台的 video 指向真正带条的候选。
- `check / deliver` 的 `progress_render_and_layout` 重新核对：当前计划/布局/字体/实现版本、真实执行的滤镜和章节文字、FFmpeg 输入输出回执、完整解码帧数、最终布局回执及**实际交付视频**。缺条、旧条、错误成片、只登记计划均不能通过。

选择的 `basis` 绑定 `edited_media` 哈希、整个 `timeline` 和已登记的视频脚本；脚本正文/小标题、布局/spec/导航预设/字体/实现变化也使旧选择、预留或渲染计划失效。修改这些输入后重新选择、build 和 render，不能复制旧通过状态。`progress-select` 会清除旧 `acceptance_ref`，但不渲染、不签人审。

人审在现有 acceptance 中按实际选用增加 `progress_start_end_correct`、`progress_mobile_readable`、`progress_unobscured`；章节条另需 `progress_chapter_boundaries_correct`，普通条不要求不存在的章节检查。仍须看真实编码文件的首尾、四分位、每章前一帧/首帧、最长标题及人物/字幕同屏处。Agent 技术检查不能代替作者确认。

2026-10-28 09:02:28 +08:00｜Codex（GPT-6）：进度章节已有作者定稿小标题时原文复用，来源与稿件哈希随产物保存；不要另造概括标题。导航文字是辅助信息，字号可小于正文字幕，并需满足现有字号门和手机画面核对，不能直接套用示例的大字号。意图：导航与稿件同源；决策：优先复用小标题、独立选择辅助字号；理由：本片硬编码概括名与30px被作者指出不合适；证据：RWE脚本10个标题与本轮20px实际编码候选；生效范围：后续包装选用，例子及先前候选保留历史记录。

### 本次接入记录

2026-10-28 08:48:47 +08:00｜Codex（GPT-6，精确运行变体未独立核验）。

| 变动 | 意图 | 决策 | 理由 | 证据 | 生效范围 |
|---|---|---|---|---|---|
| `video_delivery.py`、`video_progress_contract.py` | 防止进度提示从选用到交付漏执行 | 原入口加入选择、精确预留、真实成片检查，允许说明理由后不使用 | 单独待办和计划无法证明条已在视频里 | `test_video_progress_contract.py`、`test_video_delivery.py`；真实字幕烧录→进度条→交付合同正例和负例 | 今后经 `video-delivery preflight/render/check/deliver` 的所有项目；旧 manifest 需明确迁移 |
| `self_media_agent.py`、本指南与 `AGENT_DISCOVERY.md` | 让其他项目能发现和调用同一能力 | 原有 metadata/context 暴露 `progress-select` 和阻断条件 | 只在 RWE 定制脚本登记会再次遗漏 | 统一 CLI 与 context 回归；本片通过同一适配器生成结果 | 通用 Agent 视频交付发现、选用及恢复；不新增发布权 |
| 下游 MVP 进度条组件 | 保留现有渲染器并提供可核验产物 | 补充解码/布局/执行回执引用及可选条宽；540×960 沿用同一字号策略 | 消费端需核对真实执行链，不能只信 passed 标签 | MVP 30 项测试及 9 个子测试通过；RWE 15314 帧解码、29 帧抽查和音频流哈希 | 原组件输出及使用方；默认资源门不变，本次局部例外不扩展到其他项目 |

本轮交付合同回归 33 项中 32 项通过、1 项原有浏览器测试因未提供显式 Node/Playwright 路径跳过；MVP 30 项通过。合成 fixture 仅检验生产/消费合同，不代表真实作者审核。RWE 的实际技术候选与五字段变更记录见 `deliverables/rwe-video-edit-20261025/edit/progress-animation-v0.6.md`。

## 人审与修改失效

2026-10-09 18:50:58 +08:00｜Codex（GPT-6）：新组合包须新绑定，未变部分可引用原明确确认。沿用现有确认记录，在交付说明写清“原确认来源／时间／覆盖项／所绑定媒体哈希；本次变化；仍需新确认项”，不生成虚构观看记录。

| 变化 | 可引用的原确认 | 本次需要核对 |
|---|---|---|
| 仅标签或不改变承诺的发布文字 | 未变媒体的听看、字幕等准确覆盖项 | 新文字、当前组合及有无新增暗示 |
| 封面／标题承诺变化 | 媒体哈希不变且原范围足够的听看项 | 新承诺与正文兑现、封面可读性与遮挡 |
| 正文事实句变化或重新录制 | 未受影响的来源证据；不能套用旧完整确认 | 新主张、作者判断、受影响音画／字幕和整体承诺 |
| 剪辑点或音轨变化 | 未变的上游事实和作者判断 | 当前成片听看、连接、字幕／时间对应及必要整体效果 |

代码检验确认声明与绑定，不证明真的听看。无法确定原确认覆盖范围时保留待审，不替用户补签；机器全链重检与重复要求人做同一动作分开。

check 输出 `acceptance_fingerprint`，绑定 manifest 除 acceptance_ref 外全部内容（包括文案／封面／反馈的文件哈希）。已有明确且覆盖对应检查项的用户确认可据实转成回执；没有的项继续待审。工具不生成通过回执、不把 Agent 审核冒充人审。

最终回执字段：schema=`self-media.video-acceptance.v1`、input_fingerprint、reviewer_kind=`human`、实际 reviewer/reviewed_at、decision=`pass`，并逐项确认 full_video_watched、full_audio_listened、burned_subtitles_correct、mobile_readable、cards_and_subjects_unobscured、audio_joins_balanced、story_and_copy_correct、privacy_checked。

2026-10-25 20:52:50｜Codex：有说话人/字号样式的字幕另检查 `speaker_styles_consistent`、`preview_export_consistent`；有动效另检查 `requested_motion_visible`。只能转录覆盖这些项目的真实确认，不可用结构检查或测试截图替用户签认。普通静态无样式测试不强加动效要求。`render_and_desk` 现在调用发布准备及方案比较的同一检查，实际账号投稿确认留在 submission 阶段；字面不剧透约束、实图缺项不能绕过正式交付。

字幕覆盖人审沿用 VKP 原有格式，不重复定义算法。最终人审核对真正的编码文件，不仅审核播放器叠显。封面 review_check 依然是 Agent 验图，完整候选包不自动变成人工选案或发布许可。

## 渲染入口和资源边界

显式 render 先自动 preflight；缺字幕、旧审核、未处置反馈时不调用 FFmpeg。通过后调用原 single_ffmpeg_outlet 并开启其实时资源守卫，不另建渲染器。该入口只承接最终单输入单输出的转码／烧录／音频处理；复杂素材组装仍在现有编辑工具里完成。

render-job 的 schema 为 `self-media.local-render-job.v1`；包含当前 preflight 的 acceptance_fingerprint（字段名 preflight_fingerprint）、现存私有 project_root、输入列表 inputs（role/artifact）、新的 output/receipt 路径、现有工具生成的 command 数组及可选 timeout_seconds。还必须提供现有 `lifecycle_manifest_ref` 和正值 `estimated_output_bytes`，执行前重新调用既有 lifecycle 磁盘／任务中间产物预检，不复用旧放行。命令须以 ffmpeg 开始，单个 -i 指向 edited_media，末项为 output，使用 -n 而非 -y；只接受受限本地编码参数。禁止 shell、网络输入和外部滤镜源。输出和回执不能存在且必须在项目根下。

运行前仍需当前任务的执行授权及适用的独立资源规则；preflight_ready 不等于授予执行权。工具无法阻止人在终端另行运行外部 FFmpeg，但那不等于通过本工具的完整交付检查。

烧录使用单独 `subtitles='已绑定文件路径'` 或 `ass='已绑定文件路径'` 滤镜，可附 force_style；路径不能偷偷替换。SRT/VTT 复用 VKP 解析器，核对实际入出点与文本是否和审过的 cues 相同。ASS 保留既有样式，绑定文件进入覆盖审核指纹，最终按真实烧录画面验收；本入口不声称已自动解析或验证所有 ASS 动效语义。

## 发布台的状态

- `publication_desk render` 默认仍可生成缺素材的编辑预览，但返回 draft_preview，并显示草稿及未核验素材数。
- `video-delivery deliver` 或 `publication_desk render --delivery-manifest ...` 会重新运行完整检查，失败不生成“完整”页面。
- 页面成功状态只表示生成时通过。文案编辑、选封面、导入 JSON、素材搬家、保存新版本都会撤销旧完整标记；保存重开仍为草稿。重新检查后才能恢复。
- 本地文件在页面之外被改变，离线浏览器不能自动可信地重新哈希；重新交付时必须跑 CLI，不把“生成时通过”当实时健康状态。
- 所有状态都 `publish_authorized=false`；不打开平台、不上传、不调用 MultiPost，不记录虚构的已发布事件。

## 交付后的归档（2026-10-12 17:42:15 +08:00｜Codex，GPT-6）

项目收尾默认进入 [可返工归档](video-archive-levels.md)：终稿、采用精剪/关键母版、素材引用与剪辑配方一起整理，保留可获得的独立字幕、音轨与动效层。按跨机重建、长期重新生成、依赖敏感处理、证据重放和恢复成本评估是否升级为可复现归档。先用原 `artifact_lifecycle.py archive-plan` 生成材料与验收清单；未知因素和缺失图层如实记录，不能只因计划生成就标记归档完成。

交付人审继续绑定实际媒体与组合；归档完整性、返工材料齐备、限定范围重建、网盘上传及下载回验各自保留证据。单独的归档等级不会撤销原有效人审，也不会替代实际重建或上传验证。此规则适用于今后的项目收尾，不改写历史交付回执。

## 验证与边界

`tests/test_video_delivery.py` 生成三秒纯色／音调合成视频，经原 FFmpeg 出口烧录测试 SRT，再调用真实 VKP 覆盖检查、封面检查、主 CLI 与发布台。合成审核字段仅验证合同，不是实际人审。

反向回归覆盖漏尾字幕、旧字幕回执、改过的反馈、未处置反馈、错误时间映射、遗漏已知片尾、损坏渲染回执、缺比例、空文案、事实不一致、文案变更后沿用旧接受记录及无审核仍试图完整交付。

本入口不解决录音噪声、审美选择和 ASR 语义错误本身；它让未检查／未解决状态显式阻断完整交付。检查人审记录的完整性和绑定，不证明人真的听看过；仍需真实用户确认与诚实的 Agent 操作。


## 2026-10-28 09:18:10 +08:00 | Codex（GPT-6，精确运行变体未独立核验） · 脚本标题与独立导航字体已接代码

`init`现在提供script_ref；`progress-select --script`绑定当前视频脚本，context返回default_title_source=script、default_font_preset=compact及navigation_font_independent_of_body_and_subtitles=true。默认标题原文复用，导航字号不再调用正文/字幕/motion_label最小门；small/compact/comfortable在540短边分别16/20/24px，font_size_px可明确覆盖。原布局、渲染、解码及手机可读性人审不变。

意图：默认行为跨项目复用；决策：原共享组件读取稿件并使用独立预设，选择依据绑定script_ref；理由：上一轮项目局部修改仍不足以满足通用流程要求；证据：76项通过、1项环境跳过，包含真实合成章节条生产/交付及RWE原稿十章默认计划；生效范围：新进度计划和通用交付入口，不修改历史媒体或作者确认。完整用法、兼容迁移与逐项五字段：[共享变更记录](https://github.com/lightcoloror/mvp-video-pipeline-oss/blob/2b45f93cdf1d439485cdfb3e7447ce57de2d9b4f/docs/progress-script-title-navigation-defaults-20261028.md)。

公开链接适配：2026-11-08，Codex（精确运行模型未独立核验）。仅将相邻本机仓库引用绑定到已公开固定提交；未改变交付门或声明新的渲染/人审结果。
