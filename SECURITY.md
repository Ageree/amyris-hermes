# Security and Data Handling

## Supported reporting path

Open a private GitHub security advisory or contact the repository owner for suspected vulnerabilities. Do not include live secrets, phone numbers, message bodies, access tokens, or customer data in public issues.

## PII handling

Hermes can process phone numbers, chat identifiers, and message contents. Agents and contributors must:

- Treat phone numbers, chat IDs, message bodies, webhook tokens, Convex deploy keys, Sendblue keys, Telegram tokens, Photon secrets, and Turso tokens as sensitive data.
- Use `.env.example` files for variable names only. Never commit real `.env` files or copied production payloads.
- Prefer synthetic fixtures in tests. If a production example is required for debugging, replace phone numbers, names, tokens, URLs with signed secrets, and message text before storing it.
- Keep TODO or FIXME security follow-ups tagged, for example `TODO(security-123):`.

## Logging and scrubbing

Logs must not include raw secrets, phone numbers, message bodies, or bearer tokens. Existing Python controllers use redaction helpers for configuration output. New JavaScript and TypeScript logging should redact keys matching `token`, `secret`, `password`, `authorization`, `phone`, `number`, `message`, and `content` before writing to stdout, stderr, or third-party systems.

## Dependency updates

Dependency update PRs are grouped and delayed by Renovate for at least seven days through `minimumReleaseAge`. Emergency security updates may bypass the delay after reviewer approval.
