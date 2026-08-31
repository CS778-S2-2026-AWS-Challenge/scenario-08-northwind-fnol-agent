# Sprint 1 后续 Kanban 卡片草案

## 文档用途

本文件供团队审阅和修改。确认后再翻译为英文，并创建到 GitHub Kanban Board。

- **范围：** Day 2、Day 3、Day 4。
- **每日容量：** 5 人 x 8 小时 = 40 人时。
- **任务数量：** 每天至少 10 张卡片。
- **单张卡片：** 2 至 5 人时；超过 5 人时必须拆分。
- **Day 5：** 已确定为 Presentation，具体安排在 Day 4 测试完成后决定。

## 当前 Kanban 状态

2026 年 8 月 11 日检查 Kanban Project 12：

- 当前共有 53 张卡片；
- Day 1 共有 16 张卡片，总计 40 人时，全部位于 `Done`；
- Day 2 共有 13 张卡片，总计 40 人时；
- Day 3 共有 12 张卡片，总计 40 人时；
- Day 4 共有 12 张卡片，总计 40 人时。

## 当前成员方向

| 成员 | 主要方向 |
|---|---|
| `Ysoseri1224` | 项目基建、GitHub 管理、客户前端、Agent 行为和产品整合 |
| `liyang6620` | 行业公开资料、客户问卷、GitHub 管理、后端 API、数据模型和 AWS pipeline |
| `jxu316-arch` | 业内人士访谈，以及与 `liyang6620` 共同建设后端 |
| `LLL263` | 数据收集与分析、员工端前端和员工处理流程 |
| `bdfa123` | 数据分析、Evidence/Session 技术模块、fixture、测试工具、交叉测试和技术修复 |

## 看板运行规则

1. 前置卡片全部进入 `Done` 后，后续卡片才能进入 `Ready`。
2. 卡片必须写明具体交付物和可以直接检查的验收结果。
3. 开发者先完成基本检查，再由另一名成员独立测试；独立测试完成后才能进入 `Done`。
4. 被阻塞的卡片保留在看板中，并写明缺少的输入和下一步，不用假设补齐缺口。
5. 多人卡片必须写明每个人负责的部分，不能让多人共同负责一段无法区分的工作。
6. 面向导师的卡片使用通俗场景名称，不使用内部测试编号。
7. 每名成员每天分配到的所有卡片工时合计必须为 8 小时；卡片 Estimate 使用总人时，而不是日历持续时间。

## Day 1：补充未记录的实际工作

Day 1 原有卡片共 35 人时。以下两张补充卡增加 5 人时，使 Day 1 达到 40 人时。只有实际完成并留下验收证据后才能进入 `Done`。

### D1-X01 建立并验证本地开发环境

- **工时：** 3 人时
- **分配：** `jxu316-arch 1h`、`LLL263 1h`、`bdfa123 1h`
- **交付物：** 三人分别完成仓库获取、依赖安装和对应模块的本地启动验证。
- **验收：** 每个人记录实际运行命令和结果；环境问题和修复方式可追溯。

### D1-X02 配置仓库和 Project 操作权限

- **工时：** 2 人时
- **分配：** `Ysoseri1224 1h`、`liyang6620 1h`
- **交付物：** 验证仓库、分支、PR、review 和 Kanban 的实际操作能力。
- **验收：** 两人能够完成各自需要的 GitHub 操作；权限缺口记录具体受阻动作。

### Day 1 工时核对

| 成员 | 原有卡片 | 补充卡片 | 合计 |
|---|---:|---:|---:|
| `Ysoseri1224` | 7h | `D1-X02 1h` | 8h |
| `liyang6620` | 7h | `D1-X02 1h` | 8h |
| `jxu316-arch` | 7h | `D1-X01 1h` | 8h |
| `LLL263` | 7h | `D1-X01 1h` | 8h |
| `bdfa123` | 7h | `D1-X01 1h` | 8h |
| **总计** | **35h** | **5h** | **40h** |

## Day 2：完成调研结论并建立项目基础

Day 2 不进行大规模前后端连接。当天结束公开资料和客户问卷数据收集，完成研究分析，同时建立 GitHub 协作、后端模型、持久化接口和页面依赖。

### D2-R01 收齐公开资料和客户问卷数据

- **工时：** 3 人时
- **分配：** `liyang6620 2h`、`bdfa123 1h`
- **Depends on：** Day 1 公开资料和客户问卷卡片
- **具体工作：** `liyang6620` 收齐行业报告、公开理赔流程和当前客户问卷回答；`bdfa123` 检查重复条目、缺失字段和无法追溯的来源。
- **验收：** 每条资料都有来源和限制；只包含客户问卷，不包含从业者问卷；Day 2 后停止无边界收集。

### D2-R02 完成业内人士访谈和访谈记录

- **工时：** 3 人时
- **分配：** `jxu316-arch 2h`、`LLL263 1h`
- **Depends on：** 已确认的访谈安排
- **具体工作：** `jxu316-arch` 完成访谈并记录原话、事实和限制；`LLL263` 整理与员工受理、人工负担和交接相关的内容。
- **验收：** 受访者原话与团队理解分开；不记录真实客户数据或公司机密；单次访谈不被写成行业普遍结论。

### D2-R03 建立完整 Evidence Sheet

- **工时：** 3 人时
- **分配：** `liyang6620 1h`、`LLL263 1h`、`bdfa123 1h`
- **Depends on：** `D2-R01`、`D2-R02`
- **具体工作：** `liyang6620` 核对公开资料；`LLL263` 按理赔前、中、后分类；`bdfa123` 统一字段并建立来源引用。
- **验收：** 每条证据有原始内容、来源、阶段、团队理解、证据强度和限制。

### D2-R04 分析客户问卷数据

- **工时：** 3 人时
- **分配：** `liyang6620 1h`、`LLL263 1h`、`bdfa123 1h`
- **Depends on：** `D2-R01`、`D2-R03`
- **具体工作：** `liyang6620` 核对有效回答；`LLL263` 提炼用户目标和困难；`bdfa123` 统计重复回答、缺失回答和冲突回答。
- **验收：** 不根据少量样本计算没有意义的总体比例；样本限制明确写入结论。

### D2-R05 形成 Pain Point、User Need 和研究总结

- **工时：** 3 人时
- **分配：** `jxu316-arch 1h`、`LLL263 2h`
- **Depends on：** `D2-R03`、`D2-R04`
- **具体工作：** `LLL263` 完成用户旅程、主要 Pain Point、User Need 和临时 Persona；`jxu316-arch` 补充访谈中的人工处理和交接问题。
- **验收：** 清晰呈现“证据 -> 痛点 -> 用户类型 -> 设计机会”；单一证据和临时 Persona 明确标记。

### D2-I01 建立 GitHub 和 Kanban 协作方式

- **工时：** 4 人时
- **分配：** `Ysoseri1224 3h`、`liyang6620 1h`
- **Depends on：** Day 1 开发约定和当前 Kanban
- **具体工作：** `Ysoseri1224` 整理分支、PR、review、Kanban 状态和依赖规则；`liyang6620` 核对这些规则是否适用于后端和 AWS 工作。
- **验收：** 团队知道如何开分支、提交 PR、请求 review、运行基础检查、填写卡片依赖和记录验收结果。

### D2-I02 整理项目目录、运行命令和文档索引

- **工时：** 3 人时
- **分配：** `Ysoseri1224 2h`、`liyang6620 1h`
- **Depends on：** `D2-I01`
- **具体工作：** 明确客户端、员工端、后端、测试、文档和 Sprint 文件位置，整理各模块启动方式和文档入口。
- **验收：** 成员能够找到应修改的目录、运行对应模块，并知道接口或规则变化需要更新什么文档。

### D2-I03 建立后端基础模型和 API 路由

- **工时：** 4 人时
- **分配：** `liyang6620 1h`、`jxu316-arch 2h`、`bdfa123 1h`
- **Depends on：** 正式 API Contract
- **具体工作：** `liyang6620` 核对字段；`jxu316-arch` 建立 claim、session 和 form 路由；`bdfa123` 建立 fixture loader 和测试数据入口。
- **验收：** 基础请求能够创建并读取一份测试 claim；字段名称与 API Contract 一致；fixture 可以替换而不修改路由。

### D2-I04 设计 DynamoDB Schema 和持久化 Adapter

- **工时：** 3 人时
- **分配：** `jxu316-arch 1h`、`bdfa123 2h`
- **Depends on：** `D2-I03`
- **具体工作：** `jxu316-arch` 确认后端读写需求；`bdfa123` 设计 claim、session、message 和 evidence 的 DynamoDB 草案及 repository 接口。
- **验收：** Schema 草案支持按 customer、claim 和 session 查询；DynamoDB 字段不泄漏到公共 API；未知 AWS 条件明确标记。

### D2-I05 明确员工端数据和页面状态

- **工时：** 3 人时
- **分配：** `LLL263 2h`、`jxu316-arch 1h`
- **Depends on：** `D2-R05`、`D2-I03`
- **具体工作：** `LLL263` 列出 Workbench 页面、状态和员工操作；`jxu316-arch` 对应到后端返回字段和操作接口。
- **验收：** 员工端需要的数据、内部信息和客户可见更新明确分开。

### D2-I06 明确客户端、Agent 和测试依赖

- **工时：** 3 人时
- **分配：** `Ysoseri1224 2h`、`bdfa123 1h`
- **Depends on：** `D2-I03`、`D2-I04`
- **具体工作：** `Ysoseri1224` 整理客户页面状态、Agent 动作和所需 API；`bdfa123` 建立 Day 3 所需 fixture 与基础 API 测试结构。
- **验收：** Day 3 每条路径都知道需要哪些页面、接口、测试数据和可观察状态；Day 2 不要求完成前后端连接。

### D2-X01 将研究结论映射到 Prototype 修改

- **工时：** 3 人时
- **分配：** `Ysoseri1224 1h`、`liyang6620 1h`、`LLL263 1h`
- **Depends on：** `D2-R05`
- **具体工作：** `liyang6620` 检查研究依据，`LLL263` 映射客户与员工需要，`Ysoseri1224` 映射客户页面和 Agent 行为变化。
- **验收：** 每项 Prototype 修改能够引用研究结论，或明确标记为待验证假设；客户、Agent 和 Workbench 影响分开记录。

### D2-X02 补充 API 和 DynamoDB 示例数据

- **工时：** 2 人时
- **分配：** `jxu316-arch 1h`、`bdfa123 1h`
- **Depends on：** `D2-I03`、`D2-I04`
- **具体工作：** `jxu316-arch` 提供符合 API Contract 的示例记录，`bdfa123` 将其映射为 repository 和 DynamoDB 示例。
- **验收：** Claim、session、message、form 和 evidence 示例同时符合 API Contract 与规划的 DynamoDB 查询方式；公共 payload 不暴露 DynamoDB key。

### Day 2 工时核对

| 成员 | 分配 | 合计 |
|---|---|---:|
| `Ysoseri1224` | `D2-I01 3h + D2-I02 2h + D2-I06 2h + D2-X01 1h` | 8h |
| `liyang6620` | `D2-R01 2h + D2-R03 1h + D2-R04 1h + D2-I01 1h + D2-I02 1h + D2-I03 1h + D2-X01 1h` | 8h |
| `jxu316-arch` | `D2-R02 2h + D2-R05 1h + D2-I03 2h + D2-I04 1h + D2-I05 1h + D2-X02 1h` | 8h |
| `LLL263` | `D2-R02 1h + D2-R03 1h + D2-R04 1h + D2-R05 2h + D2-I05 2h + D2-X01 1h` | 8h |
| `bdfa123` | `D2-R01 1h + D2-R03 1h + D2-R04 1h + D2-I03 1h + D2-I04 2h + D2-I06 1h + D2-X02 1h` | 8h |
| **总计** |  | **40h** |

## Day 3：实现完整 Prototype 路径

Day 3 进入实际连接和开发。`bdfa123` 负责边界明确的 Evidence/Session 技术模块和测试工具，不接管整个后端或全部测试。

### D3-P01 实现 Claim 和 Session 持久化 API

- **工时：** 4 人时
- **分配：** `liyang6620 2h`、`jxu316-arch 2h`
- **Depends on：** `D2-I03`、`D2-I04`
- **交付物：** 创建、读取和更新 working claim 与 session 的接口和 repository 实现。
- **验收：** 同一 claim 可以跨 session 读取；状态更新包含 revision；fixture repository 可以运行。

### D3-P02 实现 Message、Form 更新和 Agent 动作校验

- **工时：** 4 人时
- **分配：** `jxu316-arch 2h`、`liyang6620 1h`、`Ysoseri1224 1h`
- **Depends on：** `D3-P01`
- **交付物：** 用户消息写入、form field 更新、Agent action 和受控状态变化。
- **验收：** 输入会形成可检查的 message、field 和 action；高影响动作未经验证不会执行。

### D3-P03 实现客户快速和引导流程

- **工时：** 4 人时
- **分配：** `Ysoseri1224 3h`、`LLL263 1h`
- **Depends on：** `D3-P02`、`D2-I06`
- **交付物：** 事故描述、集中提问、form 展示、用户确认或纠正和下一步显示。
- **验收：** 已确认问题不会重复询问；加载和失败状态完整；页面变化来自真实 claim state。

### D3-P04 实现紧急情况和人工转交

- **工时：** 3 人时
- **分配：** `Ysoseri1224 2h`、`LLL263 1h`
- **Depends on：** `D3-P02`、`D2-I05`
- **交付物：** 人员受伤、持续危险和人工请求的 Agent 响应、handoff packet 和员工端入口。
- **验收：** 紧急情况中断普通提问；转交保留已确认事实、缺失信息、原因和需要员工完成的动作。

### D3-P05 实现 Evidence 状态、上传和 Mock Storage

- **工时：** 4 人时
- **分配：** `bdfa123 3h`、`liyang6620 1h`
- **Depends on：** `D2-I04`、`D3-P01`
- **交付物：** 待生成、非官方、不完整和图片材料的状态、上传记录及 mock storage adapter。
- **验收：** 材料状态可以保存和读取；图片字段在确认前保持 proposed；未来材料不会阻塞无关动作。

### D3-P06 实现跨 Session 恢复

- **工时：** 3 人时
- **分配：** `jxu316-arch 1h`、`bdfa123 1h`、`Ysoseri1224 1h`
- **Depends on：** `D3-P01`、`D3-P02`
- **交付物：** Session 摘要、未解决问题、待补材料和已承诺下一步。
- **验收：** 用户返回后可以继续处理，不需要重复已经确认的事故事实。

### D3-P07 实现 Workbench 列表和 Claim 详情

- **工时：** 4 人时
- **分配：** `LLL263 3h`、`jxu316-arch 1h`
- **Depends on：** `D3-P01`、`D2-I05`
- **交付物：** Workbench 队列、claim 详情、form、evidence、handoff 和内部信息展示。
- **验收：** 员工可以查看处理所需上下文；客户不可见信息不会出现在客户端响应中。

### D3-P08 实现 Staff Action 和 Signal 写回

- **工时：** 3 人时
- **分配：** `LLL263 2h`、`liyang6620 1h`
- **Depends on：** `D3-P02`、`D3-P07`
- **交付物：** 员工完成 action、处理 review signal、更新 claim state 和发送客户状态更新。
- **验收：** 员工操作保留操作者、原因和结果；signal 不会变成未经授权的欺诈结论。

### D3-P09 实现 Claim 创建、路由和 AWS Adapter

- **工时：** 3 人时
- **分配：** `liyang6620 2h`、`jxu316-arch 1h`
- **Depends on：** `D3-P01`、`D3-P02`
- **交付物：** Mock claim 创建、route 结果和可替换的 AWS/claims service adapter。
- **验收：** 返回 claim number 或明确创建状态、route、next step 和已知时间；未知 AWS schema 不写死在公共 API 中。

### D3-P10 建立场景测试工具并执行第一轮连接测试

- **工时：** 3 人时
- **分配：** `bdfa123 3h`
- **Depends on：** `D3-P03` 至 `D3-P09`
- **交付物：** 可重复加载的测试数据、API 测试工具和第一轮跨模块连接测试记录。
- **验收：** 至少覆盖客户快速流程、材料流程、session 恢复和员工写回；发现的问题分配给对应模块开发者，而不是由 `bdfa123` 单独修复。

### D3-X01 检查客户端和 Workbench 的共享状态一致性

- **工时：** 3 人时
- **分配：** `Ysoseri1224 1h`、`LLL263 1h`、`bdfa123 1h`
- **Depends on：** `D3-P03`、`D3-P05`、`D3-P07`、`D3-P08`
- **具体工作：** 使用同一 claim 检查客户页面、持久化数据和 Workbench；追踪客户操作与员工操作产生的状态变化。
- **验收：** 客户更新能够出现在 Workbench，员工更新能够产生正确的客户可见状态，内部 signal 不会出现在客户响应中。

### D3-X02 增加 Session 和 Claim Creation 合约测试

- **工时：** 2 人时
- **分配：** `liyang6620 1h`、`jxu316-arch 1h`
- **Depends on：** `D3-P01`、`D3-P06`、`D3-P09`
- **具体工作：** 为 session 恢复、过期 revision、重复请求和 claim 创建增加自动化接口测试。
- **验收：** 同时覆盖成功与失败响应；重复请求不会重复创建 claim；过期 revision 返回 API Contract 规定的冲突。

### Day 3 工时核对

| 成员 | 分配 | 合计 |
|---|---|---:|
| `Ysoseri1224` | `D3-P02 1h + D3-P03 3h + D3-P04 2h + D3-P06 1h + D3-X01 1h` | 8h |
| `liyang6620` | `D3-P01 2h + D3-P02 1h + D3-P05 1h + D3-P08 1h + D3-P09 2h + D3-X02 1h` | 8h |
| `jxu316-arch` | `D3-P01 2h + D3-P02 2h + D3-P06 1h + D3-P07 1h + D3-P09 1h + D3-X02 1h` | 8h |
| `LLL263` | `D3-P03 1h + D3-P04 1h + D3-P07 3h + D3-P08 2h + D3-X01 1h` | 8h |
| `bdfa123` | `D3-P05 3h + D3-P06 1h + D3-P10 3h + D3-X01 1h` | 8h |
| **总计** |  | **40h** |

## Day 4：全员测试、修复和确定 Presentation

Day 4 的测试由五个人交叉完成。模块开发者先自查，再由其他成员按真实用户路径独立操作。

### D4-T01 合并并运行完整原型

- **工时：** 4 人时
- **分配：** `Ysoseri1224 1h`、`liyang6620 1h`、`jxu316-arch 1h`、`bdfa123 1h`
- **Depends on：** `D3-P01` 至 `D3-P10`
- **交付物：** 一个包含客户前端、Agent、后端、Evidence、Workbench 和测试数据的可运行版本。
- **验收：** 使用统一命令和固定测试数据运行，不需要临时修改隐藏数据。

### D4-T02 测试快速、引导和复杂事故流程

- **工时：** 4 人时
- **分配：** `Ysoseri1224 1h`、`jxu316-arch 1h`、`LLL263 1h`、`bdfa123 1h`
- **Depends on：** `D4-T01`
- **交付物：** 清晰事故、需要澄清和专业复核流程的测试记录。
- **验收：** 记录输入、系统反应、状态变化、结果和问题；员工端能看到专业复核上下文。

### D4-T03 测试紧急情况和人工请求

- **工时：** 3 人时
- **分配：** `Ysoseri1224 1h`、`LLL263 1h`、`bdfa123 1h`
- **Depends on：** `D4-T01`
- **交付物：** 伤亡、持续危险和用户请求人工的测试记录。
- **验收：** 紧急情况中断普通流程；handoff 保留上下文；系统不会假装联系了紧急服务。

### D4-T04 测试材料、图片和跨 Session 恢复

- **工时：** 4 人时
- **分配：** `Ysoseri1224 1h`、`liyang6620 1h`、`LLL263 1h`、`bdfa123 1h`
- **Depends on：** `D4-T01`
- **交付物：** 待生成材料、图片确认、后续补交和恢复 claim 的测试记录。
- **验收：** 材料不会错误阻塞流程；图片信息确认前不是正式事实；恢复后不重复提问。

### D4-T05 测试历史 Signal、Claim 创建、Assessor 和 Workbench

- **工时：** 4 人时
- **分配：** `liyang6620 1h`、`jxu316-arch 1h`、`LLL263 2h`
- **Depends on：** `D4-T01`
- **交付物：** 历史信息产生 review signal、claim 创建、assessor 路由和员工操作写回的测试记录。
- **验收：** Signal 不会变成欺诈结论或暴露给客户；员工操作更新同一 claim state。

### D4-T06 检查桌面、移动、无障碍和异常状态

- **工时：** 3 人时
- **分配：** `Ysoseri1224 1h`、`LLL263 2h`
- **Depends on：** `D4-T01`
- **交付物：** 桌面、移动、键盘、加载、空状态、错误、禁用、上传和转交检查记录。
- **验收：** 没有严重页面重叠、不可操作控件、无提示失败或错误角色信息。

### D4-T07 检查 API、数据边界、权限和 AWS Adapter

- **工时：** 4 人时
- **分配：** `liyang6620 2h`、`jxu316-arch 2h`
- **Depends on：** `D4-T01`
- **交付物：** API Contract、状态转换、权限、错误响应、持久化和 adapter 边界检查。
- **验收：** 客户接口不暴露内部信息；重要变化可追溯；fixture 与 AWS adapter 使用同一领域接口。

### D4-T08 修复客户前端、Agent 和 Evidence 问题

- **工时：** 3 人时
- **分配：** `Ysoseri1224 1h`、`bdfa123 2h`
- **Depends on：** `D4-T02`、`D4-T03`、`D4-T04`、`D4-T06`
- **交付物：** 客户前端、Agent 行为和 Evidence 模块的阻断问题修复。
- **验收：** 每个修复都有对应问题和成功复测记录；非本模块问题退回实际开发者。

### D4-T09 修复后端、Workbench 和连接问题

- **工时：** 3 人时
- **分配：** `liyang6620 1h`、`jxu316-arch 1h`、`bdfa123 1h`
- **Depends on：** `D4-T05`、`D4-T07`、`D4-T08`
- **交付物：** 后端、Workbench 数据和模块连接问题的修复及复测。
- **验收：** 所有阻断性问题有负责人、修复结果和复测结果；无法修复的问题进入 Presentation 限制说明。

### D4-T10 确定 Day 5 演示顺序和备用方案

- **工时：** 3 人时
- **分配：** `Ysoseri1224 1h`、`liyang6620 1h`、`jxu316-arch 1h`
- **Depends on：** `D4-T08`、`D4-T09`
- **交付物：** 最终演示顺序、讲解重点、已知限制、固定测试数据、截图或录屏备用方案。
- **验收：** Day 5 只演示已经通过测试的功能；现场失败时有不依赖临时修复的备用材料。

### D4-X01 保存已经通过测试的演示证据

- **工时：** 3 人时
- **分配：** `Ysoseri1224 1h`、`LLL263 1h`、`bdfa123 1h`
- **Depends on：** `D4-T08`、`D4-T09`
- **具体工作：** `Ysoseri1224` 保存客户和 Agent 行为，`LLL263` 保存员工处理流程，`bdfa123` 记录对应 fixture 和结果引用。
- **验收：** 截图或短录屏来自通过测试的候选版本，能够对应固定测试数据和预期结果，不错误暴露个人数据或内部 signal。

### D4-X02 实现并验证演示环境重置脚本

- **工时：** 2 人时
- **分配：** `liyang6620 1h`、`jxu316-arch 1h`
- **Depends on：** `D4-T09`
- **具体工作：** `liyang6620` 实现 claim、session、evidence、handoff 和 mock service 的 fixture reset，`jxu316-arch` 验证服务状态和重复执行结果。
- **验收：** 连续执行两次演示能够得到相同起始状态；重置失败有明确提示；脚本不会删除 Prototype fixture 范围以外的数据。

### Day 4 工时核对

| 成员 | 分配 | 合计 |
|---|---|---:|
| `Ysoseri1224` | `D4-T01 1h + D4-T02 1h + D4-T03 1h + D4-T04 1h + D4-T06 1h + D4-T08 1h + D4-T10 1h + D4-X01 1h` | 8h |
| `liyang6620` | `D4-T01 1h + D4-T04 1h + D4-T05 1h + D4-T07 2h + D4-T09 1h + D4-T10 1h + D4-X02 1h` | 8h |
| `jxu316-arch` | `D4-T01 1h + D4-T02 1h + D4-T05 1h + D4-T07 2h + D4-T09 1h + D4-T10 1h + D4-X02 1h` | 8h |
| `LLL263` | `D4-T02 1h + D4-T03 1h + D4-T04 1h + D4-T05 2h + D4-T06 2h + D4-X01 1h` | 8h |
| `bdfa123` | `D4-T01 1h + D4-T02 1h + D4-T03 1h + D4-T04 1h + D4-T08 2h + D4-T09 1h + D4-X01 1h` | 8h |
| **总计** |  | **40h** |

## 按成员查看 Day 2 至 Day 4 的主要工作

本节是个人工作概览。具体工时、依赖、交付物和验收仍以各张卡片为准。

### Ysoseri1224

- **Day 2：** 负责建立 GitHub 和 Kanban 协作方式，整理项目目录、运行命令和文档入口；明确客户页面、Agent 动作、API 数据和测试 fixture 之间的依赖，并把研究支持的结论映射为 Prototype 修改。
- **Day 3：** 负责客户输入到结构化 form 的主要交互，实现快速、引导、紧急、人工转交和跨 session 恢复体验；与后端成员确认 Agent action，并检查客户页面与 Workbench 是否读取同一状态。
- **Day 4：** 参与完整原型合并和主要客户路径测试，检查双端适配和异常状态，修复客户前端或 Agent 阻断问题；确定 Day 5 产品演示顺序并保存通过测试的客户和 Agent 演示证据。

### liyang6620

- **Day 2：** 收齐行业公开资料和客户问卷数据，参与 Evidence Sheet 与问卷分析；与 `Ysoseri1224` 建立 GitHub 工作方式，核对后端字段和 API 基础模型，并检查研究结论到 Prototype 修改的映射。
- **Day 3：** 负责 claim/session 持久化、message/form 状态校验、Evidence adapter 边界、staff action 写回，以及 claim 创建、route 和 AWS adapter；补充 session、重复请求和 claim 创建合约测试。
- **Day 4：** 参与完整原型合并，检查材料、session、历史 signal、claim 创建和 assessor 流程；检查 API、权限、数据边界和 AWS adapter，修复后端问题，准备技术演示并实现演示数据重置。

### jxu316-arch

- **Day 2：** 完成业内人士访谈并提炼人工受理和交接观察；实现 claim、session 和 form 基础路由，提供 DynamoDB 读写需求，把员工端需求映射到后端接口，并补充 API 与 DynamoDB 示例数据。
- **Day 3：** 共同实现 claim/session API、message/form 更新、Agent action 校验和 session 恢复；为 Workbench 提供 claim 详情接口，处理 claim 创建和 route 返回，并补充关键合约测试。
- **Day 4：** 参与完整原型合并和复杂流程测试，检查历史 signal、claim 创建、Workbench 写回、API、权限和错误响应；修复后端连接问题，确认技术演示并验证演示环境重置结果。

### LLL263

- **Day 2：** 参与业内人士访谈整理、Evidence Sheet 分类和客户问卷分析；负责用户旅程、Pain Point、User Need 和临时 Persona，定义 Workbench 信息和员工操作，并把研究支持的需求映射到页面修改。
- **Day 3：** 独立检查客户快速流程的表达和交接准备，定义紧急 handoff 信息；主要实现 Workbench、staff action、review signal 和客户状态更新，并检查客户与员工端共享状态一致性。
- **Day 4：** 从员工和用户角度交叉测试快速、紧急、材料、历史 signal、claim 创建和 Workbench；检查员工端双端适配、键盘和错误状态，并保存通过测试的员工流程演示证据。

### bdfa123

- **Day 2：** 参与公开资料收口、Evidence Sheet 和问卷分析；技术侧负责 fixture loader、DynamoDB schema 与 persistence adapter 草案、API/DynamoDB 示例数据，以及 Day 3 测试 fixture 和基础 API 测试结构。
- **Day 3：** 主要实现 Evidence 状态、上传记录和 mock storage adapter，参与跨 session 恢复；建立可重复测试工具，执行第一轮连接测试，并检查客户端、持久化和 Workbench 的共享状态。
- **Day 4：** 参与完整原型合并，独立测试清晰、复杂、紧急、人工、材料、图片和 session 恢复；修复 Evidence、fixture 和连接问题，重新执行测试，并记录演示证据所使用的 fixture 和结果。

## Day 5：Presentation

Day 5 保留已经确定的 Presentation 卡片。每人安排 8 小时，总计 40 人时；具体内容和人员安排由 `D4-T10` 根据测试结果决定。

Presentation 完成后如果仍有时间，可以继续：

- 修复不影响演示但仍需处理的问题；
- 更新 API、测试记录和项目文档；
- 整理最终截图、录屏和导师反馈；
- 把未完成工作转入下一 Sprint 的 Backlog。

当前不提前拆分 Day 5 卡片。

## 主要依赖关系

```text
Day 1 已完成
  ├──> Day 2 公开资料、客户问卷和访谈收口
  │       └──> Evidence Sheet 和数据分析
  │               └──> Pain Point、用户旅程和设计机会
  └──> Day 2 GitHub、后端模型、DynamoDB 草案和页面依赖
          └──> Day 3 全路径开发与连接测试
                  └──> Day 4 全员交叉测试
                          ├──> 前端、Agent 和 Evidence 修复
                          ├──> 后端、Workbench 和连接修复
                          └──> 确定 Day 5 演示内容
                                  └──> Day 5 Presentation
```
