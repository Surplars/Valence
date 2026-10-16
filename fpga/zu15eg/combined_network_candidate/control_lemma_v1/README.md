# Current diagnostic Role4 source-equality amendment

External installer only; the sealed package and mapped role checker are unchanged.
Source immediately before the existing MAC role audit. Installer first invokes
the full diagnostic export identity verifier and requires identity
`a25f9cb85ef22c6c50df514ac2986f5e597e19e5743fd0e606d14263e759c615`
and T1/selected1/1. It then enables the independently checked source lemma.
The original live encoder chain, qff clock/reset, dead-fall classification,
unique-role and all low/high transition proofs still run. This is no timing cut.

Actual complete encoder SHA256:
`208f1ab46affd9d45e4224abe0858beede0c5e374638f5b814191af8d0865a84`.
Parent: `4d0ce0c29a083cced6754ee4d6cb9ed8d2d0aec77a8aba289687601b5c5dba2f`.
Adapter: `32b96761f2019806b6e03d9d885595449d2b057a30b6bb9ca204a34162ce96fc`.

Yosys `read_verilog; proc; write_json` on the two complete emitted modules gives
both encoder control bits as positive-clock, positive-async-reset ADFFs:
D140, CLK2, ARST3, reset value0. Parent encode clock directly equals rawTxClock;
rise/fall ports forward directly and reset comes from rawTxRelease. Thus both
controls equal after reset or one clock, with equality preserved thereafter.
No unreset power-up equality is claimed. The unchanged adapter resets both
control states0, captures equal inputs together, then copies the saved high
state to selected low state, preserving equality by induction.

Generated proof artifacts remain outside Git in `network-control-lemma-r1`.
Proof receipt SHA `db1254c63361ad3fb8886d52eefe497464fa985a9ef1fcc3c1876e5ae2d5d994`.
Installer SHA `b4c7c0be21b4fdafac9c6a9d54b6974dc9cbf9bd71eaae00bb88d7c41bb7fd79`.
The checker/test source is preserved here; run against the external artifact
folder containing encoder.json, parent.json and proof.json. Changed D/clock/
reset/reset value/parent forwarding fail, as do wrong export identity or mode.
Independent source review additionally traced forwarding through the complete
bank/BoardSocTop/FpgaNextSocTop/physical wrapper. Local read-only probes reported
the original high and low mapped equations already PASS before this amendment;
the full live audit must still be rerun. No resynthesis, physical qualification,
or checkpoint substitution follows from the source proof.
