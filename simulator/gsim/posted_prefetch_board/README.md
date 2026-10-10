# Explicit posted/PF Board experiments

See [integration contract](../../../docs/posted-prefetch-integration.md) for
activation paths, inherited source identities and pending qualification.

`coexistence.py` and `head_offer.py` are independent entry points sharing the
published Board host/oracle. Their `*_audit.py` counterparts audit actual
constructors. All model/run commands require a fresh source/tool binding and an
explicit heavy slot. No historical model is implicitly reusable across the new
experiment identities or source tree.

Host-only checks:

```sh
python3 -B -m unittest discover -s simulator/gsim/posted_prefetch_board -v
```

The frozen full baseline comes from the recovered historical posted Board
constructor snapshot. Added coexistence/head-offer fields begin false; the
profile provider applies only named experiment treatments. This fixture is an
independent contract, not a fresh DUT output or hardware qualification result.
