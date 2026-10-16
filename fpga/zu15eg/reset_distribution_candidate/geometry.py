"""Read-only checkpoint endpoint geometry; distances are NOT timing estimates."""
import argparse
import csv
import hashlib
import json
import statistics
from pathlib import Path


def inspect(path):
    rows = [r for r in csv.DictReader(path.open(), delimiter='\t')
            if r['net'] == 'u_rgmii/serializer_reset']
    sources = [r for r in rows if r['direction'] == 'source']
    sinks = [r for r in rows if r['direction'] == 'sink']
    if len(sources) != 1 or len(sinks) != 20:
        raise ValueError('Expected historical one-source/twenty-sink reset net')
    point = lambda r: (int(r['tile_x']), int(r['tile_y']))
    median = tuple(statistics.median(point(r)[i] for r in sinks) for i in (0, 1))
    def distances(origin):
        values = [sum(abs(a-b) for a, b in zip(origin, point(r))) for r in sinks]
        return dict(min=min(values), max=max(values), total=sum(values))
    return dict(endpoint_file=str(path), endpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                source=sources[0], sinks=sinks, sink_count=20,
                sink_tile_bounds=[[min(point(r)[i] for r in sinks), max(point(r)[i] for r in sinks)] for i in (0, 1)],
                source_tile_l1=distances(point(sources[0])), load_median_tile=median,
                load_median_tile_l1=distances(median),
                limitation='Unweighted tile-coordinate geometry only; no route/STA/legality prediction, no design mutation.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logical_endpoints', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.logical_endpoints), indent=2))
