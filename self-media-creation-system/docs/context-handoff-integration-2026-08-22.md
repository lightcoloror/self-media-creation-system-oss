# 任务胶囊与本地工具信息的两层交接落地

> 状态：已实施并通过合成回归
> 更新时间：2026-08-22 09:25:31 +08:00
> 执行者：Codex (GPT-5.6 Sol)
> 边界：只生成候选、诊断和交接回执；不发布、不登录平台、不调用真实 Provider、不写 CRM 或知识库。

## 问题结论

用户的判断成立。旧版任务胶囊存在两个结构性问题：

1. 胶囊只是建议性元数据，下游工具没有强制验证它，所以“生成过胶囊”不等于“流程实际使用了胶囊”。
2. 胶囊复制了路线和步骤说明，却没有在执行时从当前 `tool-registry.json`、工具发现文件和本地源码补齐工具信息。工具路径、命令、边界或版本发生变化后，旧胶囊既容易漏，也容易过时。

解决办法不是继续把所有信息塞进一个大胶囊，而是将交接拆成两层，并用输入、输出回执闭合每一步。

## 新执行链

```text
用户目标
  → self-media-task-capsule.v2（轻量决策层）
  → 当前步骤 context manifest
  → context receipt（校验输入角色与哈希）
  → self-media-step-handoff.v1（执行层，实时补工具卡）
  → Owner 工具只接受 handoff
  → self-media-step-output-receipt.v1（输出层）
  → 下一步骤
```

### 第一层：决策胶囊

胶囊只携带完成路由判断所需的信息：

- 工作流与内容路线；
- 步骤索引；
- 需要哪些工具；
- 各步骤需要什么输入角色、输出和人工门；
- 路由合同与 recipe 哈希；
- `manual-only`、`candidate-only`、禁止发布等总边界。

它不复制每个工具的全部命令、帮助文档或完整步骤说明。胶囊本身不构成执行授权。

### 第二层：步骤交接

只有当前步骤即将执行时，系统才实时生成 `self-media-step-handoff.v1`。它必须自动补齐：

- 逻辑工具 ID；
- 实际注册 Owner；
- `local-tools discover <tool>` 发现命令；
- Registry 条目哈希；
- `AGENT_DISCOVERY` 符号引用与文件哈希；
- 本地源码或脚本哈希；
- 首选接口与稳定命令名；
- 如果存在，下游消费者的精确 `--handoff` 命令；
- 工具的只读、候选、人工审核、禁止发布等边界；
- 当前步骤完整说明、输入角色、输出合同及恢复入口。

因此，本地工具信息不再依靠交接人手工罗列，也不会把所有未来步骤的工具说明提前载入模型上下文。

## 防遗漏和防漂移规则

下列情况会停止执行，而不是猜测或静默回退：

- context manifest 缺少 `source_role`；
- 当前步骤要求的输入角色未全部覆盖；
- manifest、artifact 或 context receipt 哈希漂移；
- recipe、路由合同、Registry、发现文件或源码哈希漂移；
- 一个 handoff 混入其他任务、步骤或工具的引用；
- Owner 输出缺少 output receipt，或输出哈希、边界、合同与 handoff 不一致；
- 视频审片试图绕过代理文件/关键帧直接载入全分辨率媒体；
- 人工发布、客户联系、外发或 CRM 权限被自动升级。

`self-media-task-capsule.v1` 仍保留用于解释历史产物，但当前 resolver 只生成 v2；v1 不能作为新任务的执行凭证。

## 下游接入状态

当前已强制接入：

- Content Studio：只接受 `--handoff` 做内容上下文预检；
- MVP Video：`plan-review --handoff ...`，并校验代理审片计划及 ASR 决策；
- Video Knowledge Pipeline：`decide-asr --handoff ...`；
- self-media 内部的 canonical routing、合同检查、反馈跟踪和上下文压缩步骤。

视频复核固定为 proxy-first：先看代理视频、关键帧和变更窗口；只有代理或关键帧无法判断时，才允许载入全分辨率媒体。这样既降低视觉 token 和 I/O，又不取消最终人工质量门。

## 合成验证

已对五条通用流程的全部 20 个步骤逐一生成并验证：

- 决策胶囊；
- 角色化 context manifest；
- context receipt；
- Registry/Discovery/源码绑定的 step handoff；
- output receipt；
- 双跑字节稳定性。

结果：五条流程全部通过，20/20 步均产生并通过输出回执。具体机器产物见：

- `outputs/controlled-blind-20260822/two-layer-handoff-retest/summary.json`
- `outputs/controlled-blind-20260822/two-layer-handoff-retest/handoffs/`

测试结果：

- self-media agent 专项：18/18；
- context efficiency 专项：14/14；
- Content Studio consumer：1/1；
- MVP Video consumer：1/1；
- VKP consumer：1/1；
- routing convergence：6/6；
- self-media 全量：107/107。

## 上下文消耗变化

本轮没有可观测的精确 token 计量，因此不宣称确定 token 节省率。使用 UTF-8 字节数作为近似代理：

- 旧 v1 决策胶囊：平均 4395 bytes；
- 新 v2 决策胶囊：平均 3978 bytes；
- 决策层平均缩小约 9.5%；
- 当前步骤 handoff：1896–3511 bytes，按需加载；
- 其中工具卡：97–1398 bytes，未超过 1500 bytes 上限。

更重要的收益不是单次胶囊缩小，而是未来步骤的工具文档不再提前进入上下文，并且只有当前步骤需要的本地工具卡会被加载。

## 尚未覆盖的边界

1. 通过本系统 canonical route 进入的任务已经强制使用 handoff；用户或开发者直接调用某个 Owner CLI 的临时命令，仍可能处于本合同之外。不能宣称所有本地工具的所有入口都已全局封锁。
2. 本轮证明的是合成合同、工具发现和交接完整性，不是用真实内容证明传播效果。
3. 新 v2 合同由确定性回归验证；此前 Luna 低推理验证的是 v1 历史版本，尚不能冒充为 Luna 对 v2 的独立复验。
4. 精确 token 节省需要未来在真实运行中记录模型侧 usage；当前仅有字节代理指标。

## 回滚

如需回滚本轮接入：

1. 删除三份新 schema：`self-media-task-capsule.v2`、`self-media-step-handoff.v1`、`self-media-step-output-receipt.v1`；
2. 恢复 `self_media_agent.py`、`context_efficiency.py`、recipe catalog、manifest、发现说明和 README；
3. 恢复 Content Studio、MVP Video、VKP 的三个 consumer 及对应测试；
4. 删除本轮 `two-layer-handoff-retest` 合成产物。

回滚不会修改既有 v1 历史结果、内容正文、发布记录或任何真实平台状态。
