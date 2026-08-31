# Sprint 3 Week 5 计划：Validation Prototype 功能基线

## 1. 本周目标

Week 5（2026 年 8 月 31 日至 9 月 4 日）以功能实现为中心，在现有 MVP 上并行推进 `motor`、`home`、`contents` 三条代表性验证线。周末前应得到一套可以重复运行的 VP 基线：客户可以自然报案，Agent 可以根据状态选择行为并维护动态表单，staff 可以接手并继续处理，Claim Context 可以持久化，知识和数据查询有来源，Control Plane 有可管理的配置，第三方服务能真实连接时就真实连接并显示完整状态。

本周不训练或微调模型；重点是 Agent 行为与提示词、前后端功能、数据和 adapter、第三方协作、隐私边界以及可重复验证。fixtures 只用于测试、回归和离线验证，不作为运行时成功路径的替代品。

## 2. 栈级责任

| 成员 | 本周主要负责的栈级工作 |
|---|---|
| `Ysoseri1224` | 独立负责 Agent 行为与提示词、分支判断和动作选择；claimant 前端调性、UX 和 UI 重构；动态表单与 claimant 状态/隐私展示；负责状态机的 Agent 行为部分；额外完成 #363（8h）和 #364（1h） |
| `liyang6620` | 数据层、RAG、结构化业务数据、provider adapter 和 AWS/云端连接；定义 Control Plane 管理的数据和配置，并实现对应 API/配置入口 |
| `jxu316-arch` | 后端 domain、Claim Context、session/evidence/handoff 持久化与恢复；消费已批准的 Agent action contract，实现后端状态、revision 和事件；定义第三方 stakeholder 能力与服务契约；负责状态机的后端执行部分 |
| `LLL263` | Staff Workbench、队列、详情、staff 与 Agent 协作；展示和处理第三方服务状态；让 staff 能基于结构化上下文继续工作 |
| `bdfa123` | evidence/material 生命周期；第三方 adapter/service 的请求准备、状态更新、结果验证、失败和重试；不能只承担测试或杂务 |

五人均参与跨栈检查和验收，但每个功能的主要实现责任保持在对应栈负责人。后续 Kanban card 按功能目标拆分，每张 2–5 小时；每天每人正常任务合计 8 小时。

## 3. 状态机交付边界

本周交付一份可执行的统一状态模型，至少包括 Claim lifecycle、Dynamic Form、Evidence、Third-party task、Handoff、Session/Resume 六个相互关联的子状态机。两位成员协作完成同一份模型，但工作边界严格分开：

- `Ysoseri1224` 独立定义 Agent 侧的触发条件、分支判断、动作选择、提示词/工具调用和拒绝条件；
- `jxu316-arch` 根据已批准的 action contract 定义后端状态、command handler、持久化、revision 和事件记录；
- 两人共同确认字段映射和接口能否承接这些结果，但 `jxu316-arch` 不决定 Agent 应选择什么行为；
- `jxu316-arch` 定义第三方 stakeholder 的能力、请求/响应字段和服务状态，`Ysoseri1224` 定义 Agent 在什么条件下提出使用这些能力。

每个状态转换都要说明：

- 触发条件和允许的前置状态；
- Agent 的判断、动作、提示词/工具调用和拒绝条件；
- claimant 页面显示和可执行操作；
- staff Workbench 显示和可执行操作；
- 后端状态、revision 和事件写入；
- 数据层保存内容、来源、权限和 consent；
- 成功、失败、超时、重试、重复请求和未知结果的处理；
- 可以进入的下一状态。

这份状态模型必须同时适用于三条 VP 验证线，不得为每个险种复制一套互相冲突的状态。

## 4. 五天推进安排

### Day 1：让五个栈和三条线有可运行的共同基线

- `Ysoseri1224`：确定三条线共用的 Agent 输入/输出和动作结构；开始 claimant 对话、确认、纠正和动态表单 UI 重构。
- `liyang6620`：确定 RAG、结构化业务数据和 provider adapter 的实际边界；列出 Control Plane 必须管理的配置、版本和运行状态；检查当前可用的云端/AWS访问。
- `jxu316-arch`：整理 Claim Context、session、evidence、handoff、event 的后端状态和持久化接口；根据 action contract 建立后端状态机骨架。
- `LLL263`：建立 staff Workbench 的状态投影、队列和详情页结构；明确 staff 需要看到的 claimant、Agent、证据和第三方状态。
- `bdfa123`：把 evidence/material 状态和第三方请求状态落实为可调用的服务接口；区分真实可用服务、不可用服务和仅测试用 fixture。

**当日结果：** 三条线都有相同的 Claim Context、字段、状态和 API 入口；每个栈知道可以调用的接口及明确的未完成项。

### Day 2：实现动态表单、状态持久化和 Control Plane 的第一批功能

- `Ysoseri1224`：实现根据已确认事实、缺失事项和当前动作更新动态表单；加入客户可见的隐私、共享范围和第三方状态提示。
- `liyang6620`：实现 RAG/结构化查询的最小可用接口和来源返回；实现 provider 选择、连接状态和 Control Plane 配置数据的首版 API。
- `jxu316-arch`：实现 claim/session/context/revision 的保存、读取和恢复；支持三条线共用的 evidence、handoff 和 next action 状态。
- `LLL263`：实现 staff 队列、claim 详情、结构化上下文和状态筛选；展示 staff 可处理的第三方请求和待补信息。
- `bdfa123`：实现第三方请求的准备、授权范围、发送、处理中、结果和失败状态；实现 evidence 与请求结果的关联和验证记录。

**当日结果：** 一次客户输入可以进入动态表单、Claim Context、知识/数据查询和 staff 视图；第三方请求不会只返回固定成功。

### Day 3：让 Agent 行为和第三方协作推动真实业务下一步

- `Ysoseri1224`：调优快速、引导、复杂、紧急、人工请求和待补材料等行为；让 Agent 通过 RAG/数据库工具取得依据并提出结构化动作建议。
- `liyang6620`：完成数据 adapter、RAG 检索、结构化历史查询和 Model Gateway/运行配置的连接路径；对不可用 provider 返回清晰错误。
- `jxu316-arch`：完成 handoff、resume、evidence 和第三方任务的后端转换及事件记录；消费已批准的 action contract，写入统一 revision，避免多端覆盖。
- `LLL263`：完成 staff 接手、查看上下文、追问、确认/拒绝建议和写回状态的操作；显示第三方请求的责任方和当前结果。
- `bdfa123`：连接可用的真实第三方接口；对无法连接的服务实现明确 unavailable/error 状态、重试和保留上下文；完善材料结果验证。

**当日结果：** 三条线都能从用户表达进入 Agent 判断，再进入一个可解释的下一安全动作或人工/第三方协作动作。

### Day 4：并行完成三条端到端功能路径并处理失败状态

- `Ysoseri1224`：打通 claimant 对话、动态表单、确认/纠正、隐私提示、第三方状态和 Agent 动作展示。
- `liyang6620`：打通 API、RAG/结构化查询、provider adapter、Control Plane 配置和已验证云端能力；记录真实连接限制。
- `jxu316-arch`：打通 Claim Context、session resume、evidence、handoff 和事件记录；检查并发更新和重复请求。
- `LLL263`：打通 staff queue、详情、Agent 协作、第三方处理和 claimant 状态更新；确保 internal signal 不泄漏到客户端。
- `bdfa123`：打通 evidence 与第三方请求/结果/失败处理；检查所有三条线使用相同的状态和来源规则。

**当日结果：** `motor`、`home`、`contents` 都能运行一次完整的客户侧和 staff 侧路径；成功、失败、等待、拒绝和未知结果都有可观察表现。

### Day 5：重复验证、修复高影响问题并准备 Week 6 输入

- `Ysoseri1224`：根据三条线的实际运行结果修复 Agent 行为和 claimant UX；确认动态表单只使用注册字段，补充 #363（8h）和 #364（1h）额外工作。
- `liyang6620`：验证数据来源、RAG 引用、adapter 切换和 Control Plane 配置；列出 AWS/云端下一步可直接实施的连接项。
- `jxu316-arch`：验证恢复、版本、handoff 和事件链路；修复会导致 claim 状态丢失或重复写入的问题，并检查后端是否正确执行 action contract。
- `LLL263`：从 staff 角度重复处理三条路径；修复上下文不完整、状态不清楚、操作无法继续或 customer projection 错误的问题。
- `bdfa123`：独立检查材料、第三方结果和失败状态；复现并修复请求重复、结果未验证、来源丢失或 internal 数据泄漏问题。

**当日结果：** 得到一套可重复运行的 VP Week 5 基线、问题与限制清单、Week 6 可直接继续的接口和数据输入。三条线仍按代表性场景描述，不把 VP 样本误写成产品范围限制。

## 5. 工时与额外任务

### 正常工时

- 每人每天 8 小时；五人每天合计 40 小时；Week 5 正常合计 200 人时。
- 上述每日安排用于确定推进方向，后续创建 Kanban card 时按可验收功能拆成 2–5 小时的小任务。

### 额外工时（不计入每日 8 小时）

- `#363`：`Ysoseri1224`，8 小时。
- `#364`：`Ysoseri1224`，1 小时。

## 6. 本周验收依据

- 三条代表性路径均能重复运行，不依赖运行时 fixture 成功伪装。
- Agent、动态表单、Claim Context、知识/数据查询、Control Plane、第三方状态和双端界面之间的状态一致。
- 可用的真实服务被真实调用；不可用服务明确显示限制并保留上下文。
- 每个关键字段、建议、第三方请求和状态变化都能追溯来源、权限、责任方和时间。
- staff 接手后可以直接继续处理，客户不会重复提交已经确认的信息。
- 所有未完成能力和外部依赖都有明确记录，作为 Week 6 的输入，而不是被写成已完成能力。
