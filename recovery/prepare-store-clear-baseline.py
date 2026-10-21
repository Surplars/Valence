"""Materialize the exact prior production translator for the same native fixture.

Only Scala class/top names and an external observer of the old accepted-store
expression differ. No generated SV is patched and no production file is changed.
"""
import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent.parent
git = r'D:\TOOLS\ENV\Git\cmd\git.exe'
commit = 'f6f04c4f8a66b217e1c4511d3d8038a8f32b1f68'
source = 'src/main/scala/core/inorder/FiveStageAddressTranslation.scala'
raw = subprocess.check_output([git, 'show', commit + ':' + source], cwd=root)
text = raw.decode('utf-8')
assert text.count('class FiveStageAddressTranslation(') == 1
baseline = text.replace('class FiveStageAddressTranslation(', 'class BaselineFiveStageAddressTranslation(')
template = (root/'src/test/scala/inorder/StoreClearAdmissionBatch.scala').read_text()
assert template.count('io.storeAccepted := dt.io.ordinaryStoreAccepted.get') == 1
wrapper = template.replace('StoreClearAdmissionBatch', 'StoreClearAdmissionBaseline')
wrapper = wrapper.replace('class StoreClearAdmissionBaseline extends Module {',
    'class StoreClearAdmissionBaseline extends Module {\n    override def desiredName = "StoreClearAdmissionBatch"')
wrapper = wrapper.replace('new FiveStageAddressTranslation(', 'new BaselineFiveStageAddressTranslation(')
wrapper = wrapper.replace('io.storeAccepted := dt.io.ordinaryStoreAccepted.get',
    'io.storeAccepted := dt.io.request.fire && dt.io.request.bits.write && !dt.io.request.bits.atomic')
out = root/'src/test/scala/inorder/generated-store-baseline'
assert not out.exists(), 'Preserve previous materialization and its evidence'
out.mkdir()
(out/'BaselineFiveStageAddressTranslation.scala').write_text(baseline)
(out/'StoreClearAdmissionBaseline.scala').write_text(wrapper)
sha = lambda data: hashlib.sha256(data).hexdigest()
receipt = {'baseline_commit': commit, 'historical_source': source,
    'historical_source_sha256': sha(raw), 'fixture_template_sha256': sha(template.encode()),
    'generated_files_sha256': {str(p.relative_to(root)): sha(p.read_bytes()) for p in out.glob('*.scala')},
    'same_tb_seed_and_timeout': True,
    'production_unchanged': True,
    'transformations': ['Class name only in historical DT',
        'Top desiredName preserved for identical SystemVerilog testbench',
        'Observe original accepted-store equation; no feedback or control added']}
(root/'recovery/store-clear-baseline-materialization.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt))
