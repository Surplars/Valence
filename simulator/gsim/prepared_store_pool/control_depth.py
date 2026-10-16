"""Structural mapped-cell depth from current bare-mode input, never nanoseconds."""
import functools


def inspect(module):
    source = module['ports']['io_in_bare']['bits'][0]
    tag_sources = set(module['ports']['io_in_savedTag']['bits'])
    origins = {source}
    drivers = {}
    sinks = {}
    for name, cell in module['cells'].items():
        inputs = [bit for port, bits in cell['connections'].items()
                  if cell['port_directions'][port] == 'input' for bit in bits if isinstance(bit, int)]
        outputs = [bit for port, bits in cell['connections'].items()
                   if cell['port_directions'][port] == 'output' for bit in bits if isinstance(bit, int)]
        for bit in set(inputs):
            sinks.setdefault(bit, set()).add(name)
        for bit in outputs:
            if bit in drivers:
                raise RuntimeError('Multiple mapped drivers')
            drivers[bit] = (name, inputs)

    active = set()

    @functools.lru_cache(None)
    def depth(bit):
        if bit in origins:
            return 0
        if bit not in drivers:
            return None
        if bit in active:
            raise RuntimeError('Combinational cycle in mapped control cone')
        active.add(bit)
        predecessors = [value for input_bit in drivers[bit][1]
                        if (value := depth(input_bit)) is not None]
        active.remove(bit)
        return max(predecessors) + 1 if predecessors else None

    outputs = module['ports']['io_result']['bits']
    depths = [depth(bit) for bit in outputs]
    owner_depths = [d for d in depths[:16] if d is not None]
    origins = tag_sources
    depth.cache_clear()
    tag_depths = [depth(bit) for bit in outputs]
    return {'tagToResultBitDepthsLsbFirst': tag_depths,
            'tagToSelectedIndexMaxCellDepth': max(d for d in tag_depths[23:27] if d is not None),
            'method': 'Maximum mapped cell count along syntactic dependencies from io_in_bare; not delay',
            'bareDirectSinkCells': len(sinks.get(source, ())),
            'bareToFreshOwnerMaxCellDepth': max(owner_depths) if owner_depths else None,
            'bareToResultBitDepthsLsbFirst': depths}
