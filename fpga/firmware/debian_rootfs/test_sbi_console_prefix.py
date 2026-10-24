import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
from apply_sbi_console_prefix import apply, validate_vld


def packed(body):
    header=struct.pack('<8I',0x31444c56,1,0x80200000,0x80200000,len(body),zlib.crc32(body),256,0)
    return header+struct.pack('<I',zlib.crc32(header))+body

def sha(b): return hashlib.sha256(b).hexdigest()

class PrefixTest(unittest.TestCase):
    def test_safe_reassembly_and_negative_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);old=packed(b'OLDPREFIX'+b'UNCHANGED-BODY');new=packed(b'NEWPREFIX'+b'UNCHANGED-BODY');split=45
            (p/'old').write_bytes(old);(p/'prefix').write_bytes(new[:split])
            record=dict(original_vld_sha256=sha(old),original_vld_bytes=len(old),prefix_bytes=split,
                        new_prefix_sha256=sha(new[:split]),unchanged_body_sha256=sha(old[split:]),
                        new_vld_sha256=sha(new),new_vld_bytes=len(new))
            (p/'manifest').write_text(json.dumps(record));apply(p/'old',p/'prefix',p/'manifest',p/'new')
            self.assertEqual((p/'new').read_bytes(),new);self.assertEqual((p/'old').read_bytes(),old)
            for output in (p/'old',p/'prefix',p/'manifest',p/'new'):
                with self.assertRaises(ValueError):apply(p/'old',p/'prefix',p/'manifest',output)
            for key,value in [('original_vld_sha256','0'*64),('new_prefix_sha256','0'*64),('unchanged_body_sha256','0'*64),('new_vld_sha256','0'*64),('prefix_bytes',46),('new_vld_bytes',1)]:
                bad=dict(record);bad[key]=value;(p/'manifest').write_text(json.dumps(bad))
                with self.assertRaises(ValueError):apply(p/'old',p/'prefix',p/'manifest',p/'invalid')
                self.assertFalse((p/'invalid').exists())
    def test_vld_crc_and_contract(self):
        good=packed(b'0123456789');validate_vld(good)
        for offset in (0,4,8,12,16,20,24,28,32,40):
            bad=bytearray(good);bad[offset]^=1
            with self.assertRaises(ValueError):validate_vld(bad)
        with self.assertRaises(ValueError):validate_vld(good[:-1])
        with self.assertRaises(ValueError):validate_vld(good+b'x')

if __name__=='__main__':unittest.main()
