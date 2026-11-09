# Local timing changes over pinned Spinor

The upstream clone remains at e151f80e1da3a566d1a6ff5157052757fac0ddcb. `SpinorI1` replaces only the four named Scala files here; all other files compile directly from the pin. `VectorTiming` bounds full-packet/token comparisons and normalizes VSET operands at the existing admission edge. Publication, token identity, corruption checks, pipeline latency and upstream APIs remain unchanged. The paired source and receipts record both the pristine pin and these replacements.
