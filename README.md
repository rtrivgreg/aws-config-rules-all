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




printf "%-40s | %-10s | %-20s | %-20s\n" "VIRTUAL ENVIRONMENT PATH" "SIZE" "CREATION DATE" "LAST USED DATE" && \
printf "%-40s-+-%-10s-+-%-20s-+-%-20s\n" "----------------------------------------" "----------" "--------------------" "--------------------" && \
find ~ -maxdepth 5 -type f -name "pyvenv.cfg" 2>/dev/null | while read -r cfg; do
    venv_dir=$(dirname "$cfg")

    #view all envs
    # 1. Total Disk Space Usage
    size=$(du -sh "$venv_dir" | awk '{print $1}')
    
    # 2. Date of Creation (Metadata status change time)
    created=$(stat -c "%y" "$cfg" | cut -d'.' -f1)
    
    # 3. Date of Last Use (Latest access time among binary files like python/pip)
    last_used=$(find "$venv_dir/bin" -type f -exec stat -c "%X %x" {} + 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-3 | cut -d'.' -f1)
    
    # Fallback if binary scan is blank
    if [ -z "$last_used" ]; then last_used=$(stat -c "%x" "$cfg" | cut -d'.' -f1); fi
    
    # Truncate long paths cleanly for the visual layout
    display_path=$venv_dir
    if [ ${#display_path} -gt 40 ]; then display_path="...${display_path: -37}"; fi
    
    printf "%-40s | %-10s | %-20s | %-20s\n" "$display_path" "$size" "$created" "$last_used"
done




# 20260805 Y62 Conformance pack fabrication run end

