git status
git fetch origin
git pull --rebase origin main
git push


https://github.com/niaid/terraform-aws-managed-config-rules.git

python3 /home/cloudshell-user/gold/py/upack.py a1 /home/cloudshell-user/output/CP0727m-part01.yml

https://github.com/rtrivgreg/config-rules-all.git

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/compute.json --t ~/repos/config-rules-all/output/y62-truth-manifestz.yaml --o ~/output/CP0728n.yml

python emitter.py \
  --format conformance-pack-format.yaml \
  --output output/y62-truth-manifest.yaml

python emitter.py \ --format conformance-pack-format.yaml \ --output output/test-pack.yaml \ --rule-limit 2 \ --debug

https://github.com/niaid/terraform-aws-managed-config-rules/blob/main/managed_rules_variables.tf
