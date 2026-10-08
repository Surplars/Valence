"""Independent cache-state proof for the ROM tail-sweep algorithm, not RTL simulation."""
import collections, unittest, zlib
class Cache:
 def __init__(self,capacity,ways):
  self.ways=ways;self.sets=[collections.OrderedDict() for _ in range(capacity//64//ways)]
  self.ram=bytearray((i*73+(i>>9)+19)&255 for i in range(1<<20));self.epoch=0
 def line(self,address,write=None):
  tag=address//64;s=self.sets[tag%len(self.sets)]
  if tag not in s:
   if len(s)==self.ways:
    old,(data,dirty,epoch)=s.popitem(last=False)
    if dirty:self.ram[old*64:old*64+64]=data
   s[tag]=[bytearray(self.ram[tag*64:tag*64+64]),False,self.epoch]
  data=s.pop(tag);s[tag]=data
  if write is not None:data[0][:len(write)]=write;data[1]=True
  return data
 def flush(self):
  for s in self.sets:
   for tag,(data,dirty,_) in list(s.items()):
    if dirty:self.ram[tag*64:tag*64+64]=data;del s[tag]
 def prepare(self):
  self.epoch+=1;self.flush()
  for _ in range(2):
   for a in range(0xfc000-65536,0xfc000,64):self.line(a)
 def crc(self,n,require_fresh=False):
  c=0
  for a in range(0,n,64):
   data,_,epoch=self.line(a)
   if require_fresh:assert epoch==self.epoch,(a,epoch,self.epoch)
   c=zlib.crc32(data[:min(64,n-a)],c)
  return c
class Proof(unittest.TestCase):
 def test_resident_repeat_and_overlap(self):
  cases=0
  for capacity in (8192,16384,32768):
   for ways in (1,2):
    for n in (16,4096,32768,0xfc000-32768,0xfc000):
     c=Cache(capacity,ways)
     # Small and large downloads dirty every line touched; flush must publish.
     for a in range(0,n,64):c.line(a,bytes((a+i+27)&255 for i in range(min(64,n-a))))
     c.prepare();expected=zlib.crc32(c.ram[:n]);self.assertEqual(c.crc(n,True),expected)
     # Real backing-only change while prior CRC lines can remain clean-resident.
     c.ram[n-1]^=1;c.prepare();self.assertNotEqual(c.crc(n,True),expected)
     # Repeated download cannot reuse a prior clean version.
     for a in range(0,n,64):c.line(a,bytes((a+i+61)&255 for i in range(min(64,n-a))))
     c.prepare();self.assertEqual(c.crc(n,True),zlib.crc32(c.ram[:n]));cases+=1
  self.assertEqual(cases,30)
 def test_missing_sweep_negative(self):
  c=Cache(32768,2);old=c.crc(4096);c.ram[7]^=1;c.flush()
  self.assertEqual(c.crc(4096),old) # Ordinary dirty flush alone misses backing corruption.
  c.prepare();self.assertNotEqual(c.crc(4096,True),old)
if __name__=='__main__':unittest.main()
