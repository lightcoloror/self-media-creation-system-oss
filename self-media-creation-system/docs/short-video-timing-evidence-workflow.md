# 短视频实际时间证据工作流

Updated: 2026-09-11 12:33:23 +08:00 | Codex (GPT-5)

## 结论

当前系统不再只检查稿件里有没有写“0—2 秒、2—5 秒、5—15 秒”。它把同一套运营假设接入两个实际观察阶段：作者试读后的录制候选，以及剪辑完成后的最终成片。阈值来自 `config/short-video-timing-profile.v1.json`，属于可复盘的运营假设，不是平台算法、流量保证或所有视频都必须机械卡秒的事实。

| 证据阶段 | 输入 | 能证明 | 不能证明 |
|---|---|---|---|
| 故事设计 | Story Design Card | 计划在什么位置交付处境、推进和回报 | 作者真实语速、剪辑后的落点 |
| `prerecording-script` | 冻结脚本、作者实际试读时间码 | 这份录制候选按当前语速可以交付时间结构 | 后期剪辑、字幕和最终成片仍符合 |
| `final-cut` | 同一脚本、精确成片、定时文本 | 绑定成片满足当前时间假设 | 平台一定推荐、观众一定完播 |

预录制次序固定为：初稿 → 初稿审核 → 人声改写/保留 → 作者朗读与口吻确认 → 试读时间证据 → 可以录制。采访路线仍先写采访提纲并审核问题，不要求采访已经发生，也不预写受访者答案。

生产次序固定为：视频 Owner 产出候选成片 → 最终成片时间证据 → 隐私/打码、客户效果与发布前审核 → 人工决定是否发布。预录制回执不能替代最终成片回执。

## 当前检查项

- 受众处境最迟在 2 秒前出现。
- 继续观看的理由最迟在 5 秒前出现。
- 首个新动作、数字、选择、证据或结果最迟在 15 秒前出现。
- 相邻信息推进以及最后一次推进到视频结束的间隔不超过 15 秒；8 秒内出现新信息完全允许，“8—15 秒”不是最低等待时间。
- 主要回报最迟在全片 80% 位置出现；可以更早，不要求故意拖到结尾。
- 故事路线沿用配置的两次推进下限。直接回答路线如果只有一次实际推进，且该段兑现本条唯一的主要回报，一次即可。开场、回报位置和时间轴仍按现有证据核对。已有多次推进的回执继续记录原配置下限。
- 每条内容必须独立成立；系列名可以作为弱标识，但不能依赖“上一集/下一集”才能理解。
- “以后持续解决什么”只有实际说出或作为字幕呈现时，才记录为显式持续价值承诺；账号定位一致不能冒充本条已经说过。

若 Story Design Card 为该条内容设定了更严格的时间值，实际证据使用更严格值。非故事路线不强行生成故事卡，但仍使用通用短视频时间假设。

## 使用方法

先检查合成正负例和两阶段隔离：

```powershell
python scripts/short_video_timing_evidence.py check
```

作者试读后，把每个关键句的开始/结束秒数、脚本锚点和实际说法填入 `short-video-timing-evidence-input.v1`，阶段设为 `prerecording-script`，`measurement_basis=observed-read-aloud-timecode`，且 `media_binding=null`：

```powershell
python scripts/short_video_timing_evidence.py create --input <prerecord-timing-input.json> --output <repo-managed-runtime/timing-receipt.json>
```

最终剪辑后，阶段改为 `final-cut`，绑定最终视频文件、SHA-256、定时文本和同一冻结脚本。`synthetic_only=false` 时，程序会复用 `scripts/publication_version_freeze.py` 的 `ffprobe` 探测实际时长，不接受仅手填的时长：

```powershell
python scripts/short_video_timing_evidence.py create --input <final-cut-timing-input.json> --output <repo-managed-runtime/timing-receipt.json>
```

输入和输出 Schema：

- `schemas/short-video-timing-evidence-input.v1.schema.json`
- `schemas/short-video-timing-evidence.v1.schema.json`

合成示例：

- `fixtures/short-video-timing-evidence-v1/synthetic-prerecord.input.json`
- `fixtures/short-video-timing-evidence-v1/synthetic-final-cut.input.json`

## 失效与阻断

以下情况均 fail-closed：脚本或 Story Design Card 哈希漂移；时间轴引用了不存在的脚本句段；精确匹配却没有在实际话语中出现；关键角色缺失；推进乱序、间隔过长或回报过晚；预录制输入伪装成成片证据；真实成片没有 `ffprobe`；探测时长、成片哈希或定时文本时长不一致；最终人工发布交接缺少成片时间回执。

为了避免把形式检查误当成效果证明，回执状态始终为 `candidate-only`、`manual-only`，没有发布、外发或执行权限。真实阈值效果需要用本人同平台、同长度、同形式的留存数据逐步校准。

## 变更依据

- 意图：让“开头与信息推进时间设计”从纸面字段升级为实际可验证的创作证据。
- 决策：复用现有 case-video、Story Design、人声门、Content Packaging、成片冻结和人工发布链，只增加薄时间证据 sidecar。
- 理由：录制前需要先有稿件；最终视频时长可以直接从发布文件读取。把两个阶段混为一谈会颠倒创作顺序或放行剪辑漂移。
- 证据：用户对录制顺序和最终文件时长的纠正；现有故事卡阈值；`publication_version_freeze.py` 的 `ffprobe` 实现；合成正负例和集成测试。
- 生效范围：`case-video-candidate` 的口播录制候选与最终成片，不自动扩展到图文、直播或长视频。
- 回滚：移除 `video-timing` 两个步骤及最终人工交接输入，删除新增 Schema、fixture、脚本和测试；不得回退其他并行改动、旧稿、发布记录或历史回执。
