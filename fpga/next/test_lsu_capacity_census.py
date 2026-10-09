import copy,hashlib,json,tempfile,unittest
from pathlib import Path
import lsu_capacity_census as census

class LiteralCensusTests(unittest.TestCase):
    def test_scalar_and_array_widths(self):
        x=census.declarations('reg a,b; reg [7:0] c; reg [2:0] mem[0:3]; // reg hidden;\n/*reg bad;*/')
        self.assertEqual((x['scalar_reg_bits'],x['array_reg_bits']),(10,12))
    def test_unsupported_geometry_fails(self):
        with self.assertRaises(RuntimeError):census.declarations('reg [7:0] mem[N:0];')
    def fixture(self,root,owners,unknown=False):
        rtl=root/'rtl';rtl.mkdir()
        texts={
            'BoardSocTop':'  IntegerBackend core ();\n  InstructionRom rom ();',
            'IntegerBackend':'  ParallelLoadStoreUnit lsu ();\n  StoreBuffer stores ();',
            'ParallelLoadStoreUnit':'\n'.join(f'  LoadStoreUnit slots_{i} ();' for i in range(owners)),
            'LoadStoreUnit':'  reg [3:0] token;\n  reg [7:0] array[0:1];',
            'StoreBuffer':'  reg flag;',
            'InstructionRom':'  '+('unknown_ip' if unknown else 'blk_mem_gen_0')+' memory ();'}
        for name,body in texts.items():(rtl/(name+'.sv')).write_text('module '+name+'();\n'+body+'\nendmodule\n')
        hashes={'rtl/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in rtl.glob('*.sv')}
        (root/'receipt.json').write_text(json.dumps({'status':'PASS_RTL_EXPORT_ONLY','rtl_sha256':hashes,'source_sha256':{},'profile':{'lsu_entries':owners}}))
    def test_reachable_instances_are_weighted(self):
        for owners in (2,4):
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);self.fixture(p,owners);r=census.census(p)
                self.assertEqual(r['scopes']['BoardSocTop']['scalar_reg_bits'],owners*4+1)
                self.assertEqual(r['scopes']['BoardSocTop']['array_reg_bits'],owners*16)
                self.assertEqual(r['scopes']['BoardSocTop']['excluded_external_instances'],{'blk_mem_gen_0':1})
    def test_unexpected_external_ip_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.fixture(p,2,True)
            with self.assertRaises(RuntimeError):census.census(p)
    def test_native_artifact_drift_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.fixture(p,2);(p/'rtl/LoadStoreUnit.sv').write_text('modified')
            with self.assertRaises(RuntimeError):census.census(p)

    def mutate(self,root,name,transform,omit_hash=False):
        path=root/'rtl'/name;text=transform(path.read_text());path.write_text(text)
        receipt=json.loads((root/'receipt.json').read_text())
        if omit_hash:receipt['rtl_sha256'].pop('rtl/'+name)
        else:receipt['rtl_sha256']['rtl/'+name]=hashlib.sha256(path.read_bytes()).hexdigest()
        (root/'receipt.json').write_text(json.dumps(receipt))
    def test_unindented_known_instance_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.fixture(p,2)
            self.mutate(p,'BoardSocTop.sv',lambda x:x.replace('  IntegerBackend core','IntegerBackend core'))
            self.assertEqual(census.census(p)['scopes']['BoardSocTop']['scalar_reg_bits'],9)
    def test_register_spacing_cannot_hide_state(self):
        self.assertEqual(census.declarations('reg[7:0]a; reg[3:0] b;')['scalar_reg_bits'],12)
        with self.assertRaises(RuntimeError):census.declarations('reg [7:0] missing_semicolon')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.fixture(p,2)
            self.mutate(p,'LoadStoreUnit.sv',lambda x:x.replace('reg [3:0] token','reg[3:0]token'))
            self.assertEqual(census.census(p)['scopes']['BoardSocTop']['scalar_reg_bits'],9)
    def test_structure_mutants_rejected(self):
        for replacement in ('unknown_module core ();','  unknown_module #(.WIDTH(8)) core ();',
            '  for (genvar i=0;i<4;i=i+1) begin: many\n    IntegerBackend core ();\n  end',
            '  if (0) begin\n    IntegerBackend core ();\n  end',
            '  if (0)\n    IntegerBackend core ();',
            '  IntegerBackend core[0:3] ();'):
            with self.subTest(replacement=replacement),tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);self.fixture(p,2)
                self.mutate(p,'BoardSocTop.sv',lambda x:x.replace('  IntegerBackend core ();',replacement))
                with self.assertRaises(RuntimeError):census.census(p)
    def test_missing_and_extra_artifacts_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.fixture(p,2)
            self.mutate(p,'LoadStoreUnit.sv',lambda x:x.replace('[3:0]','[63:0]'),True)
            with self.assertRaises(RuntimeError):census.census(p)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.fixture(p,2);(p/'rtl/unbound.sv').write_text('module unbound();endmodule')
            with self.assertRaises(RuntimeError):census.census(p)
    def test_unsupported_state_rejected(self):
        for source in ('reg [7:0] a = 0, b = 0;', 'logic [7:0] a; always @(posedge clock) a <= d;', 'integer state;'):
            with self.subTest(source=source),self.assertRaises(RuntimeError):census.declarations(source)
        self.assertEqual(census.declarations('automatic logic [7:0] temporary; reg a;')['scalar_reg_bits'],1)
    def test_bufgce_parameterization_is_explicit(self):
        source='module Clock();\n  BUFGCE #(\n .CE_TYPE("SYNC")\n ) buffer ( .I(clock), .O(out) );\nendmodule'
        self.assertEqual(census.structural_instances(source,set()),[{'module':'BUFGCE','instance':'buffer'}])
        with self.assertRaises(RuntimeError):census.structural_instances(source.replace('SYNC','UNSUPPORTED'),set())

    def test_supplied_storage_cannot_override_fresh_geometry(self):
        fresh={'status':'PASS_SELECTED_NATIVE_STORAGE_CENSUS','groups':{'issue_pc':{'banks':[{'width':64,'depth':8}]}}}
        census.validate_storage_report(copy.deepcopy(fresh),fresh)
        for key in ('width','depth'):
            bad=copy.deepcopy(fresh);bad['groups']['issue_pc']['banks'][0][key]=999
            with self.assertRaises(RuntimeError):census.validate_storage_report(bad,fresh)
        with self.assertRaises(RuntimeError):census.validate_storage_report({},fresh)

if __name__=='__main__':unittest.main()
