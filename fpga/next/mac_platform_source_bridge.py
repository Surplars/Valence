"""Exact two-leaf current-source OFF compatibility; never a historical certificate."""
import hashlib
import json
import importlib.util
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / 'near-term-a-profile.json'


def checked_sources():
    profile = json.loads(MANIFEST.read_text())
    # Narrow current-source compatibility. Historical manifests/receipts remain
    # immutable; only these two reviewed platform plumbing leaves may differ.
    path = HERE / 'near-term-a-mac-platform-compat.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != 'f10777286e078763bf9957d9c3da38ba54775768ce5531e98f54c42adbbf70e9':
        raise RuntimeError('unreviewed MAC platform compatibility bridge')
    bridge = json.loads(path.read_text())
    names = {'src/main/scala/core/ooo/BoardSocTop.scala', 'src/main/scala/core/ooo/FpgaNextConfig.scala'}
    if bridge['schema'] != 'near-term-a-false-mac-platform-source-bridge-v1' or \
            bridge['parent_manifest_sha256'] != hashlib.sha256(MANIFEST.read_bytes()).hexdigest() or \
            bridge['project_only_when_false'] != {'triSpeedRawClockHandoff': False} or \
            (bridge['old_profile_fields'], bridge['current_profile_fields'], bridge['core_fields']) != (88, 89, 172) or \
            bridge['old_native_options'] != profile['native_options'] or \
            set(bridge['changed_sources']) != names or \
            bridge['historical_receipt_reused'] is not False or \
            bridge['source_only_compatibility'] is not True or bridge['physical_qualification'] is not False:
        raise RuntimeError('MAC platform OFF bridge contract differs')
    original = ROOT / bridge['original_complete_profile_file']
    if original != HERE / 'near-term-a-before-mac-platform.json' or \
            hashlib.sha256(original.read_bytes()).hexdigest() != bridge['original_complete_profile_sha256']:
        raise RuntimeError('original complete A profile snapshot differs')
    if '--tri-speed-raw-clock-handoff' in profile['native_options']:
        raise RuntimeError('the existing A entry must remain MAC handoff OFF')
    spec = importlib.util.spec_from_file_location("mac_to_seal_source_bridge", HERE / "young_load_seal_source_bridge.py")
    downstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(downstream)
    current = {}
    for name, row in bridge['changed_sources'].items():
        expected = downstream.current_mac_platform_digest(name, row["new_sha256"])
        if row['old_sha256'] != profile['production_leaf_sha256'][name] or \
                hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('current MAC platform plumbing source differs: ' + name)
        current[name] = {"old_sha256": row["old_sha256"], "new_sha256": expected}
    return current


