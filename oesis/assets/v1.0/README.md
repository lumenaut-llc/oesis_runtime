# Runtime Assets v1.0

This directory is the explicit opt-in future lane for runtime asset overrides.

Files here are layered on top of the frozen baseline lane
`oesis/assets/v0.1/` only when the `oesis-v10-*` commands or equivalent
environment selection are used.

This lane now carries additive governance fixtures (`consent-*` and
`sharing-*`) so consent/revocation behavior can be validated as part of
`v1.0` acceptance flows without mutating `v0.1` baselines.
