# 自媒体合同统一检查命令

> 2026-07-28 | Codex（GPT-5.6）
>
> 范围：只读、离线、合成数据。不会登录、发布、读取真实账号、素材或结果。

## 稳定入口

在仓库根目录运行：

```powershell
python scripts/check_self_media_contracts.py
```

它顺序执行既有 `content-bundle.v1` 离线校验、原始经营 P0 baseline validator、上一轮 operations regression、旧版 `legacy-feedback.v0` 的内存迁移、事件去重、快照排序，以及自媒体仓和原始经营 P0 的全部 `unittest` 负例。`--no-tests` 只验证 schema、fixture 和迁移，供测试自身调用以避免递归。

## 本轮变动（五段式）

### 1. 统一入口：`check_self_media_contracts.py`

- 意图：给维护者一个固定命令，避免遗漏不同合同的手动命令。
- 决策：聚合已有 `content_diagnosis.validate_bundle` 与 `operations_contract_regression.contract_errors`，再执行原有测试发现。
- 理由：复用已经验证的离线模块，避免再实现第二个 validator 或状态机。
- 证据：上一轮的 operations 回归、P0 诊断桥及 `python-jsonschema` 审查记录。
- 生效范围：本仓本地检查；不连接 Activepieces、平台、NoteRx 或任何外部服务。

### 2. 历史 fixture：`legacy-feedback.v0`

- 意图：让旧汇总反馈的迁移有独立、版本化的合成输入。
- 决策：增加严格 `additionalProperties=false` 的 v0 schema 与 fixture，迁移只发生在内存。
- 理由：`no_signal` 不能被迁移成客户拒绝、咨询或其他业务结论。
- 证据：既有 `content-item.feedback` 保留旧汇总字段，并将内容与业务信号分层。
- 生效范围：仅 fixture 和测试；不迁移或改写任何历史文件。

### 3. 生命周期附加断言：事件去重与快照排序

- 意图：捕获单对象 schema 无法判断的集合级错误。
- 决策：禁止重复 `event_id`，要求快照按 `as_of` 升序；沿用上一轮 48–72h、156–180h 窗口。
- 理由：时序乱序和重复事件会误导复盘，却不应通过修改或覆盖历史数据修复。
- 证据：现有 publication-event 追加式模型和 performance-snapshot 时点模型。
- 生效范围：只作用于合成回归包；生产历史继续保持追加记录与人工裁决。

### 4. 负例测试

- 意图：把未知字段、重复事件、乱序快照、边界时点与跨域结论变成持续回归项。
- 决策：新增独立测试文件，并让统一命令默认运行所有 `test_*.py`。
- 理由：成功 fixture 不能证明边界保护仍存在。
- 证据：JSON Schema 的 `additionalProperties=false`、上一轮六层信号隔离规则。
- 生效范围：离线单元测试；无发布、无真实受众或客户推断。

## 回滚

删除本轮新增的统一检查脚本、legacy v0 schema/fixture、测试和本说明即可。上一轮 operations 回归及所有生产合同均未被修改；不要使用 `reset`、`stash` 或 `checkout` 覆盖并发改动。
