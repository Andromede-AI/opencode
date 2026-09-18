# Temporary Andromede build

This fork pins upstream OpenCode v1.18.25 (`cb7d8b2f5e44876ef98b661dc10590c915af3a9f`)
and backports https://github.com/anomalyco/opencode/pull/44517 (commits
`dc1d66610a57b4a306ec279d26db4860f2a1f960` and
`b870c14b3422dfa5ec42bf650c475fc948533817`). It adds configuration without changing
upstream retry defaults or the agent harness.

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

Remove this fork once an official release supports the required retry settings:
verify equivalent behavior, replace the Train Stack installer with upstream, update
its version pin, and rebuild the runner. Core and Console do not depend on this fork.
