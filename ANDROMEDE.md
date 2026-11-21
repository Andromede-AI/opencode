# Temporary Andromede build

This fork pins upstream OpenCode v1.18.25 (`cb7d8b2f5e44876ef98b661dc10590c915af3a9f`)
and backports https://github.com/anomalyco/opencode/pull/44517 (commits
`dc1d66610a57b4a306ec279d26db4860f2a1f960` and
`b870c14b3422dfa5ec42bf650c475fc948533817`). It adds configuration without changing
upstream retry defaults or the agent harness.

The executable reports `1.18.25+andromede.3`. The suffix is SemVer build metadata,
so OpenCode can still resolve its official `@opencode-ai/plugin@1.18.25` runtime
dependency; the custom executable is published only as a GitHub release asset.

```json
{
  "autoupdate": false,
  "experimental": {
    "retry": {
      "maxRetries": 12,
      "initialDelayMs": 2000,
      "backoffFactor": 2,
      "jitterFactor": 0.25,
      "maxDelayMs": 2147483647,
      "maxDelayNoHeadersMs": 30000
    }
  }
}
```

All retry fields are optional. Omitting them preserves upstream behavior, including
five retries. `maxRetries: 0` disables retries; `-1` allows unlimited retries.
Retry-After headers retain precedence, subject to the configured absolute ceiling.
`maxDelayNoHeadersMs` applies when response headers are absent, matching upstream.

The Andromede build workflow tests the policy/config, typechecks both packages,
builds headless Linux glibc executables for x64 (baseline CPU) and arm64, then tests
real 503 requests with default, zero, and twelve retries. It publishes only from a
version tag matching `andromede/version`. Web UI assets are omitted; CLI/session
behavior is unchanged. Each release includes checksums, source commit, Bun version,
and the hash of the embedded models.dev snapshot. Consumers must pin the version
and checksum and disable auto-update. Release assets are never overwritten.

To release, update `andromede/version`, push branch `andromede`, and push the matching
`v<version>` tag. Only the Andromede workflow publishes this fork's artifacts; no
upstream npm packages are published.

`+andromede.3` builds with Bun 1.3.13 instead of upstream's pinned 1.3.14. Bun 1.3.14
drives JS timers from `rdtsc`, scaled by the frequency in CPUID leaf 0x15, and never
checks it against the kernel. On VMs whose guest TSC runs at another rate (GCP Sapphire
Rapids hosts report 1900 MHz for a 2700 MHz TSC) every timer fires at 0.70x its delay,
so the shell tool killed commands at 70% of the timeout it reported, and retry backoff
and request timeouts were shortened by the same factor. Bun 1.3.13 and 1.4.x read the
kernel's monotonic clock. `andromede/verify.py` rejects a binary that embeds Bun 1.3.14
and checks a timer against the wall clock. OpenCode's own source is unchanged.

Remove this fork once an official release supports the required retry settings:
verify equivalent behavior, replace the Train Stack installer with upstream, update
its version pin, and rebuild the runner. Core and Console do not depend on this fork.
