# 医学相关内容角标与免责声明

更新：2026-10-31（Asia/Shanghai）。工具：Codex，精确运行型号未独立核验。

依据：用户明确要求“在角标添加流程里，增加检查医学相关的也要有角标，免责声明”。这是本账号的制作要求，不宣称为所有平台统一的法律条文。

## 适用与文案

每条视频根据当前正文明确记录 `required` 或 `not_applicable`，并写理由。按正文是否解释医学知识、诊疗机制或给出健康、医药和诊疗指导来判断。疾病、治疗经历或药品只用于说明医保、费用、理赔和家庭决策时，记为账单背景。`video-delivery overlays-check / overlays-bind` 的正文引文、类别和理由是正式入口的适用性凭据。医学与保险同时相关时两类要求都保留。

医学相关视频采用独立可编辑角标。混合话题在 `overlays-bind` 的正文评估里锁定 `medical.windows` 和 `medical.rect`，角标仅在指定医学段出现。旧记录缺少窗口时沿用全片覆盖：

**医学科普｜内容仅供参考，不替代个体诊疗建议。**

现阶段使用这一受控文字，避免只写“仅供参考”却漏掉医学用途与个体诊疗边界。后续调整须明确审核并更新现有政策，不由模型随意生成免责承诺。医生姓名、机构、职称、执业资质如另需展示，必须使用已核对的真实来源；本次不自动填入，也不把保险执业号当医师资质。

免责声明不替代科学依据、专业审核、隐私、个案边界及平台当前规则检查，不赋予诊疗、发布或免责许可。

## 接入已有流程

1. 脚本/内容交接：核对全文适用性，绑定当前 `script_ref`。修改正文后重新判断；不能将旧判断直接套在新稿上。
2. 包装：复用现有文本/ASS/编辑器图层。与 AI 标识及保险身份分开核验，可同框排版；实际行区分别登记，防止重复叠字。
3. 布局复用 `video-final-layout-safety.v1` 和 `role=disclaimer`，同时检查文字、时间覆盖、位置与碰撞。每个 `windows` 记录提交 `start_seconds`、`end_seconds` 及 `evidence_quotes` 中的 `quote`，时间使用最终画面时钟。`rect` 使用归一化的 `x/y/width/height`。有章节进度条时用 `video-delivery overlays-geometry` 为组件准备几何输入，渲染后用 `overlays-finalize-layout` 将范围规则恢复到最终布局，再绑定抽帧与人工复核。
4. 成片验收：已有 `final_layout_review` 额外记录 `medical_disclaimer_visible=true`、`medical_disclaimer_text_checked=true`，同成片、布局、抽帧证据哈希绑定。需要实际看清角标；生成文件、编辑器有图层和布局通过均不等于成片已显示。
5. 返工：适用性、文字、位置、时长或成片改变后重验；不自动补签旧回执、不批量改写历史成片。

## 原入口用法

```text
python scripts/self_media_agent.py video-delivery medical-select --input <当前manifest.json> --decision required --reason <根据当前正文的理由> --output <新manifest.json>
```

非医学内容使用 `--decision not_applicable` 并说明理由。命令读取 manifest 已绑定稿件，填入受控文字及稿件引用，清除新 manifest 的旧 `acceptance_ref`；不会写入编辑器或渲染。原输入文件保留。

manifest 中 `medical_overlay` 有 `decision/reason/text/script_ref`；布局的 `medical_disclosure` 采用同一 `decision/reason/text`。缺失、未决定、稿件漂移、布局判断与 manifest 不一致均阻断。所有新布局验证都需要显式医学适用性；旧文件不自动当非医学，须新增版本如实补齐。

代码核验的是声明、当前引用、时间覆盖和证据一致性，不能自动判断全部医学题材、自动 OCR 或证明人已观看。适用性必须由创作审核根据内容判断；实际可见性及文字核对仍由当前成片人工验收负责。

## 变动记录

意图：医学内容不会在角标流程漏掉用途提示与免责声明。
决策：复用现有布局 schema、免责声明角色、选择 CLI 和最终人工复核，不另建流程。
理由：原系统已分别处理 AI 与保险标识，尚缺独立医学适用性和成片校验。
证据：本轮用户要求；新增缺省/错文案/断续覆盖/遮挡/旧稿/旧布局/缺人审负例。
生效范围：后续制作与新验证、返工；不修改锁定稿、旧视频或 STATE，不恢复真实导出。测试回执在 `<workspace>/outputs/medical-disclaimer-20261031/`。
