#Y62 Conformance pack fabrication run begin (build 202608050:800)

Build Summary: (3) conformance packs generated

compute.json->compute20260805-part01.yml, compute20260805-part02.yml, compute20260805-part03.yml, compute20260805-part04.yml

containers.json->containers20260805-part01.yml, containers20260805-part02.yml

storage.json->storage20260805-part01.yml, storage20260805-part02.yml

Build Details:
python3 ~/repos/config-rules-all/python/emitter.py --format ~/repos/config-rules-all/yaml/conformance-pack-format.yml --output ~/output/y62-AWS-manifest08052026.yml

compute - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/compute.json --t ~/output/y62-AWS-manifest08052026.yml --o ~/output/compute20260805.yml

compute - Upack
python3 ~/gold/py/upack.py a1 ~/output/compute20260805-part01.yml

python3 ~/gold/py/upack.py a1 ~/output/compute20260805-part02.yml

python3 ~/gold/py/upack.py a1 ~/output/compute20260805-part03.yml

python3 ~/gold/py/upack.py a1 ~/output/compute20260805-part04.yml

containers - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/containers.json --t ~/output/y62-AWS-manifest08052026.yml --o ~/output/containers20260805.yml

containers - Upack
python3 ~/gold/py/upack.py a1 ~/output/containers20260805-part01.yml

python3 ~/gold/py/upack.py a1 ~/output/containers20260805-part02.yml

# storage - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/storage.json --t ~/output/y62-AWS-manifest08052026.yml --o ~/output/storage20260805.yml

# storage - Upack
python3 ~/gold/py/upack.py a1 ~/output/storage20260805-part01.yml

python3 ~/gold/py/upack.py a1 ~/output/storage20260805-part02.yml
# 20260805 Y62 Conformance pack fabrication run end


Vitals

git pull

git status
git fetch origin
git pull --rebase origin main
git push

pip install python-hcl2


micro ~/output/y62-AWS-manifestz.yml
ls -lt ~/output/ 

python3 ~/gold/py/upack.py a1 ~/output/Container0803m-part01.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/containers.json --t ~/output/y62-AWS-manifestZ.yml --o ~/output/Container0803m.yml


https://github.com/niaid/terraform-aws-managed-config-rules.git
https://github.com/rtrivgreg/config-rules-all.git
https://github.com/niaid/terraform-aws-managed-config-rules/blob/main/managed_rules_variables.tf
