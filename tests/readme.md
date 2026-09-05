### Summary (quick reference)

**Ask:** Freeze a small fixture of AWS managed Config rules that exercises parameter *shapes*, not 26y coverage. Use it as a shared smoketest for `bindingsNG`, `cpgNG`, and `upackNG`.

**Size:** ~12–20 rule ids in `tests/fixtures/param-smoketest.json`. One rule per matrix cell when possible.

**Must-hit cells:** no params · single optional + CFN Default · required with no real default · `99999` placeholder · empty `Default: ""` · multi-param homogeneous · multi-param heterogeneous · CSV/array-as-string · shared param name across two rules · unique param key · duration-like name · enum string · binding-only optional.

**Starter ids already in this repo:**  
`alb-waf-enabled` · `access-keys-rotated` · `bedrock-data-source-encryption-enabled` · `s3-lifecycle-policy-check` · `api-gw-endpoint-type-check` · `bedrock-agentcore-memory-event-expiry-duration` · `vpc-endpoint-enabled` · `eks-cluster-oldest-supported-version` + `eks-cluster-supported-version` · EC2 managed-instance application/platform rules if CFN confirms.

**Pass 1 — bindingsNG:** `--update --dry-run` then default `--group 26y --dry-run`. Required iff CFN has no `Default`. `""` / `99999` do not count. Missing required → `BLOCKED_MISSING_REQUIRED`, no `GROUP#` write.

**Pass 2 — cpgNG:** emit pack + sidecar with and without `--group 26y`. Required+real default in YAML as strings. Optional defaults omitted unless bound. CSV stays one string. Description ≤256; optional note on CSV only.

**Pass 3 — upackNG:** fake `deploy_fn` first. Map by logical id / rule name / source id / unique param. Shared keys fail closed. Repair CLI printed, never executed. No Dynamo writes.

**Not this work:** full `--all-profiles` pack, `mba_csv` as the test harness, rewriting the three tools, committing aiml/container leftovers, inventing 26y values at deploy time.

**Confirm before freeze:** each id against current catalog + CFN template. Drop duplicates and rules with no `PROFILE#` or no template.
