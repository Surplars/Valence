import copy
import struct
import unittest
import zlib
import elf_debug_compression as tool

class CompressionProofTests(unittest.TestCase):
    def pair(self):
        base={'header_identity':['same'],'program_headers':[('same',)],'loaded_sha256':['same'],
              'sha256':'a','bytes':10000,'sections':{}}
        for i,name in enumerate(('.text','.symtab','.strtab','.debug_info','.debug_line')):
            data=(b'__asan_init\0__ubsan_handle_type_mismatch_v1\0' if name=='.strtab' else name.encode()*100)
            base['sections'][name]=dict(index=i,type=1,flags=2 if name=='.text' else 0,address=0,size=len(data),
                link=0,info=0,alignment=1,entsize=0,data=data)
        other=copy.deepcopy(base);other['sha256']='b';other['bytes']=5000
        for name in ('.debug_info','.debug_line'):
            row=other['sections'][name];data=row['data'];row['data']=struct.pack('<IIQQ',1,0,len(data),1)+zlib.compress(data)
            row['flags']=tool.COMPRESSED;row['size']=len(row['data']);row['alignment']=8
        return base,other

    def test_positive_preserves_sanitizers_and_dwarf(self):
        row=tool.compare(*self.pair());self.assertEqual(row['status'],'PASS_DEBUG_COMPRESSION_ONLY')
        self.assertEqual(len(row['compressed_sections']),2)

    def test_changed_loaded_metadata_symbols_and_debug_reject(self):
        for mode in ('header','program','loaded','missing','flags','text','symbols','debug','debug-trailer','debug-size','align'):
            a,b=self.pair()
            if mode=='header':b['header_identity']=['changed']
            elif mode=='program':b['program_headers']=[]
            elif mode=='loaded':b['loaded_sha256']=['bad']
            elif mode=='missing':b['sections'].pop('.debug_line')
            elif mode=='flags':b['sections']['.debug_info']['flags']|=tool.ALLOC
            elif mode=='text':b['sections']['.text']['data']=b'changed'
            elif mode=='symbols':
                for x in (a,b):x['sections']['.strtab']['data']=b'no sanitizer'
            elif mode=='debug':b['sections']['.debug_info']['data']=struct.pack('<IIQQ',1,0,3,1)+zlib.compress(b'bad')
            elif mode=='debug-trailer':b['sections']['.debug_info']['data']+=b'extra'
            elif mode=='debug-size':
                r=b['sections']['.debug_info'];r['data']=r['data'][:8]+struct.pack('<Q',tool.MAX_DEBUG_BYTES+1)+r['data'][16:]
            elif mode=='align':b['sections']['.debug_info']['data']=b['sections']['.debug_info']['data'][:16]+struct.pack('<Q',4)+b['sections']['.debug_info']['data'][24:]
            with self.subTest(mode=mode),self.assertRaises(RuntimeError):tool.compare(a,b)

    def test_no_compression_is_not_proof(self):
        a,_=self.pair()
        with self.assertRaises(RuntimeError):tool.compare(a,copy.deepcopy(a))

    def test_malformed_header_rejected(self):
        for data in (b'',b'\x7fELF\x01\x01\x01'+bytes(100),bytes(100)):
            with self.assertRaises(RuntimeError):tool.parse(data)

if __name__=='__main__':unittest.main()
