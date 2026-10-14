from pathlib import Path
import sys,json
B=Path(__file__).resolve().parent;contract=json.loads((B/'snapshot-contract.json').read_text());n=contract['serialized_words']
a=Path(sys.argv[1]).read_text().splitlines();b=Path(sys.argv[2]).read_text().splitlines()
assert len(a)==len(b)==3860,'trace must contain exactly1930 cycles'
assert [int(a[i].split()[0]) for i in range(0,len(a),2)]==list(range(1930)),'OFF cycle IDs differ'
assert [int(b[i].split()[0]) for i in range(0,len(b),2)]==list(range(1930)),'ON cycle IDs differ'
for side in [a,b]:
 for i in range(1,len(side),2):assert len(side[i].split())==n,('truncated snapshot',i,len(side[i].split()),n)
if a!=b:
 different=[i for i,(x,y)in enumerate(zip(a,b))if x!=y];print('FAIL_FULL_WIDTH_TRACE_DIFFERENCE first_line='+str(different[0])+' lines='+str(len(different)));sys.exit(1)
print('PASS_FULL_WIDTH_TRACE_PAIR cycles='+str(len(a)//2)+' fields='+str(contract['fields'])+' words='+str(n))
