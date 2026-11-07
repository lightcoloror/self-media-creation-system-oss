# AI 跨视频项目复用入口

## 2026-10-29 | Codex：分平台操作与主封面／PK

发布页支持各平台独立折叠、全部展开／收起；视频、封面和发布文案均位于平台内。小红书按1张主封面＋最多3张PK候选分别校验。数据字段、复用入口、变动依据和可重复测试见 [分平台发布页说明](publication-platform-panels-20261029.md)。

2026-09-26（Asia/Shanghai）｜Codex｜现有自媒体仓库内实现

## 何时调用

2026-09-27｜Codex 补强：视频项目的完整交付入口是 `python scripts/self_media_agent.py video-delivery`，见 [视频交付防返工](video-delivery.md)。普通 `render` 保留缺项草稿编辑能力，但明确标注 `draft_preview`，不能据此报告完整交付。完整状态要求当前 manifest 的全链重检；页面修改或保存新版本使旧完整标记失效。

用户要求“发布辅助页”“本地发布页”“可复制素材路径、标题、简介和标签的网页”时，使用 本仓库的 **publication-desk** 功能。不是 `prefill` 合成表单，也不是打开平台投稿器。

目标是 **AI 换项目数据、工具生成同一套页面**。不要复制旧项目 HTML 后改字符串，不要为每个视频重新设计界面；复用 `publication_desk.py` 与 `templates/publication-desk/manual-desk.*`。旧项目的文案、账号、审核结论、规则和发布记录不继承到新项目。

## 固定步骤

### 平台差异强制门（2026-10-25，Codex / GPT-6）

2026-10-25补正：辅助页首先交付已适配的可复制内容，不把适配任务转成用户待办。`check --stage preparation`检查已记录基线的字数、短标题符号、封面槽位、真实尺寸及文件哈希；`check`默认submission仍检查上传界面的实际核验。本地准备通过不等于当前账号已核验或正式完整交付。未指定合集、定时、PK时按本项目实际方案明确不使用并记录原因，不替用户创建或提交。历史基线写在共享配置，平台变化须更新来源，不能当成永久官方规格。抖音/快手提供描述与话题整段复制，小红书/视频号提供正文与话题整段复制，B站维持标题、简介、标签分别复制；整段内容由字段实时组合，保存和导入后不保留过期副本。

规则真源为 `config/publication-platforms.v1.json`，由生成器与共享页面共同消费。质子系列曾确认的槽位、定时、合集和标签操作，以及本说明中的划船歌验收要求，不能只留在单个发布包或聊天中。新增平台要求须更新该配置及负例测试。

- `init` 自动生成各平台核验项；短标题仅视频号有。Python 和页面 JSON 导入均拒绝其他平台的 `short_title`，不得靠隐藏错误字段通过检查。
- `check` 同时检查字段完整性、实际图片尺寸、封面槽位、逐项核验状态及依据。抖音、B站按多个独立槽位检查；快手为二选一。比例容差为0.1%，不能用文件名或自填宽高替代读取图片。无核准配置的平台阻断完整交付。
- 各平台 `platform_checks` 项必须有 `status/evidence/checked_at`。默认 pending，AI不能自动勾选已核验；不适用仅用于配置允许的可选事项，且必须说明原因。`current_specs` 必须是当日账号界面核验，历史规则不自动升格。
- 旧规则的数字限制与操作说明始终展示为待复核参考，当前未确认不硬猜。规则变化时更新有来源的共享配置，而非在项目里悄悄略过。
- `video-delivery` 的 `render_and_desk` 阶段强制调用同一平台检查。普通 `render` 可保存待办草稿，必须显示未完成数量；不能把生成HTML当作完成发布准备。CLI失败给出具体平台和缺项。
- 页面可记录核验依据、日期和不适用原因，随HTML/JSON保存。用户改过的旧文件不覆盖；从最新项目数据生成新修订。旧页不会自动升级，需要重新生成。

验证入口：`python -B -m unittest discover -s tests -p "test_publication*.py" -v`；视频交付门回归另见 `test_video_delivery.py`。这些验证只证明本地拦截有效，不证明已核验真实账号或已发布。

1. 在仓库根目录运行 `python scripts/self_media_agent.py publication-desk`；读取本说明。全局工具入口为 `content-creation-system`。
2. 读取当前项目已确认的成片、封面、平台与文案。素材版本不明确时先定位，不猜路径。页面可以准备候选，但不能声称人已审核或已发布。
3. 无发布包时用 **init** 生成新 JSON；已有项目先读取最近保存的数据，再用 **upgrade** 迁移。默认抖音、小红书、视频号、快手、B站五平台，也可显式选择；`target_platforms` 保存本次集合，漏平台会阻断检查。迁移不删除已有平台、不覆盖人工正文与发布记录；不适用的旧字段保存在 `retired_fields`，不再进入复制框。
4. AI 填写 JSON，然后依次 **check --stage preparation → render**。失败保留报告并修正；缺项只能交付为待补齐草稿。实际投稿界面的检查另用 `check --stage submission`，不把本地准备交付变成需要先上传的循环依赖。文件已存在时使用新的明确修订文件名，不覆盖人工改过的 HTML/JSON。
5. 从项目路径打开生成 HTML，核对平台数、素材和文字，验证复制路径、预览与保存；交付 HTML 和同源 JSON。保存后重新打开的内容应一致。不得只交付 JSON 让用户自己制作页面。

```powershell
# PROJECT_DIR / 项目名仅为占位符；换成当前任务获准的真实项目路径和名称。
python -B scripts/publication_desk.py init --project-id unique-project-id --title "项目名" --output "PROJECT_DIR/发布辅助数据.json"
# 上一步之后，由 AI 将下列字段填入该项目 JSON。
python -B scripts/publication_desk.py check --stage preparation --input "PROJECT_DIR/发布辅助数据.json" --output "PROJECT_DIR/素材核验.json"
python -B scripts/publication_desk.py render --input "PROJECT_DIR/发布辅助数据.json" --output "PROJECT_DIR/发布辅助页.html"
```

仅需两个平台时，init 加 `--platforms douyin bilibili`。支持键：`douyin`、`xiaohongshu`、`weixin_channels`、`kuaishou`、`bilibili`、`weibo`。这是本地文案卡，不等于平台 API 支持。

## AI 填写契约

根对象 `schema_version=local-publication-desk.v2`；`project_id` 为稳定且不同项目不重复的 ID，`title` 为项目名，`revision` 为修订号。

每条 `items[]`：

- `id/title`：条目唯一 ID 与名称。系列视频复制空结构并使用不同 ID，不复制别人的发布记录。
- `video.path`：当前成片绝对路径；`video.sha256`：有据可核的 SHA256，不知道时留空。不能猜哈希。
- `covers[]`：每个封面 `{id, label, path, sha256}`，路径与哈希约束同上。无封面时空数组，不填旧项目图。
- `platforms.<平台>.fields`：所有平台有 `body/tags`；普通 `title` 按配置适用，快手、视频号不得保留普通标题。`short_title` 仅视频号使用，完整交付时不得为空；其余平台禁止此字段。可选 `collection_name/collection_description/pinned_comment`。文案取自当前项目或明确标为 AI 草稿。
- `platforms.<平台>.cover_ids`：引用本条 covers 中真实存在的 ID。
- `platforms.<平台>.record`：init 已提供空记录，`status=prepared`；除非有用户提供的事实，不填账号、计划/定时/实际发布时间、发布 URL。不要把审核通过当成已发布。
- `rules[]`：没有最新证据就保持空。记录规则时带 `platform/source/checked_at/scope/status`；历史规则不提升为当前平台限制。

## 各项目共同验收

### 完整发布台基线（2026-09-26 补齐）

合集是固定模块，不是有数据才出现的可选功能：总览始终可见，每个平台始终提供合集名称/简介编辑与复制字段。无合集时留空、正常单条发布，不自动起名、不把空白当作漏项，不要求先点击添加按钮。旧数据缺字段时页面也必须显示空编辑框。划船歌项目明确无合集，不继承任何候选合集名称。

封面不是一张原帧加占位状态即可完成：用户要求候选/PK时，实际制作差异明确的候选及目标比例 PNG，再填 `items[].cover_pk`（recommended、selected、candidates、platform_ratios）。candidates 中 cover_by_ratio 引用 covers 的 ID；页面比较理由、四比例切换和人工选组均使用共享模板。编辑推荐不等于人工选定或线上 A/B 测试。选择后同步各平台路径，保存 HTML/JSON 保留选择，不自动修改标题或发布状态。

封面生产必须回到 `docs/视频封面多策略多比例正式路由-2026-08-25.md`：video-title-cover 动态候选、视觉 Skill 构图配方、安全媒体布局、既有 Remotion Still、多比例独立重排及人工 QA。发布台只消费封面成品及候选数据，不另建封面渲染器。2026-09-26 本次临时 publication_cover_export.cjs 与其分栏拼接成品未遵循完整正式路线，用户已否决该视觉方案；只留历史证据，不作为可复用生产入口。质子系列的历史 HTML 导出例外不能推广为新项目默认。真实素材计划与输出放项目私有目录，不放源码仓库。

每次生成必须展示内容边界、合集准备、可读排期表、观察窗口、各平台上传指导、封面缩略图与适配状态、字数统计及可选字段准备状态。缺数据时显示待准备 / 待核验 / 不适用，不能静默隐藏模块。字符统计为 Unicode 码点数，不冒充平台实际计数；没有当前证据时不硬设平台上限。

AI 需按项目填写根对象 `editorial_context`（事实与禁止扩写）、`collection`（候选名称、简介、功能状态、封面状态、不可用时的处理）、`publishing_schedule`（策略、依据、观察窗口）；平台对象可填 `preparation`（封面、合集、定时的已知状态）。这些说明独立于可复制发布文案，保存 HTML / JSON 时保留。旧系列包的同类结构从 source_snapshot 可读展示，但历史数据不能继承给新项目。

短标题、置顶评论及合集文案按需预填候选，不把候选写成已审核、合集已创建或平台已经发布。只有一张原帧时必须标注比例版本待准备，不声称已提供多比例封面。观察计划区分：24 小时为上线质量、声音字幕、告警和 provisional 观察；正式 early 为发布后 48—72 小时，d7 为 156—180 小时。复用已有记录，24 小时不写作正式 early，也不要求三次完整复盘；这不是最佳发布时间结论。更新：2026-10-09 18:50:58 +08:00，Codex（GPT-6）。

- 同一工具模板；保留素材路径、文案复制、完整视频控制、封面、保存 HTML、JSON 导入导出、素材搬家、独立发布状态。
- 所选平台逐个有卡片；没有继承另一项目的标题、路径、私密记录和发布结论。
- `check` 无 missing/hash_mismatch。`exists_hash_not_supplied` 仅证明存在，不冒充哈希已核验。
- 保存并重开可继续修改；路径有空格/中文时可带双引号复制；复制权限失败时保留手动复制。
- 页面本身不访问网络、不登录、不上传、不发布。它辅助人工填写平台，不代替人工确认与实际投稿。

模板升级时修改工具源文件并运行回归，不批量覆盖旧项目页面；需要新版的项目读取其最新已保存 JSON 重新生成。

## 2026-10-25 20:52:50 | Codex：要求实际进入页面的补强

- `upgrade --input 旧数据.json --output 新数据.json` 保留既有文案、素材及发布历史，补全显式平台集合、规则版本和方案比较范围。迁移后必须检查并重新生成当前页，不能只改配置。旧文件保留。
- `cover_pk.requested` 默认 true；不足两个候选不能用多个比例冒充多方案。每个候选需要标题、比较理由、各目标比例的真实图像及哈希；重复图像、缺比例、损坏图片均阻断正式交付。只迁移已选定稿而无需重新比较时，明确设 false 并写 `not_requested_reason` 及既有决定依据，不能为了过门随意关闭。
- 只用文件哈希可发现相同图像，无法可靠识别“同一构图略换颜色”；后者继续复用既有 `cover_strategy` 的逐图、逐对视觉审核。
- `editorial_context.forbidden_public_phrases` 可列本项目明确不应提前公开的文字；平台文案和候选标题共用检查。这是字面拦截，不证明图片内文字或语义完全不剧透，仍需对应视觉/内容审核。
- 图片只有实际解码且与记录哈希一致才内嵌。改路径后同一图的全部预览同步刷新；准备状态根据页面实际加载尺寸重新计算。离线页不能重新可信哈希外部文件，重新交付仍跑 CLI。
- `platform_checks.*.input_snapshot` 绑定共享配置 `check_dependencies` 中的相关输入。正文变化不让无关排期确认失效；相关输入变化会保留旧依据并回到待核验。旧记录无绑定时也不能当作当前核验。迁移不会伪造当日账号确认。
- `desk-build` 记录项目数据、模板哈希和规则版本；它是生成记录，编辑保存后旧交付标记失效，不能当成新版本验收。
- 实测使用 `tests/workflow-application-browser.cjs`：图片解码、正确字段、编辑后复制、换图比例拦截、保存重开和手机宽度。测试证据只说明对应页面可用，不证明已投稿或视觉审美获得用户认可。

## 能力边界

入口、空结构、生成器、验证和操作步骤已固化到本地工具。新的 AI 依照本地工具发现规则即可复用，不依赖本次对话记忆。但本工具没有自动监听所有视频项目，也没有自动插入每一条视频流水线：调用仍由当前 AI 根据用户任务触发。

文案质量、真实平台规则、当前素材版本仍需按项目判断；模板复用保障相同功能与布局，不能承诺每条内容无需审核。


## 日常使用与兼容

页面是单个离线 HTML，无需服务器。复制带双引号的路径，在平台文件选择框的“文件名”栏粘贴。修改文案/记录后点击“保存当前页面”，下载含全部修改的新 HTML；或导出 JSON，之后载入继续。关闭前必须保存，不依赖浏览器缓存。搬家功能仅替换完整根目录边界，随后运行 check。预览需要浏览器允许访问本地文件，不要把私人页面部署到公网。

convert/render 接受本工具 v2、旧单条 local-publication-page-draft.v1、旧系列 items[] 发布包。**尚未适配 self-media-platform-publication-package.v2**；不要把其中 other 平台猜成微博，也不要把相对路径无依据变成绝对路径。AI 应从该包核对当前素材与字段，显式填入 init 生成的数据，不声称自动贯通。

operations-handoff 仅导出人工观察，始终 executable=false、publication_events_written=false。实际上线后，按既有 self_media_agent.py operations 指引核对账号、内容与哈希对象，再使用已有运营记录工具；本页不自行写库，不创造第六条工作流。

实现从已验收的单条/系列发布辅助页提炼。共享源码与模板在此仓库版本管理；真实项目数据、媒体和本机测试截图不随工具提交。旧本地工具入口可转发到本仓库，避免维护两套页面实现。

## 整合验证

2026-09-26｜Codex：9 项 desk/整合测试、24 项既有 self_media_agent 测试通过；单条六平台和八条系列四十张平台卡的独立浏览器验证通过。验证包括连续“保存→继续修改→再次保存”、JSON 往返、重新打开、路径迁移边界和无外部请求。隔离检出的既有 synthetic-final-cut.bin 曾被 Git 转为 CRLF，按已登记哈希恢复其原有 LF 后完成入口回归；没有修改该 fixture 的提交内容。

```powershell
python -B -m unittest discover -s tests -p "test_publication_desk*.py" -v
python -B -m unittest discover -s tests -p "test_self_media_agent.py" -v
# 浏览器测试可选，需要本公开版未分发或验证安装的 Playwright；只操作本地页面。
node tests/publication-desk-browser.cjs PLAYWRIGHT_MODULE_PATH SINGLE_ITEM_HTML SCREENSHOT_PATH OPTIONAL_EIGHT_ITEM_HTML
```

工具运行不依赖 Playwright，浏览器自动化仅用于测试。上述结果不证明真实账号预填、上传或发布。
