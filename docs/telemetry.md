# Telemetry

`code-context-mcp` ships **opt-in** anonymous telemetry that helps the maintainer understand real-world usage. Default: **off**. Activate via `CC_TELEMETRY=on`.

## What is collected

When telemetry is enabled, two kinds of events are sent to PostHog (configurable via `CC_TELEMETRY_ENDPOINT`):

### 1. Weekly heartbeat

Sent at most once per week per install:

| Field | Example | Why |
|---|---|---|
| `version` | `1.4.0` | Version distribution helps prioritise bug fixes |
| `os` | `Linux` / `Darwin` / `Windows` | Platform compatibility insights |
| `python_version` | `3.11` | Drop deprecated Python versions safely |
| `days_since_install` | `42` | Retention insight |
| `repo_size_bucket` | `S` (<1k chunks), `M` (1k-10k), `L` (10k-100k), `XL` (>100k) | Capacity planning |
| `distinct_id` | sha256 hex (32 chars) | Anonymous, derived from local cache directory |

### 2. Session aggregate

Sent at session exit (only if any events occurred):

| Field | Example | Why |
|---|---|---|
| `query_count` | `12` | Adoption depth |
| `index_count` | `1` | Reindex frequency |
| `index_failure_count` | `0` | Failure rate |
| `query_latency_<bucket>` | `query_latency_50-200ms: 8` | Performance distribution |

Latency buckets: `0-50ms`, `50-200ms`, `200ms-1s`, `1s-5s`, `>5s`.

## What is NOT collected

**Hard exclusions, by design:**

- Query text (your search strings never leave your machine)
- Code content (no chunks, snippets, or file contents)
- File paths (not your repo path, not file names, not directory structure)
- User identity (no username, hostname, email, IP address)
- Repo identifiers (no GitHub URLs, no commit SHAs, no branch names)

The `distinct_id` is anonymous — it is a SHA256 hash derived from your local cache directory path + creation timestamp. Two installations on the same machine but different repos produce different IDs. The hash is one-way (cannot be reversed to recover the path).

## How to disable

Default is off. If you previously enabled it:

```bash
export CC_TELEMETRY=off
# or simply unset:
unset CC_TELEMETRY
```

After unsetting, no further events are sent. To delete already-collected data, contact the maintainer (see [README](../README.md)).

## How to inspect the source

Telemetry code lives in [`src/code_context/_telemetry.py`](../src/code_context/_telemetry.py). Read it. The MIT license guarantees full transparency: every event sent corresponds to one explicit `client.event(...)` or `client.heartbeat(...)` call site, all visible in the source.

To verify telemetry is truly off when not enabled, run:

```bash
CC_TELEMETRY=off python -c "from code_context._telemetry import TelemetryClient, _load_telemetry_config; from code_context.config import load_config; c = TelemetryClient(_load_telemetry_config(load_config())); c.heartbeat('test', 'S'); c.event('test'); c.flush()"
```

The `posthog` package will not be imported and no network calls happen.

## Self-hosting the collector

If you run an organization that wants its own telemetry endpoint instead of PostHog Cloud:

```bash
export CC_TELEMETRY=on
export CC_TELEMETRY_ENDPOINT=https://your-self-hosted-posthog.example.com
export POSTHOG_PROJECT_API_KEY=phc_yourkey
```

The client follows the [PostHog API](https://posthog.com/docs) so any PostHog-compatible endpoint works.

## Status

| Aspect | State |
|---|---|
| Default | OFF |
| Stable since | v1.4.0 |
| Endpoint | PostHog Cloud (free tier) |
| Self-host | Yes (set `CC_TELEMETRY_ENDPOINT`) |
| Source | [`_telemetry.py`](../src/code_context/_telemetry.py) |
