# Sprint 2 第一周计划：按栈负责，按路径并行

## 范围

- **周期：** 2026 年 8 月 17 日至 21 日
- **阶段：** Sprint 2 第一周
- **容量：** 5 人，每人 40 小时，共 200 人时
- **目标：** 让五条 MVP 业务路径在各自需要的技术栈中同步推进，每个栈都能独立运行和验收

## Sprint 2 主张

用两周把 Sprint 1 的全路径 prototype 推进为可重复运行的 MVP：团队按栈
负责，并围绕五条业务路径并行开发；可用的 AWS 能力从第一周起持续接入，
最终汇合为从报案到 claim 创建或人工接管的端到端路径。

## 栈级责任

人员按栈负责，不把一条完整业务路径交给单个人。

| 成员 | 主要责任栈 | 栈内范围 |
| --- | --- | --- |
| `Ysoseri1224` | Claimant frontend + Agent behaviour | claimant 对话、表单、恢复、人工请求、Agent action、路径选择和 authority boundary |
| `liyang6620` | Backend API + AWS integration | API、domain action、AWS access/service 接入、claim creation/routing 和 fallback boundary |
| `jxu316-arch` | Persistence + session + policy/history data | Claim State 持久化、revision、resume、policy/history mapping 和 backend/AWS 协作 |
| `LLL263` | Staff workbench + handoff/write-back workflow | staff queue、claim context、handoff、internal signals、staff action 和状态回写 |
| `bdfa123` | Evidence/media lifecycle + fixture infrastructure | evidence 状态、图片/PDF、mock storage、来源、可见性、proposed facts 和场景 fixture |

这些是主要责任，不是禁止其他人协作。任何接口变化都由提供方和使用方共同
确认。

## 五条纵向业务路径

Week 3 的任务按以下路径组织，每条路径由多个栈负责人同时贡献：

1. **Clear claim：** 自然语言报案、事实确认、下一步推进和 claim creation。
2. **Pending evidence and resume：** 材料待生成或待补时继续安全步骤，并支持稍后恢复。
3. **Human request and urgent handoff：** 用户请求人工或出现紧急信号时，带结构化上下文转交 staff。
4. **Policy/history and professional review：** 使用可用数据支持 policy/history 查询，并把高影响判断交给专业人员。
5. **Staff action and write-back：** staff 接管、处理、记录结果，并把适当状态更新给 claimant。

一条路径可以暂时使用 fixture，但 customer、Agent、API、data、staff 和 evidence
对同一 Claim State 的理解必须一致。

## 并行开发原则

### 栈级负责，路径级协作

每个人维护自己的主要技术栈。任务围绕业务路径安排，因此同一条路径会同时
出现 claimant/Agent、API/data、staff 或 evidence 方面的任务。

### AWS 从第一周持续推进

`liyang6620` 和 `jxu316-arch` 从第一天开始核对并接入可用 AWS 能力。已经
确认的能力直接进入对应路径；尚未确认的部分保留 adapter 和 fixture。第二周
不是 AWS 首次接入时间。

### 契约是边界，不是大阶段

现有 API、Claim State、Agent action 和 visibility contract 是并行开发边界。
需要修改时，由相关栈负责人一起更新，其他路径继续使用 fixture 工作，不等待
一份“大设计”全部完成。

### 测试和质量由全员负责

- 每个栈负责人完成自己的 component checks。
- API 和 persistence contract 由 `liyang6620`、`jxu316-arch` 负责。
- claimant/Agent 路径由 `Ysoseri1224` 实现并由其他成员独立检查。
- staff/handoff 路径由 `LLL263` 实现并由其他成员独立检查。
- evidence/media 路径由 `bdfa123` 实现并由其他成员独立检查。
- `bdfa123` 可以维护 fixture 工具，但不单独掌握最终质量门。

## 第一周推进顺序

| 日期 | 重点 |
| --- | --- |
| Day 1 | 在五条路径中确认各栈输入输出，并建立可独立运行的 fixture 基线 |
| Day 2 | 推进 clear claim 与 pending evidence/resume 的各栈实现 |
| Day 3 | 推进 human/urgent handoff、policy/history review 和 staff write-back |
| Day 4 | 在各栈内部连接相关路径，补齐失败、fallback 和 visibility 状态 |
| Day 5 | 由不同成员交叉验收五条路径的栈级输出，并确定 Week 4 汇合输入 |

## Week 3 完成条件

- 五个责任栈都有可独立运行的实现和 component checks；
- 五条业务路径均有 claimant、Agent、API/data、staff 或 evidence 中需要的对应输出；
- 已确认的 AWS 能力已经进入 adapter 或对应路径，未知项有 fallback 和记录；
- 同一 Claim State 不存在互相冲突的私有版本；
- evidence/media 是可运行产品能力，不只是测试数据；
- 每项模块输出都由另一名成员独立检查；
- Week 4 所需 endpoint、state、adapter、fixture 和已知 blocker 已明确。

详细 card 见同目录的 `sprint2-week1-kanban-draft.md`。确认前不会创建到
GitHub Kanban。
