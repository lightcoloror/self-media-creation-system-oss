# 高频问题驱动的自媒体最小闭环方法

- 状态：`draft_only`（公开方法指南；仅引用仓内合成夹具，不含历史业务结果）
- 原指南归属与日期：`Codex (GPT-5.6)`，`2026-07-31`（保留原始归属与日期）
- 公开源整理：`Antigravity`，`2026-11-22`（基于公开基线 `f685f08a96868230d795ddc92ba90fedf162a722` 去除历史业务叙事与未随仓私有路径，替换为仓内合成夹具与相对链接；未修改代码）
- 范围：通用方法与仓内合成夹具参考；仅写入本地 `draft_only` 产物，不写外部知识库或 CRM，不自动发布或联系任何人；本次整理未执行运行时命令。

## 1. 方法定位与可重复频率口径

本方法不预设选题，也不使用模型印象或平台固定权重。排序单位是“去重后的合格独立证据组”（`unique_qualified_evidence_group_not_people_or_messages`），不是消息条数、客户人数或文件数量。

可重复频率口径如下：

1. 候选必须先有“人工确认反复出现”的脱敏本地证据，否则不能进入高频排序。
2. 只统计 `counts_toward_frequency=true` 的证据，并按 `independence_group` 去重。
3. AI 草稿、同源镜像、流程规范、风格画像和风险卡不能抬高频率。
4. 精确出现次数没有记录时固定为 `unknown`（在 JSON 夹具中记为 `null`），不得从候选数量或机器条目数反推。
5. 排序在证据组数量基础上加入风险和事实依赖扣减；低风险、低事实依赖的主题优先进入最小闭环。
6. 个人经历、授权状态和当前产品事实不明时保留 `unknown`（或显式未声明/不适用状态），不得补写。

## 2. 仓内合成夹具、脚本与关联文档

下表所列相对路径均以本文件所在目录 `self-media-creation-system/docs/` 为基准，指向公开仓库已随仓分发的合成夹具、脚本与契约文档：

| 仓内文件 | 用途 |
|---|---|
| [../fixtures/high-frequency-question-candidates.v1.synthetic.json](../fixtures/high-frequency-question-candidates.v1.synthetic.json) | 仓内合成候选证据夹具（`source_scope: "synthetic-only"`，示例仅演示独立证据组去重、同源镜像不计频与 AI 草稿排除，所有状态与字段均为虚构模拟） |
| [../fixtures/minimal-synthetic-week.v1.draft-only.json](../fixtures/minimal-synthetic-week.v1.draft-only.json) | 仓内合成一周草稿包蓝图（`package_status: "draft_only"`，示例私域草稿、单个公域改写候选与非阻塞最小用户确认） |
| [../scripts/high_frequency_topic_loop.py](../scripts/high_frequency_topic_loop.py) | 离线确定性排序与草稿包生成脚本（默认读取上述两份合成夹具，默认输出目录为 `outputs/draft-only/synthetic-week-example`） |
| [../tests/test_high_frequency_topic_loop.py](../tests/test_high_frequency_topic_loop.py) | 高频选题闭环合成回归测试 |
| [../scripts/check_self_media_contracts.py](../scripts/check_self_media_contracts.py) | 仓库统一合同检查入口（聚合调用 `package_errors()`） |
| [../../docs/content-creation-system/content-item.schema.json](../../docs/content-creation-system/content-item.schema.json) | 复用的既有内容项 Schema |
| [./continuous-topic-discovery.md](./continuous-topic-discovery.md) | 持续选题发现追加入口指南 |

## 3. 稳定命令与输出边界

在 `self-media-creation-system/` 目录下，文档化的稳定命令如下：

```powershell
python scripts/high_frequency_topic_loop.py --print-ranked
python scripts/high_frequency_topic_loop.py --write
python scripts/high_frequency_topic_loop.py --check-generated
python scripts/check_self_media_contracts.py
```

`scripts/high_frequency_topic_loop.py` 文档化的 CLI 参数边界如下：

- `--print-ranked`：以 JSON 格式打印按独立合格证据组和风险/事实依赖扣减计算后的排序结果（未指定 `--write` 时默认同时打印排序 JSON）。
- `--write`：将 `draft_only` 一周草稿包写入 `--output-dir` 指定目录（默认 `outputs/draft-only/synthetic-week-example`）。
- `--check-generated`：校验已生成的本地输出文件与内容哈希。
- `--output-dir`：覆盖默认本地输出目录（默认为 `DEFAULT_OUTPUT`，即 `outputs/draft-only/synthetic-week-example`）。

边界说明：

- 该 CLI 在当前基线提交上读取仓内捆绑的合成候选源与合成一周蓝图；打印结果统计的是合格独立证据组，不代表真实人群规模或真实消息条数。
- `--write` 仅生成本地 `draft_only` 文件，不执行任何平台发布、消息发送或 CRM 写入动作。
- 本次文档整理未执行上述任何命令，不声称已复现排序计数或完成运行时验证。

## 4. 状态机复用、人工确认与发布边界

本流程不新增第二套发布状态机，生成的内容项继续服从既有 `content-item.schema.json`：

- 内容状态固定为 `draft`，发布边界固定为 `manual-only`，发布回执 `receipts` 为空数组 `[]`。
- `content_signal_status` 与 `business_signal_status` 初始均保持 `not-observed`。
- 公域改写候选最多保留 1–2 个且保持 `draft_only`（仓内合成一周蓝图仅包含 1 个公域候选）。
- 最小用户确认边界：待确认项未获人工答复时，不阻塞本地草稿生成；在明确人工审阅与确认前，未知项保持待确认/未核实状态，不得发布，不得作出服务承诺或补写未核实事实。
- 中性无信号口径：未发布条目不计入负面信号；已发布但无可观察内容信号时，仅记录 `content_no_signal` / `insufficient-evidence` 表示证据不足，不得转化为负面受众/客户结论、不得写入 CRM 或触发外联动作。

## 5. 公开范围说明与未验证边界

- 历史业务材料与未随仓输入：历史真实账号、客户、业务结果、真实计数与未随仓的本地历史路径及夹具均已移除；操作者若在本地输入经脱敏的真实候选材料，仍须自行完成隐私脱敏复核、合规检查与人工审阅。
- 候选来源定位符缺陷边界：既有的内容项候选来源定位符（`provenance.sources`）导出缺陷由独立源码候选分支（`codex/topic-provenance-source-20261113`）单独处理，本文档不声称该问题已在基线修复或已通过行为验证。
- 公开历史说明：如果后续另行批准普通分支推送，只会更新目标分支的最终文件树；较早的公开提交历史中仍可能保留本文件的原始版本。
