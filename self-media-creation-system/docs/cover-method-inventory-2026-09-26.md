# 封面历史 Skill 补查与复用入口

记录：2026-09-26 17:43（Asia/Shanghai），Codex，本地源码盘点与代码验证。

## 更正上轮范围

上一份封面调研是选择性调查，不是完整历史盘点。用户指出遗漏属实：旧报告、已安装 Skill、源码审查副本、风格案例库没有汇总到同一个可查询入口。本次补的是方法发现与选择层，不把登记或单元测试写成全部路线已出图。

本次去重登记 **16 项，其中 15 项找到本地 SKILL.md，1 项仅有历史指针**。范围是已定位的封面与邻接设计来源，不声称涵盖全部历史聊天、安装目录和全网 Skill。广域扫描碰到若干无关测试缓存的拒绝访问后，使用已知来源的精确目录核验；没有因此把缺失来源判成不存在。

## 找回的来源和用途

| 来源 | 主要独特价值 | 当前归类 |
|---|---|---|
| Woop thumbnail-design | 标题与封面互补、真实承诺、候选及实验计划 | 研究副本，方法选择已接入 |
| Craig Hewitt thumbnail-design | 小图识别、拍摄方向、品牌一致但构图不重复 | 研究副本，方法选择已接入 |
| Charlie youtube-thumbnail | 表情、视线、照片留白和标题位置的 brief | 研究副本，方法选择已接入 |
| Higgsfield youtube-thumbnail | 信息差、干净视觉层、针对缺陷迭代 | 方法参考；未接云端 CLI |
| atutun-xhs-cover | 8 类高密度中文封面，明确的提示词装配顺序 | 教程/产品条件选择，不作亲子默认 |
| gbro-cover-design | 收敛 brief、空间关系、构图配方 | 已有方法继续复用 |
| oh-my-cover-design | 上游来源谱系 | 不重复计作一条生产路线 |
| gpt-image-2-style-library | 模板、场景、风格、案例 ID 与失败点 | 已接本地 JSON 只读检索 |
| baoyu-cover-image | 类型、色板、质感、文字、情绪分维度 | AI 概念路线参考 |
| baoyu-xhs-images | 图文卡片系列，布局与风格独立 | 邻接方法；非视频封面同义词 |
| baoyu-article-illustrator | 根据内容结构决定图像职责 | 文章/教程条件参考 |
| baoyu-infographic | 信息结构与视觉风格分离 | 信息图方法，不直接把长图缩成封面 |
| lucas-case-cover-craft | 真实案例、证据、隐私、正式 visual plan | 本公开版未分发或验证安装；案例内容条件选择 |
| lucas-personal-visual-system | 操作者身份及品牌规范 | 本公开版未分发或验证安装；不偷换家庭账号品牌 |
| personal-editorial-illustrations | 非人物的物件、空间、动作隐喻 | 本公开版未分发或验证安装；概念图条件参考 |
| claude-youtube thumbnail | 历史摘要提及标题分工 | 精确源码尚未定位，不标可执行 |

精确路径、贡献、适用场景、不采纳边界在 `config/cover-methods.v1.json`；运行 `methods` 时附实时文件哈希。路径存在不代表完整依赖可用；哈希证明当次读取的文件身份，不自动证明旧报告的提交仍是当前 HEAD。

GPT Image 本地 JSON 实测为 **22 模板、19 风格标签、13 类别、10 场景**。不能相加称为 64 条封面路线。隔离测试副本也不重复算 Skill。baoyu-image-gen、原生 imagegen 是生成后端，Remotion 是确定性渲染实现，rembg 是抠图工具，均不拿来膨胀设计方法数量。Canva、Clueso 等历史提及也不因此视为已可用接口。

## 已落实的代码行为

1. `cover_workbench.py methods`：读取方法索引，核验源文件并返回哈希、安装/研究状态。
2. `cover_workbench.py styles --query 插画`：直接检索现有风格库；本次命中 `illustration-art-style`，返回案例 346、6 及构图/风格使用条件，不下载图片或生成模型输出。
3. `plan` 按 `content_kind` 和选中生产路线输出 `method_plan`，提供待阅读路径、采用理由和待完成的设计字段。旧 brief 默认 generic，旧出图合同不变。
4. 用户/Agent 可通过 `method_ids` 明确补选；未知/重复 ID 报错，超范围提示原因，缺源码标记 blocked。没有静默换路线。
5. 所有任务仍是 `pending_agent_read_and_design`；只有名字出现在清单中不等于方法执行完成。此轮未新增设计卡自动合格判定，也未把方法选择强塞为旧候选的新渲染硬门禁。

## 划船歌真实项目验证

保留已有 brief、build、图像及 review-02 原样，新建 `封面工作台_20260926/brief-methods-v03.json` 和 `route-plan-methods-v03.json`。不更改已审核视频或成片字幕。

- 真实摄影/拼贴：匹配 Woop、Craig、Charlie、gbro；未混入 Baoyu 生成后端。
- 混合/概念插画：在上述共用设计机制外，按需匹配 GPT Image 风格库、Baoyu cover、非人物编辑插图等参考。
- atutun 高密度教程不作亲子默认；可选医疗案例模板不自动套到该片。
- 抠图路线仍缺 `reviewed_cutout`，证据路线仍缺 `evidence`；没有因补了 Skill 而伪造输入。

这证明真实项目能产出可追踪的方法选择任务，**不证明新封面已经生成、更好看或提高点击率**。当前比较页仍是之前的 6 张图。下一步是按方法阅读与设计卡进行有差异的画面实验，再在同一发布辅助页比较；不是为了试全名单，把不适合亲子的医学证据/教程清单也硬塞进来。

## 验证

通过 13 项测试：7 项方法索引/选择/检索测试，6 项既有工作台回归。覆盖家庭与教程分流、未知 ID、缺文件、显式跨范围、保持非 AI 路线、未选路线省略、真实结构的风格查询、旧 brief 与 AI opt-in 门，以及既有素材哈希/比例/发布页合并检查。

运行回执：`<workspace>/.runtime/managed-test-runs/_evidence/codex-test-65116-0927b76629f34f258c72b0491a3622d4.child.json`；日志同目录同名 `.log`。另运行了真实源码 inventory、真实风格查询、真实项目 plan 和 CLI covers 发现入口。真实项目旧 `build-v02.json` 的 6 个候选继续通过 `validate_spec`；未重渲染。`git diff --check` 通过（仅既有文件行尾格式提示）。

没有安装新 Skill 或模型，没有家庭照片外传，没有发布、Git 提交或推送。本次 find-skills 用于补查既有来源，Code 用于拆分实现与验证；没有让第三方 Skill 的安装或云端上传建议成为执行授权。
