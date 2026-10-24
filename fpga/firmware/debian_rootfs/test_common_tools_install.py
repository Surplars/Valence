import copy
import hashlib
import json
import struct
from pathlib import Path
import tempfile
import unittest
from common_tools_install import install_tools

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.bundle=self.base/'bundle';self.root=self.base/'root'
        self.bundle.mkdir();self.root.mkdir();(self.bundle/'tool.py').write_text('#!/usr/bin/python3\nprint(1)\n')
        p=self.bundle/'tool.py'
        self.record=dict(schema=1,stage='tools_ready_host_qemu_only',target=dict(architecture='riscv64',isa='rv64gc',abi='lp64d'),required_debian_packages=['python3'],files=[dict(path='tool.py',destination='/usr/local/bin/valence-test',sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,mode='0755',kind='python',linkage='python3-stdlib',needed=[])])
    def run_install(self, packages=('python3',)):
        (self.bundle/'tools-build.json').write_text(json.dumps(self.record))
        return install_tools(self.bundle,self.root,packages)
    def test_snapshot_capability_preserved(self):
        cap={'a1-runtime':{'cpu_abi':2,'retirement_lanes':2,'scalar_request_lane':0},'fabric_abi':1}
        self.record['clockmon_snapshot_profiles']=cap
        result=self.run_install()
        self.assertEqual(result['clockmon_snapshot_profiles'],cap)
    def test_positive(self):
        self.run_install();self.assertEqual((self.root/'usr/local/bin/valence-test').read_bytes(),(self.bundle/'tool.py').read_bytes())
    def test_all_validate_before_write(self):
        bad=copy.deepcopy(self.record['files'][0]);bad['destination']='/etc/bad';self.record['files'].append(bad)
        with self.assertRaises(RuntimeError):self.run_install()
        self.assertEqual(list(self.root.iterdir()),[])
    def test_negatives(self):
        for key,value in [('path','../tool.py'),('path','/tool.py'),('destination','/usr/local/bin/../../etc/bad'),('destination','/tmp/bad'),('sha256','0'*64),('bytes',0),('mode','4755'),('linkage','dynamic')]:
            with self.subTest(key=key,value=value):
                old=self.record['files'][0][key];self.record['files'][0][key]=value
                with self.assertRaises(RuntimeError):self.run_install()
                self.record['files'][0][key]=old
        with self.assertRaises(RuntimeError):self.run_install(())
    def test_document(self):
        self.record['files'][0].update(kind='document',mode='0644',linkage='none',destination='/usr/local/share/valence-tools/README')
        self.run_install()
        self.assertEqual((self.root/'usr/local/share/valence-tools/README').stat().st_mode & 0o777,0o644)
    def test_elf_program_headers(self):
        blob=bytearray(120);blob[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<H',blob,18,243);struct.pack_into('<Q',blob,32,64)
        struct.pack_into('<I',blob,48,4);struct.pack_into('<HH',blob,54,56,1)
        struct.pack_into('<I',blob,64,1)
        p=self.bundle/'tool.py';p.write_bytes(blob)
        entry=self.record['files'][0];entry.update(kind='elf',linkage='static',bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest())
        self.run_install()
        entry['destination']='/usr/local/bin/valence-elf-negative'
        for ph_type in (2,3):
            struct.pack_into('<I',blob,64,ph_type);p.write_bytes(blob);entry['sha256']=hashlib.sha256(blob).hexdigest()
            with self.assertRaises(RuntimeError):self.run_install()
        self.assertFalse((self.root/'usr/local/bin/valence-elf-negative').exists())
    def test_existing_and_symlink_escape(self):
        dest=self.root/'usr/local/bin';dest.mkdir(parents=True);(dest/'valence-test').write_text('keep')
        with self.assertRaises(RuntimeError):self.run_install()
        self.assertEqual((dest/'valence-test').read_text(),'keep')
        self.record['files'][0]['destination']='/usr/local/lib/valence-tools/test'
        (self.root/'usr/local/lib').symlink_to(self.base)
        with self.assertRaises(RuntimeError):self.run_install()
if __name__=='__main__':unittest.main()
