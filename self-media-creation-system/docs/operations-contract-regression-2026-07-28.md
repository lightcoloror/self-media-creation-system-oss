# 自媒体经营合同离线回归（合成数据）

> 状态：本地回归包；不读取真实账号、不发布、不登录平台。
>
> 2026-07-28 | Codex（GPT-5.6）

## 范围与结论

本回归包复用既有的 `content-item` 与经营 P0 合同：`account`、`topic`、`publication-event`、`performance-snapshot`。它新增的是**独立的合成夹具、回归入口和测试**，没有修改既有生产字段、没有迁移真实资料，也没有生成真实发布稿。

夹具模拟一个明确标有 `synthetic_only=true` 的账号和图文生命周期：`prepared → published`、发布后 60 小时的 `early` 快照、发布后第 7 天的 `d7` 快照，以及准入、吸引、消费、价值、负反馈、业务六层复盘。

`content_no_signal` 被限定在内容信号域；它不会产生客户负面结论。旧 `feedback.signal_status=no_signal` 的内存迁移会得到 `content_signal_status=content_no_signal` 与独立的 `business_signal_status=not-observed`，不会伪造咨询、拒绝或客户状态。

## 复用与源码审查

| 项目 | 固定来源 | 审查结论 | 本次使用范围 |
|---|---|---|---|
| `python-jsonschema/jsonschema` | <https://github.com/python-jsonschema/jsonschema> @ `81f7a761cbaca107d3d261c1288155655b98ba08` | MIT；`pyproject.toml` 只声明 Python 数据校验依赖。`jsonschema/validators.py` 有一个已弃用的远程 `$ref` 兼容分支；本回归只传入本地、无外部 `$ref` 的字典，未调用 CLI、网络或文件写入。 | `Draft202012Validator`、`FormatChecker` 校验既有及回归 schema。 |
| 既有内容经营合同 | `<workspace>\docs\content-creation-system\operations\*.schema.json` 与 `content-item.schema.json` | 已有事件序列、冻结版本、时序快照、稳定引用与六层反馈定义。 | 直接校验，不复制或改写生产合同。 |

源码最小运行验证（隔离目录、合成对象）：`valid_errors=0`，带额外真实账号字段的对象为 `invalid_errors=1`。未运行第三方服务、Docker、浏览器、认证、遥测或网络调用。

## 回归文件

- `schemas/operations-regression.v1.schema.json`：夹具边界；`additionalProperties=false`，禁止将客户结论字段混入复盘项。
- `fixtures/operations-contract-regression.v1.synthetic.json`：纯虚构账号、选题、内容、事件与快照。
- `scripts/operations_contract_regression.py`：只读校验和内存迁移。
- `tests/test_operations_contract_regression.py`：通过、时间窗口、稳定引用、跨域污染与迁移负例。

## 字段变动说明（五段式）

本次**没有变动任何既有生产 schema 字段**。下列字段组只存在于回归夹具合同，不会写回 `content-item` 或 P0 经营对象。

### 1. 夹具边界：`schema_version`、`fixture_id`、`synthetic_only`

- 意图：使测试数据可识别、可版本化且无法被误认为真实经营记录。
- 决策：固定为 `schema_version="1"`，要求不可读但稳定的 `fixture_id`，并要求 `synthetic_only=true`。
- 理由：真实内容与客户数据不能被测试脚本读取或混入。
- 证据：现有系统坚持文件化合同、人工发布和真实/合成证据分层；本任务明确要求虚构素材。
- 生效范围：仅 `operations-regression.v1` 的 fixture；不改变真实 `account_id` 或内容对象字段。

### 2. 生命周期组：`account`、`topic`、`content_item`、`publication_events`、`performance_snapshots`

- 意图：回归稳定 ID 关系、追加事件和观察窗口，而不是创建第二套经营数据模型。
- 决策：字段组承载原对象全文；脚本分别以原 schema 校验并验证引用关系。
- 理由：外围对象不能塞回 `content-item`，但回归需要能在同一合成包中观察关系完整性。
- 证据：`operations/README.md` 与 `content-item.operating_refs` 的既有设计。
- 生效范围：仅测试 bundle；生产对象仍分别保存和管理。

### 3. 复盘组：`reviews[].layer`、`signal_domain`、`signal_status`、`evidence_refs`

- 意图：把六层复盘及内容/业务信号隔离变成可执行断言。
- 决策：业务层只能是 `business` 域；`content_no_signal` 只能是 `content` 域；未知的 `customer_conclusion` 字段被 schema 拒绝。
- 理由：无内容信号不是客户拒绝，内容曝光/互动也不能直接成为业务结论。
- 证据：统一内容系统 README 对六层反馈、`content_no_signal` 和 `customer_no_response_observed` 的边界说明。
- 生效范围：仅回归评审记录；不取代未来独立的 `lead-event` 或 CRM 合同。

### 4. 迁移输入：`legacy_feedback`

- 意图：验证历史汇总字段可在不扩张结论的前提下转入新层级。
- 决策：仅接受历史 `signal_status`、`platform_signals`、`business_signals`、`learning_decision`；迁移只在内存返回新 `feedback`。
- 理由：历史没有细分信息时，不能补造客户动作或负面漏斗。
- 证据：既有 schema 保留旧汇总字段以兼容历史内容。
- 生效范围：测试中的 dry-run；不写回原 JSON、Logseq、Obsidian 或任何平台。

## 验证与回滚

```powershell
python scripts/operations_contract_regression.py
python -m unittest discover -s tests -p 'test_operations_contract_regression.py' -v
python <workspace>\scripts\validate-content-operations.py
```

回滚只需删除本仓新增的回归 schema、fixture、脚本、测试和本说明；既有 `<workspace>\docs\content-creation-system` 合同没有改动。不得使用 reset、stash 或 checkout 覆盖其他并发改动。
