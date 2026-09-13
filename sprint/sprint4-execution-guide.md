# Sprint 4 执行指导

本文同时面向 contributor 和 contributor 使用的 coding agent。它的作用是提供一份共同的
项目上下文和思考框架，帮助每个人从完整用户旅程推导出当天值得完成的工作。它不是新的
产品需求、API 合同、逐步施工脚本，也不能替代仓库中的 `AGENT.md`、`docs/product-soul.md`、
`docs/` 或 `SPEC/` 中更高层级的权威内容。

如果本文与代码、权威文档或 maintainer 的明确决策不一致，应先指出冲突，不要自行选择
一个看似方便的解释继续实现。

## 第一节：Sprint 4 目标与拆解

### 1.1 目标原文

> 完成并验证覆盖 motor、home、contents 的完整 FNOL 用户旅程，根据 rubric expected outcome
> 收集测试数据，并根据测试结果优化系统边界。

### 1.2 这句话实际要求什么

“完成并验证完整 FNOL 用户旅程”不是把三个页面做出来，也不是让一个 prompt 在三个
fixture 上返回成功 JSON。它要求从 claimant 首次描述开始，经过事实整理、必要追问、材料
处理、policy/history 查询、第三方协作、handoff 或等待，直到 claim creation 或一个诚实的
下一安全步骤，形成可运行、可观察、可复核的路径。

“覆盖 motor、home、contents”意味着三类场景必须体现真实业务差异。Motor 不能只换一个
标题变成 home；home 不能出现没有业务依据的车辆字段；contents 不能把 item-level 的所有权、
价值和购买证据压扁成几个 motor 风格字段。三类场景可以共享 Claim Context、Runtime、
registry、权限和持久化合同，但不能共享一套未经检查的业务脚本。

“根据 rubric expected outcome 收集测试数据”意味着测试必须围绕 Scenario 8 的验收结果
设计。需要记录的不只是 pass/fail，还包括问题数量、是否需要计划外 follow-up、severity 的
盲评、fraud signal 的 precision/recall、claim number、expected timeline、最终状态、角色
可见性和完整证据链。

“根据测试结果优化系统边界”意味着 Sprint 4 不是无条件扩大功能。测试结果可能证明某项
能力应当继续自动化，也可能证明它必须停在 proposal、pending、unavailable、professional
review 或 staff decision。优化对象包括 prompt、行为规则、Runtime allow/deny、前端状态
表达、API contract 和第三方接入边界，而不是只追求更多自动成功。

### 1.3 目标拆解为四个判断

每个 issue、PR 或 Discussion 都应能回答四个问题：

1. **旅程判断：** 它改善了哪条 motor、home 或 contents 的完整路径？
2. **边界判断：** 它改变了 Agent、Runtime、staff、第三方还是 claimant 的责任边界？
3. **证据判断：** 它会留下什么可以重放、读取或比较的证据？
4. **rubric 判断：** 它如何帮助 expected outcome 的某个指标，而不是只增加代码量？

如果四个问题都回答不了，通常说明工作还停留在组件或 prompt 层，没有成为 Sprint 4
交付。

### 1.4 给 Agent 的目标理解提示词

下面这段可以直接交给 coding agent，但用户应先根据自己的任务补充场景和限制：

```text
你正在参与 Northwind FNOL 项目的 Sprint 4。请先阅读本文件、仓库中的 `docs/product-soul.md`
和与当前任务相关的仓库文档，不要立即写代码。

请用简明语言说明：
1. 你认为当前任务改善的是哪一条完整 motor/home/contents 旅程；
2. 这个任务要证明的用户结果和 Scenario 8 rubric 结果是什么；
3. Agent、Runtime、后端、前端、staff 和第三方分别负责什么；
4. 现有代码和合同已经支持什么，哪些仍未知或 unavailable；
5. 你预计留下什么可复核证据。

如果存在需要用户决定的产品语义、第三方权限、API 字段、ownership 或高影响授权，请
停下来列出问题，不要用自己的猜测替用户作决定。
```

## 第二节：项目上下文与当前 codebase

### 2.1 从前三个 Sprint 走到现在

前三个 Sprint 的结果不是三组互相独立的功能，而是逐步建立了 Northwind 的产品和工程
边界。

Sprint 1 主要确立了产品问题、用户、完整 FNOL 方向和第一批可演示的 journey framing。
要理解“为什么不是聊天机器人、为什么需要动态表单、为什么要保留人工判断”，先看：

- `docs/product-soul.md`：仓库内共享的产品权威，尤其是 two connected key features、next
  safe action、shared Claim Context 和产品 scope boundary；
- `sprint/week2/sprint1.md`：Sprint 1 的目标、原型范围和早期验收思路。

`docs/product-soul.md` 是本项目共享的产品权威，已包含产品旅程、Workbench、Control Plane、
Claim 生命周期、业务原则和待确认边界。需要产品方向判断时，先以该文件和 `SPEC/` 为准，
不要从个人工作区、旧演示或未验证的竞标材料推导新的产品合同。

Sprint 2 将产品主张转成共享数据、Claim State、Evidence、policy/history、handoff、
RAG、外部服务和前端投影等合同。要理解当前为什么不能让前端维护自己的业务状态，先看：

- `SPEC/04-claim-state-and-data.md`：Claim State 是唯一权威业务事实；
- `docs/persistence-schema.md`：Claim、Session、Message、Evidence、Retrieval、Handoff、
  WorkItem、Audit 和 Runtime record 的持久化边界；
- `docs/claim-state-transaction-boundary.md`：一次状态变化如何与消息、revision、
  idempotency 和审计保持一致；
- `docs/agent-context-contract.md`：Agent 可接收的 context、来源和角色边界；
- `docs/policy-history-mapping.md`、`docs/knowledge-source-coverage.md`：结构化 policy/history
  与 RAG 知识证据的区别；
- `docs/third-party-service-consent-and-shared-data-contract.md`：第三方共享、purpose、
  consent、recipient、visibility 和 withdrawal 的原则。

Sprint 3 进入 validation prototype，重点是把这些合同接到 claimant、staff/workbench、
Agent Runtime、外部服务和 Control Plane 的可观察路径上。要理解已经验证的路径和仍未完成
的产品验收，先看：

- `sprint/week5/sprint3-week5-plan.md`、`sprint/week6/sprint3-week6-kanban-discussion.md`：
  Sprint 3 的验证目标和跨 owner 依赖；
- `backend/demo_data/scenarios/README.md`：当前 canonical scenario record、MVP path 和
  material/record graph 的加载规则；
- `docs/status/agent-runtime-progress.md`：Agent Runtime 每项能力的状态、证据和已知限制；
- `docs/status/control-plane-progress.md`：model profile、Release Set、Runtime Snapshot、
  knowledge、integration 和配置恢复的实现状态；
- `docs/status/` 下与 external service、RAG、Workbench 和 frontend 相关的当前状态记录。

前三个 Sprint 已经让项目拥有可复用的合同和很多局部实现，但没有自动证明 Sprint 4 的
10 条产品旅程已经完成。Sprint 4 的工作是把这些局部能力组合成可量化的 vertical journey，
再根据结果决定哪些边界应扩大、收窄或明确标记为 unavailable。

### 2.2 当前 codebase 已经做到哪里

下面的描述以当前仓库和现有 status 文档为准，不把 PR 文案自动当成已合并能力。

#### `backend/domain/`

这里放置 provider-neutral 的业务合同和注册表。当前与 Sprint 4 直接相关的入口包括：

- `models.py`：Claim、Session、Message、Evidence、form、assertion、Agent provenance 等
  核心模型；
- `runtime.py`：`TurnPlan`、`AgentProposal`、`ExecutionPlan`、`ActionEnvelope`、
  `ToolResult`、`TurnResult` 和 Runtime WorkItem record；
- `branch_registry.py`、`field_registry.py`、`tag_registry.py`：motor、home、contents 的
  分支、字段和 tag 边界；
- `agent_action_registry.py`、`agent_tool_registry.py`：namespaced Action/Tool 合同、输入、
  authority、side effect、visibility、idempotency 和 failure policy；
- `workbench_action_registry.py`：staff/workbench action handler 的注册边界；
- `external_services.py`、`external_task_api.py`、`integration_registry.py`：外部服务和
  provider-neutral integration 状态；
- `audit.py`、`evidence.py`、`knowledge.py`、`handoff` 相关模型：来源、审计、证据、知识和
  handoff 的共享记录。

当前重要事实是：Agent 可以提出结构化 proposal，Runtime 才拥有验证和执行权；注册了一个
Tool 不等于它已经有真实 handler；外部能力没有真实连接时必须返回 unavailable 或
simulation-only。

#### `backend/services/`

这里连接领域合同、模型 gateway、repository 和 API。重点入口包括：

- `model_agent.py`：provider-neutral model request、structured output、tool call 和
  continuation 的 Agent 路径；
- `agent.py`：deterministic/controlled Agent proposal、行为保护和兼容路径；
- `messages.py`：claimant message turn、branch evaluation、fact mutation、Runtime record
  persistence 和 idempotency 边界；
- `branching.py`、`fact_resolution.py`：Dynamic Form、字段选择、等价重复、修正、冲突和
  provenance；
- `runtime_agent_policy.py`、`runtime_configuration.py`、`model_profiles.py`：发布的 Agent
  instruction、tool policy、controlled rules、feature settings、model profile 和 Runtime
  Snapshot；
- `staff_agent.py`、`staff_actions.py`、`workbench.py`：Staff Agent draft、确认、Workbench
  action、权限、revision、idempotency 和 staff projection；
- `external_services.py`、`integrations.py`、`runtime_integrations.py`：第三方请求、
  integration 选择、失败和 unavailable 状态；
- `claimant_form_projection.py`、`evidence_visibility.py`、`handoff_context.py`：角色安全
  投影和 handoff context。

#### `backend/api/`、`backend/repositories/` 和 `backend/demo_data/`

`backend/api/` 提供 claimant、claims、Workbench、Staff Agent、capabilities、admin 和
external task 的 HTTP 边界。`docs/api.md` 与 `docs/openapi.snapshot.json` 是检查 wire
contract 的入口，不要只从 TypeScript client 推断 API。

`backend/repositories/` 中的 `protocols.py`、`fixture.py`、`mongodb.py` 和
`scenario_loader.py` 共同定义可复位的测试/演示数据路径。Fixture repository 是重复验证
工具，不是生产能力证明。`backend/demo_data/scenarios/` 当前包含：

- `AT-01-clear-motor.json`、`AT-02-coverage-ambiguity.json`、`AT-04-urgent.json`、
  `AT-05-human-request.json`、`AT-06-pending-evidence.json`、`AT-08-resume.json`；
- `AT-10-controlled-assessor.json`、`AT-12-signal-writeback.json`、`AT-13-staff-action-lifecycle.json`；
- `AT-14-field-states-motor.json`、`AT-15-field-states-home.json`、`AT-16-field-states-contents.json`。

这些是当前可复用的 synthetic scenario 和 field-state evidence，不等于 Sprint 4 最终
冻结的 5 motor、3 home、2 contents 产品评估集。

#### 共享合同、前端和测试入口

- `docs/api.md`、`docs/openapi.snapshot.json`、`docs/persistence-schema.md`：API、wire schema
  和持久化边界；
- `docs/claim-state-transaction-boundary.md`、`docs/privacy-governance.md`、
  `docs/third-party-service-consent-and-shared-data-contract.md`：状态一致性、隐私、共享和
  consent 边界；
- `docs/rag-retrieval.md`、`docs/knowledge-source-coverage.md`、`docs/policy-history-mapping.md`：
  知识、policy/history 和来源限制；
- `customer/src/`：claimant-facing React/Vite journey、API client、消息输入和状态投影；
- `workbench/src/`：staff queue、claim detail、handoff 和 external-task projection；
- `admin/src/`：Control Plane、Release Set、model/integration/knowledge/evaluation 管理；
- `frontend/shared/`：共享 design tokens 和跨端状态样式；
- `tests/`：backend contract、scenario、external-service、Control Plane、visibility 和
  cross-journey tests。具体任务应只读取与其验收边界相关的目录和合同，不应因为本文列出
  某个目录就扩大 ownership。

## 第三节：三个 super-issue 的任务与拆解

### 3.1 #769 Backend and AWS integration（40 小时）

这一条线要解决的是：完整旅程所需要的状态和外部能力，是否有一条真实、可追踪、可恢复的
backend path。唯一后端实现 owner 是 `@liyang6620`。其他人可以提出字段、状态、权限、
fixture 或 integration 需求，但不能建立第二条后端实现路径。

后端不应从“我可以新增一个 endpoint”开始，而应从 10 条 anchor 和 100 次完整旅程倒推：
claim、session、message、evidence、handoff、third-party task、permission、visibility、
idempotency、audit 和错误状态分别需要什么。下周一取得的 AWS 能力也属于这一条线，
必须记录真实调用、配置限制、权限和失败证据；本地 stub 成功不能写成 AWS 已接入。

这一条线的验收重点是：Agent 和前端能够基于稳定 API 合同运行；重复请求、超时、未知结果、
不可用和重试都能被观察；provider-specific 字段停留在 adapter 边界；100 次测试可以使用
可复位、可追踪的输入和结果。

适合后端 owner 使用的提示词：

```text
请基于 Sprint 4 的 10 条 anchor 和 100 次完整旅程，检查这个 backend/AWS 需求。
先不要实现。请说明：
1. 该需求服务哪条完整旅程和哪一个 next safe action；
2. 现有 domain model、repository protocol、API、WorkItem/external-task 或 audit contract
   是否已经覆盖它；
3. 如果确实缺失，缺失的是字段、状态、权限、持久化、adapter 还是验证证据；
4. 失败、重复、超时、unknown outcome 和 unavailable 如何表达；
5. 哪些内容可以复用，哪些需要与现有 owner 在 Discussion 中确认；
6. 交付后应该留下什么 exact-head evidence。
请不要创建第二套 Claim State、状态词汇或 provider-specific 业务合同。
```

### 3.2 #770 Agent behaviour and Runtime（40 小时）

这一条线要解决的是：在同一份 Claim Context 上，Agent 如何理解、追问、确认、提出建议，
以及 Runtime 为什么允许、拒绝、等待或转交。它不是继续扩展 prompt 体积，也不是直接
修改 backend 来补齐其他人的工作。

Agent owner 应把 10 条 anchor 变成行为矩阵：每个场景要说明输入、事实来源、当前 branch、
最小问题、确认/修正、工具调用、Runtime directive、handoff、可见性、失败和终点。然后用
真实 replay 证明 proposal、tool result、Runtime decision、revision、WorkItem 和最终投影
之间能对应起来。

这条线必须保持高影响边界：fraud 只能是内部 review signal，severity 只能是 provisional
routing；coverage、liability、approval、rejection、safety 和 emergency decision 不能由
模型自行决定。外部 capability 没有 real handler 时，Agent 应提出安全下一步或说明
unavailable，而不是伪造成功。

适合 Agent owner 使用的提示词：

```text
请基于现有 docs/agent-behaviour-catalogue.md、docs/agent-runtime-policy.md、
backend/domain/agent_action_registry.py、backend/domain/agent_tool_registry.py 和当前
scenario，设计这个 Agent 行为任务的推进思路。
先说明：
1. claimant 的问题和期望 next safe action；
2. Agent 可以读取什么、提出什么、调用什么；
3. Runtime 必须验证什么、可能拒绝什么；
4. claimant、staff 和内部角色各自能看到什么；
5. 需要怎样的 replay、failure case 和持久化 readback 才能证明它；
6. 如果需要新增字段、Tool、Action 或后端能力，为什么现有合同不够，并应如何向 owner
   提出精确的 Discussion 请求。
不要把 prompt 文案、fixture 成功或模型回答本身当作完整 acceptance evidence。
```

### 3.3 #771 Full user journey, frontend, and testing（120 小时）

这一条线要解决的是：claimant 和 staff 是否能看懂并完成真实旅程，而不是各自实现一套
局部页面。共同 owner 为 `@LLL263`、`@jxu316-arch`、`@bdfa123`；每个 subissue 必须有
一名主要 owner 和一条清晰的验收边界。

建议的关注方向是：`@LLL263` 负责 claimant-facing experience 和状态；`@jxu316-arch` 负责
Workbench/staff journey 和交接后的 staff action；`@bdfa123` 负责跨端旅程、材料/第三方
状态呈现和测试证据整合。这是验收边界，不是允许三个人共同维护同一套后端的 ownership。

这条线要把完整旅程、前端状态、浏览器/API evidence 和 100 次测试结合起来。第三方状态
必须有清楚的责任方、共享范围、pending/retry/unavailable/unknown 语义；前端不能根据局部
加载结果推断业务状态，也不能用静态 demo data 掩盖后端缺失。

适合 journey owner 使用的提示词：

```text
请从 claimant/staff 的完整旅程检查这个前端或测试任务。
先不要改 UI。请说明：
1. 用户处于旅程的哪个阶段，下一安全步骤是什么；
2. 这个页面应该投影哪个权威 API/Claim Context 状态；
3. loading、pending、unavailable、unknown、retry、stale 和 completed 如何区分；
4. 第三方、Agent、Runtime、staff 和 claimant 的责任如何表达；
5. 需要哪一条真实 API/replay/browser evidence 才算完成；
6. 如果缺少字段或错误语义，请列出给 @liyang6620 的精确请求，而不是在前端造一个替代状态。
```

## 第四节：如何设计指导自己的研究思路

### 4.1 研究的基本方法

一个好的 Sprint 4 任务不是“我发现一个可以改的文件”，而是“我发现完整旅程中一个
用户或系统无法安全前进的断点”。研究时应先描述断点，再调查证据、责任和约束，最后
决定是代码、文档、原型、测试、第三方研究，还是明确的 blocked record。

研究可以沿着以下思考方向展开，但不要求每个任务都完整走完所有方向：

1. 从 scenario 和用户目标确定旅程终点；
2. 找到当前无法安全推进、无法解释或无法复核的断点；
3. 查阅权威产品、API、persistence、registry、privacy 和 status 文档；
4. 识别需要的参与者、输入、输出、权限、责任和失败状态；
5. 判断现有 contract 是否足够，还是需要向另一个 owner 提出明确请求；
6. 选择最小可复用的实现/表达形式；
7. 设计验收证据和测试材料，再决定当天 issue 的范围。

研究的结果不一定是代码。一个可靠的 source register、状态矩阵、第三方边界、行为 replay
或 unavailable 记录，同样可能是高价值交付。

### 4.2 第三方接入的指导示例

假设 scenario 是一个车辆碰撞，旅程中出现车辆损伤、定损和维修的第三方介入。不要直接
问 agent “帮我加一个修车按钮”。应当这样推进思考：

首先根据 scenario 写清楚完整旅程：claimant 描述事故，Agent 确认车辆是否可驾驶、是否
存在人身危险、哪些损伤已由照片支持；如果需要专业定损，系统应何时停止普通 intake，
向 claimant 解释下一步，并把 context 交给 staff 或 assessor。

然后调查第三方各自真正提供的服务。Assessor 可能只提供损伤评估和结果，不一定提供维修
预约；repairer 可能需要车辆、联系方式、损伤摘要和 consent，但不一定能直接接收保险
内部字段；Police 可能只提供报告入口或电话号码，而不是一个可由系统自动调用的接口。

接着根据责任和风险选择接入形式。若项目只能验证官方电话和网页入口，最诚实的形式可能
是一张说明责任、共享范围和下一步的 service card；若项目有可控的 request adapter，可能
需要一个带 idempotency 和状态的 external request；若需要人工确认，可能是 staff action
或 handoff，而不是 claimant 直接点击后声称已预约。

再把选择转换为工程问题：现有 external-task、WorkItem、consent、permission、audit、
visibility 和 API contract 是否足够？如果不够，缺的是哪个字段或状态？这个字段属于
Claim Context 还是仅属于 provider adapter？结果未知时怎样防止重复发送？claimant 能看到
哪些结果，staff 需要看到哪些内部原因？

最后同步前端、文档和测试材料：更新 journey description、API/OpenAPI、第三方服务记录、
前端状态原型和完整材料包，并安排一个成功、一个 unavailable/timeout、一个结果未知或
需要 staff 的 replay。没有真实 access 的部分要标为 unavailable 或 simulation-only。

### 4.3 第三方研究提示词模板

下面的模板可以直接交给 agent。用户需要替换方括号内容，并先读完本文和相关权威文件：

```text
根据 Sprint 4 的第三方接入研究思路，帮我思考 [scenario ID / motor-home-contents 类别]
中的 [第三方或服务] 应如何推进。

当前我的理解：
- What：我认为旅程中的问题/需求是 [用自己的话说明]。
- Why：我这样判断是因为 [scenario、代码、测试或用户结果证据]。
- Who：我认为需要 [staff / backend owner / Agent owner / frontend owner / maintainer] 支持。
- How：我准备先 [研究/建模/原型/测试/提出 contract 请求]。

请先不要写代码，也不要默认存在真实 provider access。请按段落回答：
1. 这条第三方服务在完整旅程中负责什么，谁拥有下一步责任；
2. 它需要哪些输入、会返回什么结果，哪些结果可能未知或不可查证；
3. 最适合的接入形态是 service card、external request、WorkItem、电话/链接、staff action、
   Agent-assisted form 还是 unavailable 状态，为什么；
4. 现有 registry、API、persistence、consent、permission、visibility、idempotency、audit
   和前端 token 是否已经能承载；
5. 如果不能，精确指出缺口属于谁，给出一个可以放进 Discussion 的 What/Why/Who/How/
   Requested action；
6. 给出最小验收证据：一个正常路径、一个失败或 unavailable 路径，以及它们如何映射到
   Scenario 8 expected outcome。

请明确区分已由仓库证明的事实、合理推断、待用户确认的产品决定和 unavailable/simulation-only
内容。不要发明字段、权限、Northwind authority 或第三方成功结果。
```

### 4.4 任务定义提示词模板

当研究已经足够，可以让 agent 帮忙把它收敛成一个 2–4 小时 issue，但 agent 不能代替用户
决定任务本身：

```text
根据我已经确认的研究结果，帮我把任务收敛成一个 2–4 小时的 Sprint 4 subissue。

我的个人理解：
- What：...
- Why：...
- Who：...
- How：...
- Requested action：...

请输出：
- 一个用户可观察的结果；
- 对应的 scenario/rubric；
- 精确交付物和 evidence；
- 依赖、non-goals 和 ownership boundary；
- 不能假设已经存在的字段、接口或 provider 能力；
- 若仍有产品语义或授权不确定性，先列为需要 Discussion 的问题。

不要把“继续完善”“补一些测试”写成验收标准，也不要扩大到另一个 owner 的实现范围。
```

## 第五节：模块指导与 Week 7 建议 issue

### 5.1 Backend/AWS：从旅程状态反推后端

这一模块的研究起点应是“完整旅程需要什么真实状态”，而不是“后端还有什么文件可以
修改”。适合优先检查 Claim、Session、Message、Evidence、Handoff、WorkItem、external
task、audit、permission、idempotency 和 provider adapter 的连接关系。

建议关注：

- AWS 能力的真实连接、配置、权限、adapter 和错误状态；
- 第三方请求的责任人、consent、状态、结果、unknown outcome 和重试；
- 前端/Agent 需要的字段、visibility 和错误语义；
- Fixture/MongoDB parity、resettable data 和 exact-head evidence；
- provider-neutral domain boundary，避免把 AWS 字段泄漏成业务合同。

### 5.2 跨层状态与行为边界：从权威合同反推责任

这一模块只用于说明三条工作线如何共享同一个业务结果，不要求其他 contributor 进入某个
模型、提示词或 Agent 实现细节。具体行为由对应 owner 维护；其他人应通过仓库已有的产品、
API、状态、权限和测试合同理解自己需要消费或提供的边界。

建议关注：

- 同一个 scenario 中，claimant、staff、系统和第三方各自拥有的责任；
- 当前状态、下一安全步骤、等待条件、handoff 和结果如何在 API、Runtime 和 UI 之间保持一致；
- 任何自动化建议进入真实业务状态前，需要经过哪些权限、revision、idempotency、visibility
  和 audit 检查；
- 正常、失败、不可用、未知结果和恢复路径如何被各端共同表达；
- 现有合同是否已经足够，若不足，应向正确 owner 提出什么精确的 contract 请求。

这里的目标是让前端、后端、测试和负责行为建设的人看到同一个状态边界，而不是让每个人
都修改所有层。

### 5.3 Journey/frontend/testing：从用户看见什么反推投影和证据

这一模块的研究起点应是“用户怎样知道现在发生了什么、谁负责下一步、还能做什么”，而
不是“页面还有哪块空白”。前端只能投影共享状态，不能在本地维护另一套 lifecycle、
responsibility、count 或排序逻辑。

建议关注：

- claimant 从进入到 claim creation 的完整 journey；
- staff 从 queue、handoff、context 到允许的 third-party action；
- loading、empty、pending、unavailable、conflict、retry、stale、unknown 和 completed；
- consent、共享范围、内部信号和 claimant-safe visibility；
- 100 次完整测试的材料包、replay、统计、失败分类和 poster 证据。

### 5.4 Week 7 建议性任务拆解

下面的内容是帮助 contributor 在没有当天具体指令时自行选题的参考，不是要提前创建的
issue，也不是对所有人强制的执行顺序。每张建议卡应再次压缩到 2–4 小时，并由实际
owner 根据当天证据重写 What、Why、Who、How 和 acceptance evidence。

#### 方向 A：Backend and AWS integration（40 小时）

| 天 | 建议卡 1 | 建议卡 2 | 当天应留下的证据 |
| --- | --- | --- | --- |
| Day 1 | 从 10 条 anchor 和一条完整旅程反推所需 Claim、Session、Evidence、handoff、external task 和 WorkItem 状态 | 对照 `backend/domain/`、`backend/api/`、`backend/repositories/` 和 `docs/api.md`，标出已有合同、真实缺口和不可假设的状态 | 旅程到后端状态的映射表，明确哪些已实现、哪些 blocked、哪些 unavailable |
| Day 2 | 选择一类第三方服务，调查责任、输入、输出、consent、访问限制和失败边界 | 判断它应复用现有 external-task/WorkItem，还是需要向 owner 提出一个精确 contract 请求 | source-linked 第三方能力表和最小接入边界，不把公共资料写成 Northwind access |
| Day 3 | 为已确认的缺口设计最小 provider-neutral API、持久化或 adapter 变化 | 为重复请求、revision 冲突、超时、unknown outcome 和 unavailable 设计可观察状态 | contract diff、失败矩阵、Discussion 请求或小范围实现 PR |
| Day 4 | 接入或验证本周可用的 AWS 能力，记录连接、权限、配置和真实调用结果 | 运行失败、重试、结果未知和恢复路径，并确认不会产生重复外部副作用 | exact-head AWS/adapter evidence，明确 configured、validated、unavailable 或 production-integrated |
| Day 5 | 把后端状态接到一条完整 journey，检查 claimant/staff/API 投影的一致性 | 整理可复位输入、结果记录、限制和交接给前端/测试 owner 的 contract 包 | 旅程 readback、API/OpenAPI/持久化同步、未完成缺口和下一周建议 |

#### 方向 B：跨层行为与状态验证（40 小时，仅供对应 owner 参考）

这一方向的建议只服务于负责共享行为边界的 owner。其他 contributor 不应因为看到这些
示例就自行修改模型、提示词、行为文档或 Runtime 实现；他们只需把自己的前端、后端和
测试工作对齐到已发布合同。

| 天 | 建议卡 1 | 建议卡 2 | 当天应留下的证据 |
| --- | --- | --- | --- |
| Day 1 | 选定 5 motor、3 home、2 contents 的稳定场景和预期 next safe action | 建立场景的输入、责任、状态、可见性和结果分类基线 | versioned scenario/behavior manifest，不改变产品 oracle |
| Day 2 | 检查三类场景的事实、材料、冲突、等待和 handoff 边界 | 把每个关键转折映射到现有 API、Runtime record、WorkItem 或 external-task contract | 状态与责任矩阵，明确已有能力和 contract 缺口 |
| Day 3 | 用真实仓库路径重放代表性场景 | 对 replay 的持久化状态、角色投影、revision 和 idempotency 做 readback | 可重放轨迹、一个正常案例和一个边界案例 |
| Day 4 | 运行 malformed、timeout、unknown、unavailable、冲突和 resume 等失败路径 | 检查失败后用户还能做什么、谁负责下一步以及是否保留已确认进度 | failure/recovery 矩阵和明确的 blocked/unavailable 记录 |
| Day 5 | 根据证据做最小边界调整并回归受影响场景 | 汇总可交给完整旅程测试的十条 anchor evidence 和限制 | exact-head 行为证据、回归结果、交给方向 C 的输入包 |

#### 方向 C：Full user journey, frontend, and testing（120 小时）

这一方向适合三位 owner 围绕完整旅程分工。每个人当天可从表中选取 2–4 小时卡，但必须
声明自己的验收边界，不能把“共同负责”作为无人负责的理由。

| 天 | 建议卡 1 | 建议卡 2 | 建议卡 3 | 当天应留下的证据 |
| --- | --- | --- | --- | --- |
| Day 1 | 画出 claimant 从进入到 claim creation 的完整路径 | 画出 staff/workbench 从 queue、handoff 到下一状态的完整路径 | 为 5/3/2 场景整理完整材料包和预期结果 | 两端旅程图、场景清单、材料来源和缺口 |
| Day 2 | 选择一个第三方介入点并制作 claimant-facing 状态原型 | 制作 staff-facing responsibility、consent、request/result 和 failure 投影 | 用现有 API/contract 检查原型是否需要后端字段 | token-based 原型、状态映射、精确 contract 请求 |
| Day 3 | 交付一条 claimant vertical slice，包括 loading、pending、retry 和 unavailable | 交付一条 Workbench/staff vertical slice，包括 handoff、context 和责任变化 | 对两端运行 API/组件测试并记录断点 | 可运行旅程、截图或 replay、测试和已知限制 |
| Day 4 | 执行完整材料包的 motor/home/contents 旅程测试 | 记录问题数量、follow-up、claimant effort、最终状态和第三方结果 | 分类 completed、partial、fixture-only、unavailable、blocked 和 failed | 100 次测试的可复核记录格式和首批结果 |
| Day 5 | 复跑失败场景并修正真实的状态理解或交互问题 | 整理 poster 所需截图、统计、失败分类和限制 | 检查 frontend、API、journey 文档和测试材料是否同步 | exact-head evidence package、poster 材料和下一周缺口 |

如果某张建议卡发现了真实 backend、AWS、权限或产品语义缺口，应保留 blocked evidence 并
提出精确 Discussion 请求，不应为了填满当天时间而越过另一个 super-issue 的 ownership。

## 第六节：硬性边界和协作规则

以下规则是治理边界，不是可根据个人方便程度修改的建议。

- 不创建第二套 Claim State、Session、lifecycle、registry、字段词汇或前端业务状态。
- `@liyang6620` 是 Week 7 唯一后端实现 owner。其他人可以提出需求、阅读代码和 review，
  但不得平行实现 backend path。
- Agent 只能提出 proposal；prompt、model output 或 UI 按钮都不能自行授予权限。
- coverage、liability、approval、rejection、fraud conclusion、safety 和 emergency decision
  必须留在已发布规则、Runtime 或授权 staff/professional boundary 内。
- 不把 fixture、stub、configured、reachable、单元测试或 UI 显示描述为生产能力。
- Northwind-specific authority、采购、凭据、真实 provider access 和第三方成功结果没有
  证据时，必须标为 unavailable、unknown 或 simulation-only。
- 新的 API、字段、permission、Tool、Action、WorkItem 或 external state 必须先说明它为何
 不能复用现有合同，并通过技术 Discussion 与正确 owner 对齐。
- Discussion 用于技术设计、需求对齐和 API contract 对齐，不是普通 Issue 的审批入口。
- 请求协作必须包含用户本人的 What、Why、Who、How 和 Requested action。只有 agent 转述、
  没有用户个人理解的模糊请求，不应进入 Discussion。
- 每张 daily card 应控制在 2–4 小时，并产生代码、文档、原型、replay、测试、统计或具体
  blocked record 之一；“继续完善”不是验收结果。
- 不擅自改变其他 contributor 的 assignee、owner、Kanban 状态或 merge 状态。
- PR 和交付说明必须写清 exact head、测试范围、证据等级、未完成项和 unavailable 限制。
- close issue、merge PR、修改受保护规则或改变 Kanban 状态时，必须有具体授权，不能从
 “把事情处理好”之类的宽泛语句推断授权。

## 第七节：何时应该停下来讨论

遇到以下情况时，应停下来形成有个人理解的 Discussion，而不是让 agent 自行补全：

- 不清楚一个新字段属于 Claim Context、provider adapter、UI projection 还是临时测试材料；
- 不清楚 claimant、staff、Agent、Runtime 或第三方谁拥有授权；
- 一个按钮或 Tool 可能产生真实外部副作用，但 consent、permission、idempotency 或 audit
  还没有明确；
- 现有状态无法区分 pending、unknown、unavailable、failed 和 completed；
- 需要依赖当前 owner 的字段、API、AWS 配置或 persistence contract；
- 现有 API、文档、frontend projection 和测试材料互相矛盾；
- home 或 contents 只能通过复制 motor 旅程解释；
- 你无法说明这项工作如何改善完整旅程或 rubric expected outcome；
- 你只能提出“让 agent 自动处理”而不能说明 Runtime 如何裁决和失败后谁负责；
- 你发现 PR 或已有代码声称完成，但实际 exact-head evidence 不足。

发 Discussion 前，先用自己的话写清楚：

```text
What：我认为当前旅程/系统有什么问题或需要什么能力。
Why：我根据哪个 scenario、用户结果、代码、文档或测试形成这个判断。
Who：我需要哪个 owner 或角色提供支持。
How：我准备如何调查、原型化、实现或验证。
Requested action：我希望对方具体提供字段、状态、决策、review、实现或证据是什么。
```

如果用户自己无法解释 What 和 Why，agent 应先要求用户澄清；不能把一段没有个人判断的
任务转成一个看似正式的 Discussion。讨论的目标是消除 contract、责任和授权边界的不确定性，
而不是把思考责任转移给 maintainer。
