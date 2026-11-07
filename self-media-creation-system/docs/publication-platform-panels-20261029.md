# 分平台发布页与小红书主封面／PK候选

2026-10-29（Asia/Shanghai）| Codex

发布页复用既有共享渲染器与原生 `details/summary`：各平台可以独立展开或收起，也可全部展开／收起。每个平台下提供需要的视频路径与预览、封面图片与路径、标题、简介和标签。页面不再展示集中封面墙及内部创作依据；这些数据仍保留在导出JSON中并参与原有校验。合集、置顶评论和核验记录默认折叠。

## 封面数据

普通单组选用保留原规则。多封面测试沿用 `cover_pk.selection_mode=parallel_test`，每个平台的 `cover_test` 保存 `candidate_ids` 和 `ratios`；创意与比例文件分别计数，不预设测试胜者。

小红书使用1张主封面＋最多3张PK候选。候选可自主上传或通过平台智能推荐添加；该规则依据2026-10-29用户明确确认，不代表已核验任意账号的入口或启动状态。

- `cover_test.main_cover_id`：独立主封面ID，不占PK候选名额。
- `cover_test.candidate_ids`：1～3个PK候选创意。
- `cover_ids`：候选的比例文件，继续采用已有候选到比例的映射。
- `platform_cover_ids(item, platform)`：供校验和消费者取得主图及候选的去重列表。
- 主图缺失、主图与候选重复或候选超过3张时，准备检查不会通过。1张主图＋3候选的总图数是4。
- 主图变化会使该平台相关裁切、封面检查失效；没有改动的平台不受影响。

各账号的原生入口、名额、裁切及真实启动状态仍需当次核对。保存页面、本地检查通过不等于已上传、开启PK或发布。

## 使用与状态保存

`ui_state.platform_panels` 保存每个平台的展开状态，键为 `item-id::platform`。保存HTML或JSON后可以恢复该状态；只展开或收起不会改变发布记录或内容审核结果。

小红书主封面可选已有且未用于本平台PK的图片，或填写其它本地图片路径。复制主图路径与PK候选路径是两个独立操作。更换素材后仍需通过现有本地检查核验文件、哈希和比例。

## 意图／决策／理由／证据／生效范围

| 变动 | 意图 | 决策 | 理由 | 证据 | 生效范围 |
| --- | --- | --- | --- | --- | --- |
| 共享平台面板 | 缩短发布操作路径 | 复用原生details，提供全部展开／收起并保存视图状态 | 多个平台无需始终占据屏幕 | 本地浏览器展开、刷新及保存重开检查 | 新生成发布页；无平台写入 |
| 平台内素材 | 文件与字段就近对应 | 只展示本平台所用封面与视频；移除集中总览调用 | 避免重复素材墙和路径列表 | 逐平台图片引用、视频路径和预览断言 | 仅展示；原资产和审计数据保留 |
| 内部依据与可选区 | 必要发布字段优先 | 内部依据不展示，可选内容默认折叠 | 不是待粘贴文案的资料不占主要区域 | DOM节点与导出JSON保留检查 | 不移除禁止用语及其它既有校验 |
| 小红书主图及PK模型 | 分开主图和候选名额 | 主封面另计；候选1～3张；Python与JS均校验 | 总图数与候选数不能混算 | 主图缺失、重复、超额、1主＋3候选回归 | 小红书默认规则；其它平台沿用原规则 |
| 核验输入绑定 | 主图变更后复核实际上传效果 | 主图加入封面相关检查快照 | 旧裁切记录不能证明新图适用 | 相关平台失效、其它平台不变测试 | 相关核验；旧记录留存 |
| 可重复测试 | 验证仓库本身可复用 | 生成明确合成的图片和不可播放的视频占位引用 | 测试不依赖个人媒体、账号或本机项目 | 相关Python回归及8组本地浏览器检查 | 仅合成夹具；不验证真实上传或解码 |

## 验证

```powershell
python -B -m unittest discover -s tests -p "test_publication_desk.py" -v
python -B -m unittest discover -s tests -p "test_publication_platforms.py" -v
python -B -m unittest discover -s tests -p "test_publication_parallel_cover_test.py" -v
python -B tests/build_publication_panel_fixture.py TEMP_FIXTURE_DIRECTORY
node tests/publication-platform-panels.cjs PLAYWRIGHT_MODULE_PATH TEMP_FIXTURE_DIRECTORY/fixture.html TEMP_BROWSER_OUTPUT
```

浏览器检查要求本机已有Playwright与Edge；工具运行本身不依赖它们。测试覆盖平台素材归属、全部及单独折叠、独立主封面、1～3候选、文案不变、JSON与HTML保存重开、412px无横向溢出，并阻断HTTP请求。生成物只写入调用者指定的临时目录，不上传或发布。

验证范围：上述33项相关Python测试及8组浏览器检查。更广的`test_publication*.py`还包含既有反馈追踪与入口清单测试，依赖仓库外父级`docs/content-creation-system`的schema；独立检出缺少该依赖时会报错。本次未修改这些模块或伪造外部schema，也不声明全仓测试通过。
