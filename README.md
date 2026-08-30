# aws-config-rules-all  Y62 Config Rule Build Suite

CPG NG (DynamoDB)

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/analytics.json -o ~/output/analytics.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/mlai.json -o ~/output/mlai.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/compute.json -o ~/output/storageNG.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/containers.json -o ~/output/storage.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/storage.json -o ~/output/storageNG.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/storage.json -o ~/output/storageNG.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/storage.json -o ~/output/storageNG.yml

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/securityidentitycompliance.json -o ~/output/securityidentitycompliance.yml

python3 ~/repos/config-rules-all/python/upack.py s1 ~/output/storage-part01.yml 
python3 ~/repos/config-rules-all/python/upack.py s2 ~/output/storage-part02.yml 
<HR>

G1 EMITTER (generate yaml manifest)
python3 ~/repos/config-rules-all/python/emitter.py --managed-rules-locals ~/repos/config-rules-all/vendor/niaid/managed_rules_locals.tf --managed-rules-variables ~/repos/config-rules-
all/vendor/niaid/managed_rules_variables.tf --format ~/repos/config-rules-all/yaml/conformance-pack-format.yml --output ~/output/y62-AWS-manifest.yml --description "Y62 NIAID AWS Config Production Baseline"

### aiml - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/aiml.json --t ~/output/y62-AWS-manifest.yml --o ~/output/aiml.yml

### analytics - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/analytics.json --t ~/output/y62-AWS-manifest.yml --o ~/output/analytics.yml

### applicationintegration - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/applicationintegration.json --t ~/output/y62-AWS-manifest.yml --o ~/output/applicationintegration.yml

### compute - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/compute.json --t ~/output/y62-AWS-manifest.yml --o ~/output/compute.yml

### database - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/database.json --t ~/output/y62-AWS-manifest.yml --o ~/output/database.yml

### managementgovernance - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/managementgovernance.json --t ~/output/y62-AWS-manifest.yml --o ~/output/managementgovernance.yml

### mlai - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/mlai.json --t ~/output/y62-AWS-manifest.yml --o ~/output/mlai.yml

### migrationtransfer - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/migrationtransfer.json --t ~/output/y62-AWS-manifest.yml --o ~/output/migrationtransfer.yml

### securityidentitycompliance.json - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/securityidentitycompliance.json --t ~/output/y62-AWS-manifest.yml --o ~/output/securityidentitycompliance.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/storage.json --t ~/output/y62-AWS-manifest.yml --o ~/output/storage.yml 

python3 ~/repos/config-rules-all/python/cpgNG.py -r ~/repos/config-rules-all/JSON/storage.json -o ~/output/storagez.yml

# Deploy
ALL - Upack (AWS Config deploy)

python3 ~/repos/config-rules-all/python/upack.py a1 ~/output/analytics.yml

python3 ~/repos/config-rules-all/python/upack.py a1 ~/output/compute-part01.yml

python3 ~/repos/config-rules-all/python/upack.py a1 ~/output/database-part02.yml

python3 ~/repos/config-rules-all/python/upack.py a1 ~/output/managementgovernance-part01.yml

python3 ~/repos/config-rules-all/python/upack.py a2 ~/output/managementgovernance-part02.yml

python3 ~/repos/config-rules-all/python/upack.py s1 ~/output/storage-part01.yml

python3 ~/repos/config-rules-all/python/upack.py s2 ~/output/storage-part02.yml

python3 ~/gold/py/upack.py a1 ~/output/securityidentitycompliance-part01.yml

PREFLIGHT
git pull 
source /home/ubuntu/repos/Y62DB/.venv/bin/activate
source /Users/sunyanggregoire/code/.venv/bin/activate  
source /home/ubuntu/repos/Y62DB/.venv/bin/activate





