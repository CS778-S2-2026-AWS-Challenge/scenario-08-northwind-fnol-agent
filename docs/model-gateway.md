# Model Gateway

The model gateway is the internal provider-neutral boundary between Agent orchestration
and model transports. It does not add a public model endpoint or grant model output any
new authority.

## Implemented Boundary

Agent orchestration sends `ModelRequest` and receives `ModelResponse`. These contracts
normalise:

- system, user, assistant, and tool messages;
- optional JSON-schema structured output;
- function-tool declarations and calls;
- assistant text, finish reason, provider model and request identity; and
- input, output, and total token usage when supplied by the endpoint.

`ModelRequest` also carries provider-neutral execution metadata: purpose, actor, claim
scope, policy and prompt versions, privacy class, required capabilities, token and latency
budgets, and a bounded trace context. These fields describe the authority and cost boundary;
they do not contain credentials or provider SDK payloads. `ModelResponse` reports normalized
capabilities in addition to text, structured output, tool calls, finish reason, usage, and
bounded provider identity.

`ModelProfile` is the selection record for an adapter. It contains a profile identifier,
protocol, provider, model identifier, credential reference, purpose, privacy class,
capabilities, timeout, fallback group, prompt version, and an explicit availability state
(`configured`, `degraded`, or `unavailable`). A credential reference names a secret location;
it is never the secret itself.

`GatewayAgent` converts a normalised structured response into the existing
`AgentProposal`. The existing deterministic validation then authorises, blocks, or
requires review for the proposal. A model response never executes a tool, writes claim
state, creates a claim, or authorises a handoff by itself.

The model receives an explicit minimum context projection rather than the durable
`WorkingClaim`. The projection contains the channel, locale, incident type, customer-safe
workflow state, evidence counts, the current customer next step, the current claimant text,
and only current-action form values from this allow-list: incident type, occurrence time,
description, injury or danger, cause, loss description, vehicle damage, vehicle drivability,
and affected property areas. A field marked for a later action is not sent even when its code
is allow-listed. Policy numbers, contact preferences, incident and property addresses, other
parties, police references, emergency-service records, vehicle registrations, and every
unregistered field remain outside routine model context.

The projection also excludes Claim, Customer, Session, Message, and Evidence identifiers;
source references and actor identities; internal fraud, coverage, and severity signals;
provider fingerprints; routes; timestamps; and external Claim or assessor results.

The model-facing proposal schema can suggest a form field, value, purpose, and confidence,
but it cannot set fact provenance or confirmation state. The server converts every accepted
model form suggestion to `source: inference` and `status: proposed`. Claimant, staff, policy,
or document provenance and confirmed state require their existing trusted server-side paths.
The resulting field actor is `model_gateway`, not `controlled_agent`.

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
provenance containing the runtime profile, provider-reported model identifier, and provider request
identifier when supplied. These provider references are internal-only and are absent from claimant
messages and decision projections. Token usage persistence remains a current limitation.

The model-facing schema does not contain the server-only `controlled_rule_authorised`
marker, and rejects a response that tries to provide it. Because the current Agent request
does not expose an approved tool manifest, provider tool calls and any model-proposed
`required_tools` entry are rejected before orchestration. This prevents a structured model
response from invoking a tool path that deterministic server policy has not exposed.

The default `controlled` profile continues to use `ControlledAgent`. The
`model_gateway` profile is enabled only through explicit startup configuration. A
configured model failure does not silently fall back to the controlled fixture.

## OpenAI-Compatible Adapter

The `openai_compatible` adapter calls `POST {MODEL_BASE_URL}/chat/completions`. Official
APIs, relay services, and local servers that implement this protocol use the same code;
only configuration changes.

| Variable | Meaning |
|---|---|
| `AGENT_RUNTIME_PROFILE` | `controlled` or `model_gateway` |
| `MODEL_PROTOCOL_ADAPTER` | Registered adapter name; currently `openai_compatible` by default |
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

## Bedrock Converse Adapter

The `bedrock_converse` adapter uses the AWS Bedrock Runtime Converse operation through the
standard boto3 credential chain. It is selected with `MODEL_PROTOCOL_ADAPTER=bedrock_converse`,
`MODEL_REGION`, and `MODEL_IDENTIFIER`; `MODEL_BASE_URL` is not used. The adapter maps the
neutral messages, optional tool declarations, structured-output instruction, stop reason,
usage, and request ID to the same `ModelResponse` contract as the compatible HTTP adapter.

The first live verification must use synthetic FNOL context and an explicitly authorised
runtime environment. A successful personal-account check is evidence for that configured
profile only; it is not evidence of Northwind production access, data, permissions, or
deployment readiness. Credentials remain in the AWS credential chain and are never committed.

Run the explicit live check only after configuring an authorised profile:

```powershell
py -3.12 -m scripts.verify_model_gateway_live
```

The command refuses to run under the default controlled profile and prints only profile,
provider, request-presence, usage, and capability metadata. The output is not a substitute
for a claimant journey or a production readiness review.

## Custom HTTP Boundary

`custom_http` is a registry entry for a non-compatible HTTP protocol. The default boundary
uses the same transport and normalized response shape as the compatible adapter so a custom
implementation can be registered without changing Agent behaviour or claimant routes. A
provider-specific request mapping belongs in a separate adapter factory; it must perform
capability checks before transport and map all failures to `ModelGatewayError` without
returning raw provider bodies.

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
- `malformed_response`;
- `unsupported_capability`; and
- `configuration`.

Only bounded, provider-neutral messages leave the adapter. Timeout, rate-limit, and
retryable provider failures retain a retryable flag for later orchestration policy.

At the claimant message API boundary, a timeout, rate limit, or other retryable provider
failure returns `503 DEPENDENCY_UNAVAILABLE` with `retryable: true`. Authentication,
configuration, unsupported capability, malformed response, and other non-retryable model
failures return `502 DEPENDENCY_FAILED` with `retryable: false`. These responses expose no
provider detail and leave the Claim revision, messages, decisions, and idempotency records
unchanged.

## Current Limitations

- The included transports implement synchronous OpenAI-compatible chat completions and
  Bedrock Converse; streaming and provider-specific response APIs beyond Converse are not
  implemented.
- Capability support is declared by configuration and verified by tests; there is no
  remote capability negotiation.
- The gateway normalises tool calls, but the current `GatewayAgent` requests only a
  structured `AgentProposal`. Existing server-side orchestration remains responsible
  for any authorised tool execution.
- Provider retries, fallback selection, circuit breaking, usage persistence, and model
  evaluation thresholds are not yet implemented. A configured runtime never substitutes
  a fixture or another provider silently.
- Readiness reports `configured` after successful local composition. It does not claim
  that remote credentials, connectivity, model quality, or production readiness have
  been verified.
