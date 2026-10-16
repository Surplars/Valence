"""Fail-closed negative checks against a completed original model manifest."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

runner = Path(__file__).with_name('posted_frozen_overlap_build.py').resolve()
spec = importlib.util.spec_from_file_location('bound_runner', runner)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
base = module.ROOT / sys.argv[1]
manifest_file = base / 'original-model-manifest.json'
original_bytes = manifest_file.read_bytes()
original = json.loads(original_bytes)
src, tools = module.sources(), module.tools()
revision = original['source_revision']
models = base / 'models'
module.validate(original, src, tools, revision, models)
results = []
def rejected(label, manifest=original, sources=src, identity=tools, rev=revision):
    try:
        module.validate(manifest, sources, identity, rev, models)
    except (ValueError, KeyError, FileNotFoundError) as error:
        results.append({'case': label, 'rejected': True, 'error': str(error)})
    else:
        raise AssertionError('accepted invalid provenance: ' + label)
rejected('legacy_unverified_manifest', {})
rejected('stale_original_revision', rev='0' * 40)
changed = dict(src)
changed['src/main/scala/core/ooo/NonBlockingCoherentLineCache.scala'] = '0' * 64
rejected('changed_production_source', sources=changed)
changed = copy.deepcopy(tools)
changed['gsim']['sha256'] = '0' * 64
rejected('changed_tool_binary', identity=changed)
header = next((models / 'off').glob('*.h'))
previous = header.read_bytes()
try:
    header.write_bytes(previous + b'\n// deliberate provenance corruption\n')
    rejected('actual_corrupt_generated_header')
finally:
    header.write_bytes(previous)
obj = next((models / 'on').glob('*.o'))
previous = obj.read_bytes()
try:
    obj.unlink()
    rejected('actual_missing_compiled_object')
finally:
    obj.write_bytes(previous)
module.validate(original, src, tools, revision, models)
assert manifest_file.read_bytes() == original_bytes
output = base / 'provenance-negatives.json'
assert not output.exists()
output.write_text(json.dumps({'status': 'PASS', 'original_manifest_sha256': module.digest(manifest_file),
    'test_sha256': module.digest(Path(__file__).resolve()), 'cases': results}, indent=2) + '\n')
print('PASS: six provenance rejections; original manifest/model bytes restored and revalidated')
