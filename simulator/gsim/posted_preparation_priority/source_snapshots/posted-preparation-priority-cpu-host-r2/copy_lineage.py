"""Retrospective full-token COPY line mapping from actual accepted physical requests only."""
import bisect,hashlib
from pathlib import Path
from contract import require
COPY_LD_PC=0xfff790b8
COPY_WORDS={0xfff78ec4:0x1e030263,0xfff790b8:0x0007b683,0xfff790bc:0x00878793,0xfff790c0:0x00870713,0xfff790c4:0xfed73c23,0xfff790c8:0xfec798e3}
def verify_guest(path):
 b=Path(path).read_bytes();require(len(b)==6104 and hashlib.sha256(b).hexdigest()=='3af27dccda6acd677bb01fdad4d240ffee2f9af1c1fb4181a71c43ff2087a810','COPY instruction proof requires original guest')
 for pc,word in COPY_WORDS.items():require(int.from_bytes(b[pc-0xfff78000:pc-0xfff78000+4],'little')==word,'original COPY loop word changed')
 return {'load_pc':COPY_LD_PC,'load_pc_hex':hex(COPY_LD_PC),'ld_source_register':15,'ld_destination_register':13,'source_step':8,'destination_step':8,'instructions_per_element':5,'guest_sha256':hashlib.sha256(b).hexdigest(),'exact_words':{hex(pc):hex(word)for pc,word in COPY_WORDS.items()}}
def correlate(lives,accepted,starts,prepared,roi_begin,roi_end,case,guest_path):
 proof=verify_guest(guest_path);counts={name:{'different_line':0,'adjacent_next_line':0}for name in ('visible','prepared','started','accepted')};examples=[]
 if case not in(19,21):return {'applicable':False,'copy_loop':proof,'stage_pair_counts':counts,'reason':'not original timed COPY case'}
 eligible={t:l for t,l in lives.items()if l['pc']==COPY_LD_PC};ordered=sorted(eligible,key=lambda t:(eligible[t]['first_seen'],t[1]));times=[eligible[t]['first_seen']for t in ordered]
 bytoken={}
 for (t,epoch),rows in prepared.items():bytoken.setdefault(t,[]).extend(dict(epoch=epoch,**x)for x in rows)
 # Every retrospective address must match the actual eventual owner and epoch.
 for t in eligible:
  if t not in accepted or not accepted[t]['ordinary']:continue
  z=accepted[t];st=starts.get(t);require(st is not None and st['epoch']==z['epoch'],'COPY start/cache full-token epoch mismatch')
  if st['prechecked']:require(st['pa']==z['pa'],'COPY prechecked start/cache PA changed')
  for q in bytoken.get(t,[]):
   if q['epoch']==z['epoch']:require(q['pa']==z['pa'] and q['va']==st['va'],'COPY prepared/final actual mapping changed')
 unknown=set();mismatch_epoch=set();older_count=0
 for ot in ordered:
  old=accepted.get(ot)
  if not old or not old['ordinary'] or not old['miss'] or not roi_begin<=old['cycle']<roi_end:continue
  response=old['first_response_visible'];require(response is not None and response>=old['cycle'],'COPY miss missing first visible response');older_count+=1
  lo=bisect.bisect_left(times,eligible[ot]['first_seen']);hi=bisect.bisect_left(times,min(response,roi_end))
  for t in ordered[lo:hi]:
   if t[1]<=ot[1]:continue
   l=eligible[t];z=accepted.get(t)
   if not z or not z['ordinary']:unknown.add(t);continue
   if z['epoch']!=old['epoch']:mismatch_epoch.add(t);continue
   oldline=old['pa']&~63;line=z['pa']&~63
   if line==oldline:continue
   st=starts[t];prep=[q for q in bytoken.get(t,[])if q['epoch']==z['epoch']and l['first_seen']<=q['cycle']<response]
   stages={'visible':l['first_seen']<response,'prepared':bool(prep),'started':st['cycle']<response,'accepted':z['cycle']<response};adjacent=line==oldline+64
   for k,v in stages.items():
    if v:counts[k]['different_line']+=1;counts[k]['adjacent_next_line']+=adjacent
   if len(examples)<32:examples.append({'older_token':list(ot),'younger_token':list(t),'epoch':z['epoch'],'older_line':oldline,'younger_line_from_eventual_cache_accept':line,'adjacent_next_line':adjacent,'first_seen':l['first_seen'],'prepared_cycles':[q['cycle']for q in prep],'lsu_start':st['cycle'],'cache_accept':z['cycle'],'older_miss_accept':old['cycle'],'older_first_response_visible':response,'stages_before_first_response':stages,'younger_is_demand_miss':z['miss']})
 return {'applicable':True,'copy_loop':proof,'older_actual_demand_misses':older_count,'stage_pair_counts':counts,'witnesses':examples,'unlinked_visible_full_tokens_unknown':len(unknown),'different_epoch_mapping_unknown':len(mismatch_epoch),'eventual_PA_does_not_claim_earlier_translation_permission':True,'token_order':'strict full64 generation ordering; allocator exhaustion never silently wraps','prefetches_counted':False}
