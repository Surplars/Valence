#!/usr/bin/env python3
"""Bind only the candidate's explicit ROB64/full-tag layout to actual model bytes."""
import hashlib,json,re,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
model=Path(sys.argv[1]).resolve();header=model/'PostedPreparationPriorityGsim.h'
s=header.read_text();p=json.loads((model/'profile.json').read_text());core=p['core']
assert core['reconstructIssueTokenIndex'] is True and core['sharedMemoryAddressState'] is True
assert core['robEntries']==64 and core['tagBits']==64 and core['memoryEntries']==4
assert core['earlyStorePreparation'] and core['sharedStoreOperandReads'] and core['memoryProofFrontier']
layouts={}
def accessor(name,width):
 typ='uint64_t' if width==64 else 'uint8_t'
 array=f'{typ} {name}[64]; // width = {width},'
 if array in s:
  layouts[name]='array64';return [f'd.{name}[{i}]' for i in range(64)]
 if all(f'{typ} {name}_{i}; // width = {width},' in s for i in range(64)):
  layouts[name]='scalar64';return [f'd.{name}_{i}' for i in range(64)]
 raise RuntimeError('unrecognized exact state ABI: '+name)
fields={'address':('backend$storeAddress',64),'lanes':('backend$storeByteLanes',8),
 'tag':('backend$queue$$renamed$$token$$tag',64),'pending':('backend$pending',1),'live':('backend$memoryLive',1)}
result=['#pragma once','#include <array>','#include <cstdint>','namespace memory_state_abi {']
for field,(name,width) in fields.items():
 refs=accessor(name,width);result.append(f'inline std::array<uint64_t,64> {field}(const SPostedPreparationPriorityGsim &d) {{ return {{'+','.join(refs)+'}; }')
for field,name,width in [('capturedOwners','backend$capturedOwners',64),('capturedIndex','backend$captured$$token$$index',6),('capturedTag','backend$captured$$token$$tag',64)]:
 typ='uint64_t' if width==64 else 'uint8_t'
 assert all(f'{typ} {name}_{i}; // width = {width},' in s for i in range(2)), 'captured full-token layout changed'
 result.append(f'inline std::array<uint64_t,2> {field}(const SPostedPreparationPriorityGsim &d) {{ return {{d.{name}_0,d.{name}_1}}; }}')
 layouts[name]='scalar2'
result.append('}');out=HERE/'state_abi.h';out.write_text('\n'.join(result)+'\n')
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
r={'schema':'memory-state-reuse-focused-abi-v1','profile_sha256':sha(model/'profile.json'),'header_sha256':sha(header),'adapter_sha256':sha(out),'layout':layouts,'token_index':'literal owning slot only; actual profile explicitly ON','tag_bits':64,'fallback':False}
(HERE/'state-abi.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
