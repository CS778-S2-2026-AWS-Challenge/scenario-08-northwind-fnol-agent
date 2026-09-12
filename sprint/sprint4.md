# Sprint 4：Rubric Convergence and Journey Validation

## 1. 阶段定位

Sprint 4 是 Scenario 8 的收敛与验证阶段。目标不是继续扩大抽象能力，而是根据
Scenario 8 rubric 固定设计边界，完成可重复的完整用户旅程，并产生可以直接进入
poster 的验证数据。

本 Sprint 以 2026-09-14 开始的 Week 7 为第一周，随后进入 Week 8 的整合、复跑和
展示准备。Week 7 只建立三个 super-issue；每天的工作由各 owner 自己提出一个
8 小时 bounded subissue，由 maintainer 当天创建或同步到 Kanban。

## 2. 最终目标与 rubric 对齐

Scenario 8 的 Expected Outcome 要求 Agent 能完成 10 个代表性场景：5 个 motor、
3 个 home、2 个 contents，从初次报案直到 claim creation。每条路径应展示：

- 多轮对话和澄清；
- 照片或 PDF 等多模态材料；
- 基于匿名 policy 文档的 RAG coverage validation；
- severity classification；
- fraud-signal flagging，但不把 signal 伪装成 fraud 结论；
- 在授权边界内使用工具创建 mock claim 或预约 mock assessor；
- 最终返回 claim number 和 expected timeline。

正式 rubric anchor 仍为 10 条代表性场景，但 Sprint 4 的初始有效测试基准为 **100
次独立的完整旅程测试**：

- 50 次 motor；
- 30 次 home；
- 20 次 contents。

这里的“一次测试”是一次从初始报案到预期终点的完整运行。每次运行都必须携带并
使用该场景所需的全部材料包（例如照片、PDF、policy 片段、历史记录和第三方结果），
而不是把单个材料拆成独立测试。后续若有余力，再增加数量或覆盖更复杂的边界。

每次测试至少记录以下指标：

1. 是否无需 follow-up 即完成；目标为 80% 或以上。
2. severity classification 的盲评结果。
3. fraud flag precision；测试集不得出现 false positive。
4. claimant effort：少于 5 分钟、少于 10 个问题。
5. claim number、expected timeline、最终 Claim 状态和完整证据链。

测试结果必须区分 `completed`、`partial`、`fixture-only`、`unavailable`、
`blocked` 和 `failed`，不能把 mock 成功写成真实 AWS 或 Northwind 能力。

## 3. 产品与工程原则

- 产品价值是把 claim 安全推进到下一个 safe action，而不是展示更多模型能力。
- Agent 负责理解、整理、追问、确认和提出建议；Runtime 负责权限、执行、持久化、
  事件和是否允许真实状态改变。
- 同一份 Claim Context 贯穿 claimant、staff、Agent、Evidence、policy、历史和
  第三方协作；前端不能维护另一套业务状态。
- 高影响的 coverage、fraud、liability、approval、rejection 和 safety 判断必须
  留在明确的业务或人工权限边界内。
- 先完成垂直旅程，再扩大功能广度。组件、endpoint、prompt 或 fixture 只有在改善
  某条完整旅程并有证据时才算 Sprint 交付。
- Fixtures 是可重复验证的输入，不是生产能力证明；AWS、第三方 access、schema 和
  permission 未验证时必须明确标为 unavailable 或 simulation-only。

## 4. Week 7 的三个 super-issue

Week 7 总工作量为 200 小时：40 + 40 + 120。每日 issue 是下列 super-issue 的
subissue，不再预先拆成几十个 2-5 小时的技术卡片。

### Super-issue A：Backend and AWS integration（40 小时）

唯一实现 owner：`@liyang6620`。其他 contributor 可以提出 API、字段、权限、状态、
fixture 或集成需求，但不得在后端建立第二条实现路径。

交付边界：

- 使 100 次完整旅程所需的 Claim、session、message、evidence、third-party task、
  handoff、权限和状态能够通过真实项目 API 运行；
- 补齐三类场景需要的最小业务数据与材料索引，不重新发明与现有 registry 冲突的字段；
- 完成下周一可用 AWS 能力与项目的实际集成，包括连接、配置、权限、adapter、错误
  状态和可重复验证；“已接入”必须有真实调用或明确失败证据；
- 对外提供前端和 Agent 所需的字段、状态、visibility、idempotency 和错误语义；
- 保持 provider-neutral domain boundary，不能把 AWS 特定字段泄漏成业务合同；
- 为 100 次测试提供可复位、可追踪的输入与结果记录。

不包含：第二位后端实现者、未经批准的产品语义改写、把 fixture 或本地 stub 宣称为
AWS 成功、前端 UI 重构。

完成标准：前端和 Agent 能基于当前 API 合同运行；AWS 能力的真实状态、权限和限制有
证据；失败、重试、重复请求和不可用路径均可观察。

### Super-issue B：Agent behaviour and Runtime（40 小时）

实现 owner：`@Ysoseri1224`。

交付边界：

- 固定 10 条 rubric anchor 的 Agent 行为和判断边界；
- 为 motor、home、contents 定义确认、推断、缺失、冲突、等待、handoff 和 next-safe-action
  的可观察触发条件；
- 使 Dynamic Form 只使用已注册字段、branch 和 tag，并与 Claim Context 保持一致；
- 明确 prompt、结构化输出、tool call、Runtime 拒绝和 claimant/staff 可见性；
- 验证 Agent 不把 fraud signal 变成 fraud 结论，不越过 Runtime 执行高影响动作；
- 产出 replay、行为日志或测试证据，供 poster 使用。

不包含：直接修改后端实现、发明独立字段词汇、以 UI 文案代替业务行为合同。

完成标准：每个关键行为都能映射到一个场景、一个可观察输出和一个允许/拒绝的运行时
结果；prompt 改动不会绕开权限、审计和 Claim Context。

### Super-issue C：Full user journey, frontend, and testing（120 小时）

共同 owner：`@LLL263`、`@jxu316-arch`、`@bdfa123`。三人共同关注完整旅程，但每个
subissue 必须声明一名主要 owner 和一个主要验收边界，避免共享前端池无人负责。

共同交付边界：

- claimant 从进入、报案、追问、确认、上传、第三方协作、等待、恢复直到 claim
  creation 的完整可用旅程；
- staff/workbench 从队列、分配、领取、查看上下文、与 claimant 沟通、使用允许的
  第三方操作直到状态推进的完整旅程；
- loading、empty、unavailable、conflict、retry、handoff、privacy 和 stale-data
  状态都必须有真实 API 投影；
- 前端新增需求通过 Discussion 与 `@liyang6620` 对齐字段、状态和权限；前端 owner
  不直接实现后端；
- 建立并运行 100 次完整旅程测试，记录材料包、结果、指标、限制和证据；
- 形成可用于 poster 的用户旅程截图、replay、统计和失败分类。

建议的验收边界（不是新的技术层 ownership）：

- `@LLL263`：claimant 体验与 claimant-facing 状态；
- `@jxu316-arch`：Workbench/staff 体验与交接后的 staff 操作；
- `@bdfa123`：跨端旅程验证、材料/第三方状态表现和测试证据整合。

## 5. 协作和 Discussions

取消 Issue 创建审核规则。任何 contributor 都可以使用 Issue Form 创建结构完整的
Issue；Issue policy 只检查字段和边界，不检查 maintainer 预批准。

GitHub Discussions 只用于：

- 技术设计讨论；
- 需求和 API contract 对齐；
- 跨 owner 的字段、权限、visibility、状态、失败和交付顺序确认。

例如，前端发现需要新字段时，应在 Discussion 中说明用户旅程、请求/响应形状、可见
范围、失败语义和 acceptance evidence，并明确 `@liyang6620` 需要实现什么。Discussion
不是普通 Issue 的准入审批，也不能替代 Issue 的 acceptance criteria。

请求另一位 contributor 协作时，必须带有用户本人的：

- **What**：我认为问题或需求是什么；
- **Why**：我如何产生这个判断；
- **Who**：需要谁支持；
- **How**：我准备怎么做；
- **Requested action**：被请求的人具体交付什么。

只有 agent 代写的任务转述、没有用户个人理解的内容，不得进入 Discussion。

## 6. 每日 subissue 与 Kanban

- 每人每天按 8 小时规划；每日只提交一个属于对应 super-issue 的 bounded subissue。
- subissue 必须写明当日可观察结果、场景编号、rubric 指标、owner、依赖、non-goals
  和完成证据。
- 可以是代码、测试、材料、文档、replay、数据分析或明确的 blocked 证据；不能只写
  “继续完善”“修一些问题”。
- maintainer 当天统一创建或同步三个 subissue 的 Kanban card。没有 maintainer 时间时，
  contributor 可以按新 Issue 模板自行创建 Issue，之后由 maintainer 补同步 card。
- card 不得拆成隐藏的技术碎片，也不得由 agent 自行改变其他 owner 的 assignee 或状态。
- 每日结束必须留下 PR、文档、测试/replay、统计或具体 blocked record；没有证据的代码
  不算完成。

## 7. 测试证据格式

每一次完整旅程测试记录：

- stable scenario ID 和类别；
- commit/head、运行时间和运行配置；
- 全部输入材料及其来源/版本；
- claimant 输入、Agent 关键行为、tool calls、Runtime 决策；
- consent、权限、visibility 和第三方请求状态；
- Claim、session、evidence、handoff 和最终状态；
- claim number、expected timeline 和 claimant effort；
- 成功、失败、重试、超时、unknown 或 unavailable 的分类；
- 对应 rubric 指标和可复核证据。

测试代码遵循 mock-first 和 impact-scoped CI 规则。不要为了达到 100 次运行而复制
表面化单元测试；一次有效旅程可以由多个有行为意义的检查共同支撑。

## 8. Definition of Done

Sprint 4 结束前必须能够：

1. 重复运行 100 次完整旅程测试，并明确列出未完成或 unavailable 项。
2. 从中选出 10 条 rubric anchor，给出完整输入、输出、状态和指标证据。
3. 证明 Agent、Runtime、Claim Context、claimant 和 staff 投影没有各自维护冲突状态。
4. 证明 AWS 集成的真实能力、权限和限制，而不是只展示 fixture 成功。
5. 证明关键高影响决策仍由授权业务或人工负责。
6. 形成 poster 可用的场景矩阵、指标表、失败分类、截图和限制说明。
