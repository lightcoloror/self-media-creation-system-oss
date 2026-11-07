# NoteRx（薯医）联动：自媒体端 P0 合同

> 更新：2026-07-26 13:25:00（Asia/Shanghai）
> 执行者：Codex（GPT-5.6）
> 状态：本地离线诊断桥；不是 NoteRx 应用接入、部署或模型评估。

## 边界

- `wechat-tools` 负责导出和导入；本仓负责读取与诊断。
- 本仓的版本化权威合同在 [`schemas/`](../schemas/)；任何兼容扩展先增加版本，不能静默改写 v1。
- 一个 `content-bundle.v1` 是同一平台的一次批量 envelope，内含一至多条内容。
- 输入必须 `local_only=true` 且 `mode=dry_run`；评论、指标、原图与本地路径均不允许进入合同。
- `profile_id` 必须是 `profile-<sha256>`，不能传显示昵称、主页 URL 或其他可读身份。
- CLI 不访问网络、不调用模型、不读取 NoteRx 数据/服务器配置/凭据、不模拟评论、不发布。
- 结果是问题—证据—建议的候选诊断。它不是爆款评分、推荐权重、真实互动、合规结论或保险/医疗决定。

## 接口

```text
wechat-tools exporter
  -> content-bundle.v1 (JSON, batch, deidentified, dry_run)
  -> self-media CLI diagnosis
  -> analysis-result.v1 (JSON, batch, candidate-only)
  -> wechat-tools importer / UI
```

### `content-bundle.v1`

顶层字段固定为：

- `schema_version`、`bundle_id`、`created_at`、`platform`、`privacy`、`items`。
- `privacy` 固定要求：`local_only=true`、`mode=dry_run`、`comments_included=false`、`metrics_included=false`、`raw_media_included=false`，另显式标记 `content_text_may_contain_personal_data`。
- `items[]`：`profile_id`、`content_id`、`content{title,body,visual_description,tags}`、`evidence_refs`，可选 `routing_context`。

`additionalProperties=false` 是有意的隐私边界：`comments`、`simulated_comments`、URL、`local_path`、`author`、`display_name`、原图或媒体字节均无字段可放，采集端传入时应失败。

### `analysis-result.v1`

顶层字段固定为：`schema_version`、`result_id`、`bundle_id`、`generated_at`、`status`、`mode`、`engine`、`summary`、`items`。

每个 item 的 `input_ref` 只回传 `profile_id` 与 `content_id`，并给出四个固定角色：

1. `clarity-reader`：主要信息与阅读清晰度；
2. `route-adapter`：形态/平台/受众/目标路由；
3. `evidence-safety`：证据、隐私、医疗保险边界；
4. `voice-visual`：本人声纹与主题视觉路线。

每个 `finding` 都有 `issue`、`evidence_refs`、`recommendation`、`confidence` 与 `confidence_reason`。`confidence` 仅表示这条诊断能否由输入合同支持，不能解释为内容效果预测。

`engine` 永远固定为：`network_calls=0`、`models_called=[]`、`comments_simulated=false`、`published=false`。

## 本地命令

```powershell
# 默认 fixture，输出到标准输出
python scripts/content_diagnosis.py

# 校验 exporter 的输入，不创建分析结果
python scripts/content_diagnosis.py --input .\content-bundle.json --validate-only

# 输出供 importer/UI 展示的结果
python scripts/content_diagnosis.py --input .\content-bundle.json --output .\analysis-result.json

# P0 测试
python -m unittest discover -s tests -v
```

## 当前规则来源

- `task-router.json`：平台、形态、路由顺序与人工发布边界；
- `quality-gates.json`：事实、隐私、医疗保险、版权、声纹与可访问性硬门；
- `skill-registry.json`：专项 skill 的适用范围与禁止范围。

P0 只将这些合同转成确定性提醒；不会复制、整仓依赖或部署 NoteRx 的任何代码。
