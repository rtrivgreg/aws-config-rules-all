# Y62 SitC Conformance pack fabrication run begin (build 202608050:800)

**Build Summary: (n) conformance packs generated**

compute.json->compute20260805-part01.yml, compute20260805-part02.yml, compute20260805-part03.yml, compute20260805-part04.yml

containers.json->containers20260805-part01.yml, containers20260805-part02.yml

storage.json->storage20260805-part01.yml, storage20260805-part02.yml

**Build generation and deploy Details**

#####################
### Manifest creation
#####################

python3 ~/repos/config-rules-all/python/emitter.py --format ~/repos/config-rules-all/yaml/conformance-pack-format.yml --output ~/output/y62-AWS-manifest.yml


#####################
### Category creations
#####################

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

### storage.json - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/storage.json --t ~/output/y62-AWS-manifest.yml --o ~/output/storage.yml
#####################

#####################
### ALL - Upack (AWS Config deploy)
python3 ~/gold/py/upack.py a1 ~/output/analytics.yml
python3 ~/gold/py/upack.py a1 ~/output/compute-part01.yml
python3 ~/gold/py/upack.py a1 ~/output/database-part02.yml

python3 ~/gold/py/upack.py a1 ~/output/managementgovernance-part01.yml
python3 ~/gold/py/upack.py a2 ~/output/managementgovernance-part02.yml

python3 ~/gold/py/upack.py a1 ~/output/storage-part01.yml
python3 ~/gold/py/upack.py a2 ~/output/storage-part02.yml

python3 ~/gold/py/upack.py a1 ~/output/securityidentitycompliance-part01.yml

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

# 20260805 Y62 Conformance pack fabrication run end

