# Experimental placed-path timing candidate

The new options split measured fetch-address/PMP, queued translation selection,
aligned next-line authorization, probe lookup and manager range paths. All new
generic defaults are false. The exact default52 profile is preserved; the
explicit candidate adds the five new options together with predecoded head
drain and retirement intent. Experimental54 and eager53 remain off.

The combined candidate passes actual-instance native/CPU parameter audits,
both fixed COPY workloads and the three original independent negative controls.
It uses one new 36-unit GSIM model with the original 17 host files, three guest
files and DDR service law. The separate architectural fetch correction is
required. Exact source hashes, qualification scope and NEMU status are in
[the public receipt](placed-timing-candidate.json).

The two original short physical integer M-mode NEMU cases and PC/GPR/memory
negative controls pass on those same objects with no reference resynchronizing.
Hot/compressed costs are 1,883/967 cycles, versus 1,847/958 (+36/+9). GPR checks
occur after each entire retire edge; independent intermediate lane GPR state,
VM, FP, CSR, permissions and concurrent DMA are outside these NEMU cases.

Sv39 remains 191,618 inclusive cycles. Bare increases from 194,153 to 198,642,
or 4,489 cycles (+2.312%). Full stdout and timestamped traces differ in both
modes. These results do not qualify this candidate as a performance improvement
or replace default52. Physical STA, routed timing, Fmax, area and board results
remain unmeasured.

Bounded native review confirms all seven selected structural boundaries and
unchanged declarations/ports for 115 matched memory instances. It finds 18
added functional scalar bits and, separately, one observer-only bit pruned by
the different export context. The GSIM and FPGA tops differ; whole-FPGA state
and mapped resources are unknown. The owner-ready/rank/asynchronous-PRF/AGU
path is unchanged and remains an open timing family.

The public Scala profile bridges validate every original field name, position
and value after removing only explicitly named false additions. Actual module
audits check the frontend, DTA and nested hint/PMP, cache, manager and four burst
slots. Component fixtures preserve the bounded independent oracles. The exact
default52 translation lab and projected manager-boundary workflows are separate
frozen evidence, not reproduced by the older public component runner alone.

Use `ooo.FpgaNextProfileMain` and `ooo.PlacedTimingFullCpuMain` for explicit
profiles and CPU emission, and `simulator/gsim/test_placed_timing_cli.py` for CLI
contracts. Native FPGA export accepts explicit options; there is no new fixed
board default. Full regression and physical implementation are outside this
qualification.
