# 可复用的多路线封面工作台

更新：2026-09-26，Codex（GPT-6 Astra）。属于现有视频封面子流程，不是新 workflow，也不是新渲染器。

## 入口

2026-09-26 内容选案补强（Codex）：新项目默认走 [内容分析 → 方案选择 → 视觉差异审核 → 全比例交付](content-driven-covers.md)。不是把所有路线固定各跑一张；先以内容证据选互补方案，缺输入、重复、不适用分别解释。

2026-09-26 通用母版补充（Codex）：新增 `design-recipes / design-init / design-build`，详见 [通用封面设计](generic-cover-design.md)。适用于不同项目和账号，包含非生成式图层、7 个起始构图配方和可编辑 JSON 母版；输出仍接本页既有 compile/render/collect，不安装第二套编辑器。

```powershell
python scripts/self_media_agent.py covers
python scripts/cover_workbench.py catalog
python scripts/cover_workbench.py methods
python scripts/cover_workbench.py styles --query "插画"
python scripts/cover_workbench.py doctor
python scripts/cover_workbench.py init --project-id new-video --title "本条视频" --output D:/private-run/brief.json
python scripts/cover_workbench.py plan --input D:/private-run/brief.json --output D:/private-run/route-plan.json
```

`doctor` 只检查文件和可发现的程序，不会启动服务、下载模型或把“文件在”写成运行成功。首次空 brief 故意不能进入 plan：Agent 要先填本项目真实内容，而不是拿上一条改标题。

## 历史 Skill 复用入口（2026-09-26 补全）

`methods` 读取 `config/cover-methods.v1.json`，逐次检查本地文件并计算哈希，区分已安装技能、研究副本和仅历史提及。当前索引 17 项（2026-09-26 补入 canvas-design 研究副本），并非全网或全部历史对话的穷尽清单。复制到隔离测试目录的同一技能不重复计数。详见 [历史技能补查](cover-method-inventory-2026-09-26.md)。

brief 可填 `content_kind`：`generic/family/tutorial/product/article/case/lucas_brand`；不填兼容旧计划为 generic。`method_ids` 可明确增加方法 ID；拼错会报错，超出默认适用场景会警告，源文件缺失会标为 `blocked_missing_source`，不自动替代路线。

`plan` 新增 `method_plan`：按内容与所选路线列出参考方法、精确源码路径/哈希、采用理由、所需设计产物和不采纳边界。**这是设计任务，不是设计完成证据，也不是源 Skill 的自动调用。** Agent 按需完整读取选用的 SKILL 和相关参考，再将交付字段落实到候选设计卡；不得一口气执行所有第三方工作流。新方法索引不改旧 visual plan 或渲染合同。

`styles --query "插画"` / `styles --template-id <实际ID>` 直接检索已有 GPT Image 风格库 JSON，返回模板、案例 ID、使用条件和坑点，不复制重建风格库、不调用图片模型。名称不是模型已安装的证据。库路径缺失时明确报错，不能捏造结果。Skill、风格、生产路线、渲染后端四者不能混计为同一个数量。

## Agent 操作配方（每个新项目复用）

1. 读当前用户要求、审核记录、现有标题封面计划；冻结 `promise/facts/forbidden_claims`。不要把旁白、笑话、比喻变成新事实。
2. 查素材，图像先看再设计。每个 asset 填 `id/kind/artifact={path,sha256}/local_use_approved/privacy_reviewed`。kind 用 `photo/evidence/reviewed_cutout/generated_decoration`。文件必须是当前私有目录的绝对路径。原件不改，照片上传默认不允许。
3. 用 `strategy-init / strategy-plan` 绑定内容观察和表达角度。默认 `all_applicable`：每个有内容依据且输入齐全的不同构图族保留一个代表，不预设三套；按当前策略检查角度和构图族覆盖，不足不凑数。`routes` 可列全部试用，`plan` 返回各路缺项。抠图需透明且复核过的衍生图；没有则保持缺输入。
4. 为每个候选写设计卡：`id/name/route/hypothesis/composition/strength/risk`。`composition` 写“何种真实瞬间、视线、主次、留白/景深/文字关系”，不是仅填风格名。检查是否只换了背景色。方法参考来自 [研究报告](cover-open-source-research-2026-09-26.md)，不是多个外部 SKILL 同时强制执行。
5. 确定性路线写现有 `lucas.case_cover_visual_plan.v1`（schema 名称为兼容保留，不代表给家庭视频套保险品牌），绑定真实 account、已审核 title plan、safe layout 和素材哈希。通用母版没有默认青红色板；按内容/情绪/素材选择 `color_selection`，同方案各比例沿用该方案颜色，不同方案可分别选色。品牌色仅在当前账号和内容明确适用时绑定引用；详见 [配色选择与账号边界](generic-cover-design.md#配色选择与账号边界)。手工可编辑 visual-plan 也在候选与计划同时附上选色对象，compile/collect 核对实际图层。摄影负空间可用 `local.photo_editorial_cover.v1`，该旧协议不声称已执行逐图层配色核对。不要把家庭账号假装成“灿哥精进”以绕过某个 recipe 的适用边界。其他既有 recipe 仅在适用账户/素材下使用。
6. AI 是可选 Agent 步骤。brief 中 `ai_authorization={allowed:true,user_quote:原始明确授权}` 只记录范围，不能自己给自己授权。读取当前 imagegen 技能后，用原生工具；完整提示词先存文件。v1 工作台只接受无参考图上传的概念生成。生成全图走 `ai-illustration`；生成非人物装饰后本地叠合走 `hybrid`。不把 Python 合成当作调用图片模型，不用生成脸替代真实女儿。
7. 比例独立排版。每个 profile 都有 layout 与 safe zone；不要为了补齐比例缩小标题、切脸或硬裁已经排好文字的海报。底稿不适合横版就换构图或明确缺输入。
8. `compile` → 已有 Still 出图 → `collect` → `review-init / review-check`。在每个比例的输出图上看中文字、眼睛、嘴、手、主视觉、字幕残留、脸部遮挡，再按 270px 竖版/360px 横版看小图并逐对检查差异。图片齐全不等于审核完成，更不产生人类通过。
9. 在已有发布辅助页选候选。缺失比例的平台封面为空并提示；不会写 undefined 路径或沿用上一组。保留合集字段。没有人工选择前不把编辑推荐变成人工采用。

## Build 合同

`self-media.cover-build.v1`：

```json
{
  "schema":"self-media.cover-build.v1",
  "project_id":"new-video",
  "route_plan_ref":{"path":"D:/private-run/route-plan.json","sha256":"文件实际哈希"},
  "strategy_plan_ref":{"path":"D:/private-run/strategy-plan.json","sha256":"文件实际哈希"},
  "safe_layout_ref":{"path":"D:/private-run/safe-layout.json","sha256":"文件实际哈希"},
  "packaging_ref":{"path":"D:/private-run/packaging.json","sha256":"文件实际哈希"},
  "candidates":[{
    "id":"real-memory","name":"真实瞬间","route":"photo-editorial",
    "hypothesis":"当前项目的真实点击理由","composition":"具体素材与空间关系",
    "strength":"为什么适合这条内容","risk":"会丢失什么信息",
    "visual_plan_ref":{"path":"D:/private-run/real-memory.json","sha256":"文件实际哈希"}
  }],
  "platform_ratios":{"xiaohongshu":["3:4"],"bilibili":["16:9","4:3"]}
}
```

上述只是字段示例，不可执行，不能把“文件实际哈希”当值。`platform_ratios` 是当前项目的人工准备需求，不是工具宣称的平台强制规则。

纯 AI 候选不填 visual_plan_ref，而填 `prompt_ref`、`reference_uploads:[]` 和 `outputs:[{ratio,artifact:{path,sha256}}]`。导入时检查实际 PNG 头、分辨率、比例和哈希，不能把 prompt 指定尺寸当实际尺寸。原生执行证据仍是 Agent 的工具结果，工作台不伪造模型执行回执。

## 执行

```powershell
python scripts/cover_workbench.py compile --input D:/private-run/build.json --output D:/private-run/build-01 --runtime-source <已登记Remotion源码> --skill-root <已登记Remotion技能源码>
python scripts/cover_workbench.py render --input D:/private-run/build-01/remotion/remotion-project-manifest.json --runtime-source <同一源码> --browser <已验证浏览器>
python scripts/cover_workbench.py collect --input D:/private-run/build.json --receipt D:/private-run/build-01/remotion/remotion-cover-run-receipt.json --desk D:/private-run/publication-data.json --item-id main --output D:/private-run/review-01
```

编译生成同一正式 Remotion 项目。已有受控运行时依赖须按原 renderer 流程安装/复用，工具不隐式 npm install。不要绕过 renderer 的运行时版本、资源检查或回执。编译不是出图；出图不是视觉审核。

`collect` 校验既有正式回执、源 manifest、精确 visual plan、真实 PNG，合并进既有发布包，保存旧候选历史、文案和发布记录；输出 JSON、HTML 和汇总回执。所有输出只新建，不覆盖已有版本。发布仍全部人工。

## 支持与不支持

现在可执行：本地确定性 visual plan 编译/出图；无上传的 AI 图接入；多路线同页比较；缺失比例检查；哈希绑定；现有发布包无损合并。Agent 仍负责选帧与设计，不是“一句话自动生成最佳封面”的承诺。

目前不做：自动云端登录/收费、人物图上传、模型安装、伪造人类批准、自动预测 CTR、自动发布。rembg、Polotno 等后端是否可用必须另做真实 doctor/试跑，不能因为出现在研究表就显示为已集成。

本轮实际执行范围及回执见 [2026-09-26 验收记录](cover-workbench-verification-2026-09-26.md)。
