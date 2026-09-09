# Model Gateway

The model gateway is the internal provider-neutral boundary between Agent orchestration
and model transports. It does not add a public model endpoint or grant model output any
new authority.

The target turn and FNOL problem mapping are defined in
[Agent Runtime Target](design/agent-runtime/agent-runtime-target.md), and the compatibility path is
isolated in [Agent Runtime Migration](design/agent-runtime/agent-runtime-migration.md).
This document remains authoritative for what the current Gateway implementation actually
supports.

## Implemented Boundary

Agent orchestration sends `ModelRequest` and receives `ModelResponse`. These contracts
normalise:

- system, user, assistant, and tool messages;
- optional JSON-schema structured output;
- function-tool declarations and calls;
- assistant text, provider-neutral completion status, raw finish reason, provider model and
  request identity; and
- input, output, and total token usage when supplied by the endpoint.

For the target model-backed claimant path, `GatewayAgent` performs a bounded two-stage
turn: it advertises the read-only `claim.read` tool, validates and executes that tool against
the authenticated `WorkingClaim`, then sends the assistant tool call and typed tool result back
to the same model for a namespaced final response. A model response never executes a tool,
writes Claim State, creates a claim, or authorises a handoff by itself.

The final target subset is `conversation.answer` plus `runtime.continue`. The Runtime persists
the claimant and agent messages, a bounded `RuntimeTraceRecord`, Session activity, and the
idempotency response atomically. `claim.read` is observational: Claim revision and form state
remain unchanged, and no legacy `AgentDecisionRecord` is created. The trace retains both provider
invocations, tool call identity and arguments, result status, selected model profile, and final
namespaced codes.

Every adapter maps provider termination data to `complete`, `incomplete`, `refused`, or
`unknown`. `GatewayAgent` accepts a proposal only from a `complete` response. Truncated,
refused, filtered, cancelled, and unrecognised results are discarded before proposal
validation or persistence, even when their partial content happens to match the schema.

The model receives an explicit bounded context projection rather than the durable
`WorkingClaim`. The projection contains channel, locale, selected family, claimant-safe workflow
state, evidence counts, current next step, current claimant text, typed contents items, and only
current-action fields permitted by the latest Branch Evaluation. Inactive, system-owned,
later-action, hidden, and unregistered fields remain outside routine model context. When no Branch
Evaluation exists, a compatibility allow-list restricts the context to approved intake fields.

The projection also excludes Claim, Customer, Session, and Evidence resource identities; actor
identities; internal fraud, coverage, and severity signals; provider fingerprints; routes;
timestamps; and external Claim or assessor results. Bounded source references for selected facts
may be included so the model can distinguish supported facts and corrections; Runtime still owns
source validation and role visibility.
For current-action fields whose values are intentionally excluded, `known_field_codes` tells the
model that the field already exists without disclosing its value. This supports non-repetition
without widening the routine model-data projection.

The model-facing proposal schema can suggest a registered field value, purpose, confidence,
precision, relation, and the claimant wording that supports it. Runtime verifies whether that
wording directly supports the normalized value. A supported explicit claimant fact is recorded
with claimant provenance; a model interpretation remains `source: inference` and `status:
proposed`. Policy, history, document, and staff provenance require their trusted server paths.

The model-facing `proposed_signals` collection has a maximum length of zero. Any response that
attempts to create an internal signal is malformed and the entire turn is rejected before a
message, decision, Workbench signal, or idempotency record is written. Signals continue to use
their existing deterministic, retrieval, or staff-owned paths.

Model-authored customer prose is not response authority. Before persistence, the server renders
`customer_reason`, the conversational reply, and the next-step summary from the validated action
and authority outcome. Review-required and blocked proposals always use fixed bounded responses;
authorised low-impact actions use action-specific server responses. This prevents a model from
presenting approval, rejection, liability, fraud, or emergency-service claims to a claimant.

Each persisted model-backed decision records `proposal_source: model_gateway` and bounded audit
provenance containing the runtime profile, executable prompt identifier, provider-reported model
identifier, and provider request identifier when supplied. These references are internal-only and
are absent from claimant messages and decision projections. Token usage persistence remains a
current limitation.

The model-facing schema does not contain the server-only `controlled_rule_authorised`
marker, and rejects a response that tries to provide it. The target request exposes only the
`claim.read` manifest; unknown, multiple, or malformed tool calls fail closed before any
persistence. A model response using the deprecated eight-action schema is rejected with
`LEGACY_AGENT_ACTION_DEPRECATED` and cannot fall back to the controlled Agent. The compatibility
path still permits structured `required_tools` proposals for the bounded context operations
published by Branch Evaluation and Runtime policy; it validates arguments, executes at most one
context lookup, and permits one typed re-plan. The target model-backed path uses the provider
tool-call side channel for `claim.read` and never mixes it with the legacy eight-action response.

The default `controlled` profile continues to use `ControlledAgent`. The
`model_gateway` profile is enabled only through explicit startup configuration. A
configured model failure does not silently fall back to the controlled fixture.

## Enforced Model Profile

Each configured gateway has one `ModelProfile` that binds the profile identifier, protocol,
provider label, model identifier, credential reference, purpose, privacy class, declared
capabilities, timeout, prompt version, and evaluation status. The composition root rejects
transport configuration that disagrees with the profile's model, credential reference,
capabilities, or timeout. The registry also rejects a selected protocol that differs from the
profile protocol.

Before an adapter reads credentials or opens a network connection, it requires the profile status
to be `configured` and checks the request purpose, privacy class, prompt version, and explicit
capability requirements against the selected profile. A `degraded` or `unavailable` profile fails
closed. This boundary does not discover provider capabilities remotely; a capability declaration
must still be supported by repeatable adapter tests and the selected endpoint.

## Implemented Adapters

### OpenAI-Compatible

The `openai_compatible` adapter calls `POST {MODEL_BASE_URL}/chat/completions`. Official
APIs, relay services, and local servers that implement this protocol use the same code;
only configuration changes.

When an endpoint implements OpenAI strict structured outputs, the adapter translates the
provider-neutral Pydantic schema into that protocol's accepted JSON Schema subset. Every object
property becomes required, optional values remain nullable, object shapes reject undeclared
properties, defaults are removed, and unconstrained scalar values are represented explicitly.
This is a transport transformation only: the returned object must still pass the original domain
model and Runtime authority validation before it can affect Claim State.

| Variable | Meaning |
| --- | --- |
| `AGENT_RUNTIME_PROFILE` | `controlled` or `model_gateway` |
| `MODEL_PROTOCOL_ADAPTER` | Registered adapter name; currently `openai_compatible` by default |
| `MODEL_PROFILE_ID` | Identifier of the selected model profile |
| `MODEL_PROVIDER` | Provider label used for internal profile audit context |
| `MODEL_PURPOSE` | Allowed request purpose; `agent_turn` for the claimant Agent |
| `MODEL_PRIVACY_CLASS` | Allowed data classification for requests |
| `MODEL_PROMPT_VERSION` | Exact executable prompt identifier allowed by the profile |
| `MODEL_EVALUATION_STATUS` | `configured`, `degraded`, or `unavailable`; only `configured` can call transport |
| `MODEL_BASE_URL` | Endpoint root, including a compatible version prefix when required |
| `MODEL_IDENTIFIER` | Model identifier sent to the endpoint |
| `MODEL_API_KEY_ENV` | Name of the environment variable containing the credential, not the credential |
| `MODEL_TIMEOUT_SECONDS` | Positive request timeout; default `30` |
| `MODEL_SUPPORTS_STRUCTURED_OUTPUT` | Declared endpoint capability required by `GatewayAgent` |
| `MODEL_SUPPORTS_TOOLS` | Declared endpoint tool-call capability |

For an unauthenticated local server, leave `MODEL_API_KEY_ENV` empty. For an
authenticated endpoint, set it to a separate secret environment variable name, for
example `NORTHWIND_MODEL_API_KEY`, and supply that variable through the runtime secret
mechanism. Never place the credential in `.env.example`, source, logs, or a pull request.

Capability declarations are startup configuration, not provider discovery. Structured
output and tool requests are rejected before transport when the selected adapter does
not declare the required capability. `GatewayAgent` requires structured output, so that
capability must be enabled for the `model_gateway` runtime to start.

Both published claimant profiles use this adapter contract:

| Profile | Model | Role | Required capabilities |
| --- | --- | --- | --- |
| `qwen-local` | `qwen3.8-27b` at `http://100.71.25.5:8080/v1` | primary/default | structured output and tools |
| `nowcoding-gpt54mini` | `gpt-5.4-mini` through the existing nowcoding endpoint | selectable | structured output and tools |

The credential reference is stored as a secret environment-variable name only. The selected
profile is bound to the Session at creation/resume; message requests do not accept a model
override and never silently switch profiles.

### Amazon Bedrock Converse

The `bedrock_converse` adapter calls
`POST {MODEL_BASE_URL}/model/{MODEL_IDENTIFIER}/converse`. It authenticates with the bearer token
stored in the environment variable named by `MODEL_API_KEY_ENV`; for Bedrock API keys this should
name `AWS_BEARER_TOKEN_BEDROCK`. The adapter never reads a credential from a source-controlled
profile.

Bedrock Converse does not use the OpenAI request or response shape. The adapter maps system and
conversation messages to Converse content blocks and supplies the response schema as a forced
`toolChoice` with `toolSpec.inputSchema.json`. Only one `toolUse` block for the reserved
`northwind_agent_proposal` transport tool is accepted as structured output; prompt-only JSON text
does not satisfy the declared capability. The adapter normalises text, completion status, stop
reason, usage, configured model identity, and AWS request identity into `ModelResponse`. HTTP
authentication, rate-limit, provider, timeout, and malformed-output failures use the same
provider-neutral errors as other adapters.

The executable claimant prompt is `northwind-fnol-claimant-v5`, stored under
`backend/prompts/`. It defines the bounded motor, home, and contents VP behaviour, natural-language
correction, current-action questioning, context lookup, and handoff proposals. Runtime injects the
Branch Evaluation, minimum Claim projection, bounded knowledge citations, typed tool results, and
response schema; the adapter does not own FNOL authority. Earlier prompt versions remain immutable
historical artifacts. Changing executable prompt content requires another prompt identifier and
regression evidence.

The repository includes configuration and transport tests, but a deployment is live only after an
authorised model invocation succeeds in its selected AWS account and region. Model listing or
successful local composition is not proof of Runtime access.

Run the repeatable synthetic live verifier only in an authorised, budgeted environment after
injecting the configured credential through the environment variable named by
`MODEL_API_KEY_ENV`:

```powershell
py -3.12 -m scripts.verify_model_gateway_live
```

The verifier requires a complete structured response and reports only bounded metadata,
capabilities, and usage. It never prints the credential or full provider output.
When the profile is not enabled or the provider call fails, it prints a bounded machine-readable
failure status and exits non-zero without exposing a traceback or provider response.

## Custom Protocols

A non-compatible HTTP or local protocol implements the `ModelGateway` contract and is
registered in `ModelGatewayRegistry` under a unique protocol name. The composition root
selects it with `MODEL_PROTOCOL_ADAPTER`. Adding an adapter does not require a change to
Agent behaviour or public API routes.

Adapters must return the neutral response contract, perform capability checks before
transport, and map provider failures to `ModelGatewayError`. They must not expose raw
provider bodies or credentials in error messages.

## Normalised Failures

The gateway distinguishes:

- `timeout`;
- `authentication`;
- `rate_limit`;
- `provider`;
- `incomplete_response`;
- `refused_response`;
- `malformed_response`;
- `unsupported_capability`; and
- `configuration`.

Only bounded, provider-neutral messages leave the adapter. Timeout, rate-limit, and
retryable provider failures retain a retryable flag for later orchestration policy.

At the claimant message API boundary, a timeout, rate limit, or other retryable provider
failure returns `503 DEPENDENCY_UNAVAILABLE` with `retryable: true`. Authentication,
configuration, unsupported capability, incomplete or refused completion, malformed response, and
other non-retryable model failures return `502 DEPENDENCY_FAILED` with `retryable: false`. These
responses expose no provider detail and leave the Claim revision, messages, decisions, and
idempotency records unchanged.

## Current Limitations

- The included transports implement synchronous OpenAI-compatible chat completions and Bedrock
  Converse; streaming is not implemented.
- Capability support is declared by configuration and verified by tests; there is no
  remote capability negotiation.
- Only `claim.read` is currently wired into the target tool loop. Other registered tools and
  namespaced actions remain unavailable until their handlers, authority checks, and persistence
  contracts are implemented.
- Runtime trace persistence is implemented for the fixture and Mongo repositories; a complete
  `TurnPlan`/`ExecutionPlan`/`TurnResult` record family and admin trace projection remain open.
- The compatibility gateway still normalises provider tool calls into structured
  `AgentProposal.required_tools`; those context operations are bounded by Runtime policy and a
  single re-plan.
- Provider retries, fallback selection, circuit breaking, usage persistence, and model
  evaluation thresholds are not yet implemented. A configured runtime never substitutes
  a fixture or another provider silently.
- Readiness reports `configured` after successful local composition. It does not claim
  that remote credentials, connectivity, model quality, or production readiness have
  been verified.

## Target Runtime Relationship

The implemented Gateway is the first provider-neutral transport and validation layer. It
does not yet implement the complete target Agent Runtime contract:

- the current `ModelRequest` binds purpose, privacy class, prompt version, capability requirements,
  messages, response schema, and tool declarations; the target request also binds actor, Claim
  scope, policy and Registry versions, budgets, trace context, and the exact actions and tools
  allowed;
- the current `ModelResponse` normalises transport output; the target Runtime additionally
  distinguishes model proposal, validated `ExecutionPlan`, actual tool and state results,
  and final `TurnResult`;
- the target claimant path now produces the minimal namespaced pair
  `conversation.answer`/`runtime.continue`; the broader action model still needs complete
  conversation moves, Claim commands, human actions, and external coordination;
- the current configuration declares endpoint capabilities; the target Model Profile
  Registry also governs allowed purposes, privacy terms, evaluation evidence, lifecycle,
  and qualified fallback groups; and
- the current Gateway executes the published `claim.read` Tool Registry capability on the target
  path, while compatibility context tools remain bounded by a per-turn allow-list and one
  re-plan; additional action tools require published Tool Registry entries, authority checks,
  typed results, idempotency, and trajectory tests before execution is enabled.

These are incremental extensions, not reasons to replace the implemented provider-neutral
port. Legacy compatibility types remain readable for controlled/fixture migration only; a
model-backed response using the deprecated eight-action contract is rejected and cannot enter
the target Runtime path.
