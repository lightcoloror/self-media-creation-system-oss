# 跨项目个人素材目录

更新时间：2026-09-25 21:35:39（Asia/Shanghai）  
执行者：Codex（GPT-6 Astra）  
派发：PERSONAL-MEDIA-LIBRARY-FEEDBACK-20260925-01

## 最小实现与使用边界

复用现有 `artifact_lifecycle.py` 的项目清理流程，在旁边增加 `personal_media_library.py` 和 `personal-media-library.v1.schema.json`。使用一个原子写入、互斥锁保护的本地 JSON catalog，无数据库服务、索引服务、UI、模型或媒体处理依赖。现有 jsonschema 依赖继续复用。

库根目录必须由用户选择，预先存在，并通过 `init --confirm-root` 确认。目录内的 `.personal-media-library.json` 同时保存库位置、稳定库 ID、资产信息和引用关系；没有全局默认位置，也不扫描个人磁盘。真实目录禁止位于 Git 仓库内；合成测试需显式 `--synthetic-only`，且只能登记 synthetic-only 元数据。是否适合云同步由用户决定，本工具不检测或承诺同步安全。

首版只登记已在所选根目录内的文件，不复制、迁移或自动归档原件。此次未创建真实库、未读取/登记真实家庭素材。未来若原件在其他位置，需要另行确认库位置和是否迁移；本工具无迁移命令。

## 本地 CLI 合同

以下占位路径仅为语法，不能直接执行。所有命令都显式带 `--library-root`。

```text
python scripts/personal_media_library.py --library-root <用户选择的现存私有目录> init --confirm-root
python scripts/personal_media_library.py --library-root <目录> register --path <相对文件名> --metadata <人工确认的元数据.json> --confirm-registration
python scripts/personal_media_library.py --library-root <目录> search --tag <标签>
python scripts/personal_media_library.py --library-root <目录> show --asset-id <asset-ID>
python scripts/personal_media_library.py --library-root <目录> reference --asset-id <asset-ID> --project-root <独立项目目录> --in-seconds 0 --out-seconds 2 --confirm-use
python scripts/personal_media_library.py --library-root <目录> check
python scripts/personal_media_library.py --library-root <目录> references
```

合成元数据示例见 `fixtures/personal-media-library-v1/synthetic.metadata.json`；它不代表真人授权。登记元数据字段见 Schema 的 `$defs.asset`；ID、路径、字节数、哈希、登记时间由工具写入。调用者提供：人工确认的摘要、原声文字、语言、标签、适用主题、不适用场景、来源/拍摄者、时长及其依据、隐私权利说明。时长是人工提供或合成测试值，不冒充媒体探测结果。工具只读文件流计算 SHA-256，不解码内容。

资产 ID 是 UUID，不从文件名推导；重名路径不能重复登记。源路径丢失、哈希改变、符号链接/目录连接、库迁移或权限不明时不静默寻找替代品。新文件/新版本需另行登记，已有记录不覆盖。首版不生成派生文件；引用范围保留原资产 ID + in/out，可追溯原件。将来独立派生资产的血缘登记另作扩展，当前不宣称已具备。

## 查询、引用与人工门

`search/show` 先查完整性和权利范围，再返回候选。`candidate_only=true`、`automatic_insert=false`、`publication_authorized=false` 固定不变。标签和适用/不适用说明供用户判断，本版不自动匹配剧情或插入时间线。某条引用得到 `--confirm-use` 只代表当前项目、当前时间范围的内部候选使用；公开发布和外部服务上传依然分别需要授权。

库与项目必须互不包含。`reference` 在 catalog 写入权威引用，再在项目 `.personal-media-links.json` 保存库根、库 ID、资产 ID 和引用 ID；不保存第二份媒体。项目链接有自己的版本标识 `personal-media-project-links.v1`，不是发布状态机。库锁和项目锁防止并发覆盖。如果第二步失败，保留孤立引用供 `check/references` 报告，继续保护原件。遇到残留锁、移动目录或手改元数据，不自动修复/清理，需核对后修复；首版无删除资产、释放引用或自动迁移命令。

## 与清理工具的关系

项目 v1/v2 manifest 结构不变，不把外部资产伪装为项目相对路径产物。原 `plan-gc` 与 `apply-gc` 均增加只读防护：

- 库根及子目录不可作为项目清理工作区；即使没有引用也保护原件。
- 从外层工作区误登记的库内文件仍被保护。
- 项目引用元数据不能进入清理候选。
- 计划报告 `cross_project_original_protected`、资产 ID 和引用 ID；不把外部字节数计入可回收容量。
- 库不可访问、源文件变化或引用不匹配时整个计划/执行失败关闭；旧清理计划不能绕过后来出现的库保护。

此防护覆盖本仓库的 lifecycle 入口；不授权、不声称拦截资源管理器、第三方清理器或人为删除标记。跨项目原件永不进入本工具的 purge 候选，因此孤立引用也不会自动释放原件。源文件只读；只有 catalog 和项目引用 JSON 被修改。

## 验收和取舍

测试用字节占位文件，不是可播放视频；验证元数据、哈希、引用和清理边界，不证明真实媒体可播放、真实权利审核或业务采用。聚焦测试文件为 `tests/test_personal_media_library.py` 和原 `tests/test_artifact_lifecycle.py`，经共享 Windows 受控运行入口执行。确切结果和日志见本派发独立回执。

意图：后续项目能找到同一资产，不靠复制原片。决策：独立 catalog + 项目只读引用 + 现有清理入口保护。理由：项目产物的到期清理与私人原件长期保留职责不同，小量个人库无需额外服务。证据：需求反馈、现有源码与定向合成测试。生效范围：本地 CLI 与相关清理防护；没有真实库或发布状态变更。回滚：停用新增入口，保留已经存在的库标记/引用与保护，不可在仍有库引用时单独移除清理防护；回滚代码前先经人工核对引用。原 dirty 文件不修改、不清理。
