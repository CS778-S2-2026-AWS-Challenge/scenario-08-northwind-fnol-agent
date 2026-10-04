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

The current claimant v8 release uses a complete `claimant.turn.v1` envelope for ordinary,
media and lookup turns. It preserves facts, questions and optional service suggestions in the
same validated result. v7-specific schemas and routing described below remain available only
when an explicit v7 release is selected; they are not a hidden fallback for v8.

`validate_turn_proposal` validates core facts and discards individual invalid optional
suggestions, then `reduce_turn` applies the result against the authoritative Claim. Supported
claimant quotations retain their source after normalization. Model prose cannot authorize a
service, claim creation or a handoff. The Runtime derives eligibility from the registry,
active external tasks, handoff status and consent cooldown; approved suggestions become new
message-bound offers requiring their own consent. An open handoff still receives replies and
records facts, while all new third-party suggestions remain suppressed.

The accepted inbound message is persisted before transport. A failed model attempt produces
the saved-message recovery projection documented in [API](api.md); it does not fabricate an
Agent reply. The original HTTP key replays its original result, while an explicit retry uses
the same `submit_message` entrypoint and saved inbound checkpoint. Bounded provider HTTP status
and `error.type`/`error.code` are retained for diagnosis; raw provider error messages are excluded.

The v8 envelope is bounded at the model boundary: scalar text values are at most 300
characters, text-list values have at most 50 entries of 100 characters, Contents quantity
is 1–999, and v8 monetary amounts are finite values from zero to 10,000,000. `V8MoneyAmount`
converts to the unchanged shared `MoneyAmount` after parsing. Runtime mirrors length and
count constraints even for providers that do not enforce strict output; an oversized field
is rejected individually, while a wrong core type still rejects the proposal. The 4500/5500
token output caps rely on incomplete-response recovery for extreme responses, not a guarantee
that arbitrary schema-legal text fits.

Agent orchestration sends `ModelRequest` and receives `ModelResponse`. These contracts
normalise:

- system, user, assistant, and tool messages;
- optional JSON-schema structured output;
- function-tool declarations and calls;
- text, image Evidence, and PDF Evidence content blocks. Evidence blocks contain only an
  Evidence ID and media type; an already-authorised resolver supplies bounded bytes to the
  adapter, so storage keys and object URLs never enter the model contract;
- assistant text, provider-neutral completion status, raw finish reason, provider model and
  request identity; and
- input, output, total, cache-read, and cache-write token usage when supplied by the endpoint;
  unavailable usage fields remain explicitly unknown rather than being reported as zero; and
- optional first-token latency when a transport can report it.

The explicitly selected v7 claimant path selects a published Request Profile before transport. Ordinary intake,
answer, correction, confirmation, claim creation, and third-party offers make one tool-free model
call over a server-built Claim projection. A lookup profile may resolve one turn-scoped
`context.resolve` reference and make one continuation call. PDF, multi-Evidence, and cross-Claim
review run in a mutation-incapable isolated request. The model never executes a tool, writes Claim
State, grants consent, creates a claim, or authorises a handoff by itself; Runtime performs those
checks.

The third-party offer schema contains conversation fields only. Exact service identities are
selected before transport by Runtime from the shared turn-family resolution and published service
registry. Older provider responses that still include `service_offer_ids` are accepted only as a
compatibility input: Runtime removes and ignores that field before validating the conversation.
It never becomes execution authority. This keeps provider wording replaceable while
GPT-compatible and Gemini transports produce the same registered service option for the same
bounded intent.

When a claimant message explicitly carries `evidence_refs`, the message boundary resolves only
claimant-visible records on that claimant's Claim whose lifecycle and media type permit model
input. Staff and external-system Evidence remains internal-only even when it belongs to the same
Claim. The boundary binds eligible IDs and media types to a resolver that exists for that turn
only. The adapter uses that same resolver for the selected v7 request; it re-checks the allow-list,
claimant visibility, current record, media type,
lifecycle state, and immutable storage key before reading bytes. Arbitrary URLs, storage keys,
unselected Evidence, internal-only Evidence, and cross-Claim records never enter the model
request. Missing content or a profile without the required image/document capability fails before
a text fallback can be attempted.

The applied claimant Runtime persists the claimant and agent messages, the Claim revision and
validated form changes, the compatibility decision projection, a bounded `RuntimeTraceRecord`,
the TurnPlan/AgentProposal/ExecutionPlan/ActionEnvelope/ToolResult/TurnResult/WorkItem family,
Session activity, and the idempotency response atomically. The current Claim projection is built
at the authenticated message boundary and is followed by the validated Claim mutation path. A model may
propose `human.create_handoff`, but model output never authorises that action. A server-owned
support or safety interrupt runs before the provider and is the only Runtime path that authorises
the handoff builder.

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

The projection also excludes Claim, Customer, Session, and unrelated Evidence resource identities;
actor identities; internal fraud, coverage, and severity signals; provider fingerprints; routes;
timestamps; and external Claim or assessor results. Bounded source references for selected facts
may be included so the model can distinguish supported facts and corrections; Runtime still owns
source validation and role visibility.
For an explicitly attached file only, `attached_evidence` contains its Evidence ID and media type
so a structured proposal can identify which selected object supports a fact. It contains no
filename, object location, customer identity, or storage metadata.
For current-action fields whose values are intentionally excluded, `known_field_codes` tells the
model that the field already exists without disclosing its value. This supports non-repetition
without widening the routine model-data projection.

The model-facing proposal schema can suggest a registered field value or contents item, purpose,
confidence, precision, relation, the claimant wording that supports it, and an optional
`source_evidence_id`. Runtime verifies whether claimant wording directly supports the normalized
value and whether an Evidence source names an exact attachment from this turn with the matching
image/document media type. A supported explicit claimant fact is recorded with claimant
provenance. An attachment-derived form value or contents item is always `proposed`, uses `image`
or `document` source, and retains the Evidence ID on both its current projection and immutable
assertion; it cannot become confirmed through model output. A model interpretation without either
source remains `source: inference` and `status: proposed`. Policy, history, and staff provenance
still require their trusted server paths.

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
are absent from claimant messages and decision projections. Every provider invocation also emits a
structured, size-only observation with its stage, ordinal, elapsed time, request composition, and
provider-reported usage. Prompt text, claimant messages, tool contents, raw provider payloads,
credentials, and unrestricted identifiers are never logged. The existing Control Plane operation
projection retains its bounded result shape; cache usage, first-token latency, and request/context
sizes are observation fields rather than a public API contract. A successful multimodal Runtime
trace additionally records only the selected Evidence ID, media type, and `submitted` outcome; raw
bytes and storage metadata are excluded.

The model-facing schemas do not contain the server-only `controlled_rule_authorised`
marker. v7 publishes separate answer, intake patch, external offer, Evidence action, handoff,
claim-creation, and sourced-summary schemas. Tool-free profiles expose no tool manifest. Lookup
profiles expose only `context.resolve`; unknown, multiple, recursive, stale, cross-scope, or
malformed resolutions fail closed before persistence. A model response using the deprecated eight-action schema is rejected with
`LEGACY_AGENT_ACTION_DEPRECATED` and cannot fall back to the controlled Agent. The compatibility
path still permits structured `required_tools` proposals for the bounded context operations
published by Branch Evaluation and Runtime policy; it validates arguments, executes at most one
context lookup, and permits one typed re-plan. The v7 continuation removes tools after the first
bounded resolution, so recursive tool chains are impossible. Provider adapters materialize the
selected stable schema and output limit without changing Runtime authority. Ordinary
intake uses `conversation.answer` with `runtime.wait_for_user` or `runtime.continue`; human support
uses `human.create_handoff` with `runtime.pause_for_review`. Claim preparation, creation, and
prior-Evidence proposals use only their explicitly registered directives. The proposal remains
advisory and cannot authorise a mutation; matching deterministic safety input is handled before
the provider call. External participant actions remain separate handlers and are never reported
as complete merely because a model requested them.

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

Image and document input are separate declared capabilities. A request that requires one of them
is rejected before transport when the selected profile does not declare support. A configured
profile must also provide an authorised Evidence resolver for a multimodal request; a missing or
empty resolution returns `evidence_unavailable` and is never reported as a successful text-only
fallback.

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
| `MODEL_PROTOCOL_ADAPTER` | Registered adapter name (`openai_compatible`, `bedrock_converse`, or `google_generate_content`); required with `model_gateway` when no binding is selected |
| `MODEL_PROFILE_ID` | Identifier of the selected model profile; required with `model_gateway` |
| `PDF_MODEL_PROFILE_ID` | Published profile that reads PDF evidence; it must be the governed OpenRouter `openai/gpt-4o` profile with document input, and PDF processing is unavailable while it is empty |
| `MODEL_PROVIDER` | Provider label used for internal profile audit context; required with `model_gateway` when no binding is selected |
| `MODEL_PURPOSE` | Allowed request purpose; `agent_turn` for the claimant Agent |
| `MODEL_PRIVACY_CLASS` | Allowed data classification for requests |
| `MODEL_PROMPT_VERSION` | Exact executable prompt identifier allowed by the profile |
| `MODEL_EVALUATION_STATUS` | `configured`, `degraded`, or `unavailable`; only `configured` can call transport |
| `MODEL_BASE_URL` | Endpoint root, including a compatible version prefix when required |
| `MODEL_IDENTIFIER` | Model identifier sent to the endpoint |
| `MODEL_API_KEY_ENV` | Name of the environment variable containing the credential, not the credential |
| `MODEL_TIMEOUT_SECONDS` | Positive request timeout; default `130` |
| `MODEL_SUPPORTS_STRUCTURED_OUTPUT` | Declared endpoint capability required by `GatewayAgent` |
| `MODEL_SUPPORTS_TOOLS` | Declared endpoint tool-call capability |
| `MODEL_SUPPORTS_IMAGE_INPUT` | Declared endpoint capability for image Evidence blocks; default `false` |
| `MODEL_SUPPORTS_DOCUMENT_INPUT` | Declared endpoint capability for PDF Evidence blocks; default `false` |
| `MODEL_RUNTIME_BINDINGS_PATH` | Path to the deployment-owned, non-secret list of model bindings that Control Plane publication is allowed to reference |
| `NORTHWIND_QWEN_BASE_URL` | Environment-owned Qwen endpoint resolved by the checked-in binding manifest |
| `MODEL_REASONING_MODE` | Bootstrap-only reasoning policy: `provider_default` or `disabled`; published bindings override it |
| `GEMINI_API_KEY` | Environment-owned Google AI Studio credential referenced by the Gemini binding |

For an unauthenticated local server, leave `MODEL_API_KEY_ENV` empty. For an
authenticated endpoint, set it to a separate secret environment variable name, for
example `NORTHWIND_MODEL_API_KEY`, and supply that variable through the runtime secret
mechanism. Never place the credential in `.env.example`, source, logs, or a pull request.

Capability declarations are startup configuration, not provider discovery. Structured
output and tool requests are rejected before transport when the selected adapter does
not declare the required capability. `GatewayAgent` requires structured output, so that
capability must be enabled for the `model_gateway` runtime to start.

`MODEL_RUNTIME_BINDINGS_PATH` is an allow-list, not the model catalogue. It lets the deployment
approve more than one exact profile, adapter, endpoint, model, and credential-name combination
without putting a credential in configuration. A profile becomes selectable only after a matching
high-impact model configuration is independently approved, published, included in the active
Release Set, and marked `configured`. Publishing a deployment-bound `degraded` or `unavailable`
profile registers it without making it selectable or allowing provider transport. A provider,
model identifier, endpoint, prompt, evaluation status, capability, or credential-reference mismatch
fails validation with `PROVIDER_CONFIGURATION_UNAVAILABLE`.

The development launcher `scripts/start-dev.ps1` pulls model credentials from the team secrets
endpoint, selects the `model_gateway` runtime profile and supplies the checked-in binding manifest
path to the backend process. It does not construct or inject model records: the backend still
validates, publishes, and resolves the version-controlled manifest through the same Control Plane
release boundary used by other deployments.

The published claimant profiles use this adapter contract:

| Profile | Model | Role | Required capabilities |
| --- | --- | --- | --- |
| `qwen-local` | `qwen3.8-27b` through the environment-owned Qwen endpoint | selectable through `MODEL_PROFILE_ID` | structured output (`json_object`) and tools |
| `openrouter-gpt4o-mini` | `openai/gpt-4o` through OpenRouter | the profile `start-dev.ps1` and `.env.example` select | structured output, tools, image input, and PDF document input |
| `bedrock-nova2-lite` | `global.amazon.nova-2-lite-v1:0` through Bedrock Sydney | published but unavailable until AWS account verification completes | structured output and image input |
| `google-gemini35-flash-lite` | `gemini-3.5-flash-lite` through Google AI Studio | selectable | structured output, tools, image input, and PDF document input |

The Google profile publishes `reasoning_mode=disabled`. For Gemini 3 models the native adapter
translates that setting to `generationConfig.thinkingConfig.thinkingLevel=minimal`; it does
not send the OpenAI-compatible `chat_template_kwargs` field.  The default
`openrouter-gpt4o-mini` profile is a non-reasoning model and therefore carries no
reasoning control parameter.  These are transport details of the published binding,
not a second Runtime decision.

A direct synthetic probe on 21 September 2026 returned HTTP 400 for Gemini 3.5 Flash Lite
with `thinkingBudget=0`, and HTTP 200 with `thinkingLevel=minimal` (1.700 seconds, 25 input
and 6 output tokens, no reported thought tokens). This establishes parameter compatibility,
not full claimant-journey acceptance. A later production-planner probe used the synthetic
message "My bathroom pipe burst last night and flooded the kitchen" with the corrected
Google wire schema. `provider_default` completed in 2.825 seconds (1,349 input / 429 output
tokens); the published `disabled` setting, translated to `minimal`, completed in 2.523 seconds
(1,349 input / 373 output tokens). Both returned complete field proposals. This single paired
observation establishes working transport, not a latency distribution or proof that minimal
reasoning always speeds up responses. `minimal` is the provider's lowest reasoning level,
not a promise of zero reasoning tokens.

A separate OpenRouter output-volume probe returned 828 output tokens in 6.901 seconds,
about 120 output tokens per second including request latency. At that observed rate, the
4,500/5,500-token operating caps represent roughly 37.5/45.8 seconds of output; twice the
media estimate is approximately 91.7 seconds. These are practical calibration estimates,
not upper latency guarantees. They provide no evidence for increasing the 130-second
bootstrap timeout or the existing 180-second published-release ceiling. Neither timeout
was changed by the probe.

On 2026-09-30, a live synthetic PDF probe sent the checked-in simulated contents receipt to the
OpenRouter `openai/gpt-4o` profile as a private Base64 `application/pdf` file block. The same request
used the profile's strict JSON Schema response mode. It returned the correct document type and
confirmed the document's explicit simulated-material marker in 169 input and 15 output tokens. The
probe did not select a parser plugin, so it verifies OpenRouter's documented default PDF-processing
path for this exact profile and payload, not native GPT-4o file handling or a fixed parser engine.
Provider availability, parser selection, price, and latency remain deployment observations. This
transport result does not prove automatic Evidence processing, which remains a separate lifecycle
boundary.

After the existing development secret injection, repeat the bounded probe with synthetic material:

```powershell
$env:AGENT_RUNTIME_PROFILE = 'model_gateway'
$env:MODEL_RUNTIME_BINDINGS_PATH = 'config/model-runtime-bindings.json'
$env:MODEL_PROFILE_ID = 'openrouter-gpt4o-mini'
py -3.12 -m scripts.verify_model_gateway_live `
  --pdf backend/demo_data/materials/contents/contents-purchase-receipt.pdf
```

The command prints only bounded status, profile, usage, and capability metadata. It does not print
the provider credential, PDF bytes, extracted document content, or the complete model response.

The local Qwen deployment uses the OpenAI-compatible transport with `json_object` structured
output. Its llama.cpp endpoint cannot compile the larger claimant JSON Schema grammar used by
the other providers during continuation. The Runtime still validates every returned object
against the exact claimant schema before applying a proposal; this changes only the wire-level
grammar and does not weaken field, permission, or state validation.

The OpenRouter `openai/gpt-4o` profile is the current default claimant model. The
credential reference is stored as an environment-variable name only. A Release Set binds each selectable model in a keyed
`model:<profile_id>` slot. The selected profile is the default for a Session, but each message may
explicitly select another published profile in the same conversation. The Runtime persists the
actual profile used for every turn and updates the Session's latest selection; it never silently
switches providers or falls back to a different profile.

The checked-in `config/model-runtime-bindings.json` is the current non-secret VP deployment
allow-list. Private endpoints are represented by environment-variable references and resolved only
inside the deployment process. The backend ships a reviewed initial Runtime Release that registers
and publishes the complete Agent policy plus every binding in this allow-list. A Control Plane
scope with no Release Set history installs that initial Release during application composition, so
`qwen-local`, `openrouter-gpt4o-mini`, and `google-gemini35-flash-lite` are available, while
`bedrock-nova2-lite` is published with its explicit evaluation status through the capabilities
APIs on a clean deployment. The initializer installs a release for a never-initialised scope. It
also replaces a stale active release only when that release was created by the repository
initializer and uses the same Prompt generation as the checked-in bindings. The replacement is a
new validated, published, and audited Release Set; prior configuration and release revisions remain
immutable. An operator-authored active release, a different Prompt generation, or superseded,
withdrawn, and otherwise inactive history remains authoritative and is never repaired or
overwritten on startup. Initial model records use a 180-second transport ceiling so a slow provider
can return a controlled result instead of failing at the former 30-second boundary. This ceiling is
not a response-time target: ordinary v7 profiles retain their input and output budgets, one-call
path, and deployment telemetry for measuring actual latency.

For a later governed replacement, an operator supplies independent administrator bearer tokens
through process environment variables and publishes the prompt and model slots while preserving
the active Release Set's other references:

```powershell
$env:NORTHWIND_CONTROL_PLANE_AUTHOR_TOKEN = '<author bearer token>'
$env:NORTHWIND_CONTROL_PLANE_APPROVER_TOKEN = '<independent approver bearer token>'
$env:NORTHWIND_QWEN_BASE_URL = '<private Qwen endpoint>'
$env:GEMINI_API_KEY = '<Google AI Studio API key>'
py -3.12 scripts/publish_fnol_model_release.py `
  --validation-evidence 'Live strict schema and forced tool-call probes passed.'
```

The replacement command never accepts or prints the provider credential. Publication stores only the
credential environment-variable name; runtime startup resolves the secret through the deployment-owned
secret mechanism. The command refuses publication when there is no active complete Release Set to extend,
or when the resulting active snapshot does not contain the exact manifest-defined catalogue.

The Workbench Staff Agent uses the same published profile catalog under its separate
`staff_assistant` purpose and `staff_internal_fnol` privacy class. Its selected profile is
stored on the Staff Agent session and passed to each provider request; a message cannot change
the session profile and the browser never receives endpoint or credential fields.

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

### Google Gemini GenerateContent

The `google_generate_content` adapter calls
`POST {MODEL_BASE_URL}/models/{MODEL_IDENTIFIER}:generateContent`. It authenticates with the
`x-goog-api-key` header using the credential stored in the environment variable named by
`MODEL_API_KEY_ENV`; the checked-in Gemini binding names `GEMINI_API_KEY`. Credentials never
appear in the URL, request body, model configuration, or provider-neutral response.

The adapter maps system instructions, user and model messages, authorised image Evidence, JSON
Schema output, function declarations, function calls, and function responses to the native Gemini
shape. Runtime opens one concrete provider exchange for a turn and reuses it for the optional
function-result continuation. That exchange returns a short provider-neutral call ID while keeping
Gemini's provider call ID and `thoughtSignature` in adapter-owned transient memory. The continuation
must use the same exchange; another exchange, a stale ID, or a replay after consumption fails
closed. Provider continuation state is consumed after the continuation attempt and is never placed
in a domain message, durable Runtime record, log, global cache, or fallback store. The same exchange
boundary can hold equivalent provider-private continuation metadata for another adapter without
changing the Runtime contract. Text, structured output, completion status, usage, cache-read usage,
model version, and response identity are normalised into `ModelResponse`.

Live requests to the current Gemini profile reject the complete claimant JSON Schema and
a variant restoring only array bounds with HTTP 400. The adapter therefore removes
`additionalProperties`, string and collection length bounds, numeric bounds, and `pattern` only
from the Gemini wire schema. For `field_changes`, the canonical object-level `anyOf` caused
repetitive role proposals until `MAX_TOKENS`; resolving references alone did not fix it.
The Google adapter expands local references and emits one field object with an allowed-code
enum and a union of registered value shapes. All four text keys, or five media keys including
`source_evidence_id`, remain required; nullable provenance remains nullable. OpenAI retains
the canonical per-field object variants.

The Google wire grammar alone no longer couples each field code to its exact value type.
`validate_field_changes` still validates that pair against the unchanged turn field contract;
source and Evidence checks also remain Runtime responsibilities. Tests prove that a
code/value mismatch accepted by the broader Google wire union is rejected by Runtime.
Unsupported provider-side length limits are likewise enforced after parsing. An incomplete
response still enters the existing recovery path and never applies partial facts.

The `google-gemini35-flash-lite` profile was verified on 2026-09-17 with live image and PDF
`inlineData` requests, a structured-output request, and a live forced `context.resolve` call followed
by structured continuation. This verifies transport compatibility for synthetic FNOL data. Provider
availability and latency remain deployment observations rather than a permanent guarantee. The
OpenRouter GPT-4o binding supports authorised Base64 PDF file blocks through OpenRouter's verified
PDF-processing path. The local Qwen profile remains text-only until a vision-capable deployment is
qualified.

The executable claimant Prompt Pack is `northwind-fnol-claimant-v8`, authored under
`backend/prompts/v8/` and embedded immutably in the published `agent_instruction` configuration.
Runtime composes bounded core, family, turn and capability instructions with one complete
turn envelope. The v7 pack and versioned bindings remain available for an explicit complete
Release Set rollback together with reverting/deploying the pre-v8 change set; selecting the
old prompt alone is not the operational rollback procedure. v6 source artifacts remain
deprecated and are not enabled as fallback.
Changing executable fragment content requires a new fragment or pack version and a complete
atomic Release Set; changing a manifest alone never mutates an existing active release.

The repository includes configuration and transport tests, but a deployment is live only after an
authorised model invocation succeeds in its selected AWS account and region. Model listing or
successful local composition is not proof of Runtime access.

The Sydney catalogue exposes the active Global Amazon Nova 2 Lite inference profile as
`global.amazon.nova-2-lite-v1:0`. The repository publishes that profile as `unavailable` because
the current AWS account can list Bedrock models but Runtime invocation is blocked pending AWS
account verification. Promote its binding to `configured` only after a live image request with
forced structured output succeeds; publishing the profile does not by itself make it selectable.

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

## Turn-scoped field contract

For claimant intake, one `TurnFieldContract` is compiled from the exact branch evaluation and
Field Registry snapshot used for the turn. It records a deterministic contract ID, Field Registry
version, branch-rule version, evaluated Claim revision, and only active or candidate
claimant-writable field definitions. The prompt projection, provider response schema, and Runtime
validator consume this object. They do not rebuild field meaning independently or send the entire
field catalogue.

Provider constraints bind each allowed `field_code` to its boolean, enum, text, location,
text-list, or temporal value contract. Fields with identical value shapes share one schema variant
without limiting how many distinct fields can be proposed. Runtime performs only
meaning-preserving normalization, such as canonical enum casing or an unambiguous boolean string.
If the completed provider response violates the contract, Runtime permits one isolated repair
request containing only the invalid field changes and their expected shapes. The repair has no
tools, cannot alter response text, actions, offers, or valid field changes, and has separate input
and output limits. A second failure aborts the turn before any Claim or Message mutation.

The retained trace records contract identity, safe field/reason metadata, whether repair was
attempted, its outcome, both invocation usage records, actual provider model, and latency. It does
not retain claimant text, the complete model response, hidden reasoning, or credentials as repair
diagnostics.

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
- `unsupported_capability`;
- `evidence_unavailable`; and
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

- The included transports implement synchronous OpenAI-compatible chat completions, Bedrock
  Converse, and Google Gemini GenerateContent; streaming is not implemented.
- Capability support is declared by configuration and verified by tests; there is no
  remote capability negotiation.
- v7 lookup profiles wire only the read-only `context.resolve` tool. Policy and approved guidance,
  claimant-owned Claim history, claimant-scoped Evidence history, and older message ranges are
  exposed through turn-scoped references; mutation tools remain separate Runtime handlers.
- Runtime trace and the claimant `TurnPlan`/`AgentProposal`/`ExecutionPlan`/`ActionEnvelope`/
  `ToolResult`/`TurnResult` record family are implemented for Fixture and MongoDB repositories.
  Admin trace projection and broader external action records remain open.
- The compatibility gateway still normalises provider tool calls into structured
  `AgentProposal.required_tools`; those context operations are bounded by Runtime policy and a
  single re-plan.
- The Agent/Runtime path can consume authorised Evidence references supplied on a claimant
  message. The claimant client remains responsible for supplying the selected Evidence IDs; it
  cannot infer capability, visibility, or storage access.
- Provider retries, fallback selection, circuit breaking, durable rich usage analytics, and model
  evaluation thresholds are not yet implemented. Provider usage and bounded composition metrics
  are observable when supplied, but structured logs are not a durable analytics store. A
  configured runtime never substitutes a fixture or another provider silently.
- Model capability projection separates `published`, process-local `runtime_ready`, and nullable
  `healthy`. A missing named credential makes the profile unavailable for selection without
  preventing startup or silently selecting another provider. `healthy` does not claim remote
  connectivity or model quality until a controlled health result exists.

## Target Runtime Relationship

The implemented Gateway remains the provider-neutral transport and validation layer, while the
claimant Runtime now applies the core target turn contract. The following boundaries are still
deliberately explicit:

- the current `ModelRequest` binds purpose, privacy class, prompt version, capability requirements,
  messages, response schema, and tool declarations; the target request also binds actor, Claim
  scope, policy and Registry versions, budgets, trace context, and the exact actions and tools
  allowed;
- the current `ModelResponse` normalises transport output; the target Runtime additionally
  distinguishes model proposal, validated `ExecutionPlan`, actual tool and state results,
  and final `TurnResult`;
- the claimant path persists the target turn record family and supports
  `conversation.answer`/`runtime.continue` plus deterministic `human.create_handoff`; broader
  Claim creation and external coordination still need their real action handlers;
- the current configuration declares endpoint capabilities; the target Model Profile
  Registry also governs allowed purposes, privacy terms, evaluation evidence, lifecycle,
  and qualified fallback groups; and
- the current Gateway executes only the published v7 Request Profile: ordinary calls are tool-free,
  bounded lookup allows one `context.resolve` and one re-plan, and isolated execution has no
  mutation capability; additional action tools require published Tool Registry entries, authority checks,
  typed results, idempotency, and trajectory tests before execution is enabled.

These are incremental extensions, not reasons to replace the implemented provider-neutral
port. Legacy compatibility types remain readable for controlled/fixture migration only; a
model-backed response using the deprecated eight-action contract is rejected and cannot enter
the target Runtime path.
