# Parameter-shape smoketest matrix

Frozen 2026-09-05 against AWS managed-rule CFN templates
(`https://s3.amazonaws.com/aws-configservice-us-east-1/cloudformation-templates-for-managed-rules/{SOURCE_IDENTIFIER}.template`).

`ConfigRuleName` and `MaximumExecutionFrequency` are pack/template plumbing.
They are not catalog InputParameters (`bindingsNG.CFN_NON_INPUT_PARAMS`).

NIAID sample defaults on `s3-lifecycle-policy-check` (30 / 90 / STANDARD_IA)
are catalog overlays, not CFN Defaults. CFN lists those five params as
`Default: ""` → `required=false`.

## Frozen list (16)

| Rule | SourceIdentifier | InputParameters (CFN) | Cells |
|---|---|---|---|
| s3-bucket-public-read-prohibited | S3_BUCKET_PUBLIC_READ_PROHIBITED | none | zero parameters |
| alb-waf-enabled | ALB_WAF_ENABLED | wafWebAclIds optional `""` | empty Default; binding-only optional |
| access-keys-rotated | ACCESS_KEYS_ROTATED | maxAccessKeyAge optional `"90"` | single optional + real CFN Default |
| encrypted-volumes | ENCRYPTED_VOLUMES | kmsId optional `""` | empty Default optional scalar |
| api-gw-endpoint-type-check | API_GW_ENDPOINT_TYPE_CHECK | endpointConfigurationTypes **required** | unique required key |
| desired-instance-type | DESIRED_INSTANCE_TYPE | instanceType **required** | required scalar, no default |
| vpc-endpoint-enabled | VPC_ENDPOINT_ENABLED | serviceNames **required**; vpcIds / scopeConfigResourceTypes optional `""` | required CSV-as-string |
| s3-lifecycle-policy-check | S3_LIFECYCLE_POLICY_CHECK | targetTransitionDays, targetExpirationDays, targetTransitionStorageClass, targetPrefix, bucketNames all optional `""` | heterogeneous; enum; CSV; empty Default; placeholder `99999` via catalog overlay |
| restricted-common-ports | RESTRICTED_INCOMING_TRAFFIC | blockedPort1–5 optional with numeric defaults; blockedPorts optional `""` | homogeneous scalars + CSV |
| iam-password-policy | IAM_PASSWORD_POLICY | seven homogeneous optional bool/int defaults | multi-param homogeneous with real defaults |
| eks-cluster-oldest-supported-version | EKS_CLUSTER_OLDEST_SUPPORTED_VERSION | oldestVersionSupported **required** | shared required name (A) |
| eks-cluster-supported-version | EKS_CLUSTER_SUPPORTED_VERSION | oldestVersionSupported **required** | shared required name (B) |
| ec2-managedinstance-applications-required | EC2_MANAGEDINSTANCE_APPLICATIONS_REQUIRED | applicationNames **required**; platformType optional `""` | shared applicationNames (A) |
| ec2-managedinstance-applications-blacklisted | EC2_MANAGEDINSTANCE_APPLICATIONS_BLACKLISTED | applicationNames **required**; platformType optional `""` | shared applicationNames (B) |
| bedrock-agentcore-memory-event-expiry-duration | BEDROCK_AGENTCORE_MEMORY_EVENT_EXPIRY_DURATION | minEventExpiryDuration optional `"7"` | duration-like name |
| cloudwatch-alarm-resource-check | CLOUDWATCH_ALARM_RESOURCE_CHECK | resourceType + metricName both **required** | two required heterogeneous params |

## Skip list

| Rule | Why skipped |
|---|---|
| bedrock-data-source-encryption-enabled | CFN has no InputParameters. Older unit tests invented `kmsKeyId`. |
| ec2-managedinstance-platform-check | `platformType` already covered on the two application rules. |
| lambda-function-settings-check | required+optional mix already covered by vpc-endpoint-enabled. |
| lambda-inside-vpc | optional CSV already covered. |
| required-tags | homogeneous pair list; iam-password-policy + restricted-common-ports suffice. |

## Expected tool results

### bindingsNG `--update --dry-run --rules-json tests/fixtures/param-smoketest.json --group 26y`

- `required=true` iff the CFN Parameters entry has **no** `Default` key.
- `Default: ""` → required=false; empty string is not a catalog default (keep any existing NIAID sample).
- No `GROUP#` writes.
- Compat `MISSING_REQUIRED` for required params with no catalog default and no 26y binding (api-gw, desired-instance-type, vpc-endpoint serviceNames, both EKS, both EC2 application rules, cloudwatch pair).

### bindingsNG default mode `--dry-run --group 26y`

- Optional + CFN/NIAID default → not written to the binding (optional defaults are emit-time / overlay-time).
- Required + no value → `BLOCKED_MISSING_REQUIRED`, no persist.
- Required + real PARAMDEF default → READY payload would include that value (dry-run still writes nothing).

### cpgNG

- No `--group`: emit required params that have a real catalog default; omit optionals.
- `--group 26y`: emit binding values (non-placeholder) plus required catalog defaults.
- CSV stays one string (`"s3.amazonaws.com,lambda"`), never a YAML list.
- `99999` omitted.
- Sidecar lists every PARAMDEF; pack Description is official text only.

### upackNG (fake deploy_fn)

- Unique `endpointConfigurationTypes` maps to api-gw-endpoint-type-check.
- Shared `oldestVersionSupported` or `applicationNames` in one pack → `UnmappableError`.
- Duration-like `minEventExpiryDuration` may infer `30` in the suggested CLI; that CLI is not executed.
- Zero Dynamo writes.
