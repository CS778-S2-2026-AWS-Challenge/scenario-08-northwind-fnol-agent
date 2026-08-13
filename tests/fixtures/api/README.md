# Synthetic API Fixture Examples

`AT-08-resume-public.json` contains claimant-facing API response examples for a
claim, session, message collection, form update, and evidence collection. All
identifiers, timestamps, narrative text, and customer references are synthetic.

The canonical domain data is
`../scenarios/AT-08-resume.json`. The public fixture deliberately reuses that
scenario's claim, session, message, form, and evidence relationships instead of
introducing a second data model. Each top-level value is shaped for its current
Pydantic response model:

- `claim`: `ClaimantClaim`
- `session`: `ClaimantSession`
- `messages`: `MessageListResponse`
- `form`: `FormPatchResponse`
- `evidence`: `EvidenceListResponse`

The projection excludes the internal-only system message, durable message
visibility and retry fields, evidence provenance, customer ownership fields,
and all persistence-provider details.

The canonical AT-08 session currently records `last_active_at` at the time of an
internal system message. This public example normalises that field to the last
accepted claimant or Agent message time, as required by `docs/api.md`. No other
canonical record value is reinterpreted.

`../../../docs/persistence-schema.md` is the existing Sprint 1 logical
persistence design draft, and its logical access patterns remain the current
provider-neutral design boundary. Real DynamoDB physical tables, indexes,
region, IAM configuration, and storage configuration are not confirmed. This
public fixture does not define or imply an official AWS or production Northwind
schema. The repository and DynamoDB example mapping remains the follow-up
contribution owned by `bdfa123` under Issue #53.
