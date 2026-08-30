# AWS Config Conformance Pack Generator

## `python/cpgNG.py`

`cpgNG.py` generates deployable AWS Config Conformance Pack YAML files from a JSON list of AWS-managed Config rule names, using the Y62DB DynamoDB catalog as its source of truth. It retrieves rule profiles, parameter definitions, scopes, descriptions, and optional group-specific parameter bindings; constructs valid `AWS::Config::ConfigRule` resources; and divides output into packs containing no more than 30 rules. When a requested rule is absent from DynamoDB, it generates a minimal rule definition so pack generation can continue. Command-line options specify the rules JSON file, output filename, DynamoDB table and region, and optional organizational group and binding.

---
## `python/cpg.py`

`cpgNG.py` generates deployable AWS Config Conformance Pack YAML files from a JSON array of AWS-managed Config rule names and a YAML source-of-truth manifest. It preserves available rule descriptions, scopes, source identifiers, and input parameters; generates minimal definitions for rules missing from the source of truth; derives CloudFormation logical IDs; normalizes descriptions; and divides the requested rules into pack files containing no more than 30 rules each. Command-line options specify the source-of-truth YAML file, rules JSON file, and output filename.

---

# CPG aws-config-rules-all  
NG (DynamoDB)

PREFLIGHT
git pull 
source /home/ubuntu/repos/Y62DB/.venv/bin/activate
source /Users/sunyanggregoire/code/.venv/bin/activate  
source /home/ubuntu/repos/Y62DB/.venv/bin/activate

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/applicationintegration.json -o ~/output/applicationintegration.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/analytics.json -o ~/output/analytics.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/compute.json -o ~/output/compute.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/containers.json -o ~/output/containers.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/database.json -o ~/output/database.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/managementgovernance.json -o ~/output/managementgovernance.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/migrationtransfer.json -o ~/output/migrationtransfer.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/mlai.json -o ~/output/mlai.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/securityidentitycompliance.json -o ~/output/securityidentitycompliance.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/storage.json -o ~/output/storage.yml

python3 ~/repos/config-rules-all/python/upack.py s1 ~/output/storage-part01.yml 
python3 ~/repos/config-rules-all/python/upack.py s2 ~/output/storage-part02.yml 
<HR>

EMITTER (generate yaml manifest)
python3 ~/repos/config-rules-all/python/emitter.py --managed-rules-locals ~/repos/config-rules-all/vendor/niaid/managed_rules_locals.tf --managed-rules-variables ~/repos/config-rules-
all/vendor/niaid/managed_rules_variables.tf --format ~/repos/config-rules-all/yaml/conformance-pack-format.yml --output ~/output/y62-AWS-manifest.yml --description "Y62 NIAID AWS Config Production Baseline"

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/mlai.json --t ~/output/y62-AWS-manifest.yml --o ~/output/mlai.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/analytics.json --t ~/output/y62-AWS-manifest.yml --o ~/output/analytics.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/applicationintegration.json --t ~/output/y62-AWS-manifest.yml --o ~/output/applicationintegration.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/compute.json --t ~/output/y62-AWS-manifest.yml --o ~/output/compute.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/database.json --t ~/output/y62-AWS-manifest.yml --o ~/output/database.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/managementgovernance.json --t ~/output/y62-AWS-manifest.yml --o ~/output/managementgovernance.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/mlai.json --t ~/output/y62-AWS-manifest.yml --o ~/output/mlai.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/migrationtransfer.json --t ~/output/y62-AWS-manifest.yml --o ~/output/migrationtransfer.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/securityidentitycompliance.json --t ~/output/y62-AWS-manifest.yml --o ~/output/securityidentitycompliance.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/storage.json --t ~/output/y62-AWS-manifest.yml --o ~/output/storage.yml 

# Deploy
ALL - Upack 

python3 ~/repos/config-rules-all/python/upack.py a1 ~/output/analytics.yml

python3 ~/repos/config-rules-all/python/upack.py a1 ~/output/compute-part01.yml

python3 ~/repos/config-rules-all/python/upack.py a1 ~/output/database-part02.yml

python3 ~/repos/config-rules-all/python/upack.py a1 ~/output/managementgovernance-part01.yml

python3 ~/repos/config-rules-all/python/upack.py a2 ~/output/managementgovernance-part02.yml

python3 ~/repos/config-rules-all/python/upack.py s1 ~/output/storage-part01.yml

python3 ~/repos/config-rules-all/python/upack.py s2 ~/output/storage-part02.yml

python3 ~/gold/py/upack.py a1 ~/output/securityidentitycompliance-part01.yml





