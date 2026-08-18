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

### analytics - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/analytics.json --t ~/output/y62-AWS-manifest.yml --o ~/output/analytics.yml

### applicationintegration - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/applicationintegration.json --t ~/output/y62-AWS-manifest.yml --o ~/output/applicationintegration.yml

### compute - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/compute.json --t ~/output/y62-AWS-manifest08052026.yml --o ~/output/compute20260805.yml

### database - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/database.json --t ~/output/y62-AWS-manifest08182026.yml --o ~/output/database2026018b.yml

### migrationtransfer - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/migrationtransfer.json --t ~/output/y62-AWS-manifest08182026.yml --o ~/output/migrationtransfer.yml

### securityidentitycompliance.json - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/securityidentitycompliance.json --t ~/output/y62-AWS-manifest08172026.yml --o ~/output/securityidentitycompliance2026017u.yml
#####################

#####################
### ALL - Upack (AWS Config deploy)
python3 ~/gold/py/upack.py a1 ~/output/analytics.yml
python3 ~/gold/py/upack.py a1 ~/output/compute20260805-part01.yml

python3 ~/gold/py/upack.py a1 ~/output/database20260818v-part02.yml

python3 ~/gold/py/upack.py a1 ~/output/securityidentitycompliance2026017u-part01.yml

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

# 20260805 Y62 Conformance pack fabrication run end

