import copy,importlib.util,json,subprocess,unittest
from pathlib import Path
H=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('lemma',H/'verify_lemma.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class LemmaTests(unittest.TestCase):
 def test_structural_and_negatives(self):
  e=json.loads((H/'encoder.json').read_text());p=json.loads((H/'parent.json').read_text());m.proof(e,p)
  for change in ('D','CLK','ARST','VALUE'):
   x=copy.deepcopy(e);c=x['modules']['TriSpeedRgmiiTx']['cells']['$procdff$87']
   if change=='VALUE':c['parameters']['ARST_VALUE']='10000'
   else:c['connections'][change][-1]=999999
   with self.assertRaises(ValueError):m.proof(x,p)
  q=copy.deepcopy(p);q['modules']['TriSpeedManagedGmac']['cells']['encode']['connections']['io_fall']=[999]*5
  with self.assertRaises(ValueError):m.proof(e,q)
 def test_tcl_identity_and_modes(self):
  expected='a25f9cb85ef22c6c50df514ac2986f5e597e19e5743fd0e606d14263e759c615'
  for identity,t1,selected,success in [(expected,1,1,True),('0'*64,1,1,False),(expected,0,1,False),(expected,1,0,False)]:
   script=f'proc valence_native_mac_verify_export {{}} {{return {identity}}}\nnamespace eval valence_native_mac_mode {{variable t1 {t1};variable selected {selected};variable control_lemma 0}}\n'
   script+=f'if {{[catch {{source {{{H}/install_control_lemma.tcl}}}} reason]}} {{puts REJECT}} else {{puts ACCEPT}}\n'
   result=subprocess.run(['tclsh'],input=script,text=True,capture_output=True)
   self.assertEqual(result.stderr,'');self.assertEqual(result.stdout.strip().splitlines()[-1],'ACCEPT' if success else 'REJECT')
if __name__=='__main__':unittest.main()
