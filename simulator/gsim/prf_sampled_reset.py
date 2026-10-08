"""Test-only synchronous-reset lowering for the small PRF capacity matrix.
Regreset has reset-priority next-state semantics. Lower it to an ordinary reg
plus final-priority reset assignment; retain all normal writes/data memories.
Fail closed outside the nine known matrix metadata/reference registers.
"""
import re

def lower(text):
    if 'AsyncReset' in text:
        raise ValueError('this lowering applies only to synchronous matrix reset')
    pieces=re.split(r'(?=^  (?:public )?module )',text,flags=re.M)
    output=[pieces[0]]; count=0
    for module in pieces[1:]:
        records=[]
        pattern=r'^    regreset (initialized|owner|legacy) : (UInt<(?:1|64)>\[(?:48|64|128)\]), clock, reset, (\w+)([^\n]*)$'
        def declaration(m):
            records.append((m[1],m[3]))
            return f'    reg {m[1]} : {m[2]}, clock{m[4]}'
        module=re.sub(pattern,declaration,module,flags=re.M)
        if 'regreset ' in module:
            raise ValueError('unrecognized reset register in matrix')
        if records:
            module=module.rstrip()+'\n    when asUInt(reset) :\n'
            module+=''.join(f'      connect {name}, {value}\n' for name,value in records)
            module+='\n'
        output.append(module);count+=len(records)
    if count!=9: raise ValueError(f'expected nine reset registers, got {count}')
    return ''.join(output)

if __name__=='__main__':
    import sys
    from pathlib import Path
    source,destination=map(Path,sys.argv[1:])
    destination.write_text(lower(source.read_text()))
