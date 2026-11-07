# RV64 VS sireg exception classification

For VS-mode with a valid nonzero VGEIN and no additional state-enable denial:

- 0x70 and 0x72: normal guest eidelivery/eithreshold access.
- 0x71 and 0x73..0x7f: read zero, writes ignored, no exception.
- Even selectors 0x80..0xbe and 0xc0..0xfe: normal access. Unimplemented identity
  bits, including an entirely unimplemented even bank, are read-only zero.
- Odd selectors 0x81..0xbf and 0xc1..0xff under RV64: virtual-instruction exception,
  cause 22. M/HS accesses instead receive illegal-instruction cause 2.
- Priority selectors 0x30..0x3f, odd or even: VS accesses trap virtually for
  hypervisor emulation.
- Reserved selectors outside AIA's defined windows, such as 0x40 or 0x100, must
  not be converted wholesale to cause 22; illegal cause 2 is a supported choice.
- With invalid VGEIN, guest-file registers 0x70..0xff become inaccessible, even
  locations normally read-zero/write-ignore, and VS access receives cause 22.

Official AIA v1.0 IMSIC sections 2.1.8.3 and2.1.8.4 explicitly state for the odd
RV64 banks: “an attempt to access the matching *ireg CSR raises an illegal
instruction exception, unless done in VS-mode, in which case it raises a virtual
instruction exception.” Section 2.1.7 defines the read-zero/write-ignore slots.

The v1.0 Preface RC5 note distinguishes reserved values from defined but
inaccessible registers: a reserved vsiselect value should preferably raise an
illegal instruction exception rather than a virtual instruction exception.

The component IMSIC's generic error result was correct. The discovered defect
was the MSU's default mapping to cause 2 without the VS odd-bank distinction.
The clean integration tests reproduced the old behavior against a new oracle
and added the narrow front-end classification. Do not replace it with a blanket
“virtualized plus IMSIC error means cause 22” rule.

Sources:
- https://docs.riscv.org/reference/aia/v1.0/IMSIC.html
- https://docs.riscv.org/reference/aia/v1.0/colophon.html
- https://docs.riscv.org/reference/aia/CSRs.html
- https://docs.riscv.org/reference/aia/VSLevel.html
