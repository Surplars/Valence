import copy,json,tempfile,unittest
from pathlib import Path
from parser import validate_owner_trace,OWNER_KINDS
class OwnerControls(unittest.TestCase):
 def setUp(self):
  self.result={'roi':{'begin_offer':10,'end_offer':15,'tail_offer':20},'owner_observation':[]}
  for w in ('roi','flush','whole_boot_diagnostic'):
   d={'window':w,**{k:0 for k in OWNER_KINDS}};d['accepted']=int(w!='flush');self.result['owner_observation'].append(d)
  self.event={'sequence':0,'window':'roi','owner':{'event':'accepted','slot':1,'generation':2**48+1,'epoch':9,'line':0x80210000,'cycle':10,'cohort_slot':1,'cohort_generation':2**48+1,'token_index':15,'token_tag':2**50+3,'response_ticket':1,'new_line':1,'mshr':1,'set':0,'way':1,'victim_valid':0}}
  self.end={'terminal':True,'events':1}
 def check(self,rows):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d)/'trace.jsonl';p.write_text('\n'.join(map(json.dumps,rows))+'\n');return validate_owner_trace(p,self.result)
 def test_full_width(self):self.assertEqual(self.check([self.event,self.end])['events'],1)
 def test_clean_and_dirty_release_ack(self):
  for dirty in (0,1):
   e=copy.deepcopy(self.event);x=e['owner'];x['event']='victim_release_ack'
   for k in ('token_index','token_tag','response_ticket','new_line'):del x[k]
   x.update(victim_valid=1,victim_dirty=dirty,victim_address=0x80220000,wb_ticket_slot=0,wb_ticket_owner_slot=1,wb_ticket_owner_generation=x['generation'])
   for r in self.result['owner_observation']:r['accepted']=0;r['victim_release_ack']=int(r['window']!='flush')
   result=self.check([e,self.end]);self.assertEqual(result['dirty_victim_release_ack'],dirty);self.assertEqual(result['clean_victim_release_ack'],1-dirty)
   x['wb_ticket_owner_generation']+=1
   with self.assertRaises(RuntimeError):self.check([e,self.end])
 def test_missing_duplicate_gap_and_terminal(self):
  for rows in ([self.end],[self.event,self.event,self.end],[self.event], [self.event,self.end,self.event]):
   with self.assertRaises(RuntimeError):self.check(rows)
 def test_wrong_token_owner_window(self):
  for key,value in [('token_tag',2**64),('token_index',16),('generation',-1),('epoch',2**32),('cycle',20),('slot',2)]:
   e=copy.deepcopy(self.event);e['owner'][key]=value
   with self.subTest(key=key),self.assertRaises(RuntimeError):self.check([e,self.end])
 def test_missing_token_and_inactive_field(self):
  e=copy.deepcopy(self.event);del e['owner']['token_tag']
  with self.assertRaises(RuntimeError):self.check([e,self.end])
  e=copy.deepcopy(self.event);e['owner']['victim_dirty']=0
  with self.assertRaises(RuntimeError):self.check([e,self.end])
if __name__=='__main__':unittest.main()
