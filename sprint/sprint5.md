# Sprint 5：Delivery Freeze, Evidence Validation, and Poster

## 1. 阶段定位

Sprint 5 是 Scenario 8 的最终交付和 poster sprint。正式周期以
`schedule/AWS Challenge Calendar.xlsx` 为准，从 2026-09-28 至 2026-10-09，终点是
Poster Competition。

本 Sprint 不再无边界扩大功能。工作围绕三个结果展开：

1. 完成前后端、模型、Runtime、Workbench 和 AWS 路径的开发收尾，并冻结稳定的
   Release Candidate。
2. 在冻结版本上完成技术验证、不少于 100 个完整受控旅程和独立真实盲测，形成可复核的
   测试数据、失败分类和验收结论。
3. 基于同一 exact head 的证据录制演示视频，完成并打磨 slides 和 poster；在下一次与
   University Supervisor Vita 和 AWS Mentor Jay Qin 的 meeting 前交付 slides 初版。

Sprint 5 是当前两周的项目交付阶段，不代表长期产品路线。任何新增实现都必须直接服务于
稳定测试、Scenario 8 expected outcome、AWS 迁移、证据采集、演示或 poster；其他需求记录为
后续事项。

## 2. 一句话目标

> 在冻结的 Release Candidate 上，完成模型、Runtime、前后端、Workbench 和 AWS 路径的
> 技术验收；用不少于 100 个完整合成旅程和独立真实盲测形成可复核数据；最后基于同一
> exact head 制作演示视频、slides 和 poster 证据。

## 3. Scenario 8 验收目标

最终证据继续覆盖 10 个代表性场景：

- 5 个 motor；
- 3 个 home；
- 2 个 contents。

每条正式旅程从初始报案运行到预期终点，并按场景使用完整材料包。验收至少记录：

1. 是否无需 follow-up 即完成，目标为 80% 或以上。
2. Severity classification 的 blind review 结果。
3. Fraud flag precision，测试集不得出现 false positive。
4. Claimant effort，目标为少于 5 分钟、少于 10 个问题。
5. Claim number、expected timeline、最终 Claim 状态和完整证据链。

这些指标来自 synthetic controlled corpus 和 blind role-play，不能未经说明外推为 Northwind
生产表现或真实 Business ROI。`$4.2M` staffing base 和 `$12M` fraud loss 仍是 Scenario 8
背景，不是项目已经实现的节省额。

## 4. 交付原则

### 4.1 Release Candidate 冻结

- `RC1` 是技术测试开始前的功能冻结版本。此后只接受阻塞验证、数据安全、权限、状态和
  完整旅程的缺陷修复。
- `RC2` 是受控测试优化完成后的最终证据版本。真实盲测、视频、slides 和 poster 均基于
  RC2。
- 每个版本必须记录代码 exact SHA、Prompt Pack、模型 profile、Registry 版本、数据 profile、
  材料包版本和环境状态。
- Freeze 后发现的新功能需求默认延期。只有直接影响 expected outcome 或证据可信度的内容
  可以解除冻结。

### 4.2 测试和调优隔离

- 技术测试用于判断系统是否具备进入批量测试的条件，不计入最终成功率样本。
- 受控测试集可用于 Runtime、Prompt 和交互调整，但每次变更必须产生新版本并重跑受影响
  案例和固定回归集。
- 盲测集在 `RC2` 前锁定。开发者和调优人员不得提前读取隐藏标签或预期结果。
- 第一次盲测结果不可覆盖。修复后的结果属于新的 run/round。
- Controlled 和 blind 的结果分别报告，不合并为一个未经解释的成功率。

### 4.3 能力诚实

- 模型真实接入已经实现；测试必须区分实现存在、provider 可调用和完整旅程已验证。
- AWS 真实迁移和接入属于 Sprint 5 必须完成的交付。若外部账号、权限或服务条件阻塞，必须
  记录实际调用、错误和 unavailable/blocked 状态，不能用 fixture 替代。
- Assessor、repairer、Police 等第三方参与者使用 provider-neutral simulation。学生项目不要求
  建立真实商业服务关系，但 simulation 必须覆盖 consent、共享范围、责任方、幂等、失败、
  unknown outcome、验证和恢复，并明确标记 provenance。
- Fixture、simulation、configured、reachable、verified 和 production-integrated 必须保持区分。

### 4.4 数据、版权和隐私

- 测试材料必须是匿名、synthetic 或具有明确使用权的内容。
- 生成材料应记录生成方式、生成模型、时间、用途和 synthetic 标记。
- 不使用真实 claimant 数据、真实 Claim、真实身份材料或未经授权的第三方文件。
- Ground truth、fraud/severity 标签和预期结果与模型可见输入分开保存，避免标签泄漏。

## 5. 阶段门

阶段只表示依赖和验收顺序，不分配 Week、Day 或固定日期。

### 阶段 A：开发收尾与 RC1

目标是把当前实现收敛成可稳定测试的版本。

交付内容：

- 完成 #769、#770、#771 范围内仍阻塞完整旅程的代码和契约工作。
- 确认 Claimant、Workbench、Admin、Backend、数据库、MinIO、模型和相关 adapter 的实际版本。
- 完成 AWS 迁移前置条件、连接配置、权限检查、失败状态和最小真实调用路径。
- 清除正式界面中的占位内容、无行为按钮、误导性成功状态和本地业务推断。
- 确认 motor、home、contents 的最小 smoke journey 能在同一 exact head 上启动和恢复。
- 建立 RC1 版本清单和已知限制。

进入下一阶段的门槛：

- 没有阻断技术测试的已知状态或权限缺口。
- 所有运行组件能够从受支持入口启动并报告真实 readiness。
- 新功能冻结，只允许验证阻塞修复。

### 阶段 B：技术 readiness 验证

技术性测试不计入最终 100-case 结果。它证明测试环境和关键路径可被信任。

#### RAG 和模型调用

- 验证模型真实触发 RAG/context lookup，而不是只靠预载上下文或模型常识回答。
- 验证检索过滤、source/version/section citation、无结果、冲突和 unavailable 路径。
- 验证最终回答实际使用了授权检索结果，且不泄漏内部 retrieval metadata。
- 记录 input/output/cache token、latency、模型 profile 和实际 provider。
- 验证 tool request、Runtime authorization、tool result、re-plan 和最终回复保持可追溯。

#### 图片和文档

- 验证 JPEG、PNG 和 PDF 从上传、存储、授权、model input、Runtime validation 到前端 readback
  的完整路径。
- 覆盖正常、不可读、损坏、过大、错误 media type、provider 不支持、处理失败和跨 Claim 越权。
- 当前正式 upload contract 不支持 DOCX。Sprint 5 不为非必要 DOCX 扩大核心范围；应验证 UI/API
  明确拒绝并给出可操作的转换说明。只有 Maintainer 在 RC1 前明确改变范围时，才建立有界的
  DOCX 安全解析/转换任务。
- 区分 provider 原生 PDF 输入与应用层提取，不能把解析器结果描述为模型原生能力。

#### Claimant 前端和完整旅程

- 建立全部 button、link、menu、route 和入口的 control inventory。
- 每个控件必须有真实 API/route 行为，或明确的 disabled/unavailable 状态和原因。
- 禁止占位文案、静态成功提示、不可达入口和无反馈动作。
- 验证 natural-language intake、Dynamic Form、Evidence、RAG、handoff、agreement、Claim creation、
  resume、history 和错误恢复。
- 检查重复问题、错误字段确认、跨 family 泄漏、语义重复、内部字段泄漏和责任方错误。

#### Workbench 和 Staff Agent

- 验证 queue、Claim context、conversation、Evidence、work item、handoff、external task 和
  claimant update 的完整工作流。
- 验证 Staff Agent 在当前 staff identity、role、Claim scope 和 task 中工作。
- 明确区分 read、explain、propose、draft 和 execute。
- mutation 必须经过注册 action、resource scope、revision、confirmation、idempotency 和 audit。
- 覆盖 unauthorized、wrong Claim、stale revision、blocked action、unknown outcome 和恢复路径。
- 验证任务优先的信息层级、唯一主动作、键盘操作、响应式布局、loading/empty/error/stale 状态。

进入下一阶段的门槛：

- 技术测试矩阵通过，或每个失败都有明确的 blocker、owner 和处理方式。
- 测试环境不会静默回退到 controlled Runtime、fixture 或错误 provider。
- 记录格式能够保存 exact head、配置、token、结果和失败分类。

### 阶段 C：测试标准与材料库

目标是形成不少于 100 个可重复、可追溯、具有真实场景语义的完整测试包：

- 50 个 motor；
- 30 个 home；
- 20 个 contents。

“一份测试材料”定义为一个完整测试包，而不是一张图片或一个 PDF。每个测试包至少包含：

- `case_id`、family、场景摘要和 claimant persona；
- 初始输入，以及多轮回答规则或完整事实表；
- 相关图片、PDF 和材料清单；
- 正常、缺失、模糊、冲突、过期、不可读或 unavailable 等材料条件；
- 模型不可见的 ground truth：事实、severity、fraud signal、预期终点和禁止行为；
- 预期 RAG source、允许的结果差异和必须发生的 Runtime 动作；
- 文件来源、生成方式、生成模型、时间、使用权和 synthetic 标记；
- 文件间一致性或有意设置的冲突；
- test-pack schema/version、场景版本和适用 Runtime/Registry 版本。

材料标准至少覆盖：

- 事故或损失照片；
- Police report 或官方报告类材料；
- Policy wording/schedule；
- Receipt、invoice、valuation 和 proof of ownership；
- Assessor report、repair quote 和 attendance note；
- Consent record、unavailable notice 和 conflicting document。

每类材料定义必要结构化信息、可选信息、禁止信息、质量条件和边界变体。生成后执行内容、
文件格式、可读性、跨文件一致性、隐私和版权检查。

进入下一阶段的门槛：

- 100 个测试包全部通过 schema 和材料质量检查。
- 输入材料与隐藏标签物理或逻辑隔离。
- 测试包版本冻结；测试执行期间不得修改 oracle 以迎合实现。

### 阶段 D：受控 E2E 测试与优化

先运行少量 pilot，确认执行器、材料加载、结果记录和 failure taxonomy 可用，再执行完整
100-case 受控测试。

每次运行至少记录：

- case ID、exact code head、Prompt Pack、model/data profile 和 Registry 版本；
- 开始/结束时间、turn 数、问题数、重复问题、确认和上传次数；
- RAG/tool 调用、citation、token、latency 和 provider 状态；
- Claim、Evidence、handoff、external task、Workbench 和 claimant projection；
- severity/fraud 预测与隐藏 ground truth；
- Claim number、expected timeline、最终状态和 next-step owner；
- `completed`、`partial`、`fixture-only`、`unavailable`、`blocked` 或 `failed`；
- 截图、日志和可复核结果位置。

失败分类至少包括：

- 模型理解或事实提取；
- RAG 检索、来源或引用；
- 图片/PDF处理；
- Runtime 权限、状态或副作用；
- Persistence、revision 或 idempotency；
- Claimant 前端交互或渲染；
- Workbench 权限、工作流或 UX；
- AWS/环境 unavailable；
- 测试数据或 oracle 错误；
- 非确定性或 flaky failure。

测试发现的产品缺陷按责任回流：

- #769：Backend、数据、AWS、Evidence、RAG 和 integration。
- #770：模型、Runtime、Prompt、行为和工具授权。
- #771：Claimant、Workbench、浏览器旅程和 UX。

任何修改都创建新版本，不覆盖原 run。完成修复后重跑受影响案例和固定回归子集。

进入下一阶段的门槛：

- 100-case 结果完整、可解析并通过数据质量检查。
- 所有 blocker 已修复或以明确限制接受。
- 调优已停止，形成 RC2 exact head 和配置清单。

### 阶段 E：RC2 与真实盲测

盲测用于验证系统面对开发者未预设输入时的泛化能力。

- 在 RC2 前锁定测试材料和隐藏标签。
- 测试者可自由表达，但每次测试必须保留完整 transcript、材料、时间、问题数和最终状态。
- 开发和 Prompt 调优人员不得提前查看盲测 oracle。
- 第一次结果永久保留；修复后的结果记录为新的 round。
- 成功和失败全部进入统计分母。可以展示成功案例，但不能只选择成功案例扩充 poster 数据。
- Controlled 和 blind 结果分别报告，并分别注明样本数、版本、环境和限制。

进入下一阶段的门槛：

- 每次盲测都有成功/失败分类和完整证据。
- 缺陷已经形成修复或限制记录。
- 若 RC2 后发生代码、Prompt 或配置变化，则建立新的 release candidate 和独立复测记录。

### 阶段 F：标注、数据处理与统计

目标是形成可以直接进入 poster 的证据集，同时保留完整分母和限制。

正式指标包括：

- 无需 follow-up 的完成比例；
- severity blind review 结果；
- fraud flag precision 和 false positives；
- claimant 时间、问题数、重复问题和纠正次数；
- Claim creation、claim number、expected timeline 和完整证据链。

补充技术指标包括：

- RAG 调用、citation support、无结果和冲突处理；
- 图片/PDF ingestion 和模型可读率；
- token、latency、tool calls 和失败/重试；
- handoff 完整性和 staff 重建上下文成本；
- Workbench action 成功、权限拒绝、stale revision 和 unknown outcome；
- AWS 连接、调用、失败和恢复结果。

统计要求：

- Controlled、blind、fixture、simulation、model-backed 和 AWS 结果分层报告。
- 不删除失败样本，不通过修改 oracle 抬高成功率。
- 每个数字可以追溯到 case IDs 和 exact-head run records。
- 使用 synthetic corpus 得出的结果只能说明该测试集，不外推为生产准确率或 ROI。

### 阶段 G：演示视频、slides 和 poster

演示材料从验证证据反推，不先写结论再寻找支持截图。

建议叙事顺序：

1. Scenario 8 问题与 expected outcome。
2. Northwind 产品主张和 Agent-first 旅程。
3. Claimant 与 Claims Professional 两端体验。
4. Model proposal 与 Runtime authorization/execution 的边界。
5. 一条 Claimant 到 Claim creation 的完整演示。
6. 一条 Workbench 接手并推进的完整演示。
7. 100-case controlled 结果与 blind test 结果。
8. 失败分类、修复结果、限制和 AWS 状态。
9. Business ROI 机制和下一步，不把背景数字写成已实现节省。

交付要求：

- 视频、截图、图表、slides 和 poster 使用同一 RC2 exact head 或明确记录差异。
- 每个结论标明 evidence level、样本数、model/runtime profile 和 simulation/AWS 状态。
- 演示脚本与操作逐步对应，并提前按秒排练。
- 若现场链路无法稳定复现，使用经过验证的预录短视频作为正式演示路径。
- 在 Vita 和 Jay Qin 的下一次 meeting 前完成 slides 初版；初版必须包含首轮真实测试数据，
  不能只有页面截图和未来计划。

## 6. Super-issue 结构

### 现有开发责任线

现有 super-issue 继续承载开发收尾和测试发现的产品修复：

| Super-issue | 责任边界 |
| --- | --- |
| #769 Backend/AWS | Backend、数据、Evidence、RAG、AWS 和 adapter |
| #770 Agent/Runtime | 模型、Runtime、Prompt、action authority 和恢复 |
| #771 Journey/frontends | Claimant、Workbench、浏览器旅程、projection 和 UX |

测试任务不通过修改 oracle 或建立私有字段修复产品问题。缺陷必须回到对应开发责任线，并引用
发现它的 case/run。

### 新增测试和交付责任线

#### S5-D：Test corpus and material governance

范围：

- 测试包 schema 和材料标准；
- 图片/PDF/报告/receipt 等材料模板；
- 生成流程、版权、隐私和 provenance；
- Ground truth 和模型可见输入隔离；
- 100 个完整测试包的生成、验证、版本和冻结。

不包含产品代码修复、执行结果统计或 poster 结论。

#### S5-E：Journey validation and evidence analysis

范围：

- 技术 readiness gate；
- pilot、100-case controlled E2E 和 blind testing；
- 执行记录、失败分类、rerun 和版本管理；
- 标注、数据清洗、统计和 poster evidence package；
- 将缺陷分派回 #769、#770 或 #771。

不包含私自修改测试 oracle、隐藏失败或直接实现跨 owner 产品修复。

#### S5-F：Poster and demonstration delivery

范围：

- 场景与证据叙事；
- 视频脚本、录制和演练；
- 截图、图表、slides 和 poster；
- 每个结论的 exact-head evidence 和限制；
- Vita/Jay Qin meeting 前的 slides 初版与反馈收敛。

不包含未经验证的产品主张、生产能力或 ROI 数字。

每个新增 super-issue 和 subissue 必须指定实际 owner、依赖、非目标和可复核输出。材料制定、
测试执行和最终评价应保持足够独立，避免实现方通过调整 oracle 证明自己正确。

## 7. 最终 Definition of Done

Sprint 5 只有在以下条件同时满足时才完成：

- RC1 和 RC2 均有 exact SHA、配置清单和限制记录。
- #769、#770、#771 的阻塞性交付已收尾，或以不影响最终证据的方式明确延期。
- RAG、token、图片/PDF、Claimant、Workbench Agent、权限、完整旅程和 AWS 技术测试有结果。
- 不少于 100 个完整测试包通过材料标准和 schema 检查。
- 100-case controlled 测试和独立 blind tests 均保留完整分母、成功、失败和限制。
- 测试结果能够重现，并可追溯到 case、材料、模型、Prompt、Registry、环境和 exact head。
- 第三方 simulation 与 AWS 真实集成的证据边界清楚。
- 演示视频、slides 和 poster 使用已冻结证据；slides 初版在指定 meeting 前完成。
- Poster 中的 expected outcome、Business ROI 机制、stretch goal 和限制均有明确来源。

## 8. 开始前仍需确定的执行信息

以下信息不改变本 Sprint 的目标，但必须在相应 super-issue 进入 Ready 前确定：

- S5-D、S5-E、S5-F 的 primary owner 和协作者交付物；
- Blind test 的样本量、测试者和隐藏标签保管方式；
- 100 个测试包二进制材料的受控存储位置和版本策略；
- RC1/RC2 的批准人和解除冻结条件；
- Vita/Jay Qin meeting 的实际时间、slides 初版格式和反馈入口；
- Poster Competition 的尺寸、提交格式和展示时长。
