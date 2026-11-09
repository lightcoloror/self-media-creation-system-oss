# 本地发布项目浏览器回归：源码与前置校验

#### 概述与目标
本指南针对开源版本（Apache-2.0，基于 Main 分支）中的本地发布项目浏览器端回归测试运行器 `self-media-creation-system/tests/publication-current-projects.cjs`。该脚本设计用于在本地无头浏览器环境中检查发布工作台页面的 DOM 结构、数据绑定、文案修改交互、导出与保存恢复、移动端视口布局及 HTTP/S 请求拦截记录。本说明仅提供源码级边界指导，不构成运行测试通过认证，亦不代表底层业务平台真实发布。

#### 运行前置依赖
1. **Node.js**：支持 CommonJS 的原生运行环境。
2. **外部 Playwright**：需要已安装 Playwright 包。由于脚本采用 `require(process.argv[2])` 加载，遵循 Node 模块解析规则，**强烈建议传入 Playwright 模块入口的绝对路径**。
3. **Microsoft Edge**：脚本固定指定 `channel: 'msedge'` 启动 Chromium，依赖宿主系统已安装的 Edge 浏览器。未提供任何额外的浏览器配置标志。
4. **合成资产（调用方自备）**：本批不分发调用所需的私有项目清单、页面 HTML 或媒体资源；公开仓库内其他合成样例不自动组成这份运行器的完整配套输入。调用方必须自行生成受控的合成页面与对应数据 JSON。
5. **前置规则链说明**：仓库公开事实已包含 `scripts/purpose_continuity.py`。页面初始状态与失效检查依赖渲染器与该模块的规则输出，但真实匹配的上下文及渲染报告仍取决于调用方输入，严禁通过硬编码或篡改 HTML 状态制造虚假测试通过。

#### 命令行调用约定
执行命令必须使用受控占位符，请勿直接执行缺失夹具的命令：
```text
node self-media-creation-system/tests/publication-current-projects.cjs <ABSOLUTE_PATH_TO_PLAYWRIGHT> <MANIFEST_JSON_PATH> <OUTPUT_DIR>
```
- **路径解析关键差异**：
  - `process.argv[2]`（Playwright）：作为模块路径由 `require()` 解析，建议绝对路径。
  - `process.argv[3]`（Manifest）：文件由 `fs.readFileSync` 读取。**重要警告**：清单中各项目的 `page_ref.path` 与 `current_data_ref.path` 在当前脚本实现中是相对于**进程启动时的当前工作目录（cwd）**解析，而非清单文件所在目录。
  - `process.argv[4]`（输出目录）：通过 `path.resolve()` 解析为绝对路径。每个项目会在其下建立以 `project_id` 命名的子目录，存放 `edited-test-only.json`、`saved-test-only.html` 和 `mobile.png`，根目录下生成 `browser-report.json`。务必指定全新的隔离输出目录。

#### 清单（Manifest）结构示例
以下包含两个示例项目 ID 的 JSON 结构仅供结构示意，并非可运行的随附测试夹具：
```json
{
  "projects": [
    {
      "project_id": "synthetic_project_alpha",
      "page_ref": { "path": "./fixtures/synthetic/alpha/index.html" },
      "current_data_ref": { "path": "./fixtures/synthetic/alpha/data.json" }
    },
    {
      "project_id": "synthetic_project_beta",
      "page_ref": { "path": "./fixtures/synthetic/beta/index.html" },
      "current_data_ref": { "path": "./fixtures/synthetic/beta/data.json" }
    }
  ]
}
```

#### 核心断言与交互流
原脚本的 17 个 assert 调用位置完整保留（其中含循环内检查及全局网络／页面错误检查，实际调用次数随项目和图片数变化）。主要行为为：
1. **数据一致性**：校验页面 `#desk-data` 与 `current_data_ref` 一致，校验 `project_id`。
2. **卡片与媒体**：核对平台卡片数、`video[controls]` 数量，确认 `#delivery-status` 为 `draft`。
3. **初始非失效**：断言初始页面 `#local-preparation` 不含“通用要求需保存数据后重新检查”。
4. **展示与图像解码**：点击“全部展开”；对所有 `img[data-cover-id]` 执行 `decode()` 并断言 `naturalWidth > 0`。
5. **交互与失效触发**：在小红书面板修改简介正文，断言整段文案同步更新，且 `#local-preparation` 出现重新检查失效提示。
6. **导出与再载入**：触发“导出发布数据 JSON”与“保存当前页面”；重新打开保存的 HTML，验证修改保留且状态仍为 `draft`。
7. **折叠与移动端**：点击“全部收起”；展开单卡片并将视口切至 412x915，断言横向无溢出（`scrollWidth <= innerWidth + 1`），全页截图保存。

#### 边界、防护与安全警告
- **本批源码适配**：在任何输出目录创建、Playwright 模块加载和浏览器启动前校验整个清单：projects 必须非空、引用须为非空字符串、project_id 须为安全且不重复的直接子目录名称。拒绝分隔符、盘符、路径逃逸、控制字符、Windows 保留设备名／别名及大小写重复。没有减少或条件跳过原页面／目的贯穿检查。
- **沙箱局限性**：词法层面的路径校验无法防止符号链接攻击或 TOCTOU 竞争；输入的页面脚本与数据本身必须是受信任的合成测试资产。
- **网络与权限边界**：脚本通过 Playwright route 对 HTTP/S 请求执行 `r.abort()`，并在 `report.network` 中收集。这仅属于脚本层拦截，绝非操作系统级网络沙箱；`browser-report.json` 中的状态声明亦不代表实际已完成云端发布、人工审批或符合临床真实性。


## 本批实际验证与未验证

原4902字节工作快照及既有逐文件审查保留；不冒称固定历史Git原件。Apache-2.0仅适用于本批第一方源码；不分发Playwright、Edge或字体／媒体二进制。Gemini 3.8 Flash／high提供说明提案，由Owner核对整合。源码语法与原17个断言文本保全有独立检查记录。Node --test 首次启动测试文件子进程即遇到 spawn EPERM；测试用例尚未执行，未切换运行模式、提权或修改安全设置。后续源码修正的最终非执行解析结果见本批审核材料，不能把测试文件存在称为测试通过。

实际浏览器交互、生成页面／数据／目的上下文整链、截图、图片解码、安装／跨机能力均未验证；运行前需调用方自行在获准环境验收。输入页面脚本必须可信，HTTP/S拦截和报告字段不能证明无其他网络行为、无真实上传或人工发布许可。
