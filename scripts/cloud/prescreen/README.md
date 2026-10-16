# Minimal cloud synthesis and device-inspection tools

This restores the previously approved Debian 13 amd64 cloud prescreen stack. It
extracts only workspace-local tools; no root, system installation, Vivado,
Verilator, full-device archive, or unrelated FPGA device download is used.

```sh
# Restore Java/Scala first if this workspace has no JDK (javac is required).
python3 scripts/cloud/bootstrap.py
python3 scripts/cloud/prescreen/bootstrap.py --smoke
source scripts/cloud/env.sh
source simulator/build/cloud-prescreen/env.sh
```

Use `--output PATH` to select another local tool directory. The generated env.sh
is relocatable and exports Yosys/sv2v PATH plus RAPIDWRIGHT_PATH and
RAPIDWRIGHT_JAR. It does not overwrite JAVA_TOOL_OPTIONS: existing proxy and trust
settings are preserved. `JAVA_HOME` may select a JDK; otherwise the script uses
available Java tools or the main bootstrap's cached JDK.

## Pinned inputs and licensing

`downloads.lock.json` pins exact official URLs, byte sizes, and SHA-256 values:

- Debian Yosys 0.52-2, upstream git
  `fee39a3284c90249e1d9684cf6944ffbbcbb8f90`, and matching ABC package.
- Upstream sv2v 0.0.13 Linux release.
- Xilinx RapidWright 2025.1.3 Linux standalone jar, official
  [v2025.1.3-beta release](https://github.com/Xilinx/RapidWright/releases/tag/v2025.1.3-beta).
- Only the 6.6MB xczu15eg device database, from the endpoint documented by pinned
  FileTools.java. Its upstream DataVersions.java MD5 is also recorded. This
  official data endpoint uses HTTP; a pinned SHA-256 is mandatory and verified
  before any use. A checksum mismatch fails closed.

The jar's MD5 was checked against the official release MD5SUM.TXT before recording
its SHA-256. RapidWright combines Apache-licensed code with an API library partly
covered by the [Xilinx EULA in LICENSE.TXT](https://github.com/Xilinx/RapidWright/blob/v2025.1.3-beta/LICENSE.TXT).
This script restores the version previously approved for this project; it does
not click through or accept any new agreement. For a new user/version/terms,
review and obtain the necessary license approval before downloading or using it.
Bundled license notices are retained. No jar, database, package, or binary belongs
in Git.

## Bounded evidence and safety guards

`--smoke` performs sv2v conversion, a Yosys SAT proof of a tiny XOR circuit, a
Yosys/ABC synthesis smoke, and an exact-part RapidWright database load for
`xczu15eg-ffvb1156-2-i` (435 rows, 455 columns). Logs and a receipt stay in the
ignored output directory. Each rerun archives prior logs and receipt under
`history/run-NNNN`, sets the current receipt to RUNNING before changing artifacts,
and records FAILED_PRESERVE_EVIDENCE on failure. A previous PASS cannot qualify a
failed rerun. A forced compiler failure and subsequent successful rerun verified
this lifecycle. The fresh cloud recovery reproduced these checks.

`RapidWrightSmoke.java` calls `FileTools.setOverrideDataFileDownload(true)` and
`Design.setAutoGenerateReadableEdif(false)` before accessing the part/device.
Reuse both guards in every prescreen program. The installer unpacks only the
small common part/primitive data and the explicitly pinned ZU15EG database; it
never runs RapidWright's general-purpose installer or data downloader.

These tests establish tool readiness only. They do not prove an actual DCP can
be read or routed, establish FPGA resources/timing, replace Vivado signoff, or
qualify board operation. Run the project's short, affected formal/behavioral
checks separately; do not automatically run full design synthesis or regressions.
