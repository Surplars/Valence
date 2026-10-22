# r24 dynamic platform WIP2: real ports, no native switching qualification yet

Compile and emission only. No end-to-end dynamic frequency test has run at this checkpoint.
Production software rate tables remain empty. CPU300/fabric250 constraints are not relaxed; boot is 50 MHz.

The actual platform now connects CMU external drain leases to the existing real epoch adapter and
CPU/Home/network/debug/fixed DDR/timer/fixed125 MAC owners. Same-epoch source-local final-close
commits retain their live predicates until real uncommit consumption. The fixed MAC safety guard
uses existing command and receipt mailboxes, registers and holds any safety revocation in its source
domain, and synchronizes that sticky fault to AON. Release requires backend lock/open/resumed
feedback, actual CPU/fabric uncommit consumption, then the fixed guard disarm receipt before
original epoch cleanup and retirement. Initial unsafe arm returns a false proof, not a fabricated ACK.

Backend/fixed/debug fault revokes program and retirement permission on AON observation, then a
registered emergency stop crosses to fixed MAC/debug to inhibit only new admission. Accepted
owners are retained; this path is fatal until coordinated cold reset, with nonzero CDC latency.
It does not instantaneously abort an accepted physical DRP operation.

- Focused IonSoC.test.compile passed.
- Full functional dynamic platform: 270 emitted SV files.
- Actual hardwareClocks=true boot50-dynamic production composition emitted successfully,
  with programmable ROM absent and no enabled software rate point.
- Default OFF comparison: actual 248/248 SV byte-identical to frozen r16, no normalization.
- Physical backend is not yet merged at this exact checkpoint.
- Fixed guard native tests and whole-platform MMIO-to-clock tests remain pending.
- No UNISIM, physical timing, gate-CE STA or board validation is claimed.

Fabric IRQ qualification applies only to the existing board hardwired io.sources=0 configuration.
No user IRQ source is masked to qualify a clock. UART must be observed actually running and
old control receipts consumed, not assumed quiescent by software.
