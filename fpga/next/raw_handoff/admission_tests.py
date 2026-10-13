#!/usr/bin/env python3
"""Real Python admission execution on explicitly synthetic host-only bundles."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import traceback
import os

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ['MAC_HANDOFF_SOURCE_ROOT']).resolve() if 'MAC_HANDOFF_SOURCE_ROOT' in os.environ else next(
    candidate for parent in HERE.parents for candidate in (parent, parent/'source')
    if (candidate/'src/main/scala/ip/ethernet/MacRawHandoff.scala').is_file())
OVERLAY = Path(os.environ.get('MAC_HANDOFF_OVERLAY_ROOT', SOURCE.parent/'entry-proposal-r1/source')).resolve()
EVIDENCE = HERE/'evidence'
spec = importlib.util.spec_from_file_location('admission', HERE/'verify_binding.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


class Bundle:
    def __init__(self, root, enabled):
        self.root = root
        self.b = dict(schema='fresh-mac-handoff-binding-v1', enabled=enabled)
        source = {}
        for logical, expected in json.loads((HERE/'source_expected.json').read_text()).items():
            path = OVERLAY/logical
            if not path.exists():
                path = SOURCE/logical
            assert sha(path) == expected, f'REVIEWED SOURCE SNAPSHOT DRIFT: {logical}'
            source[logical] = self.write('sources/'+logical, path.read_bytes())
        self.save('source_manifest', source)
        rtl = {'top': self.write('rtl/top.sv', b'// HOST MOCK ONLY\nmodule top;endmodule\n')}
        if enabled:
            rtl['helper'] = self.write('rtl/ValenceMacRawFallingSample.sv',
                                      (SOURCE/'src/main/resources/ethernet/ValenceMacRawFallingSample.sv').read_bytes())
        self.save('rtl_manifest', rtl)
        self.save('constraints_manifest', {'clock':self.write('constraints/mock.xdc', b'# HOST MOCK ONLY\n')})
        self.b['synthesis_filelist'] = self.write('synthesis-files.f', ('\n'.join(x['path'] for x in rtl.values())+'\n').encode())
        self.save('parameters', dict(schema='mac-raw-handoff-export-parameters-v1',
                  triSpeedRawClockHandoff=enabled, ingress_delay_cycles=128, profileFields=89, coreFields=172))
        self.save('actual_constructor', dict(schema='actual-mac-raw-handoff-platform-v1', scope='actual-constructor-only',
                  triSpeedRawClockHandoff=enabled, actualHandoffPresent=enabled, actualTriSpeedMac=True,
                  mappedFfCountVerified=False, physicalQualification=False, profileFields=89, coreFields=172,
                  expectedRawFallingScalarBits=12 if enabled else 0, expectedManagedRxScalarBits=11 if enabled else 0))
        self.b['contract'] = self.write('contract.tcldict', b'schema raw-handoff-mapped-v1\n')
        self.b['checkpoint'] = self.write('mock.dcp', b'NOT A DCP: HOST MOCK ONLY\n')
        self.provenance = dict(schema='fresh-mac-handoff-build-v1', review='REVIEWED_SOURCE_TO_DCP',
                               build_id='SYNTHETIC-HOST-ONLY', invocation=['MOCK'], stage='synth', enabled=enabled)
        self.seal()

    def write(self, relative, data):
        p = self.root/relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return dict(path=relative, sha256=sha(p))

    def save(self, key, data):
        self.b[key] = self.write(key+'.json', (json.dumps(data, sort_keys=True)+'\n').encode())

    def get(self, key):
        return json.loads((self.root/self.b[key]['path']).read_text())

    def seal(self):
        for key in ('source_manifest','rtl_manifest','constraints_manifest','parameters','actual_constructor','checkpoint','synthesis_filelist'):
            self.provenance[key+'_sha256'] = self.b[key]['sha256']
        self.save('provenance', self.provenance)
        self.publish()

    def publish(self):
        (self.root/'binding.json').write_text(json.dumps(self.b)+'\n')


def mutate_field(bundle, key, field, value):
    data = bundle.get(key)
    data[field] = value
    bundle.save(key, data)
    bundle.seal()


def run():
    results = []
    cases = [('on_positive', True, None), ('off_positive', False, None)]
    cases += [
        ('source_bytes_changed', True, lambda x:(x.root/next(iter(x.get('source_manifest').values()))['path']).write_bytes(b'changed')),
        ('rtl_bytes_changed', True, lambda x:(x.root/'rtl/top.sv').write_bytes(b'changed')),
        ('checkpoint_substitution', True, lambda x:(x.root/'mock.dcp').write_bytes(b'changed')),
        ('constraint_bytes_changed', True, lambda x:(x.root/'constraints/mock.xdc').write_bytes(b'changed')),
        ('old_binding_schema', True, lambda x:x.b.update(schema='old-exact64')),
        ('mode_not_boolean', True, lambda x:x.b.update(enabled=1)),
        ('unsafe_artifact_path', True, lambda x:x.b['contract'].update(path='../contract.tcldict')),
        ('wrong_original128', True, lambda x:mutate_field(x,'parameters','ingress_delay_cycles',64)),
        ('wrong_core_fields', True, lambda x:mutate_field(x,'parameters','coreFields',173)),
        ('wrong_profile_fields', True, lambda x:mutate_field(x,'parameters','profileFields',88)),
        ('actual_mode_false_on', True, lambda x:mutate_field(x,'actual_constructor','triSpeedRawClockHandoff',False)),
        ('actual_mode_true_off', False, lambda x:mutate_field(x,'actual_constructor','triSpeedRawClockHandoff',True)),
        ('actual_helper_absent_on', True, lambda x:mutate_field(x,'actual_constructor','actualHandoffPresent',False)),
        ('actual_helper_present_off', False, lambda x:mutate_field(x,'actual_constructor','actualHandoffPresent',True)),
        ('actual_receipt_scope', True, lambda x:mutate_field(x,'actual_constructor','scope','profile-only')),
        ('fabricated_physical_flag', True, lambda x:mutate_field(x,'actual_constructor','physicalQualification',True)),
        ('wrong_expected_ff_count', True, lambda x:mutate_field(x,'actual_constructor','expectedRawFallingScalarBits',11)),
        ('old_provenance_schema', True, lambda x:mutate_field(x,'provenance','schema','old-exact64')),
        ('provenance_checkpoint_hash', True, lambda x:mutate_field(x,'provenance','checkpoint_sha256','0'*64)),
    ]
    # Provenance mutation must avoid seal restoring the field under test.
    cases[-2] = ('old_provenance_schema', True, lambda x:x.save('provenance', {**x.get('provenance'),'schema':'old-exact64'}))
    cases[-1] = ('provenance_checkpoint_hash', True, lambda x:x.save('provenance', {**x.get('provenance'),'checkpoint_sha256':'0'*64}))
    def resource_change(x, add):
        rtl=x.get('rtl_manifest')
        if add:
            rtl['helper']=x.write('rtl/ValenceMacRawFallingSample.sv', (SOURCE/'src/main/resources/ethernet/ValenceMacRawFallingSample.sv').read_bytes())
        else:
            del rtl['helper']
        x.save('rtl_manifest',rtl)
        x.b['synthesis_filelist']=x.write('synthesis-files.f', ('\n'.join(r['path'] for r in rtl.values())+'\n').encode())
        x.seal()
    cases += [('missing_helper_on',True,lambda x:resource_change(x,False)),('helper_emitted_off',False,lambda x:resource_change(x,True))]
    for name, mode, mutation in cases:
        with tempfile.TemporaryDirectory(prefix='mac-admission-') as tmp:
            b = Bundle(Path(tmp), mode)
            if mutation:
                mutation(b)
                b.publish()
            try:
                output = verifier.verify(b.root/'contract.tcldict', b.root/'binding.json', b.root/'mock.dcp')
                rejected = False
            except Exception:
                output = traceback.format_exc()
                rejected = True
            passed = rejected == bool(mutation)
            (EVIDENCE/f'admission_{name}.log').write_text(output+'\n')
            result=dict(case=name, expected='reject' if mutation else 'accept', passed=passed, rejected=rejected)
            results.append(result)
            print(json.dumps(result), flush=True)
    receipt=dict(status='HOST_ADMISSION_ONLY', passed=all(x['passed'] for x in results), tests=results,
                 source_sha256={p.name:sha(p) for p in [HERE/'verify_binding.py',HERE/'source_expected.json',HERE/'admission_tests.py']})
    (EVIDENCE/'admission-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt['passed']


if __name__ == '__main__':
    raise SystemExit(0 if run() else 1)
