python3 ~/gold/py/cpg0727a.py --r ~/gold/json/mrs2.json --t ~/gold/yml/y62-truth-manifest.yml --o ~/output/CP0727.yml

python emitter.py \
  --format conformance-pack-format.yaml \
  --output output/y62-truth-manifest.yaml

python emitter.py \ --format conformance-pack-format.yaml \ --output output/test-pack.yaml \ --rule-limit 2 \ --debug

https://github.com/niaid/terraform-aws-managed-config-rules/blob/main/managed_rules_variables.tf
