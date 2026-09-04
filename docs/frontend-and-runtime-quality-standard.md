# Northwind FNOL 前端与运行时质量标准

## 文档定位

本文是 Northwind FNOL 前端重构与相关后端联动的项目级设计、开发和验收标准。它同时承担两项作用：

1. 作为产品、设计、前端、后端和 Agent 实现的指导性提示词；
2. 作为评审一个实现是否达到最低可接受质量的权威检查表。

本文特别用于防止一种常见误判：代码能够运行、测试能够通过、页面看起来比旧页面漂亮，并不代表实现符合 Northwind 的产品方向。

本文不替代仓库中的 `AGENT.md`、治理 skill、`SPEC/`、`docs/api.md` 和 `docs/persistence-schema.md`。当它们对现有契约有更具体的规定时，仓库规范和已确认的产品决策优先；本文负责把重构路线、设计原则、实现边界和质量门槛具体化。

本文的阅读顺序不是从旧页面迁移开始，而是从最终产品目标开始。旧 `index.html`、旧 `app.js` 和旧 `styles.css` 只属于迁移背景与清理范围；它们不能继续决定新 `main` 的信息架构、路由、组件边界或业务行为。

---

## 0. Big picture：最终产品目标与实现闭环

### 0.1 产品要解决的问题

Northwind FNOL Agent 是一个面向保险首次报案（FNOL）和 Claim 协同的可信、自适应服务。它要减少两类人的判断成本：

- claimant 不需要先学会保险术语、固定问卷或内部流程，就能用自己的话说明发生了什么，并得到清晰、可继续的帮助；
- staff 不需要在对话、字段、证据、policy、历史和外部服务之间手工拼接事实，就能知道哪个 Claim 需要处理、为什么需要处理、谁负责、缺什么以及下一步唯一主动作是什么。

最终目标不是“做一个更漂亮的聊天页”，也不是“把旧 MVP 页面拆成多个文件”，而是让同一份可追溯的 Claim Context 在不同角色之间安全流动，并让 Agent、运行时和 UI 各自承担正确职责。

### 0.2 端到端闭环

```text
Claimant / Staff natural language
        ↓
Agent understanding and explanation
        ↓
registered fields + branch + retrieval proposals
        ↓
RAG / policy / history / database / evidence / adapter
        ↓
Runtime identity, permission, revision and action checks
        ↓
approved execution, handoff or external coordination
        ↓
shared Claim Context, WorkItems and audit record
        ↓
claimant projection + staff projection + control-plane projection
```

这条链路中的关键边界必须始终成立：模型可以理解、抽取、检索、解释和提出建议；只有 Runtime 才能授权、执行、写入、改变业务状态和形成审计记录。前端只呈现后端 projection，并把用户意图安全地提交回受控动作接口。

### 0.3 两个 key feature 与最终体验

#### Key feature 1：Trusted adaptive claim entry

- Agent 是 claimant 的主视觉窗口和唯一主要入口；用户永远可以用自然语言开始或纠正；
- Agent 在内部维护 dynamic form、content branch、证据需求和下一步建议，但不把用户锁进固定问题清单；
- 文件、语音、无障碍、传统 Web Form 和 Staff Assistance 是辅助入口，保留可发现性，但不能与 Agent 争夺主入口；
- 设计必须同时改善 claimant 和 staff 的体验：降低 claimant 的认知压力，也要让 staff 更快理解、更少重复收集、更愿意信任并协作使用 Agent。

#### Key feature 2：Shared Claim Context coordination layer

- claimant、Agent、staff、evidence、policy、history、数据库和获准的外部参与方围绕同一份事实基础协作；
- 角色不是共享全部数据，而是由后端按权限生成不同 projection；
- 每个重要事实、建议、动作和外部结果都保留来源、时间、revision、责任方、可见性和不确定性；
- 外部服务不是演示终点，而是 Agent 协助用户获取资料、采取行动和推进 Claim 的一类能力。

### 0.4 新 main 的完成定义

在新 `main` 上，合格的 VP 实现应当满足：

1. 从根路径开始，用户能自然地进入匿名 Claim、登录/注册或已有会话；
2. 登录后进入 Agent workspace，而不是 Account 中转页；
3. Claimant 的消息、字段、附件、handoff、第三方服务和失败路径都连接真实 API；
4. Workbench 以任务顺序和后端投影为中心，能在多个 Claim 间安全切换；
5. 两端共用 token、状态语义和组件原则，但保持不同信息密度；
6. router、session、revision、权限和动作执行不依赖浏览器后退、前端猜测或 fixture；
7. motor、home、contents 只是三条可重复验证的 VP 路径，不是产品能力边界；
8. 未接通或未验证的 AWS/provider 能力明确标注，不被包装为已完成的生产能力。

### 0.5 交付优先级

所有设计和开发决策按以下优先级排序：

```text
真实用户旅程
  > 状态、权限与数据来源正确
  > 可执行动作和失败恢复完整
  > 组件、路由和 token 可演进
  > 视觉精致度和装饰
```

如果视觉改动会掩盖状态错误、鉴权错误、前端业务推断或真实 API 未连接，应先修正行为和边界，再调整外观。

---

## 1. “不要 T 恤，要西装”的质量标准

### 1.1 T 恤式实现是什么

以下情况即使能运行，也只是 T 恤式实现：

- 页面仍然能打开，但把错误的 landing page、旧流程或旧导航继续保留；
- 功能局部正确，但它把状态、权限或业务判断放错层；
- 测试只证明 DOM 存在或请求返回 200，没有证明用户旅程和失败路径；
- 前端根据字符串、数组顺序、角色名称或 tag 自己猜业务状态；
- 后端拒绝了请求，前端才被动显示错误，但页面事先已经承诺了该能力；
- 把一个 fixture 场景做成看似完整的生产能力；
- 使用新的颜色和组件包裹旧的单文件逻辑；
- 用固定模板代替 Agent 的通用理解、检索、建议和草稿能力；
- 将所有信息和所有动作同时堆在首屏，要求员工自己寻找重点；
- 通过 `index.html`、全局变量、字符串模板和级联覆盖维持复杂应用；
- 只要“看起来可用”，就不记录 projection、revision、权限、失败和审计边界。

### 1.2 西装式实现是什么

合格实现必须同时满足：

- 产品方向正确：Agent 是 claimant 的主入口，Workbench 是员工的任务工作区；
- 用户旅程正确：匿名聊天、认证、恢复、handoff、第三方服务和状态更新都能继续；
- 信息层级正确：当前主任务突出，次要动作和参考信息渐进式揭露；
- 前后端边界正确：模型提出建议，Runtime 授权和执行，projection 决定展示；
- 状态来源正确：业务状态、责任方、优先级、风险、缺失信息和下一步来自后端权威投影；
- 数据可追踪：来源、revision、actor、时间、结果未知、失败原因和审计关系不丢失；
- 权限可验证：前端不会显示明知当前身份无权执行的动作；后端仍是最终授权者；
- 失败可恢复：错误、等待、中断、未知结果、重试和重新同步都有明确路径；
- 实现可演进：组件、路由、API、状态容器、token 和测试边界清晰；
- 实际能力诚实：fixture、仿真、未验证 provider 和未接通 AWS 能力不会被表述为生产事实；
- 可访问和可响应：键盘、触控、移动端、屏幕阅读器和减少动画设置都能使用；
- 验收证据匹配行为：浏览器级行为用浏览器验证，权限用权限测试，业务状态用 API/集成测试。

### 1.3 最低可接受原则

任何重构切片只要触及以下任一项，就不能以“局部看起来可用”结束：

- 改变用户入口、认证、session、Claim tab 或主导航；
- 改变 Claim projection、Staff projection、Admin projection 或敏感字段；
- 改变 allowed action、权限、状态转换、handoff 或第三方请求；
- 改变动态表单、字段来源、branch、缺失信息或风险信号；
- 改变模型、RAG、policy、history、数据库或外部服务的调用边界；
- 删除或迁移旧页面、旧 API、旧测试或旧 token。

这些切片必须同时更新相应契约、失败路径和测试，而不能只补一条成功路径。

---

## 2. 产品和交互总原则

### 2.1 Agent-first claimant

Claimant 打开产品后，主要动作是用自己的话说明发生了什么。Agent 负责理解表达、提出澄清、调用授权的 RAG/数据库/证据能力、维护动态字段、解释下一步并在必要时发起 handoff。

Claimant 不应被迫先理解：

- 保险术语；
- 固定的问题顺序；
- 三种 Claim 类型的完整差异；
- 内部 workflow state；
- 哪个员工或第三方负责下一步。

Claimant 可以不登录开始聊天。匿名 session 可以保存本次会话中的必要上下文；登录只负责把本次 session/Claim 幂等地关联到用户，并获得历史、profile 和文件持久化能力。

### 2.2 Workbench-first staff

Staff Workbench 不是客户聊天页面的复制品，也不是数据库镜像。第一屏必须帮助员工依次回答：

1. 哪个 Claim 需要我处理；
2. 当前 Claim 发生了什么；
3. 哪些事实已经确认；
4. 哪些信息缺失、冲突或不确定；
5. 当前风险 signal 是什么，证据来自哪里；
6. 谁负责下一步；
7. 当前唯一的主动作是什么；
8. 完成该动作会改变哪些状态、任务、消息或责任。

队列固定遵循三层关系：

```text
当前责任/待处理工作
        ↓
优先级与时限
        ↓
Claim tag、risk signal 和筛选
```

`Fraud`、`dispute` 等是风险 signal/tag，不是未经专业确认的业务结论。`Incomplete` 是正式 Claim，必须可见，只降低默认排序权重，不折叠、不隐藏。

### 2.3 共享性格，不共享密度

Claimant 和 Staff 共享：

- 保险领域的专业性；
- 友好和清晰；
- 安全感；
- 尊重；
- 不制造不必要的紧张感；
- reliability：不承诺不确定结果，但始终给出诚实、可继续的帮助。

两端不共享相同的信息密度：

- claimant 以低认知压力、对话和逐步确认优先；
- staff 以任务排序、快速扫描、来源、责任和可追溯动作优先；
- staff 可以更密，但不能用密度制造视觉噪音。

### 2.4 先设计关键功能，再设计外壳

不能先决定“三列、侧边栏、深色导航或悬浮助手”，再把功能塞进去。设计顺序必须是：

```text
真实用户任务
  → 状态和责任变化
  → 所需信息与动作
  → 角色 projection
  → 路由与组件
  → 信息层级
  → token 和视觉外壳
```

任何布局选择都必须能说明它如何降低用户判断成本、保护上下文或支持下一步动作。

### 2.5 用户旅程必须可被逐步解释

每个可见控件都必须属于一个明确旅程，而不是因为“页面上通常应该有这个按钮”而存在。实现前应能回答四个问题：

| 问题 | 必须明确的内容 |
|---|---|
| 触发点 | 用户点击、发送、上传、登录、确认或返回后发生什么 |
| 当前上下文 | 当前 route、session、Claim、角色、revision 和 projection 是什么 |
| 可见变化 | 哪些消息、字段、状态卡片、队列或 tab 会更新 |
| 失败与恢复 | 如果未授权、超时、冲突、未知结果或资源不存在，用户下一步怎么继续 |

任何只描述“点击后弹窗出现”却没有说明上下文、持久化和失败路径的设计，都不能作为实现规格。对话中的辅助入口（How it works、Staff Assistance、传统 Web Form、上传和语音）必须说明它如何回到主对话，而不是把用户带入一条互相独立的替代流程。

### 2.6 信息层级优先于装饰

页面首先表达任务和状态，然后才表达品牌和氛围：

- 主入口只有一个；
- 同一屏只突出一个主要下一步；
- 辅助动作使用 link/quiet/secondary 层级，不与主动作竞争；
- 状态同时使用文字、图标/符号和语义色；
- 不依赖 hover 才能发现关键信息；
- 空、等待、错误、不可用和未知结果都要说明“现在是什么”和“现在能做什么”。

---

## 3. 前端架构标准

### 3.1 应用形态

正式 claimant 和 Workbench 前端使用 React/Vite 组件化结构或等价的模块化结构。禁止把复杂业务继续集中在：

- 单个静态 `index.html`；
- 一个包含所有 API 调用、DOM 操作和状态变量的 `app.js`；
- 一个包含早期样式、响应式补丁和后置覆盖的 `styles.css`；
- 用 `innerHTML` 字符串拼装主要业务界面；
- 用浏览器 history state 和一个内存变量冒充完整路由系统。

旧页面可以在迁移期间保留为 archive 或非正式入口，但不能继续作为正式功能的第二套实现。迁移完成后，旧页面必须删除或移出仓库，并重写依赖静态 HTML 的测试。

### 3.2 分层职责

```text
Route / page
  → feature state container
    → domain-aware components
      → presentational components
        → shared tokens and status primitives

API transport
  → schema normalization
    → projection-aware state
      → components
```

组件不能自行：

- 拼接 API URL；
- 判断 Claim 是否 fraud；
- 根据字段数量计算 priority；
- 根据 access level 推断每个动作是否允许；
- 根据 provider 字符串推断责任方；
- 解析错误文案来决定重试；
- 用 fixture 数据代替正式 API。

### 3.3 路由与保护

路由必须表达真实页面边界和权限边界。至少应区分：

- claimant 入口、登录、注册、workspace、history、profile、privacy、files 和教学视图；
- Workbench 登录、队列、Claim tab、Claim section、Claim conversations 和 Workbench Agent session；
- Control Plane/Admin 独立应用和独立认证。

路由保护必须处理：

- 未登录访问受保护页面；
- 已登录用户访问登录/注册页；
- session 过期；
- 直接深链接；
- 刷新后的 tab/session 恢复；
- 不允许通过浏览器 Back 随意跳过业务保护；
- not found、无权限和资源不可用的区别。

### 3.4 状态容器

页面状态、Claim 状态、session 状态、资源加载状态、草稿状态、revision 和权限状态必须分开保存。刷新或切换 tab 时至少保留：

- 当前 Claim tab；
- 当前 section；
- 当前 conversation/session；
- 展开状态；
- 消息草稿；
- 待确认动作；
- 最新已知 revision。

任何写入都必须在返回后以权威 projection 更新，而不是只修改本地按钮或列表。

### 3.5 新 main 的模块边界与数据流

新 `main` 的代码组织应围绕功能和数据流，而不是围绕旧页面文件名：

```text
route guard
  → page shell
    → feature controller (session / claim / queue / tab)
      → API client + schema normalizer
        → projection/state store
          → domain components
            → token-based presentational primitives
```

最低拆分要求：

- `app/router`：canonical route、深链接、认证保护、错误边界和离开保护；
- `features/claimant`：入口、对话、composer、动态字段、文件和辅助页面；
- `features/workbench`：队列、Claim tabs、Claim 详情、conversation 和 Staff Agent；
- `services/api`：transport、认证、revision、幂等键和错误 envelope；
- `domain/projections`：按 API schema 映射为 claimant/staff 可用的只读 view model；
- `shared/components`：按钮、输入、状态、卡片、折叠面板、focus 和无障碍 primitives；
- `shared/tokens`：唯一视觉 token 源和 density 变体；
- `tests`：按旅程、组件、路由、契约和权限划分。

组件之间传递已规范化的数据和事件，不传递隐含的业务规则。数据流必须可追踪：请求发起 → loading → API 返回 → projection 更新 → UI 呈现；不能通过局部 DOM 修改绕开状态容器。

### 3.6 路由是产品边界，不是地址栏装饰

每个 route 都必须有 canonical owner、允许的身份、可读取的资源和离开条件。`history.pushState` 只能改变导航，不得代替鉴权、资源加载或状态恢复。受保护资源必须在服务端再次校验，前端 guard 只负责及时反馈和避免错误渲染。

路由切换时：

1. 先保存当前草稿和展开状态；
2. 再验证目标 route 的身份、scope、resource 和 revision；
3. 加载对应 projection；
4. 成功才替换页面内容；
5. 失败时显示明确的 not found / forbidden / unavailable 页面，并提供回到安全流程的动作。

禁止让多个页面共享一个可变背景层、一个全局 `innerHTML` 容器或一个“当前 page”字符串来决定互斥视图。

---

## 4. Claimant 交互标准

### 4.1 入口和认证

- 顶部窄 bar 左侧放产品 logo，右侧放低强调的 `Use the traditional web form` 和 `Staff Assistance`；
- 主视觉是 Agent 对话入口，不是三张 Claim type landing cards；
- 品牌句使用 `Understand insurance. Understand you better.`；
- 输入区附近用非必选 Claim type select 提供辅助提示；
- Agent 确认进入某个 content branch 后，select 锁定；
- `Helpful details to include` 作为新 Claim 的主动 greeting 或空状态提示；
- `How it works` 不离开当前对话：登录状态下由 Agent 发送说明消息并附 `See more →`，未登录时可进入教学视图；
- 传统 Web Form 与 Staff Assistance 属于辅助导航，不得与 Agent 争夺主入口。

登录/注册成功后必须自动进入 Agent workspace：

```text
入口 → Login/Register → 成功
  ├─ 当前有匿名 Claim/session：绑定后回到该 workspace
  └─ 没有 Claim：进入空的 Agent workspace
```

`Your account` 只能由 Profile 入口打开，不能作为认证成功后的默认落点。

### 4.2 动态表单

动态表单是内部根据以下内容持续重建的 Claim Context：

- 已确认事实；
- 新增或变更的事实；
- 当前 content branch；
- 未完成事项；
- 当前动作需要的字段；
- 证据、policy、history 和数据库查询结果；
- 当前角色和可见性。

字段只能来自 Field Registry。用户应看到由对话确定的字段，但不需要看到内部规则：

- 桌面端使用可折叠 `What we have so far` 右侧面板；
- 移动端使用对话中的可展开 `Details captured` 区域；
- 每次只突出本轮新增或变更字段；
- 已确认字段不重复询问；
- 用户可以点击编辑，也可以自然语言纠正；
- 字段显示 source、状态和必要的可理解说明；
- 内部置信度、检索 ID、策略细节和员工专用内容不泄露。

### 4.3 Composer 和多模态

文字、附件、语音、无障碍、Claim type 和发送属于同一个 input shell：

- 初始 textarea 约两行高；
- 高度随文字和已选文件自适应；
- toolbar 在 input shell 内部，不另起独立条带；
- attach 使用明确的圆形加号控件；
- Listen 位于每条 Agent 回复右下角，不与 attach 紧贴；
- 未登录也允许发送文字和合法请求；
- 文件持久化需要认证，但匿名上传可以在当前 session 中处理并明确生命周期；
- 语音权限、录音、转写…8 tokens truncated…_access` 自己推导某个具体动作是否允许；
- 不显示明知当前 projection 未授权的 mutation 控件。

后端必须再次验证所有动作，不能信任前端传来的 action code、role、target 或 revision。

### 7.4 动态表单与 Registry

Field Registry、Content Branch Registry、Lifecycle Registry、Action Registry、Tool Registry、Model Profile Registry 和 Error Registry 必须彼此分工：

- Field Registry 限制可以存在和显示哪些字段；
- Branch Registry 限制 content branch、字段、工具和激活条件；
- Lifecycle Registry 限制 Claim 状态和合法转换；
- Action Registry 限制可以提出和执行哪些动作；
- Tool Registry 限制工具参数、权限、副作用和失败；
- Model Profile Registry 限制 endpoint、能力、隐私和评估状态；
- Error Registry 限制稳定错误代码、重试类别和安全响应。

前端不能通过自由文本创建正式 action、reason code、状态或字段。后端不能让模型发明 registry 条目。

动态表单的重建必须是可解释的运行时结果，而不是前端的字段拼接：

```text
confirmed facts + unresolved items + active branch + evidence state
  + current action requirements + role visibility
  → registered field projection
```

每次 Agent turn 或 Runtime action 完成后，后端应返回字段的稳定身份、值、状态（proposed/confirmed/changed/unavailable）、来源、更新时间、revision 和下一步需要。前端只比较 revision/field identity 来突出变化，不凭字段数量或空值自行判断 Claim 完成度。

Claim branch 与 Claim state branch 必须分开：

- content branch 表示当前处理的保险情境或路径；
- lifecycle/state branch 表示 Claim 在业务生命周期中的位置；
- branch 进入、锁定、切换和回退均由 Registry/Runtime 规则决定；
- Claim type 下拉框只是 claimant 的辅助提示，不能绕过 Agent 理解或强行写入 branch；
- 字段、工具和动作必须声明所属 branch 及激活条件，避免 motor/home/contents 的字段互相泄漏；
- branch 或字段冲突时，Agent 应解释冲突并请求澄清，Runtime 不得静默覆盖已确认事实。

### 7.5 第三方服务生命周期

第三方能力不是一个泛化的 `request()` 按钮，而是完整生命周期：

```text
capability discovery
  → requirement loading
  → request preparation
  → request classification
  → authority and consent
  → submission
  → tracking
  → response verification
  → reconciliation
  → safe retry/cancellation
  → failure escalation
```

每一步都必须能表达状态、责任方、来源、时间、限制和结果未知。provider 是提供方，不是默认责任方；Northwind 是业务组织，不是未经定义的执行责任方。

fixture、仿真、configured service 和 verified production result 必须是不同的状态，不能只用 provider 名称区分。

### 7.6 API、错误、并发和审计

后端必须遵守：

- `/api/v1` 与 `/internal/v1` 的角色和资源边界；
- REST 资源模型和 snake_case 字段；
- 所有列表使用 cursor pagination；
- side-effecting POST 使用 Idempotency-Key；
- 写入使用 revision/If-Match 处理并发；
- 统一错误 envelope：`code`、`message`、`request_id`、`details`、`retryable`、`current_revision`；
- 4xx、429、5xx 语义分明，重试依据结构化状态而不是解析文案；
- 授权检查先于资源存在性检查，避免泄漏 Claim 是否存在；
- 写入后后续读取能看到最新状态；
- 外部模型、AWS SDK 和 provider 调用具有 timeout、retry cap 和明确失败路径；
- 日志包含 correlation key 和 claim id，但不记录不必要的 PII、完整 prompt、token 或 raw provider response；
- 状态、动作、来源、actor、时间和 resulting revision 可审计。

### 7.7 认证与匿名 session

Claimant 和 Staff 必须使用独立认证边界。匿名 Claim/session：

- 使用不可预测的临时 ID；
- 只允许当前会话继续访问；
- 不等同于用户身份；
- 登录后一次性、幂等地绑定到用户；
- 未在本次会话内完成登录时，不能被其他用户认领；
- 按既定 retention 规则过期或清理；
- 上传文件、profile 和历史持久化能力必须明确区分匿名和认证状态。

### 7.8 前端不得执行的业务逻辑

以下逻辑必须由后端/Runtime 计算并投影，前端只能展示、收集受控输入和提交动作：

- Claim lifecycle state、branch 是否已确认、字段是否完整；
- priority、rank、due time、risk level、fraud/dispute 结论和责任方；
- 缺失信息的业务优先级、阻塞关系和下一步主动作；
- claimant/staff 可见性、数据脱敏和跨 Claim scope；
- action 是否可执行、是否需要确认、revision 是否仍有效；
- 第三方请求分类、provider 状态、pending owner、验证结果和恢复路径；
- RAG、policy、history、database 和 evidence 结果的可信度及 unavailable 原因；
- Agent 草稿是否可以转化为正式消息、Claim 更新或外部副作用。

前端可以做纯展示层排序（例如按后端返回的 rank 渲染）、本地输入校验、折叠/展开和 viewport 适配；不能把展示层方便实现误认为业务规则。

### 7.9 真实 API 优先与能力诚实

新 main 的功能实现必须优先连接真实 API、Model Gateway 和 adapter：

- fixture 只用于测试场景、回归和离线开发，不是生产运行时的替身；
- 真实 API 暂不可用时，页面显示 `unavailable` 或 `not configured`，并给出可继续路径；
- 仿真服务必须明确标记为 simulation，并保留与目标真实服务相同的输入/输出边界、生命周期和失败模型；
- GPT-5.4-mini 通过 Model Gateway/adapter 选择，不在前端硬编码模型行为或绕过 gateway；
- 未完成的 AWS/provider 能力不得由静态成功文案、假数据或演示按钮包装成已交付能力；
- 任何“已保存”“已提交”“已交接”“已验证”都必须对应后端返回的状态和 revision。

---

## 8. 测试和验收标准

### 8.1 测试类型必须匹配行为

| 行为 | 最低证据 |
|---|---|
| 组件显示和交互 | component test |
| 路由、鉴权和深链接 | browser/router test |
| projection 字段和可见性 | API contract/regression test |
| 权限和动作 | authorized/unauthorized API + UI test |
| revision、幂等和冲突 | backend integration test |
| 第三方生命周期 | adapter/service transition test |
| 真实用户旅程 | browser-level journey |
| 响应式和可访问性 | representative viewport + keyboard/screen-reader-oriented test |
| 长内容和滚动 | browser overflow verification |

字符串正则测试只能证明源代码包含某个字符串，不能证明页面行为正确。

### 8.2 Claimant 验收

- 未登录可以开始对话并发送合法请求；
- 登录/注册成功后回到原 workspace；
- 匿名 session 登录后保留消息、字段和草稿；
- history 打开已有 session，不制造额外的“resume”流程；
- 新建聊天创建新 session，空 session 才允许复用；
- Agent greeting、动态字段、字段编辑和自然语言纠正可用；
- 右侧 Details 真正隐藏/展开，不留下空栏；
- 文件、语音、Listen、无障碍和不可用状态诚实表达；
- handoff 后状态卡片、下一步和人工支持信息与后端 projection 一致；
- motor、home、contents 三条 VP 路径使用同一套组件和行为原则。

### 8.3 Workbench 验收

- 队列由责任/工作、优先级、tag/signal 三层组织；
- Incomplete Claim 可见且不折叠；
- fraud 只显示为 signal/tag，不被前端推成结论；
- Claim tab 可打开、切换、关闭、刷新恢复；
- 同一 Claim 默认不重复创建 tab；
- revision 变化会提示并保留草稿；
- 首屏只突出一个主动作；
- 具体动作按 allowed action 和 target gating；
- staff-only 内容不会进入 claimant projection；
- Workbench Agent session 跨 Claim 切换保持全局状态；
- 外部服务展示 participant、purpose、consent、data、status、owner、result、verification 和 limitation；
- 没有把 fixture 描述成生产完成；
- 不含 demo queue、reset、开发控制和旧静态页面依赖。

### 8.4 VP 级别的完整验收

一次 VP 验收必须沿三条路径分别走完同一套核心闭环：

```text
motor / home / contents
  → natural-language intake
  → registered dynamic fields
  → evidence or retrieval when required
  → Runtime-authorized action or handoff
  → shared Claim Context
  → claimant and staff projections
```

每条路径至少要有：

- 一条正常推进案例；
- 一条缺失或冲突信息案例；
- 一条权限、外部服务或不可用能力失败案例；
- 一条刷新、重试或 revision 变化案例；
- 一条 claimant 与 staff 交接后继续处理的案例。

验收记录必须标注是真实 API、仿真 adapter 还是 fixture 测试；不能因为 fixture 通过就宣称真实链路完成。

---

## 9. 典型反模式与推荐改法

### 9.1 用 `availability !== blocked` 代表可执行

问题：把 `confirmation_required`、`available` 和 `blocked` 混为一谈。

改法：

- `available` 才表示可以执行；
- `confirmation_required` 必须先展示确认；
- `blocked` 展示原因但不提供执行按钮；
- 主动作按 `primary_action_code` 定位。

### 9.2 用角色 access 推断所有权限

问题：primary/coworker 只能说明大致 Claim access，不能说明每个 signal、WorkItem、第三方请求或状态动作都允许。

改法：每个 mutation 控件都绑定具体 action code、target ref、revision 和 projected availability。

### 9.3 用自由文本填写正式 action

问题：Action Registry、reason code、影响范围和审计边界被绕过。

改法：后端返回注册动作和输入 schema，前端渲染受控输入；开放式说明只能作为 action 的补充文本，不能决定 action 类型。

### 9.4 在前端写第三方状态机

问题：provider、责任方、验证状态和恢复路径被页面硬编码。

改法：后端投影 typed lifecycle、pending owner、verification、limitation 和 next action；前端只负责格式化和渐进式展示。

### 9.5 第一屏列出所有动作

问题：员工无法判断优先级，主动作被次要动作淹没。

改法：显示后端指定的唯一主动作；协作、重排队、资料查看和审计作为辅助区域按需展开。

### 9.6 用新 CSS 包裹旧架构

问题：页面看起来焕新，但状态、路由和数据边界仍不可维护。

改法：先拆 route、state、API、projection 和组件，再迁移视觉；不要在单文件中继续追加覆盖。

### 9.7 把旧单页面迁移当成产品目标

问题：团队把大量时间用于复刻旧 landing page、旧按钮或旧布局，结果新 main 仍然没有清晰的路由、状态、组件和真实 API 边界。

改法：旧页面只用于识别需要保留、取代、删除或迁移的功能；新实现以本标准的 big picture、Claimant/Workbench 旅程和后端 projection 为验收基线。迁移完成后删除或归档旧实现，不能让“与旧页面视觉一致”成为完成条件。

---

## 10. 实现 Agent 指导性提示词

下面的提示词可以直接提供给负责前端或前后端联动的实现 Agent：

```text
You are implementing Northwind FNOL, an insurance claim-entry and coordination product.

Treat the current product direction and repository contracts as authoritative. Do not optimise
for a page that merely renders or a test suite that merely passes. The minimum acceptable result
is a coherent, production-shaped implementation: the right user journey, the right state owner,
the right permission boundary, the right failure behavior, and an implementation that can evolve.

Design and implementation rules:

1. Claimant is Agent-first. Let the claimant describe what happened in natural language. Use the
   Agent, registered fields, branch rules, retrieval, policy/history/database tools, evidence and
   runtime actions to progress the Claim. Do not turn the product into a fixed questionnaire,
   landing-page card selector or Guided Motor flow.

2. Staff Workbench is task-first. The first viewport must answer what needs attention, why, who
   owns the next step, what is missing or risky, and what one primary action is available. Do not
   show every action with equal visual weight.

3. The model is advisory. It may understand, extract, retrieve, explain, propose fields, propose
   branches, propose tools and draft communication. Runtime validates identity, scope, registry,
   permission, revision, state transition, side effects and audit before execution.

4. Never infer business truth in the frontend. Do not calculate priority, fraud, responsibility,
   blocking relationships, next action or third-party lifecycle from tags, strings, array order,
   provider names or field counts. Consume backend projections.

5. Treat allowed_actions as action contracts. Use the backend primary_action_code. Distinguish
   available, confirmation_required and blocked. Match every control to the exact action code and
   target ref. Do not gate mutations only by a broad role or current_staff_access.

6. Dynamic Form is rebuilt from confirmed facts, unresolved work, the active content branch and
   the current action. It uses only registered fields. Show claimant-safe fields progressively;
   highlight newly changed fields; allow direct editing and natural-language correction.

7. Keep projections separate. Never send a complete internal WorkingClaim to the browser and
   filter it on the client. Claimant, staff, admin and audit projections must be assembled by the
   backend with explicit visibility rules.

8. External services are lifecycles, not generic request buttons. Preserve purpose, data scope,
   consent, request type, submission, tracking, verification, reconciliation, retry, failure,
   limitation, pending owner and result unknown. Provider is not automatically the responsible
   party. Northwind is the business organisation, not an inferred executor.

9. Use React/Vite component boundaries, real routes, shared state containers and one shared token
   source. Do not continue a complex application in one static index.html, one global app.js,
   one giant CSS file, innerHTML templates or post-hoc selector overrides.

10. Use the warm Northwind token system. Do not reintroduce the old white-green palette. Claimant
    body text is at least 16px; Workbench business text is at least 14px. State never relies on
    colour alone. Do not depend on hover for key information.

11. Preserve anonymous-session behavior. An unauthenticated claimant may start a conversation.
    Login/register must return to the existing workspace and bind the anonymous session exactly
    once. Profile is not the post-login landing page.

12. Every error must state what happened, why it happened, and what the user can do now. Unknown
    outcomes must not be labelled success or failure. Keep revision, idempotency, source refs and
    audit information intact.

13. Test the behavior at the right level: component, route/browser, API contract, authorization,
    concurrency, external-task transition, responsive and accessibility. A source-string test
    cannot prove a user journey.

14. Treat the new `main` as the only product baseline. Do not spend the implementation budget
    polishing the old single-page layout. Preserve a legacy behavior only when it is explicitly
    part of the current journey; otherwise replace it with a route, component and API-backed
    behavior that matches this standard.

15. Keep the big picture visible in every slice: a claimant can start naturally, an Agent can
    understand and propose, Runtime can authorize and execute, and both claimant and staff can
    continue from the same audited Claim Context. If a slice cannot explain where it sits in this
    loop, its scope or design is incomplete.

Before coding, inspect the exact current branch, SPEC, API contract, projection fields, tests and
related ownership. Separate verified implementation facts from intended design. If a field or
permission must change, record the proposed change and its impact before changing the contract.
After coding, report what is implemented, what is still unavailable, what was tested, and which
production claims are deliberately not made.
```

---

## 11. Review checklist

### 产品和旅程

- [ ] 是否仍然存在旧 landing page、Guided Motor 或固定步骤主路径？
- [ ] claimant 是否可以匿名开始并在认证后保留上下文？
- [ ] 登录成功后是否进入 workspace，而不是 Account？
- [ ] history 是否打开 session，而不是制造额外 resume 流程？
- [ ] Workbench 是否先表达任务顺序而不是展示数据库镜像？

### 架构和组件

- [ ] 是否使用真实路由和权限保护？
- [ ] 是否拆分 page、state、API、projection 和组件？
- [ ] 是否消除了单 HTML、全局字符串模板和 CSS 覆盖堆叠？
- [ ] claimant 与 staff 是否共享 token 但保持不同密度？

### 状态和权限

- [ ] 主动作是否来自 `primary_action_code`？
- [ ] 是否区分 available、confirmation_required 和 blocked？
- [ ] 每个 mutation 是否匹配具体 action code、target 和 revision？
- [ ] 是否避免用 access level 推断具体权限？
- [ ] 是否避免前端推断 priority、fraud、责任方和第三方 next step？

### 数据和后端

- [ ] claimant/staff/admin/audit projection 是否明确分离？
- [ ] 动态字段是否全部来自 Field Registry？
- [ ] Agent proposal、Runtime approved plan 和实际结果是否分开？
- [ ] 外部服务是否覆盖授权、提交、追踪、验证、未知结果和恢复？
- [ ] 是否保留 source、revision、actor、timestamp、idempotency 和审计记录？

### 视觉和可访问性

- [ ] 是否使用共享 token，且没有旧绿色值回归？
- [ ] 主要信息是否不依赖 hover？
- [ ] 状态是否不只靠颜色？
- [ ] claimant 文字是否至少 16px，Workbench 业务文字是否至少 14px？
- [ ] 键盘、触控、移动端、focus、动态错误和滚动是否有真实验证？

### 能力诚实和测试

- [ ] fixture、仿真和未验证 provider 是否明确标记？
- [ ] unavailable、error、pending、unknown outcome 是否有可继续路径？
- [ ] 测试证据是否真的覆盖声称的行为，而不只是检查字符串？
- [ ] motor、home、contents 是否作为 VP 验证路径，而不是产品能力限制？
- [ ] 是否删除正式 Workbench 中的 demo/reset/development controls？

---

## 12. 最终验收判断

只有在以下条件同时满足时，才可以说一个前端重构切片达到“西装”标准：

```text
正确的用户旅程
  + 正确的状态和权限边界
  + 正确的 projection 和 action contract
  + 正确的视觉层级与 token
  + 正确的失败、恢复和审计
  + 正确匹配行为的测试证据
  = 可合并的 Northwind 实现
```

如果只是把旧页面换成 React、换成新颜色、增加几个卡片或让测试通过，而仍然保留错误的主路径、前端业务推断、自由文本动作、混淆的责任方、单一 fixture 设计或不完整的 projection，那么它仍然是 T 恤，不是西装。
