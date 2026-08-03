Vitals

git pull

git status
git fetch origin
git pull --rebase origin main
git push

pip install python-hcl2

python3 ~/repos/config-rules-all/python/emitter.py --format ~/repos/config-rules-all/yaml/conformance-pack-format.yml --output ~/output/y62-AWS-manifestz.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/compute.json --t ~/output/y62-AWS-manifest.yml --o ~/output/compute0803a.yml
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/containers.json --t ~/output/y62-AWS-manifest.yml --o ~/output/Container0803a.yml

micro ~/output/y62-AWS-manifestz.yml
ls -lt ~/output/ 

python3 ~/gold/py/upack.py a1 ~/output/Container0803m-part01.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/containers.json --t ~/output/y62-AWS-manifestZ.yml --o ~/output/Container0803m.yml


https://github.com/niaid/terraform-aws-managed-config-rules.git
https://github.com/rtrivgreg/config-rules-all.git
https://github.com/niaid/terraform-aws-managed-config-rules/blob/main/managed_rules_variables.tf
