# Security Policy

## Reporting a Vulnerability

While the repository is private and no dedicated disclosure channel exists,
collaborators should report security concerns directly and privately to the
repository owner.

If the repository becomes public, do not report sensitive vulnerabilities
through public GitHub Issues. A private disclosure process must be established
before public vulnerability reports are invited.

## Repository Safety

- Never commit credentials, secrets, tokens, personal user data, or production
  data.
- If a credential reaches Git history, rotate it immediately. Removing it from
  a later commit is not sufficient.
- Security-sensitive implementation requires explicit security review.
- Use synthetic development data unless sanitized real data has been explicitly
  approved.

## Release Expectations

Authentication or authorization failures are release blockers.

Artifact and media uploads will require strict validation before those features
are released, including validation of type, size, content, ownership, and access.
The specific controls will be designed with the feature rather than assumed in
advance.
