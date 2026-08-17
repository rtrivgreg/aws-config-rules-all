# Y62 SitC Conformance pack fabrication run begin (build 202608050:800)

**Build Summary: (3) conformance packs generated**

compute.json->compute20260805-part01.yml, compute20260805-part02.yml, compute20260805-part03.yml, compute20260805-part04.yml

containers.json->containers20260805-part01.yml, containers20260805-part02.yml

storage.json->storage20260805-part01.yml, storage20260805-part02.yml

**Build generation and deploy Details**

# Manifest creation

python3 ~/repos/config-rules-all/python/emitter.py --format ~/repos/config-rules-all/yaml/conformance-pack-format.yml --output ~/output/y62-AWS-manifest08052026.yml
python3 ~/repos/config-rules-all/python/emitter.py --format ~/repos/config-rules-all/yaml/conformance-pack-format.yml --output ~/output/y62-AWS-manifest08172026.yml

### compute - CPG
python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/compute.json --t ~/output/y62-AWS-manifest08052026.yml --o ~/output/compute20260805.yml

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/database.json --t ~/output/y62-AWS-manifest08172026.yml --o ~/output/database2026017m.yml
### compute - Upack (AWS Config deploy)

python3 ~/gold/py/upack.py a1 ~/output/compute20260805-part01.yml

python3 ~/gold/py/upack.py a1 ~/output/database2026017p-part01.yml

Deployment completed at: 2026-08-05 12:36:02 UTC
Total time to deploy: 90.5 seconds


python3 ~/gold/py/upack.py a1 ~/output/compute20260805-part02.yml

Deployment completed at: 2026-08-05 12:39:02 UTC
Total time to deploy: 90.6 seconds

python3 ~/gold/py/upack.py a1 ~/output/compute20260805-part03.yml

Deployment completed at: 2026-08-05 12:41:04 UTC
Total time to deploy: 90.5 seconds

python3 ~/gold/py/upack.py a1 ~/output/compute20260805-part04.yml

Deployment completed at: 2026-08-05 12:42:55 UTC
Total time to deploy: 90.5 seconds

### containers - CPG

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/containers.json --t ~/output/y62-AWS-manifest08052026.yml --o ~/output/containers20260805.yml

### containers - Upack

python3 ~/gold/py/upack.py a1 ~/output/containers20260805-part01.yml

python3 ~/gold/py/upack.py a1 ~/output/containers20260805-part02.yml

### storage - CPG

python3 ~/repos/config-rules-all/python/cpg.py --r ~/repos/config-rules-all/JSON/storage.json --t ~/output/y62-AWS-manifest08052026.yml --o ~/output/storage20260805.yml

### storage - Upack
python3 ~/gold/py/upack.py a1 ~/output/storage20260805-part01.yml

python3 ~/gold/py/upack.py a1 ~/output/storage20260805-part02.yml
# 20260805 Y62 Conformance pack fabrication run end

