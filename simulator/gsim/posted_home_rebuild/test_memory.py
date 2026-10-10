"""Independent AXI oracle preflight, including rejection of malformed owners."""
import unittest
from memory import Memory


def observation():
    return {**{'ddrAxi.'+c+'.valid':0 for c in ['ar','aw','w']},
            'ddrAxi.r.ready':0,'ddrAxi.b.ready':0}


def address(channel,tag=0,offset=0,beats=1):
    return {'ddrAxi.'+channel+'.valid':1,**{'ddrAxi.'+channel+'.bits.'+k:v for k,v in
             dict(id=tag,addr=offset,len=beats-1,size=3,burst=1).items()}}


class MemoryTests(unittest.TestCase):
    def setUp(self):self.m=Memory({4096+i:i&255 for i in range(256)})
    def step(self,cycle,**updates):
        a=observation();a.update(updates);s=self.m.inputs(cycle);self.m.sample(a,s,cycle);return s
    def test_read_reordering_retains_ids_and_held_data(self):
        self.m.delay_by_line={4096:20,4160:2}
        self.step(0,**address('ar',1,0));self.step(1,**address('ar',2,64))
        a=self.step(3);self.assertEqual(a['ddrAxi.r.bits.id'],2)
        self.m.bytes[4160]=99
        self.assertEqual(self.step(4)['ddrAxi.r.bits.data'],a['ddrAxi.r.bits.data'])
        self.step(5,**{'ddrAxi.r.ready':1});self.assertIn(1,self.m.reads);self.assertNotIn(2,self.m.reads)
    def test_masked_write_retains_owner_until_b(self):
        self.step(0,**address('aw',3,8));before=dict(self.m.bytes)
        self.step(1,**{'ddrAxi.w.valid':1,'ddrAxi.w.bits.data':0xFFEEDDCCBBAA9988,'ddrAxi.w.bits.strb':0x81,'ddrAxi.w.bits.last':1})
        self.assertEqual(self.m.bytes[4104],0x88);self.assertEqual(self.m.bytes[4111],0xFF)
        self.assertEqual(self.m.bytes[4105],before[4105]);self.assertTrue(self.m.busy())
        self.step(5,**{'ddrAxi.b.ready':1});self.assertFalse(self.m.busy())
    def test_read_id_reuse_is_rejected(self):
        self.step(0,**address('ar',1))
        with self.assertRaisesRegex(AssertionError,'reused a live read'):self.step(1,**address('ar',1,64))
    def test_write_id_reuse_in_b_tail_is_rejected(self):
        self.step(0,**address('aw',1));self.step(1,**{'ddrAxi.w.valid':1,'ddrAxi.w.bits.data':0,'ddrAxi.w.bits.strb':255,'ddrAxi.w.bits.last':1})
        with self.assertRaisesRegex(AssertionError,'reused a live write'):self.step(2,**address('aw',1,64))
    def test_early_last_is_rejected(self):
        self.step(0,**address('aw',1,0,8))
        with self.assertRaisesRegex(AssertionError,'WLAST'):self.step(1,**{'ddrAxi.w.valid':1,'ddrAxi.w.bits.data':0,'ddrAxi.w.bits.strb':255,'ddrAxi.w.bits.last':1})
    def test_outside_address_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'escaped'):self.step(0,**address('ar',0,256))
    def test_bad_axi_geometry_is_rejected(self):
        q=address('ar');q['ddrAxi.ar.bits.size']=2
        with self.assertRaisesRegex(AssertionError,'aligned'):self.step(0,**q)

if __name__=='__main__':unittest.main()
