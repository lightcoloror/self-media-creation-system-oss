# 跨平台事实一致性门禁

当同一内容产生两个以上平台版本时，平台适配可以改变长度、顺序、开头和表达密度，但不能悄悄改变事实。

## 输入与判断

`cross-platform-fact-consistency-review.v1` 要求：

- 所有平台版本绑定同一份已锁定事实卡及同一修订版；
- 标准化主张账本明确哪些是核心主张、哪些是可省略主张；
- 每个平台逐项声明主张是保留还是省略；
- 保留主张的标准化文本哈希必须与权威账本一致；
- 核心主张不得因字数、版面或时长省略；
- 非核心主张只允许因 `density`、`format` 或 `duration` 省略，并记录理由；
- 事实卡、平台正文和审核回执都绑定 SHA-256。

比较器不会从正文自动推断主张，不生成文案，也不授予上传或发布权限。主张与正文的对应关系仍需人工确认；机器负责拒绝混用事实修订版、哈希漂移、漏报主张和核心事实删改。

## 稳定命令

```text
python scripts/cross_platform_fact_consistency_gate.py check
python scripts/cross_platform_fact_consistency_gate.py create --input fixtures/cross-platform-fact-consistency-v1/synthetic.input.json --output .runtime/cross-platform-fact-consistency/review.json
python scripts/cross_platform_fact_consistency_gate.py validate --receipt .runtime/cross-platform-fact-consistency/review.json
```

## 更新记录

### 2026-09-03 17:31:30 | Codex (GPT-5.6 Sol)

- 意图：让多平台版本共享事实不再依赖人工记忆。
- 决策：增加一个薄的、只读式声明比较器，复用事实卡、主张账本和文件哈希，不另建生成器或发布状态机。
- 理由：平台压缩和改写最容易把非核心删减升级成核心事实变化，而单个平台审核看不出这种漂移。
- 证据：合成双平台正例以及混合修订版、主张漂移、漏报主张、核心主张省略、来源和回执哈希漂移负例。
- 生效范围：同一内容存在两个以上平台候选版本时；单平台稿件不适用。
- 回滚：同时删除 Schema、脚本、fixture、测试、路由扩展、质量门和文档；不得只留下无法执行的文字规则。
