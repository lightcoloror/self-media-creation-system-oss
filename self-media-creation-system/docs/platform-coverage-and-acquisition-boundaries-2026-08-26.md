# 十二平台覆盖与采集边界变更说明

> 更新时间：2026-08-26 10:37:07（Asia/Shanghai）
> 执行者：Codex（GPT-5.6 Sol）
> dispatch_id：`SELF-MEDIA-PLATFORM-COVERAGE-20260826-01`

## 结果

2026-09-03 更新：Self Media 已消费 `registered-content-routing@1.2.0`；十二平台枚举与 1.1.0 相同，本次仅增加严肃内容翻译双阶段门。唯一平台枚举仍由注册路由的 `task-router.json` 提供；本仓没有建立竞争枚举。

现有运营优先级没有改变：朋友圈和小红书为 P0，视频号为 P1，公众号和 B站为 P2，抖音继续暂停。微信群/企微为 `service-only`；知乎、快手、今日头条、微博和 YouTube 为 `observe`。单一核心主题最多生成 1–2 个公域改写，发布始终为 `manual-only`。

## 采集与运行真值

- 朋友圈、微信群/企微：只接受人工提供的私域输入；不授权账号访问、自动采集或下载。
- 小红书：仅公共只读工具，仍受登录、反爬、版权与隐私边界约束；不因纳入平台组合而获得下载或发布权。
- 视频号：引用 V16 分享链接方案；合成链已经验证，真实 MediaGo 下载仍为 `pending-user-validation`。
- 抖音：只有平台适配层，自动抽样和真实媒体下载均未验证、未授权。
- B站、公众号：可使用公共页面或用户批准的只读入口；不授权后台登录或发布。
- 知乎：普通网页/direct fetch best-effort，尚无原生抽样器。
- 快手：自动抽样能力未验证。
- 今日头条、微博：普通网页 best-effort，自动抽样能力未验证。
- YouTube：允许只读搜索、元数据、字幕和转录；整段视频下载不是默认授权。

## 变更依据

- `<workspace>/docs/content-creation-system/routing/routing-contract-set.v1.json`
- `<workspace>/docs/content-creation-system/routing/全平台纳入与采集状态说明-2026-08-26.md`
- `<workspace>/video-download-orchestrator/docs/plans/2026-08-23-微信视频号自动下载与手动模式-V16.md`

## 变更记录

### 意图

让 12 个平台进入同一渠道组合、路由与校验链，同时防止“能识别平台”被误解为“获准采集、下载、登录或发布”。

### 决策

1. 将消费者绑定提升到注册路由 1.1.0，并继续校验 canonical manifest 和组件哈希。
2. Schema 只接受平台字符串，实际平台合法性由 canonical task-router 在运行时验证，避免复制第二套枚举。
3. 为每个平台增加 `acquisition_runtime`，将采集模式、运行状态、下载边界和证据引用变成机器可检验字段。
4. 新增只用于合成回归的 12 平台 fixture 与越权负例。

### 理由

平台清单、运营优先级、采集能力和执行权限是四个不同维度。拆开后既能完整纳入平台，也不会把观察位升级为运营主阵地或把只读能力升级为执行权限。

### 证据

注册路由 1.1.0 是唯一平台枚举和组件哈希来源；平台覆盖说明提供了各平台采集成熟度；V16 明确了视频号“合成已验证、真实下载待验收”的边界。

### 生效范围

仅影响 Self Media 的 canonical 路由绑定、渠道组合合同、合成 fixture、校验器和相关文档。没有修改注册路由、平台账号、真实素材、发布系统、CRM、Logseq 或 Obsidian。

### 回滚

回滚本 dispatch 修改的文件即可恢复此前消费者状态；不要修改注册路由 1.1.0。若仅撤销平台运行真值，应同步撤销 Schema、fixture、校验器和测试，避免合同与数据分叉。
