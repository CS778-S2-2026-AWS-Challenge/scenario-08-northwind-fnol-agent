# Sprint 3：Validation Prototype（VP）总纲

## 1. 阶段定位

- **阶段：** Sprint 3，Validation Prototype（VP）。
- **周期：** Week 5（2026 年 8 月 31 日至 9 月 4 日）和 Week 6（2026 年 9 月 7 日至 11 日）。
- **总体目标：** 在现有 MVP 基础上，把 Agent、claimant 端、staff 端、Claim Context、知识检索、数据与运行配置、Control Plane、第三方服务适配和 AWS 接入能力推进成一套可以反复运行和验证的 VP。
- **方法：** 六个栈级工作流在两周内并行推进。AWS 接入从 Week 5 起持续准备和实现，不等到第二周才开始；具体可用能力必须以实际访问、权限和接口验证为准。

## 2. 产品主张与两个 Key Feature

Northwind 的产品价值不是训练一个新的通用模型，而是构建一个能在保险 FNOL 场景中可靠工作的 Agent：它理解客户和 staff 的自然语言，结合已确认的 Claim Context、证据、保单知识和历史数据提出建议，再由运行时决定哪些建议可以被授权、执行和记录为真实业务状态。

### Key Feature 1：可信、自适应的理赔入口

Agent 用友好、主动的对话把客户的自然描述整理成可确认的结构化信息，按当前风险、缺口和用户状态选择快速推进、澄清、等待、人工接手或紧急升级。它减少客户填写固定表单的认知压力，也减少 staff 重读聊天记录和重复询问的时间。Staff 是同等重要的使用者：Agent 要提供有来源、有不确定性和待处理事项的上下文，让 staff 能追问、修正、拒绝或覆盖建议，并愿意信任和使用它。

### Key Feature 2：基于统一 Claim Context 的理赔协同层

同一份 Claim Context 连接 claimant、staff、证据、保单、历史记录、Northwind 系统和过程中需要协作的外部 stakeholder。第三方服务不是展示性的终点，而是帮助用户取得材料、采取行动和继续推进 claim 的能力。系统要识别需要哪个 stakeholder，准备必要信息，在取得授权后联系、交接或跳转，并显示处理中、完成、失败、拒绝、超时和需要补充信息等真实状态。

两项能力在 VP 中同时实现并逐步加深，不是两个先后隔离的阶段。

## 3. VP 验证范围

`motor`、`home` 和 `contents` 是三类代表性验收场景，不是产品只支持的三类险种。三条线从 Week 5 Day 1 起并行推进，每条线都要覆盖自然报案、动态信息表、证据状态、知识或历史查询、next-step-ready、claim 状态更新、人工交接和必要的第三方协作。

## 4. 六个并行工作流与栈级责任

| 工作流 | 固定责任成员 | 交付重点 |
| --- | --- | --- |
| Agent 行为与提示词 | `Ysoseri1224` | Agent 行为分层、提示词、结构化输出、工具调用、动态表单行为和 claimant 侧体验 |
| Claimant 体验 | `Ysoseri1224` | 调性、UX 优化、UI 重构、状态和隐私/共享信息展示 |
| Staff 体验与协作 | `LLL263` | Staff Workbench、队列、详情、Agent 协作和第三方服务运营状态 |
| Claim Context 与持久化 | `jxu316-arch` | 后端 domain、Claim Context、session/evidence/handoff/event 持久化、恢复和版本一致性；执行已批准的 Agent action contract |
| 知识、数据与运行配置 | `liyang6620` | RAG、结构化业务数据、Control Plane 数据定义、provider adapter 和 AWS/云端连接 |
| 第三方服务与证据处理 | `bdfa123` | evidence/material 生命周期、第三方 adapter/service 请求、结果验证、失败和重试状态 |

状态机的责任按边界分开：`Ysoseri1224` 独立负责 Agent 行为、分支条件、动作选择和 Agent 侧的状态转换规则；`jxu316-arch` 根据已批准的 action contract 负责后端状态、持久化、revision 和事件实现。两人只在 action contract 和字段映射处协作，`jxu316-arch` 不定义 Agent 应选择什么行为。`jxu316-arch` 负责第三方 stakeholder 的能力、请求/响应和服务状态契约；`Ysoseri1224` 再决定 Agent 何时提出使用这些能力。`liyang6620` 负责 Control Plane 应管理的配置和数据模型，`Ysoseri1224` 负责其 claimant 侧相关展示，`LLL263` 负责 staff 侧操作展示。

## 5. 固定工程与协作决策

- 不训练或微调模型；重点是 Agent 行为、提示词、结构化输出、工具边界和运行时判断。
- 模型负责理解、整理和提出建议；运行时负责检查权限、执行动作、写入状态、记录事件，并决定建议是否能改变真实业务状态。
- Dynamic Form 根据已确认事实、未完成事项、证据状态和当前动作持续重建，只能使用已注册字段、标签和分支规则；它不是一份预先固定的问题清单。
- Claim lifecycle、Dynamic Form、Evidence、Third-party task、Handoff、Session/Resume 是相互关联的子状态机。每个转换要说明触发条件、Agent 行为、两端表现、后端和数据写入、权限/consent、允许的下一状态，以及失败、重试、重复请求和未知结果处理。
- 三类场景必须并行开发，代码和文档不能把它们写成系统边界；它们只是 VP 的代表性验证样本。
- 运行时优先真实连接可用的服务。不可用的服务必须显示明确的 unavailable/error 状态，不得用 fixture 把未验证的能力伪装成成功；fixtures 只用于测试、回归和离线验证。
- MongoDB、Cloudflare 和 AWS 是互斥的运行配置；同一条 adapter 契约适配三种 provider，但一次运行只启用一个 provider。
- Model Gateway 应保持通配接口，支持官方 API、中转站、自定义接口和本地接口；当前实际接入的模型是 `gpt-5.4-mini`，未验证的模型或云能力必须标为未完成。
- 第三方请求必须保留授权范围、发送字段、stakeholder、请求状态、返回来源、验证结果和失败原因；失败时保留 Claim Context，不能让客户重新开始。
- 客户端要清楚展示收集用途、保存范围、第三方共享范围、人工交接和恢复/删除信息；privacy/security 不能只依靠创建 claim 前一个 consent 复选框。
- 每人每天正常 Kanban 工作量为 8 小时；单张 card 为 2–5 小时，超过 5 小时必须拆分。测试和验收由全员参与，不能只交给一人。

## 6. Week 5 与 Week 6 的高层安排

### Week 5：完成可运行的功能基线

五个栈同时在 `motor`、`home`、`contents` 三条线上实现关键功能：Agent 与动态表单、双端状态展示、Claim Context 与持久化、知识/数据查询、Control Plane 配置、真实第三方连接和失败状态。完成一轮从客户报案到 claim 推进或人工交接的可重复运行路径，并记录未完成能力。

### Week 6：加深、集成与 VP 验证

继续并行完善六个栈，接入已获确认的 AWS 能力，完成跨栈状态一致性、第三方协作、隐私边界、Agent 行为调优和重复验证。最终准备可重复的 VP 演示、验收证据和能力限制说明；不把无法验证的 AWS 数据、接口或生产能力写成已完成结果。

## 7. VP 完成标准

- 三条代表性场景均可重复运行，且运行时不依赖隐藏跳转或人工改数据库。
- Agent 能依据用户表达、Claim State 和证据状态选择正确行为；高风险或紧急情况不会被普通收集流程阻塞。
- Dynamic Form 只产生已注册字段，字段来源、状态和确认结果可追溯。
- RAG、policy、claim history 和结构化查询用途分明，有来源；无结果、超时或数据不可用时明确失败。
- claimant、staff 和 Agent 围绕同一份 Claim Context 工作；handoff 后 staff 不需要重复收集已有信息。
- Control Plane 能管理或展示 MVP 所需的配置、provider、版本和状态。
- 可用的第三方服务真实反映请求、处理中、完成和失败；不可用服务明确显示限制并保留上下文。
- 已完成、部分完成、fixture-only、unavailable 和待确认能力都有证据支持。

## 8. Week 5 额外工时

以下任务属于 Week 5 必要工作，计入成员额外投入，但不计入每天正常 8 小时：

- `#363`：`Ysoseri1224`，8 小时。
- `#364`：`Ysoseri1224`，1 小时。
