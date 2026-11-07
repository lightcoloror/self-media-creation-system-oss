# W10-G72 自媒体经营合成回归

- 状态：完成
- 执行者：Codex（GPT-5）
- 更新时间：2026-07-31 16:06:17
- 数据边界：只使用完全虚构的账号、内容、事件、快照和业务信号

## 1. 结论

本轮没有修改 `account`、`topic`、`publication-event`、`performance-snapshot` 四张生产 Schema，而是在现有合同、迁移器、状态机和统一检查器之上增加了一层薄的合成场景回归。

统一入口：

```powershell
python scripts/check_self_media_contracts.py
```

最终结果：

- 仓内合同、迁移、场景和负例：31 项通过。
- 既有四张生产 Schema 的基线回归：6 项通过。
- 三组完整经营旅程的确定性 SHA-256 与场景矩阵一致。
- `content_no_signal` 不会生成客户、咨询或业务层面的负面结论。
- 内容信号与业务信号可以独立存在，不能互相推导。

## 2. 复用的既有模块

本轮没有建立平行流程，也没有新增外部依赖。

- 生产数据合同：`account`、`topic`、`publication-event`、`performance-snapshot` 四张既有 Schema。
- 内容引用：既有 `content-item.operating_refs`。
- Schema 校验：项目已经使用的 `jsonschema`。
- 迁移与六层复盘：`operations_contract_regression.py` 中既有迁移、观察窗口、内容/业务隔离逻辑。
- 常规入口：`check_self_media_contracts.py`。

生产 Schema 在本轮结束时的文件状态：

| Schema | 最后修改时间 | SHA-256 |
|---|---:|---|
| `account.schema.json` | 2026-07-19 00:09:23 | `A40EDA949752AE2090C6232B7E36192A85DF63EDB8186B619286AEC5D10AAA91` |
| `topic.schema.json` | 2026-07-19 00:09:23 | `681AA49046F7AA94FD68F489F61928F81C0063F4A41A139BEA0F02E0917EA05B` |
| `publication-event.schema.json` | 2026-07-19 00:13:32 | `A6B3D941C26EE86DBFB734B4C541917B3F3655459EC138855A7BB653DC78982D` |
| `performance-snapshot.schema.json` | 2026-07-19 00:09:23 | `ED795D13EC646956BDC99EEE18E7893753D7C55E92E549E707BF5D980E81E936` |

## 3. 回归链路

三组场景都从同一份既有合成 fixture 生成，覆盖以下经营链路：

```text
私域候选
→ 公域改写
→ prepared
→ published
→ 48–72 小时观察
→ 第 7 天复盘
→ 可选 deleted 终态
```

三组虚构主题：

1. `虚构：纸飞机问题卡`：已发布，但内容无信号，业务无信号。
2. `虚构：云朵收纳清单`：发布后删除，历史事件和观察快照仍保留。
3. `虚构：星光路线问答`：内容信号和独立业务信号都有虚构证据。

六层复盘继续使用既有分层：

1. admission
2. attraction
3. consumption
4. value
5. negative_feedback
6. business

其中前五层不允许产生客户结论；业务层也必须由独立的业务证据驱动。

## 4. 幂等 hash

生成器对完整 bundle 做键排序、紧凑 JSON 序列化后计算 SHA-256。相同输入必须得到相同结果，任何内容变动都会改变 hash。

| 场景 | SHA-256 |
|---|---|
| `private_to_public_no_signal` | `f493253f17c6e008f7ad23313613a1c7fe720ff72a28b1397c61695cf66ec4f2` |
| `private_to_public_deleted` | `44f0cf3c7f91595ad12e37c1127b14575d5aa6004f471af29f9e9bcca29b6d5d` |
| `private_to_public_business_observed` | `4a32ad0918b52908e45525000b1f3266a981c3e2558e5e58b0fc76d6c7001cc8` |

## 5. 负例与边界

已覆盖：

- 未经过 `private-candidate → public-rewrite` 前缀。
- 内容状态冒充发布事件。
- 缺少 `published` 事件却标记为已发布。
- `deleted` 发生在 `published` 之前。
- 重复 publication event。
- 事件序号、时间或 `supersedes_event_id` 链错误。
- snapshot 引用错误的 publication。
- 48–72 小时和第 7 天窗口边界及乱序快照。
- 未知字段。
- 旧版 fixture 迁移后错误推断业务状态。
- 篡改场景的预期 hash。
- `content_no_signal` 被错误送入客户负面漏斗。
- `content_no_signal` 与已有独立业务信号并存时被错误互相覆盖。

篡改 hash 的测试只在内存中构建 bundle，不创建临时目录，也不写运行时数据。

## 6. 变更依据

### 6.1 场景矩阵与幂等 hash

- 意图：把私域候选、公域改写、发布、两次观察和复盘串成可重复验证的完整旅程。
- 决策：新增一份严格的三场景矩阵；生成结果不落盘，只计算 canonical SHA-256。
- 理由：减少复制 fixture 带来的漂移，并让场景篡改能够被自动发现。
- 证据：三组 hash 重跑一致；hash 篡改和内容变动测试通过。
- 生效范围：仅合成回归和检查器，不影响生产 Schema 或真实数据。
- 回滚：删除场景矩阵、薄生成器及对应测试，并从统一检查器移除该导入。

### 6.2 publication 生命周期薄扩展

- 意图：在不改生产 Schema 的前提下验证 `prepared → published → deleted` 等追加式事件链。
- 决策：在既有回归脚本中加入事件 ID 唯一性、允许转换、时间顺序和 `supersedes` 链检查。
- 理由：JSON Schema 能验证单条事件形状，但不能独立验证跨事件状态机。
- 证据：正常发布、发布后删除通过；发布前删除、重复事件和断链负例被拒绝。
- 生效范围：仅本地合同回归逻辑。
- 回滚：移除 `publication_lifecycle_errors` 调用，恢复原有单一发布链检查。

### 6.3 内容信号与业务信号隔离

- 意图：防止“没有内容反馈”被解释为“客户不认可”或“没有业务价值”。
- 决策：保留既有六层复盘，并增加跨场景断言：内容无信号不产生客户结论；独立业务证据可与内容无信号并存。
- 理由：内容表现和业务观察来源不同，不能互相代替。
- 证据：相关正反例均由统一 checker 自动执行并通过。
- 生效范围：合成 fixture、回归断言和诊断结论边界。
- 回滚：可以删除新增测试，但不建议移除既有信号隔离规则。

### 6.4 统一检查入口

- 意图：让 schema、fixture、迁移、场景、负例和基线测试由一个稳定命令执行。
- 决策：在既有 `check_self_media_contracts.py` 中调用场景套件，并让测试发现覆盖新增用例。
- 理由：避免“单独测试能过、常规检查没有运行”的遗漏。
- 证据：统一命令一次执行 31 + 6 项测试并全部通过；`--no-tests` 快速合同检查也通过。
- 生效范围：本仓库本地验证命令。
- 回滚：从检查器移除场景套件导入和错误聚合，其他测试文件仍可独立执行。

### 6.5 临时路径修复

- 意图：消除仓库本地临时目录 ACL 对边界测试的影响。
- 决策：hash 篡改测试改为纯内存构造与比较。
- 理由：该测试只需要证明预期 hash 被篡改，不需要验证文件 I/O。
- 证据：原来唯一失败的边界测试修复后 3/3 通过，全量检查 31 + 6 通过。
- 生效范围：`test_w10_g72_regression_edges.py`。
- 回滚：恢复临时文件测试会重新引入对本机目录权限的依赖，不建议回滚。

## 7. 本轮文件

新增：

- `fixtures/operations-contract-regression.v1.scenarios.synthetic.json`
- `scripts/operations_scenario_suite.py`
- `tests/test_operations_scenario_suite.py`
- `tests/test_w10_g72_regression_edges.py`
- `docs/w10-g72-synthetic-operations-regression-2026-07-31.md`

薄适配：

- `scripts/operations_contract_regression.py`
- `scripts/check_self_media_contracts.py`

未修改：

- 四张生产 Schema。
- 真实账号、真实内容、真实指标和真实客户资料。

## 8. 验证命令

```powershell
python scripts/operations_scenario_suite.py --print-hashes
python -m unittest discover -s tests -p "test_w10_g72_regression_edges.py" -v
python scripts/check_self_media_contracts.py --no-tests
python scripts/check_self_media_contracts.py
```

最终结果：全部通过。

## 9. 边界检查与剩余缺口

- 没有登录任何平台。
- 没有读取真实账号、素材、发布结果或客户数据。
- 没有生成真实发布稿。
- 没有发布、联系客户或写入 CRM、Logseq、Obsidian。
- 没有调用外部 API，也没有新增依赖。
- 没有 push、commit、stash、reset 或修改生产 Schema。

剩余缺口是刻意保留的：本回归只能证明合同、状态机和隔离规则在合成数据上稳定，不能证明真实平台采集质量、平台指标含义或真实业务归因。
