### Summary (quick reference)

**Ask:** Freeze a small fixture of AWS managed Config rules that exercises parameter *shapes*, not 26y coverage. Use it as a shared smoketest for `bindingsNG`, `cpgNG`, and `upackNG`.

**Frozen list:** `tests/fixtures/param-smoketest.json` (16 ids, CFN-confirmed 2026-09-05).
Matrix: `tests/fixtures/param-smoketest-matrix.md`.
Tests: `tests/test_param_smoketest.py`.

**Must-hit cells:** no params · single optional + CFN Default · required with no real default · `99999` placeholder · empty `Default: ""` · multi-param homogeneous · multi-param heterogeneous · CSV/array-as-string · shared param name across two rules · unique param key · duration-like name · enum string · binding-only optional.

**Frozen ids:**
`s3-bucket-public-read-prohibited` · `alb-waf-enabled` · `access-keys-rotated` · `encrypted-volumes` · `api-gw-endpoint-type-check` · `desired-instance-type` · `vpc-endpoint-enabled` · `s3-lifecycle-policy-check` · `restricted-common-ports` · `iam-password-policy` · `eks-cluster-oldest-supported-version` · `eks-cluster-supported-version` · `ec2-managedinstance-applications-required` · `ec2-managedinstance-applications-blacklisted` · `bedrock-agentcore-memory-event-expiry-duration` · `cloudwatch-alarm-resource-check`

**CFN corrections vs earlier notes:**
- `bedrock-data-source-encryption-enabled` has **no** InputParameters in CFN (skipped).
- Expiry rule param is `minEventExpiryDuration` (default `"7"`), not `eventExpiryDuration`.
- `s3-lifecycle-policy-check` five params are all optional with `Default: ""`. 30 / 90 / STANDARD_IA are NIAID catalog samples.
- `restricted-common-ports` template identifier is `RESTRICTED_INCOMING_TRAFFIC`.

**Pass 1 — bindingsNG:** `--update --dry-run` then default `--group 26y --dry-run`. Required iff CFN has no `Default`. `""` / `99999` do not count. Missing required → `BLOCKED_MISSING_REQUIRED`, no `GROUP#` write.

**Pass 2 — cpgNG:** emit pack + sidecar with and without `--group 26y`. Required+real default in YAML as strings. Optional defaults omitted unless bound. CSV stays one string. Description ≤256; optional note on CSV only.

**Pass 3 — upackNG:** fake `deploy_fn` first. Map by logical id / rule name / source id / unique param. Shared keys fail closed. Repair CLI printed, never executed. No Dynamo writes.

**Not this work:** full `--all-profiles` pack, `mba_csv` as the test harness, rewriting the three tools, committing aiml/container leftovers, inventing 26y values at deploy time.

**Confirm before adding ids:** each new id against current catalog + CFN template. Drop duplicates and rules with no `PROFILE#` or no template.
