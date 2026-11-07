# 冷启动与四周压力测试：现有记录体系落地说明

> Acting tool/model: Codex (GPT-5.6 Sol)
> Updated at: 2026-08-30 09:04:09 +08:00
> Status: implemented in existing contracts; synthetic fixtures only; publication remains manual-only

## 结论

冷启动与四周压力测试不建立新表和第二套状态机。所有记录继续进入现有经营对象：

| 要回答的问题 | 权威记录对象 | 记录时点 |
|---|---|---|
| 这条是否真的发布、何时发布、发到哪里 | `publication-event` | 用户确认“已发送/已发布”时 |
| 这条用了多少制作时间 | `resource-ledger-event`，`resource_type=human-time` | 内容达到 publish-ready 后人工登记 |
| 是否发生一次结构或脚本级大返工 | `resource-ledger-event`，`resource_type=other`、`unit=count` | 发生大返工时追加事件 |
| 内容是否吸引、被看完、带来关注 | `performance-snapshot` | 发布后 48–72 小时及第 7 天 |
| 四周是否能稳定产出、哪类题值得继续 | `operating-review` | 每周小结、第四周总复盘 |
| 标题、封面、开头等单变量是否有效 | `experiment-run` | 测试前登记假设，观察窗结束后结论 |

`content-item` 仍是唯一内容主对象；上述对象通过稳定 ID 引用它，不把全部字段塞进一个大 JSON。

## 单条内容的最小记录

### 1. 发布确认

人工确认“已经发布”后保存 `publication-event`。发布动作本身不由系统执行。朋友圈只有一个微信账号时可使用既定默认账号；如果没有提供图片，只记录大致视觉描述，不保存图片副本。

### 2. 生产能力

每条只需要两项硬记录：

- `total_production_time_hours`：从确定选题到 publish-ready 的人工总用时。
- `major_rework_count`：完整初稿之后，发生脚本或结构级重做的次数；错字、单句微调、字幕校对不算。

它们复用 `resource-ledger-event`。合成示例位于：

- `templates/cold-start-production-records-v1/human-time.resource-event.synthetic.json`
- `templates/cold-start-production-records-v1/major-rework.resource-event.synthetic.json`

库存/储备不为每条另造字段。周复盘时，从处于 `draft_only`、`publish-ready` 等现有状态的内容对象聚合得到可发布储备。

### 3. 内容与增长

在 48–72 小时和第 7 天分别记录平台能够提供的原始值：

| 层 | 优先指标 |
|---|---|
| 准入 | 是否正常发布、是否出现平台处理 |
| 吸引 | `reach`、`views` |
| 消费 | 3/5/10 秒留存、平均观看时长、完播率、主要流失秒点 |
| 价值 | 点赞、收藏、分享、有内容的评论、主页访问、可归因新增关注 |
| 负反馈 | 隐藏、举报、取关等聚合数量 |
| 业务 | 明确继续咨询、主动提供必要资料、预约下一步；必须人工确认 |

系统只从原始值计算三个诊断率，不允许手工录入成另一套真相：

```text
千次播放关注数 = 可归因新增关注 / 播放量 × 1000
主页访问率     = 主页访问 / 播放量 × 100%
主页关注转化率 = 可归因新增关注 / 主页访问 × 100%
```

分母为 0 或平台不提供数据时不计算，不填 0、不猜测。朋友圈没有曝光、阅读或留存后台，因此相应字段为 `null + unavailable`；朋友圈只记录可见互动及用户明确告知的后续动作。

## 四周复盘看什么

周复盘和第四周总复盘使用现有 `operating-review`，至少回答：

1. 本周完成了多少条，是否达到预设发布节奏。
2. 单条制作时间中位数是否下降，大返工是否减少。
3. 哪类题在吸引、消费、价值三个层面分别更强。
4. 关注发生在“被看见不足”“看后不进主页”还是“进主页但不关注”。
5. 是否出现重复的真实问题，能否进入下一轮选题池。
6. 是否可持续：疲劳、拖延、储备和工具成本是否失控。

不同平台、时长和内容形态不直接混比。优先和自己近期同平台、同长度、同形式的内容比较。点赞、播放和收藏仍是内容信号；`content_no_signal` 只是证据不足，不升级成客户负面或选题失败。

## 运行入口

```powershell
python -B scripts\publication_feedback_tracker.py generate
python -B scripts\publication_feedback_tracker.py check
python -B -m unittest tests.test_publication_feedback_tracker tests.test_cold_start_recording_contract -v
```

## 变更依据

- 意图：把冷启动、涨粉和持续产出能力的指标变成可重复记录，而不是停留在行动方案文字中。
- 决策：扩展现有人工反馈指标字典，并复用资源台账、发布事件、快照、经营复盘和实验合同。
- 理由：这样同一条内容从发布、反馈到周复盘保持稳定引用，也避免个人记录和平台数据形成两套口径。
- 证据：现有 Schema 已支持追加资源事件、任意平台指标、两个观察窗口、六层信号和周/月经营复盘。
- 生效范围：当前只对合成 fixture 和人工录入模板生效；不读取真实平台、不自动发布、不写 CRM。
- 回滚：删除新增模板和测试，恢复 `publication_feedback_tracker.py`、人工输入模板及生成 fixture 到变更前版本；无需迁移生产 Schema。
