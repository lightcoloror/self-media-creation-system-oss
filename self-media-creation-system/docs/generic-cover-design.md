# 通用封面设计：从可编辑母版到本地候选

更新：2026-09-26，Codex。入口属于现有自媒体封面子流程；不增加 workflow 或 renderer。

## 能力与边界

现在支持 7 个非生成式起始配方：`photo-caption`、`photo-doodle`、`comparison`、`storyboard`、`cutout-type`、`type-symbol`、`evidence-focus`。这些是构图配方，不是 7 个生成模型；`photo-doodle` 当前提供简单可编辑几何标记，不是完整手绘插图库。

照片与素材仍是用户自己的当前项目输入。工具不会自动挑“最好表情”、虚构比较依据、从旧项目借脸，也不会为了填满配方自动生图。通用母版的账号必填，无家庭账号或专业账号默认值。旧专业品牌 recipe 的账户限制保留。

2026-09-27，Codex 更新：通用 `design-init` 不再提供一套默认青红配色，而是创建待填写的 `color_selection`。先按当前内容、情绪、素材与阅读性选择颜色；“灿哥诊风险”的品牌规范仅在当前账号和内容明确适用时引用，不继承到家庭、旅行、教程等其他内容。青色或红色并未禁用，也不替换成另一套万能色板。

母版保存图片、文字、矩形、椭圆、线条的图层及每种比例的布局。编辑 JSON 后可重新编译到新目录；不是拖拽式画布，也不是已接入 Polotno/Penpot。所有图像输出继续走现有 Remotion Still，旧 AI 路线仍可选。

## Agent 每次复用的入口

```powershell
python scripts/self_media_agent.py covers
python scripts/cover_workbench.py design-recipes
python scripts/cover_workbench.py strategy-init --input <当前项目route-plan.json> --output <strategy-request.json>
# 填写当前内容证据、角度和取舍，不能只填题材标签。
python scripts/cover_workbench.py strategy-plan --input <strategy-request.json> --output <strategy-plan.json>
python scripts/cover_workbench.py design-init --input <当前项目route-plan.json> --strategy-plan <strategy-plan.json> --output <新的design.json>
python scripts/cover_workbench.py design-build --input <填写后的design.json> --output <新design目录>
python scripts/cover_workbench.py compile --input <新design目录/build.json> --output <新编译目录> --runtime-source <已登记Remotion源码> --skill-root <已登记技能源码>
# render、collect 继续使用 docs/cover-workbench.md 的入口。
```

新项目默认使用 [内容驱动选案](content-driven-covers.md)。`design-init` 依据已绑定选案创建候选骨架，等 Agent 填设计与每比例布局，不替用户决定事实；历史 v1 无选案输入仍创建空候选。`design-build` 自动编译所有 requested_ratios；它不会渲染。缺素材就报告缺项，不静默换成生图。

步骤：先按既有工具创建 brief、route-plan、视频 packaging 和安全素材布局，再创建 design。设计输入及合成输出建议放在各项目私有 run 目录，不提交家庭、客户或证据原件。

## 输入示例（字段示意，路径和哈希须用真实值）

```json
{
  "schema":"self-media.cover-design.v1",
  "project_id":"current-project",
  "route_plan_ref":{"path":"绝对路径/route-plan.json","sha256":"实际哈希"},
  "strategy_plan_ref":{"path":"绝对路径/strategy-plan.json","sha256":"实际哈希"},
  "packaging_ref":{"path":"绝对路径/packaging.json","sha256":"实际哈希"},
  "safe_layout_ref":{"path":"绝对路径/safe-layout.json","sha256":"实际哈希"},
  "account":"当前项目账号",
  "color_selection":{
    "mode":"content","account":"当前项目账号",
    "palette":{"background":"#FFF8EF","foreground":"#382B25","accent":"#87511D"},
    "content_basis":["此示例假定是温暖的家庭回忆，实际使用须重填"],
    "rationale":"此处示意奶油白与可可棕呼应家庭回忆；不是其他项目的默认配色"
  },
  "candidate_only":true,
  "manual_publish_only":true,
  "candidates":[{
    "id":"compare-a","recipe":"comparison","name":"真实对照",
    "title":"已核对的发布标题","headline":"封面短标题",
    "asset_ids":["素材A的ID","素材B的ID"],"labels":["真实A","真实B"],
    "relation_basis":"说明为什么这两张能比较，不虚构效果",
    "hypothesis":"要验证的理解方式","composition":"主次、空间与文字职责",
    "strength":"当前项目的优势","risk":"会损失的信息"
  }]
}
```

示例候选 ID、recipe 和 asset_ids 必须以选案结果为准，不可原样复制。纯 `type-symbol` 不需要 safe_layout_ref。其他配方使用 brief 中的素材 ID，必须和既有 safe-layout 的 asset_id 相同，原件哈希重新核验。

### 配色选择与账号边界

- `color_selection` 可放在母版上共享，也可由每个 candidate 独立提供完整对象。不同方案可选择不同色板，同方案的横竖衍生共用该方案色板，布局仍分别设计。
- `mode:content` 必须有当前 `account`、至少一个当前内容依据 `content_basis`、选色说明 `rationale` 和六位十六进制 `palette`。必需角色为 background / foreground / accent；确有需要可增加如 highlight 等颜色角色。不能只写“高级感”而忽略当前内容与素材。
- `mode:brand` 还必须显式提供 `brand_applies_to_content:true` 以及适用于当前账号的本地 `brand_ref` 文件哈希。账号绑定必须匹配；工具不按标题关键词猜品牌，不自动证明品牌规范适用。Agent 仍要核对引用和适用范围。
- 可编辑图层的实际背景和非图片图层颜色必须属于所选色板，避免“说明改了，渲染还是旧色”。修改已展开母版时同步改图层颜色；照片像素不改色，不用色板检查冒充图片审核。
- 原生 AI 图可在 build 候选记录相同的选色依据；工具不能仅从元数据证明生图实际遵循配色，必须看成图。复用的旧图须注明复用，不声称重新生成。
- 旧 v1 母版原有显式 `palette` 仍可重放，但不自动补造“按内容选色”的理由。新母版缺选色数据会要求填写，不静默回退。

brief 素材增加以下显式字段：

- `generated:false`：不接受生成图冒充真实素材。
- `subject_reviewed:true`、`protected_regions:[{x,y,width,height}]`：保护区相对于源图、归一化坐标；空数组只代表明确审过且无需保护的人物/手势区域，不是自动检测结论。
- `local_use_approved:true`、`privacy_reviewed:true`：沿用现有本地使用和隐私门。
- `reviewed_cutout` 要有非全不透明的 alpha 通道及 `cutout_reviewed:true`；蒙版质量仍由人审核。`segmentation_model_used` 可声明 true/false，未声明保留未知，不伪造为没有使用模型。
- `evidence` 要有 `verified_focus`；这记录用户提供的核验焦点，不自动证明证据真假。
- 建议附 `provenance`：原素材身份、原片时间点、裁切/蒙版关系。现有文件哈希是强制绑定，provenance 的事实仍需 Agent/人工核对。

`comparison` 与 `storyboard` 需要每图 label 和 relation_basis；不能用相同文件哈希的图片凑两张。前者等面积对照，后者可两至三格、保持给定顺序。配方不改变正文事实。

## 编辑与重新出图

`design-build` 输出 `editable-master.json`、各候选 `.visual-plan.json`、`title-packages.json`、`build.json`、`design-build-receipt.json`。

优先编辑 `editable-master.json` 中每个 candidate 的 `profile_layouts`，再对它运行 design-build，输出到另一个新目录。修改标题时同步调整对应 headline 文本层；若只改上层 headline 而不改已展开图层，会报 `headline_drift`。希望重新自动排版时，显式移除相应 profile_layouts；不把生成后的文字静默替换。

图层类型：image/text/rect/ellipse/line。坐标 box 均为画布归一化坐标；image 通过 asset_id 引用已绑定原件；字色限定十六进制，字体与字号沿用本地政策，不允许注入 CSS/脚本/URL。源图只 contain，不隐式裁切；需要裁切时先制作并审核独立衍生素材。

文字过长会要求精简或重新排版，不缩小到手机不可读。内建宽度判断是保守估算，不取代实际字体渲染与小图验看。图层不自动执行颜色对比度、语义正确性或审美打分。

## 后端与状态

`rendered:false` 的设计回执仅表示母版编译完成。必须继续得到原有 Remotion 出图回执并 collect 才进入发布页。collect 保留 design_method、source_methods、generative_model_used、segmentation_model_used 等追溯字段；不自动选中或发布。

当前配方来源参考：Woop/Charlie 的真实承诺与留白、gbro 的空间组织、canvas-design 的图形与排版方法。方法参考不等于完整执行第三方 Skill。来源索引见 `config/cover-design-recipes.v1.json` 与 `config/cover-methods.v1.json`。

Polotno/Penpot、自动抠图、复杂手绘路径、拖拽编辑均未集成。用户提供并批准的透明图已可使用；不再把没有透明图误判为题材不适用。

## 验证与恢复

本轮实际执行结果与证据路径见 [验证记录](generic-cover-design-verification-2026-09-26.md)。

测试入口：`tests/test_cover_design.py`，覆盖 7 配方×5上游profile、跨项目隔离、母版 round-trip、素材/字号/保护区/文字溢出等；图片类设计合同单测中安全布局校验有明确隔离 mock，不能单独当完整生产证据。

`tests/prepare_cover_design_smoke.py --output <新目录> --engine <现有justified-layout/lib/index.js>` 使用几何合成 PNG，不用家庭素材，真实调用现有安全布局工具，再输出 7 配方的横竖版设计。后续用正式 compile/render/collect 检查完整链路。

输出不可覆盖。后期绑定失败时目录里保留 `FAILED.json`，不要把残留计划当成功回执；修正输入后使用新的输出目录。代码回滚只撤销本轮新增层与入口，不删除既有用户改动或私有素材。
