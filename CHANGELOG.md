# Changelog

All notable changes to DriftWatch are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.2.0] - 2026-07-22

### Added
- **Health probe** — unauthenticated `GET /healthz` liveness/readiness endpoint
  (200 healthy, 503 when the database is unreachable), reporting version and
  scheduler state. Wired to a Docker `HEALTHCHECK`.
- **Per-probe metrics** — a lightweight `ProbeResult` table records latency and
  outcome status on every probe, exposed via `GET /api/endpoints/{id}/history`
  and retention-pruned like drift events.
- **Dashboard observability** — a latency sparkline and per-probe status
  timeline on each endpoint card.
- **Continuous integration** — GitHub Actions runs the test suite on every push
  and pull request.
- Project docs: `LICENSE` (MIT), `CONTRIBUTING.md`, and this changelog.

### Changed
- Scheduler now adds jitter so endpoints on the same interval don't probe in
  lockstep (smoothing outbound load and de-correlating alert timing).

## [1.1.0] - 2026-07-16

### Added
- Retry with linear backoff for network errors and 5xx responses.
- Learned baselines: a new endpoint's first N probes merge into its baseline so
  intermittent/optional fields and enum values are captured before detection
  arms.
- Data retention: acknowledged events and orphaned snapshots are pruned daily.
- Email alert channels (SMTP), alongside Discord/Slack/generic webhooks.
- Dashboard upgrades and a Windows Scheduled Task installer for run-at-logon.

## [1.0.0] - 2026-07-16

### Added
- Initial release: scheduled probing, JSON type-shape inference, shape diffing
  with breaking/risky/benign classification, drift feed, accept-as-baseline,
  alert channels, a zero-build dashboard, and a REST API.

[Unreleased]: https://github.com/manijose1919/driftwatch/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/manijose1919/driftwatch/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/manijose1919/driftwatch/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/manijose1919/driftwatch/releases/tag/v1.0.0
