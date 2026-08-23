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

`GatewayAgent` converts a normalised structured response into the existing
`AgentProposal`. The existing deterministic validation then authorises, blocks, or
requires review for the proposal. A model response never executes a tool, writes claim
state, creates a claim, or authorises a handoff by itself.

The model receives an explicit minimum context projection rather than the durable
`WorkingClaim`. The projection contains the channel, locale, incident type, customer-safe
workflow state, structured form values without source references or actor identities,
evidence counts, and the current customer next step. It excludes Claim, Customer, Session,
Message, and Evidence identifiers; internal fraud, coverage, and severity signals; provider
fingerprints; routes; timestamps; and external Claim or assessor results.

The model-facing proposal schema can suggest a form field, value, purpose, and confidence,
but it cannot set fact provenance or confirmation state. The server converts every accepted
model form suggestion to `source: inference` and `status: proposed`. Claimant, staff, policy,
or document provenance and confirmed state require their existing trusted server-side paths.

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

- The included transport implements synchronous OpenAI-compatible chat completions;
  streaming and provider-specific response APIs are not implemented.
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
