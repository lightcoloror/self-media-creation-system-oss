# 自媒体创作工作流：中文快速上手指南

本指南帮助你从空白目录冷启动部署并验证由 11 个公开仓库组成的离线自媒体创作工作流。主控工作区为 `self-media-creation-system-oss`；其余仓库通过 `requirements-owners.txt` 固定提交安装，或按 `tools/public_toolchain.lock.json` 检出到对应子目录。

## 1. 适用人群、在线 API 现状与硬件要求

### 1.1 现在适合试一试的人群

1. **熟悉命令行 / Python、日常用 Coding Agent 辅助创作的人**（如搭配 Codex、Claude Code、Cursor 等）：可由 Agent 直接驱动 CLI，串联选题约束、证据绑定、口吻/合规校验与图文排版，无需从零搭框架。
2. **高合规 / 重证据垂类创作者或技术负责人**（如保险、医疗健康、财税、法律科普）：可直接复用“未核验事实拦截”“隐私脱敏校验”“`manual-only` 人工发布红线”及“发布后 48h/7d 复盘闭环”。
3. **熟悉 FFmpeg 与云端模型 Key 配置的视频创作者 / 开发者**：借助 `model-provider-gateway`（LiteLLM 路由与同意门控）及 `video-knowledge-pipeline` 云端路线，可跑通视频转录切片、结构化拆解与受控成片导出。

### 1.2 建议等在线 API 封装 / 图形化接入更完善再试的人群

1. **纯非技术背景、期待“装好即用桌面软件 / 填一个 Key 点按钮就出片”的普通创作者**：当前以 CLI 与本地 JSON/Schema 契约为主，尚无面向大众的一键图形安装向导。
2. **不用 Coding Agent、且不愿手动配置模型 Key / Profile / 同意门控的用户**：公开版遵循 fail-closed 原则，默认**不内置任何在线 API Key、不预绑定厂商账号、不自动发起联网推理**；虽然底层已提供 `model-provider-gateway`（支持 LiteLLM 路由、系统 `keyring` 与执行同意记录）和 VKP `[online]` 可选扩展，但面向普通用户的“开箱即用一键云端接入”仍在完善中。
3. **期待“全自动爬取 -> 全自动剪辑 -> 全自动登录发号”无人值守流量的用户**：本系统明确坚持人工事实核对与 `manual-only` 发布边界，不会绕过平台规则自动发号。

### 1.3 电脑空间与 CPU / 内存 / GPU 配置参考

> **空白冷启动实测参考**：在全新空白目录完成核心依赖 + `requirements-owners.txt` 安装，并检出 5 个同级 owner 仓库源码（不含视频素材与本地模型权重），磁盘实测总占用约为 **`240 MB`**（实测 `239.70 MB`：`.venv` 占 `168.26 MB`，主仓及 5 个同级仓源码合计约 `71.44 MB`）。

| 使用档位 | 硬盘空间需求 | CPU 建议 | 内存（RAM） | 显卡（GPU / 显存） |
| --- | --- | --- | --- | --- |
| **档位 1：轻量图文 / Agent 编排**（跑契约、选题、合规校验、HTML/卡片排版） | 底座实测 `~0.24 GB`；建议日常预留 **`2–5 GB`**（存草稿与快照） | 任意近 5 年 4 核处理器 | **`8 GB`** 起（推荐 `16 GB`） | **无需独显**（集成显卡即可） |
| **档位 2：视频粗剪 + 在线大模型 API（最推荐）** | 环境 `1–2 GB` + 素材缓存，工作盘建议预留 **`20–50 GB`** | **`6–8 核+`**（FFmpeg 抽帧、转码、烧录字幕为主，含 `psutil` 资源守卫） | **`16–32 GB`** | **无需独显**（推理走云端 API；核显/CPU 可跑通 `birefnet_matting.py` 等轻量化脚本） |
| **档位 3：纯本地跑 ASR / 抠图 / 本地多模态模型** | 依赖 + 模型权重 `10–30 GB`（如 `faster-whisper` large-v3 约 `3 GB`、BiRefNet ONNX、CUDA/PyTorch 运行时）+ 视频素材，建议 SSD 预留 **`50–100 GB+`** | **`8 核+`** | **`32 GB+`** | 本地 Whisper / BiRefNet 推荐 NVIDIA **`8 GB+ VRAM`**（Windows 下 `birefnet_matting.py` ONNX 也支持 `DmlExecutionProvider` 走 AMD/Intel/NVIDIA GPU，无独显会回退 CPU 且耗时明显上升）；若另跑本地 VLM 服务，建议 **`12–24 GB+ VRAM`**（或 Apple Silicon **`32 GB+`** 统一内存） |

## 2. 环境前置条件

- **Python**: `>= 3.11`（含 `venv` 与 `pip`）
- **Git**: 建议 `>= 2.40`
  - **Windows 必做提示**：执行安装前先开启长路径支持，否则克隆 `video-knowledge-pipeline-oss` 等含深层路径的仓库时可能失败：
    ```powershell
    git config --global core.longpaths true
    ```
- **可选系统依赖**（按需安装，未安装时基础契约与离线逻辑仍可运行，对应扩展用例会自动跳过）：
  - **FFmpeg / FFprobe**（加入系统 `PATH`）：`video-delivery` 本地音视频成片渲染与 `test_video_delivery.py` 实测必需。
  - **Node.js**：仅在自行构建 `video-knowledge-pipeline` 前端资产（进入该目录执行 `npm install && node build.mjs`）或搭配可选第三方仓库 `external/ryan-wechat-publisher` 排版适配器时需要。
  - **计算机视觉库**（`numpy`、`opencv-python`）：仅局部抠图（`birefnet_matting`）、接触表及视觉多样性检测脚本需要；基础 `requirements.txt` 不强制捆绑。

## 3. 空白目录冷启动安装步骤

以下示例在全新空白工作区中执行（Linux/macOS 可将 `.venv\Scripts\python` 替换为 `.venv/bin/python`）：

```bash
# 1) 克隆主工作区仓库
git clone https://github.com/lightcoloror/self-media-creation-system-oss.git
cd self-media-creation-system-oss

# 2) 创建隔离虚拟环境并安装核心依赖与固定版本 owner 包
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pip install -r requirements-owners.txt
```

如需运行完整工作区契约联调与源码发现，将以下 5 个同级 owner 仓库精确检出到 `tools/public_toolchain.lock.json` 指定的路径与提交：

```bash
git clone https://github.com/lightcoloror/question-research-poc-oss.git question-research-poc
git -C question-research-poc checkout c9957bf680da8a7232ef332519e33a788a17c93d

git clone https://github.com/lightcoloror/content-visual-studio-oss.git content-studio-poc
git -C content-studio-poc checkout db610dda39548d6eab4502bf23117e303bc5062b

git clone https://github.com/lightcoloror/artifact-lifecycle-core-oss.git artifact-lifecycle-core
git -C artifact-lifecycle-core checkout fab239085724458c2a6b9452d0a1ba4f4012593e

git clone https://github.com/lightcoloror/video-knowledge-pipeline-oss.git video-knowledge-pipeline
git -C video-knowledge-pipeline checkout 870460c9e758850aadd548011510c7b7e780ddc5

mkdir -p ai-video-tools-20260708
git clone https://github.com/lightcoloror/mvp-video-pipeline-oss.git ai-video-tools-20260708/mvp-video-pipeline
git -C ai-video-tools-20260708/mvp-video-pipeline checkout 8592e867b2e0c969205b3e30ec6ef05b0ec18217

# 初始化并校验本地只读工具发现清单
.venv/Scripts/python tools/public_toolchain.py init
.venv/Scripts/python tools/public_toolchain.py discover content-studio
```

## 4. 最小冒烟验证命令

```bash
# A. 主入口只读自检与路由解析（先进入 self-media-creation-system 子目录）
cd self-media-creation-system
../.venv/Scripts/python scripts/self_media_agent.py capabilities
../.venv/Scripts/python scripts/self_media_agent.py doctor
../.venv/Scripts/python scripts/self_media_agent.py resolve --request fixtures/agent-entry/moments-short-post.request.json
../.venv/Scripts/python scripts/self_media_agent.py operations

# B. 全套契约与运营模型校验
../.venv/Scripts/python scripts/check_self_media_contracts.py --no-tests
cd ..
.venv/Scripts/python scripts/validate-content-operations.py

# C. 已安装 CLI 入口检查
.venv/Scripts/video-knowledge --help
.venv/Scripts/video-content-brief --help
.venv/Scripts/research-poc --help
.venv/Scripts/content-studio-visual --help
.venv/Scripts/wcf --help
.venv/Scripts/research --help

# D. 运行测试集
.venv/Scripts/python -m pytest -p no:cacheprovider -q self-media-creation-system/tests tests tools/test_public_toolchain.py
```

### 冷启动实测基线与验证边界（2026-11-23）

- **实测环境**：全新空白工作区、Python 3.13.5、仅安装 `requirements.txt` + `requirements-owners.txt`，未预装 FFmpeg、`numpy`/`cv2`、Node.js 或第三方可选仓库 `external/ryan-wechat-publisher`。
- **实测结果**：
  - `check_self_media_contracts.py --no-tests` 退出码 `0`（通过全部 Schema 与合成契约门禁）。
  - `pytest` 运行结果：`869 passed, 41 skipped, 329 subtests passed`（`0 failed, 0 errors`）。
  - **41 项跳过明细（诚实边界）**：31 项因未安装 `ffmpeg`/`ffprobe` 跳过（`test_video_delivery.py`）；3 项因未装可选 `numpy`/`cv2` 跳过（抠图、接触表、图文视觉多样性测试）；1 项因完整封面渲染扩展未随公开版分发跳过（`test_cover_design.py`）；1 项因未克隆可选 `external/ryan-wechat-publisher` 跳过（`test_flow_connections.py`）；1 项因测试环境不支持目录符号链接跳过（`test_content_operations_cycle.py`）；其余 4 项为公开版保留的私有启动器/线程历史/发布包装边界占位校验。
- **重要边界**：上述离线合成与契约测试通过，**不代表**已完成真实自媒体账号登录、外部大模型 API 鉴权配额验证或线上平台真实发布。

## 5. 11 仓库生态版本矩阵（2026-11-23）

| 角色 | 公开仓库 | 发行标签 | 锁定提交（`main`） | 说明 |
| --- | --- | --- | --- | --- |
| 总控与自媒体规则引擎 | [`self-media-creation-system-oss`](https://github.com/lightcoloror/self-media-creation-system-oss) | `v0.1.8` | `main`（本指南所属发布） | 入口调度、选题/口吻/合规/交付门禁与工作区粘合 |
| 图文排版与视觉规范 | [`content-visual-studio-oss`](https://github.com/lightcoloror/content-visual-studio-oss) | `v0.1.11` | `db610dda39548d6eab4502bf23117e303bc5062b` | 图文/长文章卡片、视觉检查与候选交付适配 |
| 视频知识抽提与切分 | [`video-knowledge-pipeline-oss`](https://github.com/lightcoloror/video-knowledge-pipeline-oss) | `v0.1.5` | `870460c9e758850aadd548011510c7b7e780ddc5` | 视频转录、知识点拆解与审计；前端需另行 `npm install && node build.mjs` |
| 粗剪与渲染执行出口 | [`mvp-video-pipeline-oss`](https://github.com/lightcoloror/mvp-video-pipeline-oss) | `v0.8.2` | `8592e867b2e0c969205b3e30ec6ef05b0ec18217` | 唯一受控 FFmpeg 执行出口与成片清单核验 |
| 问题研究编排入口 | [`question-research-poc-oss`](https://github.com/lightcoloror/question-research-poc-oss) | `v0.1.3` | `c9957bf680da8a7232ef332519e33a788a17c93d` | 研究问题规划、证据缺口与结构化结论桥接 |
| 产物生命周期状态机 | [`artifact-lifecycle-core-oss`](https://github.com/lightcoloror/artifact-lifecycle-core-oss) | `v0.2.0` | `fab239085724458c2a6b9452d0a1ba4f4012593e` | 候选/审核/定稿产物哈希锁定与磁盘清理门禁 |
| 多源检索与事实核查 | [`ai-research-workflow-oss`](https://github.com/lightcoloror/ai-research-workflow-oss) | `v0.1.2` | `82a00ec6a80e0e15fe5643be25c079466142b693` | 多来源检索与原子事实核验引擎 |
| 合规网页抓取与归档 | [`web-content-fetcher-oss`](https://github.com/lightcoloror/web-content-fetcher-oss) | `v0.1.2` | `99d63462ebe9b3e2dfb9f36f121a3f6cfc970e1a` | 公开网页正文抽取与证据快照归档（`wcf` CLI） |
| 媒体下载调度层 | [`video-download-orchestrator-oss`](https://github.com/lightcoloror/video-download-orchestrator-oss) | `v0.1.1` | `b24e4e08446a91b41b07383ff20cc407b926f7fb` | 独立授权媒体下载与任务状态编排（按需单独安装） |
| 模型供应统一网关 | [`model-provider-gateway-oss`](https://github.com/lightcoloror/model-provider-gateway-oss) | `v0.3.1` | `bdbae4edf28f599c951d2e6f755d390961ddc134` | 统一大模型调用路由、配额与同意门控（按需配置密钥） |
| 本地协作与规则治理 | [`codex-local-governance-oss`](https://github.com/lightcoloror/codex-local-governance-oss) | `v0.1.1` | `ba0bca6632979a35881583d531f4637593e2e66c` | 本地跨任务规则与门禁校验工具参考（按需查阅） |

## 6. 人工把关与隐私红线

- **人工发布边界（`manual-only`）**：本工作流所有脚本与 CLI 仅输出候选稿、审核包或本地渲染预检结果，**不会**代为执行线上发布；任何对外发布前必须完成人工事实复核、口吻确认与合规签字。
- **隐私与密钥脱敏**：严禁向公开分支、测试样本或提交记录中写入真实客户姓名、保单号、个人健康/病历详情、账号 Cookie 或第三方 API Token；生产使用前请在本地隔离目录配置独立凭证。
