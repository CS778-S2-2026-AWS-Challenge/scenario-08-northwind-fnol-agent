# Sprint 2 第二周 Kanban 任务草案（中文）

## 说明

本文件保留中文计划和创建结果。对应英文卡片已创建到 GitHub Project 12。

- **周期：** 2026 年 8 月 24 日至 28 日
- **目标：** 证明“可信、自适应的理赔入口”可以在当前 MVP 中重复运行，并开始呈现基于统一 Claim Context 的理赔协同能力
- **容量：** 5 人 × 5 天 × 8 小时 = 200 人时
- **工时规则：** 单张卡 2–5 人时；每人每天卡片工时合计 8 小时
- **语言规则：** 本草案用中文；确认后写入 GitHub 的卡片使用英文
- **现有任务：** #204、#208–#215、#224 作为较大的关联 Issue 保留；本周只创建可在 2–5 人时内验收的实施切片并引用对应 Issue。#228、#229 已完成实现和验证，只等待现有 PR 的 review/merge，不计入 Week 4 开发容量。

## Kanban 创建结果

- **标签：** `Sprint 2`、`sprint2-week4`
- **Day 1：** #233–#242，共 10 张，`Ready`，40 人时
- **Day 2：** #243–#252，共 10 张，`Backlog`，40 人时
- **Day 3：** #253–#262，共 10 张，`Backlog`，40 人时
- **Day 4：** #263–#272，共 10 张，`Backlog`，40 人时
- **Day 5：** #273–#283，共 11 张，`Backlog`，40 人时
- **合计：** 51 张卡、200 人时；每人每天 8 人时

## 两个 Key Features 在本周的范围

1. **可信、自适应的理赔入口：** 用户自然描述事故，Agent 在内部维护受控的动态信息表，查询知识和结构化数据，推进下一安全步骤，必要时带着上下文转交人工。
2. **基于统一 Claim Context 的理赔协同层：** 客户、Agent、员工和首批第三方服务围绕同一 claim 状态沟通和行动，减少重复说明与自行协调。

第二项不是等第一项全部完成后才开始。本周先实现有限但真实的连接方式和呈现方式。

## 栈级责任

| 成员 | 主要负责栈 | 栈内范围 |
| --- | --- | --- |
| `Ysoseri1224` | Agent Runtime + Claimant Experience | Agent 行为、意图分发、提示词、模型接口、工具调用、动态信息表、客户对话和客户页面 |
| `liyang6620` | Data Platform + Knowledge/RAG + Cloud Integration | RAG、结构化业务数据、MinIO/S3、boto3、Cloudflare/MongoDB/AWS runtime profile 和部署配置 |
| `jxu316-arch` | Backend Domain + Persistence + Identity | Claim State、session、消息、handoff、revision、repository、Admin API、鉴权和审计 |
| `LLL263` | Staff Operations + Control Plane Frontend | Staff workbench、员工聊天、`@Agent` 协作、人工处理、客户回写和 Control Plane 前端 |
| `bdfa123` | Evidence + External Service Integration | 图片/PDF 证据处理、第三方服务 adapter、外部服务状态、模拟业务数据、canonical scenarios 和集成测试工具 |

这些是主要责任边界，不禁止跨栈合作。跨栈能力按以下方式共同完成：

- **Control Plane：** `LLL263` 负责前端，`jxu316-arch` 负责 Admin API；每个栈负责人提供本模块的配置规则和运行状态。
- **鉴权：** `jxu316-arch` 负责统一身份、权限和开发者模式；`Ysoseri1224`、`LLL263` 分别接入客户端和员工端，Control Plane 使用 admin 权限。
- **真实聊天：** `jxu316-arch` 负责消息、可见性和状态；`Ysoseri1224` 负责客户侧，`LLL263` 负责员工侧。
- **RAG：** `liyang6620` 提供导入和检索服务；`Ysoseri1224` 负责 Agent 何时调用以及如何使用结果。
- **第三方服务：** `bdfa123` 负责 adapter 和服务状态；`Ysoseri1224` 负责客户侧呈现，`LLL263` 负责员工侧处理。
- **测试：** 每个人负责本栈基础测试，Day 4 由其他成员交叉验证；`bdfa123` 维护公共 fixtures，但不是唯一测试负责人。

## 各层级与模块的整体目标

### MVP 总目标

本周不是泛泛地“接入所有系统”，而是证明可信理赔协同入口可以重复运行。最终 MVP
需要让客户自然报案，让 Agent 真实参与对话并记录 claim，在需要人工时把结构化上下文
交给员工，并让员工继续与客户沟通。尚未开放、部分可用或仍依赖 fixture 的能力必须
如实说明，不能描述为已经达到生产条件。

### 漂移处理

以 `project_soul.md`、`agent-runtime-policy.md`、`data-architecture.md`、
`fnol-field-model.md`、`registry_design.md` 和 `api.md` 为当前基线。清理或修改与这些
文档冲突的旧实现、旧测试和旧 card 描述，不从历史 Day 3–Day 5 记录反向定义当前产品。

### Agent 行为层

- 明确 Agent 的完整行为体系，包括普通对话、模式、显式命令、meta-command、意图识别与分发、RAG/数据库调用、人工转交和失败处理。
- 调研成熟 Agent 的行为设计，精细度参考 Codex 和 Claude Code，但把能力转换到 FNOL 场景，不照搬开发工具的交互方式。
- 使用通用大模型和提示词工程完成首版真实 Agent，不把模型训练或微调列为本周完成目标。
- 模型接口支持官方 API、中转、自定义和本地 endpoint；本周验证结构化输出、超时、错误和权限边界。
- 动态信息表只使用已注册字段、标签和规则，先覆盖有限的 motor、home 和 contents 分支；模型不能发明 schema 或高影响结论。

### 数据层

- 使用已经收集的资料完成首版 RAG，包括文档版本、解析、切分、过滤、索引、引用和无结果处理。
- RAG 只负责知识检索；policy、claim history、coverage 和 fraud signal 使用结构化查询与人工权限边界。
- 在 FastAPI 中接入 boto3，并将 endpoint 指向 MinIO，先跑通 S3-compatible 代码路径；以后获得 AWS access 时只替换环境变量和 credential，不修改业务逻辑。
- Cloudflare、MongoDB 和 AWS 是三套互斥的数据运行配置。分别验证共同契约、实际连通性和明确失败行为，不在同一进程中混用 provider。
- 所有 provider、endpoint 和 credential 通过环境变量装配，使后端可以临时部署到常见云服务器。
- 按现有字段约定建立一份模拟真实业务的结构化数据，覆盖 customer、claim、policy、history、evidence、handoff 和消息之间的关系。

### Journey

- 把动态 form、Claim State、session、handoff、staff workbench、evidence 和消息接到同一份持续更新的 claim 状态。
- 跑通“用户报案 → 与真实 Agent 对话 → Agent 记录 claim → 转交人工 → 员工接管 → 员工与客户继续聊天”的完整旅程。
- 员工可以在聊天中 `@Agent` 获取建议，但建议不能自动成为员工决定或直接发送给客户。
- 员工接手时先看到结构化摘要、来源、缺口和待决定事项，不需要先重读完整聊天记录。
- 设计并实现客户侧第一批第三方服务的接口和呈现方式，使服务只在适用下一步出现，并说明授权、共享数据、处理方和状态。

### 管理与鉴权

- Control Plane 完成具有可交付前端和真实逻辑的初版，而不是静态管理页面。
- 首版覆盖知识、模型、数据 profile、Agent 配置和第三方服务接口管理，并能展示配置版本和发布状态。
- Customer、Staff Workbench 和 Control Plane 分别接入 claimant、staff 和 admin 权限。
- MVP 提供显式开发者模式用于跳过交互式登录，但必须标记 synthetic principal，并且不能成为生产环境的鉴权旁路。

### Validation、Fixtures 与 Presentation

- 使用最新 canonical scenarios 验证，不继续引用已经修复或过时的 Day 4 缺陷作为当前事实。
- 保留证据来源、fixture 绑定、Claimant/Staff 可见性、权限、revision 和失败后状态保留检查。
- Day 4 由不同栈成员交叉运行完整旅程并登记问题；测试不能只交给 `bdfa123`。
- Day 5 修复阻塞 MVP 的问题，并将能力分为已验证、部分可用、未开放和依赖 fixture 四类。
- 根据官方安排准备周五 Presentation；五个人各投入 1 小时完成内容分配、计时排练和演示失败时的替代方案。

## Day 1：处理漂移，确定本周可实现边界

| # | 任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 梳理 Agent 的模式、命令和行为 | `Ysoseri1224 4h` | project soul、Agent Runtime Policy | Agent 行为清单：普通对话、显式命令、意图分发、RAG/数据库调用、人工转交和失败处理 | 每类行为都有触发方式、输入、输出、允许动作和禁止动作；不照搬 Codex/Claude Code 的开发工具语境 |
| 2 | 收窄并确认通用模型接口任务（沿用 #204） | `Ysoseri1224 4h` | 当前 Agent controller | 官方 API、中转、自定义和本地接口的共同请求、响应、错误和权限边界 | 本周只承诺接口、真实调用和失败处理，不把训练或微调列为完成目标 |
| 3 | 核对三套数据配置和 MongoDB 任务（沿用 #224） | `liyang6620 4h` | Data Architecture、当前 adapters | Cloudflare、MongoDB、AWS 的能力清单、环境变量和明确失败条件 | 三套配置互斥；每套缺少什么可直接查明，不会静默混用 provider |
| 4 | 建立 boto3 与 MinIO 的实现边界 | `liyang6620 4h` | Evidence/Object Store port | S3-compatible 配置、bucket/object 操作和错误约定 | FastAPI 通过 boto3 调用 MinIO endpoint；以后切换 AWS S3 不修改业务逻辑 |
| 5 | 明确 Claim State、session、handoff 和消息的共同状态边界 | `jxu316-arch 4h` | Data Architecture、API contract、当前 repositories | 共享 ID、revision、ownership、可见性和事务边界 | 四类记录的唯一事实来源和更新顺序明确；任何失败都不会留下互相矛盾的状态 |
| 6 | 明确 claimant、staff、admin 鉴权和开发者模式边界 | `jxu316-arch 4h` | API auth contract、三个客户端入口 | 身份、角色、scope、开发者模式和审计规则 | 正常模式不能绕过鉴权；开发者模式只创建明确标记的 synthetic principal，且不能在生产配置启用 |
| 7 | 明确客户、员工和 Agent 的真实聊天旅程 | `LLL263 4h` | 当前 customer/workbench/API | 从用户报案、转人工到员工回复的页面和状态流 | 明确每条消息的发送者、可见范围、发送状态、失败状态和 Agent 建议入口 |
| 8 | 收窄 Control Plane 首版页面范围（沿用 #210） | `LLL263 4h` | #208–#215、当前前端结构 | 首版信息架构和可操作页面清单 | 首版至少能进入知识、模型、数据配置和发布状态页面；不以静态展示冒充可交付逻辑 |
| 9 | 更新 canonical scenario 与证据基线 | `bdfa123 4h` | 最新 main 的 canonical fixtures | 与本周旅程对应的 clear、pending、urgent、review、handoff 数据入口 | 每条路径引用 canonical evidence；不再复制已经修复的 Day 4 缺陷 |
| 10 | 整理 RAG 资料与首批第三方服务场景 | `bdfa123 4h` | 已收集 policy/行业资料、Key Feature 2 | 可导入资料清单，以及一个客户可见的第三方服务场景 | 资料有来源、版本和适用范围；第三方场景说明参与方、授权、输入、输出和失败状态 |

**Day 1：**每人 8h，全组 40h。

## Day 2：完成五个栈的首版实现

| # | 任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 实现 Agent 意图分发和显式命令 | `Ysoseri1224 4h` | Day 1 Agent 行为清单 | 普通输入、命令、人工请求、状态查询和未知意图的分发器 | 同一输入只进入一个明确处理入口；未知命令不会执行隐藏动作 |
| 2 | 接入一个真实通用大模型并建立提示词基线 | `Ysoseri1224 4h` | #204 共同接口、可用 API | 真实模型调用、结构化输出、基础提示词和安全 fallback | 用户可获得真实模型回复；无效输出、超时或拒绝不会破坏 Claim State |
| 3 | 通过 boto3 跑通 MinIO 对象存储 | `liyang6620 4h` | Day 1 S3-compatible 边界 | 上传、读取 metadata、删除/失败处理和健康检查 | synthetic 文件可通过 FastAPI 保存和读取；endpoint 与 credential 只来自环境变量 |
| 4 | 建立首版 RAG 导入流程 | `liyang6620 4h` | Day 1 资料清单 | 文档解析、切分、版本、metadata 和索引入口 | 一份已授权资料可重复导入；重复、无版本或缺来源文档被明确拒绝 |
| 5 | 实现三角色鉴权与开发者模式后端 | `jxu316-arch 4h` | API auth contract | claimant、staff、admin 身份边界和显式开发者模式 | 正常模式拒绝越权；开发者模式可跳过登录但仍生成明确的 synthetic principal 标记 |
| 6 | 建立客户与员工双向消息 API | `jxu316-arch 4h` | Day 1 消息旅程、Claim State | 持久化消息、可见性、revision、发送失败和重试接口 | 客户和员工能围绕同一 claim 发送消息；内部消息不会泄漏给客户 |
| 7 | 实现 Staff 聊天页面首版 | `LLL263 4h` | 双向消息 API shape | claim 对话、发送状态、失败重试和上下文摘要区域 | staff 可在详情页查看客户消息并回复，不需要切换到独立聊天数据源 |
| 8 | 实现 Control Plane 前端壳和访问边界（沿用 #210） | `LLL263 4h` | Day 1 页面范围、admin auth | 可导航的管理端、登录/开发者模式和四类配置入口 | 非 admin 无法进入；页面路由、空状态、加载和错误状态可操作 |
| 9 | 建立模拟真实业务的结构化数据 | `bdfa123 4h` | FNOL Field Model、canonical scenarios | customer、claim、policy、history、evidence、handoff 和消息关联数据 | 数据遵守现有字段约定和 visibility；多个表通过稳定 ID 关联，不靠页面硬编码 |
| 10 | 建立第三方服务 adapter fixture | `bdfa123 4h` | Day 1 第三方场景 | 请求、授权、状态、响应和失败 fixture | 第三方服务使用同一 claim context；未授权或不可用时不会伪造成功 |

**Day 2：**每人 8h，全组 40h。

## Day 3：打通真实业务旅程

| # | 任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 实现受控动态信息表的有限分支 | `Ysoseri1224 4h` | Field Registry、Day 2 Agent | motor、home、contents 和必要条件分支 | Agent 只激活已注册字段、标签和规则；每轮只询问当前安全动作所需信息 |
| 2 | 让 Agent 调用 RAG、结构化数据和人工转交工具 | `Ysoseri1224 4h` | 模型接口、RAG/数据库 API | 有范围的工具调用和统一 Agent action 输出 | RAG 只回答知识问题；policy/history 使用结构化查询；高影响判断转交员工 |
| 3 | 完成 RAG 检索、过滤、引用和无结果处理 | `liyang6620 4h` | Day 2 RAG 导入 | 带 insurer、产品、辖区、版本和有效期过滤的检索 API | 回答可追溯到文档片段；不适用、过期或无结果时明确返回限制 |
| 4 | 完成数据配置与常见云主机环境变量 | `liyang6620 4h` | #224、MinIO、runtime profiles | Cloudflare、MongoDB、AWS/MinIO 配置示例和启动检查 | 同一镜像可通过环境变量选择一套配置；缺配置时立即且清楚地失败 |
| 5 | 将 Claim State、session、handoff 和消息接为同一事务流 | `jxu316-arch 4h` | 双向消息 API、repositories | 报案、保存、转交、接管、回复和恢复的共享 revision | 任一端更新后其他端读取到同一状态；失败不会留下半完成转交 |
| 6 | 建立 Admin API 与版本化配置基础（沿用 #209） | `jxu316-arch 4h` | admin auth、Control Plane 页面约定 | 配置读取、草稿、发布状态和审计记录 API | 管理端读取真实数据；发布状态和修改者可追踪，不能直接覆盖已发布版本 |
| 7 | 完成员工聊天、`@Agent` 建议和人工决定界面 | `LLL263 4h` | staff chat、Agent tool boundary | 员工回复、`@Agent` 建议、采纳/忽略和理由记录 | Agent 建议不会自动发送给客户；员工明确决定后才形成客户可见回复 |
| 8 | 完成 Control Plane 配置页面首版 | `LLL263 4h` | #209、#210、#212 | 知识、模型、数据 profile、第三方服务的查看与编辑页面 | 至少一类配置可完成读取、修改草稿、校验和保存；其余页面明确当前状态 |
| 9 | 将 evidence、模拟业务数据和 canonical scenarios 接入旅程 | `bdfa123 4h` | Day 2 数据和 fixture | clear、pending、urgent、review、handoff 的统一加载入口 | 五类场景使用同一 domain schema；证据来源和 claimant/staff 可见性正确 |
| 10 | 实现客户侧首批第三方服务入口 | `bdfa123 4h` | 第三方 adapter fixture、customer 页面边界 | 与 claim 下一步相关的服务卡、授权、状态和失败展示 | 入口只在适用下一步出现；客户知道将共享什么、由谁处理和当前结果 |

**Day 3：**每人 8h，全组 40h。

## Day 4：跨栈验证并修复阻塞问题

| # | 任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 验证自然报案、动态信息表和真实模型路径 | `Ysoseri1224 4h` | Day 3 旅程 | clear、pending 和 correction 运行记录 | Agent 不把对话变成逐字段问卷，不重复已确认事实，能推进下一安全动作 |
| 2 | 验证 Agent 命令、工具、越权和模型失败 | `Ysoseri1224 4h` | 行为分发、模型/RAG/数据库工具 | 未知命令、提示注入、超时、无效输出和高影响动作测试 | 模型不能发明 schema 或绕过权限；失败时已接受的 claim 进度保留 |
| 3 | 验证 MinIO/S3 和 RAG 全流程 | `liyang6620 4h` | Day 3 数据能力 | 上传、导入、检索、引用、无结果和 provider 失败记录 | 对象与知识记录可追踪；RAG 不替代结构化 policy/history 判断 |
| 4 | 验证三套数据配置和临时部署能力 | `liyang6620 4h` | profile 配置和健康检查 | 三套契约检查、实际连通状态和部署记录 | 每套标明已连通、部分可用或未开放；进程不会访问未选 provider |
| 5 | 验证报案、转交、聊天、恢复和 revision 冲突 | `jxu316-arch 4h` | 共享事务流 | 完整状态变化和失败恢复测试 | 转人工携带结构化上下文；员工和客户消息不丢失、不重复、不越权 |
| 6 | 验证 claimant、staff、admin 鉴权和开发者模式 | `jxu316-arch 4h` | 三角色 auth | 跨角色访问、禁用开发者模式和审计检查 | 正常模式无法绕过鉴权；开发者模式有显式环境标记且不能用于生产配置 |
| 7 | 验证 Staff 处理和 `@Agent` 协作旅程 | `LLL263 4h` | workbench、chat、Agent suggestion | 员工接管、判断、回复和客户回写记录 | staff 不必重读全部对话；Agent 建议与员工决定清楚区分 |
| 8 | 验证 Control Plane 前端及其真实逻辑 | `LLL263 4h` | Admin API、配置页面 | 登录、读取、修改、校验、失败和审计页面记录 | 页面不是静态 mock；至少一类配置完成真实闭环，其他未完成能力不伪装可用 |
| 9 | 用最新 canonical scenarios 交叉运行全旅程 | `bdfa123 4h` | Day 4 前八项 | 五类场景结果、实际结果与预期差异 | fixture 全部绑定 canonical scenario；证据来源和两端可见性没有回归 |
| 10 | 验证第三方服务并登记跨栈问题 | `bdfa123 4h` | 第三方入口和 adapter | 成功、未授权、不可用和超时场景，以及问题负责人 | 第三方失败不阻塞 claim；所有阻塞问题有负责人、复现步骤和预期结果 |

**Day 4：**每人 8h，全组 40h。

## Day 5：稳定 MVP、记录限制并准备 Presentation

| # | 任务 | 分配 | 前置条件 | 交付物 | 验收结果 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 修复 Agent 行为和模型调用的最高优先级问题 | `Ysoseri1224 4h` | Day 4 问题记录 | Agent/模型修复和复测结果 | clear、pending、urgent、review 路径中的阻塞问题已修复或明确限制 |
| 2 | 完成客户侧 Agent 旅程和提示词基线 | `Ysoseri1224 3h` | 任务 1 | 可重复客户旅程、提示词版本和已知限制 | 用户可自然报案、纠正、继续或转人工；不把单次好回答当成稳定能力 |
| 3 | 修复数据、MinIO/S3 和 RAG 的最高优先级问题 | `liyang6620 4h` | Day 4 问题记录 | 数据与检索修复、复测结果 | 当前可用配置可重复运行；失败不会产生无来源回答或丢失对象状态 |
| 4 | 记录三套配置和云端运行的真实能力 | `liyang6620 3h` | 任务 3 | 配置、连通性、限制和切换说明 | 明确哪些使用 MinIO、MongoDB、Cloudflare、AWS 或 fixture，不把兼容接口称为真实 AWS 接入 |
| 5 | 修复 Claim State、消息、handoff 和鉴权问题 | `jxu316-arch 4h` | Day 4 问题记录 | 后端修复与复测结果 | 同一 claim 的状态、消息和 ownership 保持一致；权限和 revision 检查有效 |
| 6 | 完成 API、状态和审计能力记录 | `jxu316-arch 3h` | 任务 5 | 当前 API、数据流和未完成项记录 | 文档与实际 endpoint 一致；未实现能力有明确边界，不引用过时 Day 4 结论 |
| 7 | 修复 Staff workbench 和 Control Plane 问题 | `LLL263 4h` | Day 4 问题记录 | 两个员工侧界面的修复和复测 | 员工可接管、聊天、使用 Agent 建议并操作至少一类真实管理配置 |
| 8 | 完成员工侧关键旅程的体验整理 | `LLL263 3h` | 任务 7 | workbench 与 Control Plane 的最终 MVP 页面状态 | 正常、空、加载、失败和无权限状态完整；员工操作不会丢失输入 |
| 9 | 固化 fixtures、第三方服务和全路径复测 | `bdfa123 4h` | Day 4 场景与问题记录 | 可重复 fixtures、第三方场景和复测结果 | 非实现者能按同一入口重复运行；fixture 与真实 provider 能力明确区分 |
| 10 | 汇总 MVP 状态和真实限制 | `bdfa123 3h` | 前九项结果 | 已验证、部分可用、未开放、依赖 fixture 四类清单 | 每项能力有证据和负责人；没有把演示效果写成生产能力 |
| 11 | 准备并排练 Sprint 2 Presentation | 全员各 `1h`，共 `5h` | 当天可演示版本和 MVP 状态清单 | 演示顺序、每人内容、计时结果和故障替代方案 | 完整演示按官方时间要求完成；每人知道自己的页面、时长和失败时如何继续 |

**Day 5：**每人 `4h + 3h + 1h Presentation = 8h`，全组 40h。

## 全周工时

| 成员 | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 | 合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `Ysoseri1224` | 8h | 8h | 8h | 8h | 8h | 40h |
| `liyang6620` | 8h | 8h | 8h | 8h | 8h | 40h |
| `jxu316-arch` | 8h | 8h | 8h | 8h | 8h | 40h |
| `LLL263` | 8h | 8h | 8h | 8h | 8h | 40h |
| `bdfa123` | 8h | 8h | 8h | 8h | 8h | 40h |
| **全组** | **40h** | **40h** | **40h** | **40h** | **40h** | **200h** |

## 关键依赖

- Agent 行为清单和模型接口是动态信息表、真实模型和工具调用的前置条件。
- MinIO/S3、RAG 导入和模拟业务数据可以并行完成，但都必须遵守 Data Architecture 的 provider-neutral 接口。
- 双向消息、共享 Claim State 和 handoff 必须先通过 API/数据层，再接客户和员工页面。
- Control Plane 前端必须读取真实 Admin API；未完成的配置类型可以显示明确状态，但不能使用只改本地页面变量的假逻辑。
- 第三方服务先使用受控 adapter fixture，但授权、共享数据、状态和失败行为必须按真实集成设计。
- Day 5 的修复范围由 Day 4 的实际问题决定；没有独立复测的任务不能进入 `Done`。

## 创建卡片前待确认

1. 是否接受上述五人责任分配。
2. Control Plane 的 #208–#215 是否从 `extra` 调整为本周正式 Sprint 2 工作，并按本草案收窄首版范围。
3. 第一个第三方服务场景具体选择哪一种；未确定前先保留通用 adapter 和授权展示任务。
4. Presentation 的官方时长和内容要求若有更新，Day 5 卡片应同步修改，但每人 1h 的准备容量保持不变。
