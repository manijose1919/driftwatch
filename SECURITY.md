# Security Policy

## Supported versions

DriftWatch is a small, single-process, self-hosted application. Security fixes
are applied to the latest release on the `main` branch. Please run a current
version before reporting an issue.

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Instead, use GitHub's private reporting: open the repository's
**Security → Advisories → Report a vulnerability** form, or email the maintainer
at manijose1919@gmail.com with:

- a description of the issue and its impact,
- steps to reproduce (a proof of concept if possible), and
- any suggested remediation.

You can expect an initial acknowledgement within a few days. Once a fix is
available, it will be released and the reporter credited (unless anonymity is
requested).

## Deployment hardening notes

DriftWatch is designed to run on a trusted host or LAN. When exposing it more
widely, please note:

- **Set `DRIFTWATCH_API_TOKEN`.** The `/api/*` routes are unauthenticated by
  default (self-hosted LAN assumption); a token enables Bearer-auth. `/healthz`
  is intentionally unauthenticated and exposes no sensitive data.
- **DriftWatch fetches URLs you register.** Only add endpoints you trust; probe
  requests originate from the host running DriftWatch, so treat registration as
  a potential SSRF vector on internal networks.
- **Stores no response data.** Probes are reduced to structure-only type-shapes;
  request headers/bodies you configure (e.g. auth tokens for probed APIs) are
  stored to replay the probe — protect the database file accordingly.
