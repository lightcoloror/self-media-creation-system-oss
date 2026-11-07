# 平台采集、网页复用与恢复操作卡

更新：2026-11-02 15:40:52 +08:00｜执行者：Codex（GPT-6）

本卡补齐现有研究工作流的采集步骤，继续使用原内容 ID、路由卡、研究包、网页账本和 `research-output.v1`，不增加内容生命周期、采集器、数据库或服务。

## 入口和工具复用

先 `local-tools.ps1 discover content-creation-system`，从返回的注册 launcher 调用 `scripts/self_media_agent.py research-capture`。仓库内可用：

```text
python scripts/self_media_agent.py research-capture policy
python scripts/self_media_agent.py research-capture lookup --url <规范URL> --registry <当前tool-registry.json> --ledger <既有网页内容抓取账本.jsonl> --output <新回执.json>
python scripts/self_media_agent.py research-capture check --input <本次采集回执清单.json> --artifact-root <本次归档目录> --output <新审核.json>
```

`policy` 仅提供操作规则，不证明当前在线；`lookup` 只读原 JSONL 和归档，复用 WCF 的 URL 身份处理，检查新鲜度、正文文件及已有哈希；`check` 核查显式输入的回执与文件，不采集页面。旧回执、新正文、截图和原始失败不得互相覆盖。输出使用新文件。

`policy.receipt_validator` 显示当前是否已安装经独立验收的委派模块；模块缺失时 `check` 返回 `capture_validator_not_installed`，不得把未执行的检查标为通过。安装存在仍须以本次验收记录为准。

| 环节 | 复用入口 | 实际证明什么 |
|---|---|---|
| 普通 URL 获取 | 注册的 WCF `fetch`／`fetch-and-rebuild` | 本次响应、正文、资产与归档状态 |
| 小红书搜索／双组采样 | `wechat-tools/scripts/xhs_opencli_collect.py`／`xhs_opencli_research_collect.py` | 实际可见候选、筛选条件、详情与评论；依赖实时桥接 |
| B站发现／详情 | Agent Reach 当前 doctor 指向的 bili-cli | 搜索／元数据；简介、字幕与视频本体分别判断 |
| 动态页面 | 当前实际可用且已获授权的浏览器工具 | 指定页面同会话 URL、可见文字与截图；不能靠历史工具名推定可用 |
| 保存页面和图页复核 | WCF `platform_samples`／`completeness`，必要时已有 ebook 工具 | 正文、展示图、原图、字幕分别检查；OCR 不替代原图 |
| 研究和创作 | 已有 `capture_research_candidate`、QRP、`research-output.v1` 与 Content Studio | 候选材料进入研究和原来的稿件流程；采集不等于事实核验 |

普通网页默认 WCF。仅当 WCF 不可用或不适用并记录原因后，才考虑 Jina；登录、验证码、401/403、平台频控不能以切换工具绕过。WCF `--backend direct` 可用于明确限制本次传输路线。

## 按平台分阶段执行

沿用本次任务卡的样本预算；没有需求时不执行所有平台。每个平台按“搜索 → 入选详情 → 归档 → 验收”推进，每完成一阶段立即更新原研究包中的台账与错误记录，再开始下一平台／阶段。先小样本验证真实返回，再扩到任务预算。

连接／命令默认 30 秒止损，20 秒可用于已知不可用路线。小红书两个现成 CLI 已提供 `--command-timeout 1..30`，默认 30；调用原 OpenCLIReadRunner 的期限，不启动额外等待器。单个工具超时、空结果或没有结构化输出时留下稳定错误，不无限重试。多平台并行或小模型执行不改变这个要求。

沿用既有手动信息流的会话和脱敏导出；动作节奏复用 wechat-tools 2—3 秒有界参数。等待不能代替加载检查。JSON／Markdown 中分别记录：

- 候选数与唯一 URL／内容 ID；
- 详情元数据、简介、正文、逐字稿／字幕各自成功数；
- 展示图片、原尺寸图片、截图各自本地有效数；
- 评论问题摘要与页面可见发布时间；
- 失败、未请求、受限、不完整与合成样本；
- 来源哈希、归档路径、工具／模型和时间。

标题、搜索摘要和 B站简介都不算全文；零张已下载图不等于页面没有图；重复来源不作为新的独立证据。合成用例不计真实平台采集量。

## 网页账本前检与写回

使用既有 `research-ledgers/网页内容抓取账本.jsonl`，不另建缓存或来源库。普通动态页面最多复用 7 天；已发表固定记录用 `lookup --fixed-record`，最多 365 天，不能超过原 `fresh_until`。只有新鲜、成功且正文文件可读、已声明哈希匹配时返回 `reuse_archive`。

用户要求最新、旧正文／图片不完整、已知更正或旧抓取失败时允许刷新，使用 `--refresh` 留明原因。该 helper 不自动写账本；实际采集完成后继续按原账本规则更新同 URL 的当前记录，保存旧档案。只把真实成功页记录为成功，失败另保留，不以重新生成文件时间刷新来源新鲜度。

## 浏览器和登录恢复

| 观察到的问题 | 下一步 | 恢复证据 |
|---|---|---|
| CLI 不存在 | 重新 discover 现成本地入口；有已授权替代则记录路线 | 实际入口和版本，不自行安装 |
| doctor 正常但桥未连／命令超时 | 停止该 CLI；检查当前工具是否提供目标浏览器 | 真实搜索返回；doctor 不能代替 |
| 子任务看不到浏览器 | 由主任务复查当前可用实例；可让执行者整理已保存材料 | 当次可见性，只证明实例/会话状态，不判断模型能力 |
| 浏览器可打开但未登录 | 用户在当前明确页面自行登录 | 登录提示消失、目标页面可见；不收集密码／验证码 |
| 验证码、人机验证或访问限制 | 停止当前自动链，人工接管或保留缺口 | 记录限制；不换源冒充原平台完成 |
| 页面已打开但正文不完整 | 检查加载、正文图页、可见时间；有权限时人工导出并导入 WCF | 明确 `imported`／`saved`，不伪称 WCF 实时抓取 |
| 网络 SSL／连接失败 | 记录精确阶段，必要时一次有理由重试现有传输 | 新响应与归档；不改全局 TLS/代理/证书设置 |

原 `self_media_agent.py resume` 已登记 `capture_bridge_unavailable`、`capture_browser_unavailable`、`capture_login_required`、`capture_access_blocked`、`capture_body_incomplete`、`capture_connection_timeout`。保留错误回执，恢复后继续原内容任务的受影响步骤，不重做已完成研究。

登录持久化状态默认 `unknown`。只在同一工具入口/同一会话环境由用户完成登录后，重新打开目标站点并看到登录仍有效，才记为 `verified`，记录两个观察时间和证据。一次页面打开、使用同一账号名称或另一个浏览器曾登录，都不证明持久化；不复制、导出 Cookie、token 或账号 profile。后续再次使用仍先复查。Sol/Luna 是用户指定的分工方案，不作为硬编码的模型限制或默认改模授权。

本次用户要求通过 DeepSeek 协作时，该协作 Skill 禁止 computer-use/CUA/GUI，本卡不覆盖该限制。可以先验 CLI 和离线文件；交互式登录恢复留作明确的待人工动作，不报已恢复。

## 采集回执和验收

`check` 消费本次研究包中显式保存的 `receipts` 数组；不替换现有 WCF 归档、ManualFeedStore、对标 Schema 或 QRP 合同。每条观察包含来源规范 URL、采集前后 URL、同一 `capture_session_id`、带时区时间、真实／合成、使用范围、`captured/partial/blocked`、正文种类及产物引用。产物必须有 role、路径、SHA-256、来源和会话；宿主只读取 `--artifact-root` 内的非链接文件。

只有实文件和哈希验证通过，才计对应组件。认证参数、错误页、跨会话截图、旧哈希、缺文件、未知字段不得冒充完整证据；错误输出只含稳定代码，不回显秘密。`minimum_bodies`、`minimum_images` 按本题预算显式设置，不能为凑数降低标准。验收仍须实际阅读正文、查看图片并执行 WCF 完整性检查；函数不证明来源真实、语义完整、最大原图、专业正确或用户效果。

2026-11-02 18:19:12 +08:00｜Codex（GPT-6）：已接入独立验收后的 DeepSeek 校验函数。宿主继续限制归档根、拒绝同文件路径别名重复，并复用 WCF `completeness._local_image` 校验图片/截图哈希及实际解码。只有blocked、partial或合成输入时不得冒充真实采集通过。鉴权检查只做明确参数和有界解码，不等同完整DLP；权限与人工语义审核仍沿用原流程。

派给 DeepSeek 的校验函数只接收原创通用需求与合成数据。其回传须由 Codex 独立测试、检查边界和实际模型/推理强度后才能安装；委派完成、文件存在和模型自报均不等于通过。

## 变更依据

- 意图：把 8 月试跑的阶段落盘、超时止损和浏览器恢复经验接回正式研究入口。
- 决策：扩展 `self_media_agent.py` 原 CLI 和原错误恢复目录；复用 WCF、wechat-tools、bili-cli、研究包与网页账本。
- 理由：工具 doctor、元数据成功和正文／图页成功是不同证据，必须独立验收。
- 证据：8 月两份试跑验收；9 月 WCF platform_samples 和对标采集合同；本次回归/现场检查见 `outputs/capture-integration-20261102`。
- 生效范围：研究发现与已授权采集，不改变内容结构自由、人工中途修改、事实核验和人工发布。
- 回滚：只撤销本次入口增量及其测试／指针，保留原归档、账本和其他未提交改动。
