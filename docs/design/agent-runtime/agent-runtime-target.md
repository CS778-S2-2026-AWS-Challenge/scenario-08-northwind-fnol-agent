# Agent Runtime Target

## Status and Authority

This document is the engineering target for the Northwind FNOL Agent Runtime. It is a
guidance contract for the target architecture, not a claim that every object or route is
implemented today.

- Product behaviour and acceptance remain in `SPEC/`.
- The implemented HTTP contract remains in `docs/api.md`.
- Runtime safety and authority rules remain in `docs/agent-runtime-policy.md` and
  `SPEC/06-safety-and-governance.md`.
- Compatibility and removal of the current transport are defined in
  `docs/design/agent-runtime/agent-runtime-migration.md`.
- Repeatable implementation evidence is maintained in `docs/status/agent-runtime-progress.md`.

The target runtime must be read as a product-guided design. An object earns a place by
solving a concrete FNOL problem and by having an authority boundary, failure behaviour,
and a proof path.

## Product Outcome

The intended connected journey is:

```text
natural claimant or staff language
 -> multi-intent understanding
 -> one authoritative Claim State
 -> targeted questions and evidence-aware progress
 -> cited, source-preserving proposals
 -> deterministic or staff authority for material actions
 -> recoverable external work and a decision-ready staff case
```

The Agent is not a form reader or an unrestricted chatbot. It carries the complexity of
the FNOL process while keeping the claimant's interaction simple and keeping staff
decisions explicit.

## Target Objects and FNOL Problems

| Object | FNOL problem it solves | Authority and state effect | Required proof |
| --- | --- | --- | --- |
| `TurnPlan` | One message may contain an accident description, an injury concern, and a request for human help. Field-by-field questioning repeats work. | Plans conversation moves, candidate facts, tools, unresolved work, and one runtime directive. It cannot write Claim State. | Multi-intent fixture, reduced repeated-question count, and safe partial-understanding test. |
| `AgentProposal` | A model can produce a plausible answer without producing a trustworthy claim fact or action. | Carries structured proposals with sources and confidence. Runtime validation may reject it; it has no side effect. | Malformed, conflicting, unsupported, and source-preserving proposal tests. |
| `ExecutionPlan` | Several proposed actions may depend on confirmation, authority, revision, or an external result. | Contains only validated actions and rejected proposals. The server, not the model, determines execution. | Authority matrix, revision-conflict test, and ordered multi-action scenario. |
| `ActionEnvelope` | Tool and state operations need a stable target, purpose, source, permission, and idempotency boundary. | Namespaced action with preconditions, authority, visibility, expected effects, and status. It cannot redefine policy. | Allow-list, prompt-injection, visibility, idempotency, and high-impact blocking tests. |
| `TurnResult` | “The Agent suggested it” and “the system completed it” are different facts, especially after a timeout. | Records actual state/tool outcomes, unknown outcomes, limitations, and the final role-safe response. | Provider failure, unknown external outcome, retry reconciliation, and claimant projection tests. |
| `WorkItem` | A police report, professional review, or external request can remain outstanding while safe work continues. | A bounded unresolved-work record around Claim State. It does not become a second lifecycle or claim truth. | Pending-evidence progress, resume, ownership, completion, and blocked-action tests. |
| Fact assertion history | A resumed claimant may refine, correct, repeat, or contradict an earlier answer without the Runtime silently discarding either source. | Keeps one selected Claim fact plus source-linked assertions and resolution state. Runtime, not the model, classifies their relation; an unresolved discrepancy is not a fraud finding. | Equivalent, correction, conflict, cross-session provenance, and role-visibility tests. |
| Question accounting | A complete FNOL must remain thorough without exceeding the challenge's customer-effort threshold. | Persists a nine-question Claim-trajectory budget and repeated-field accounting across sessions; exhaustion saves progress and transfers remaining follow-up without another question. | Motor, home, contents, resume, repetition, and exhausted-budget tests. |
| Content branch | Motor, collision, another party, and evidence needs can overlap and change after correction. | A published rule activates or exits branches; the model may only propose candidates. Branches do not represent lifecycle. | Branch activation/correction fixtures and no irrelevant cross-branch questions. |
| Staff `@Agent` | Staff need summaries, evidence comparison, and next-step help without rereading a full transcript. | Reads authorised context and proposes or drafts. Staff must explicitly accept sends, mutations, disclosures, and high-impact actions. | Suggestion-versus-decision test, claimant-send control, source citation, and role-scope test. |

## Claim State Authority

Claim State is the only authoritative current claim truth. Sessions, forms, Workbench
views, content branches, WorkItems, proposals, plans, external-service records, and
summaries are bounded records or projections around it.

```text
Claim State
  <- validated state mutation with revision and authority

TurnPlan / AgentProposal / ExecutionPlan / WorkItem / UI projection
  -> plan, propose, track, or display; never create competing Claim truth
```

Content branches answer which information and rules apply. Lifecycle and WorkItems answer
who owns work, what is waiting, and which safe step can continue. Neither may silently
rewrite a confirmed fact or replace the current Claim revision.

## Target Turn Sequence

```text
authorised input and current Claim State
 -> bounded context and applicable Registry versions
 -> TurnPlan
 -> provider-neutral model request
 -> AgentProposal
 -> schema, source, permission, revision, and authority validation
 -> ExecutionPlan
 -> idempotent tool and Claim operations
 -> TurnResult and role-safe projections
```

Model output, retrieved knowledge, and extracted evidence are inputs. They do not grant
permission, confirm facts, or authorise high-impact decisions. External timeouts remain
unknown until reconciled; accepted Claim progress is preserved.

## Capability-to-Outcome Map

| Target capability | Observable outcome | Measurement or proof direction |
| --- | --- | --- |
| Multi-intent understanding | Fewer repeated questions and fewer turns to reach the next safe step | Compare repeated confirmed-fact questions in a repeatable trajectory fixture. |
| Dynamic required-now selection | Fewer incomplete FNOLs without forcing an ordered questionnaire | Verify only current-action fields are requested and unrelated pending evidence does not block progress. |
| Source-preserving proposals | Faster staff verification and clearer disagreement handling | Assert source references, confidence, confirmation state, and correction history. |
| Selective provenance recovery | Resolve ambiguity after a gap without loading the whole transcript on every turn | Prove full source messages are loaded only for unresolved fields and remain absent from resolved routine context. |
| Bounded questions | Complete the scenario with fewer than ten Agent questions | Persist question and repeated-fact counts across resumed sessions and stop before a tenth question. |
| Evidence-aware WorkItems | Better evidence completeness without stopping safe work | Resume a claim with pending police evidence and prove unrelated creation/progress continues. |
| Authority-aware execution | Fewer unsafe mutations, disclosures, and accidental high-impact decisions | Reject unsupported actions and prove claimant projections exclude internal signals. |
| Recoverable external work | No loss of accepted progress after provider failure | Fail a model or external call, reload Claim State, and reconcile before retry. |
| Staff `@Agent` assistance | Faster review with less transcript rereading, without autonomous staff decisions | Compare source-linked suggestions with explicit accept/ignore and claimant-send controls. |

Baselines and production targets are not invented here. The progress ledger records the
current evidence, measurement method, and known limitations as each capability is promoted.

## Delivery Levels

### Current implemented contract

The current API and persistence stack use the compatibility `AgentDecision` transport and
the implemented provider-neutral Model Gateway. Their exact schemas, errors, projections,
and tests remain authoritative in `docs/api.md`, `docs/model-gateway.md`, and the current
repository code.

### Challenge/MVP target

The smallest differentiating slice should demonstrate multi-intent extraction, one Claim
State, source-preserving proposals, targeted follow-up, safe authority checks, a bounded
staff suggestion, and recovery that preserves progress. Each promoted capability needs an
owner, contract, acceptance scenario, failure case, visibility rule, and repeatable proof.

### Post-MVP target

Qualified model fallback groups, a published Tool Registry, complete WorkItem lifecycle,
trajectory evaluation, model-profile governance, long-running external coordination, and
full staff capability composition may be developed after the MVP slice is proven. They
must not be presented as connected production capabilities before their evidence exists.

## Non-Goals and Safety Boundaries

- The model never owns Claim State or final coverage, fraud, liability, approval, rejection,
  or emergency authority.
- Retrieved knowledge is evidence with citations, not authority.
- Staff read access does not imply write, disclosure, send, or external execution authority.
- A fixture, configured adapter, degraded service, unavailable service, and production
  integration remain visibly distinct.
- The target design does not create a new public route or persistence record by itself.
  Coordinated implementation must update schemas, adapters, consumers, fixtures, OpenAPI,
  and contract tests together.
