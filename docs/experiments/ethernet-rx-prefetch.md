# Optional Ethernet RX read prefetch

Two independent options default OFF:

- `--network-mac-rx-read-prefetch=1`: pipeline GmiiFrameRx staging reads through a two-entry elastic queue.
- `--network-rx-write-prefetch=1`: pipeline EthernetPacketDma RX RAM reads through a four-word queue.

The MAC still validates FCS before publishing a complete frame and releases its bank only on the final output handshake. DMA still validates data/status before writes, uses the existing 8-byte masked coherent requests, retains stalled offers across STOP/error, and completes only after all accepted write replies. Descriptor slots, memory credits, TX, register ABI and production defaults are unchanged. Default-OFF normalized MAC/DMA graphs match the original ea77475 modules; this is not a synthesis/timing result.

## Standalone fixtures

1. `ip.EthernetRxPrefetchGsimMain`: real GmiiFrameRx → EthernetDmaFrameAdapter → EthernetPacketDma → independent RegisterPort sink. Common125MHz GMII, or compile-time100MHz backpressurable AXIS diagnostic.
2. `ooo.EthernetHomeRxGsimMain`: real GMII/MAC/DMA → selected-aligned coherent cache/home/Atomic/fabric/TileLink/AXI chain. Copy DMA, debug, walker and instruction masters are held idle and checked. All modules share125MHz. The selected profile’s original CPU100MHz/DDR250MHz clocks, CPU execution, PHY and actual CDC are absent. Exact23 cache fields, DDR configuration and fabric comparison are in `simulator/gsim/config/ethernet-rx-selected-memory.json`.
3. `ip.EthernetClockedRxMain`: MAC125MHz → unchanged production16-entry EthernetFrameClockBridge → DMA100MHz, with independent ideal memory responses. Its testbench is `simulator/gsim/harness/ethernet_clocked_rx_tb.sv`. Icarus is restricted to this network-clock fixture; CPU tests remain GSIM.

The Home C++ ledger independently tracks accepted descriptor POST order, per-slot generations, frame bytes/status, scalar requests, matching AXI AW/W/B, packet replies and ordered completion POP. It checks every byte and preserved tail/sentinel, stages’ accepted-minus-returned ownership, STOP/error/restart and final drain. Full64-bit frame identity is encoded before CRC. Negative controls include CRC-valid256-generation replay and descriptor/POP ordering corruption.

The original TierA continuous host assigns slots from DUT activeAddress: its independent byte/ACK/count checks are not an independent descriptor FIFO-order proof. Its data repeats every256frames; a separate short identity supplement encoded full generation IDs and rejected valid-CRC stale frames. Do not extend the performance receipt’s proof scope. The Home and true-clock ledgers supply separate ordering coverage. The separate154-case packet-DMA and255-case MAC safety checks retain their finite-case scope.

## Reproduce without installing tools

`simulator/gsim/ethernet_rx_prefetch.py` builds one explicit GSIM variant, using an existing Mill, Clang and the repaired GSIM executable. The qualified GSIM SHA is `f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116`; the runner rejects another binary rather than silently using the historical buggy one. Use `--dry-run` first. Mill execution requires a complete checkout with its existing dependencies; the isolated sparse development worktree is not a complete Mill build tree. The portable orchestration layer has CLI/dry-run validation; frozen fixture/host bytes were exercised by the recorded isolated build commands.

Example one-variant build:

```
python3 simulator/gsim/ethernet_rx_prefetch.py --kind home \
  --mac-prefetch 1 --dma-prefetch 1 --output build/ethernet-home-both \
  --gsim "$QUALIFIED_GSIM" --cxx clang++-19 --mill mill
```

This compiles the active test source module, emits only the requested focused hardware fixture, and compiles at most two C++ units concurrently. No tool setup/install, full-SoC RTL emit or Verilator is invoked. Keep a resource budget appropriate to the environment; the default free-disk floor is800MiB. Do not replace an existing evidence directory.

Host commands (ASan/UBSan remain enabled; leak detection is disabled only for the executor’s ptrace limitation):

```
ASAN_OPTIONS=detect_leaks=0 build/ethernet-home-both/run safety dirty
ASAN_OPTIONS=detect_leaks=0 build/ethernet-home-both/run safety stop-held
ASAN_OPTIONS=detect_leaks=0 build/ethernet-home-both/run primary 1514 4096 4
```

Home safety cases: dirty, stop-collect, stop-held, stop-drain, error. Primary arguments: body length, primary frame count, independent DDR read/B delay. The matched matrix is60/1514bytes ×delay4/32/64 ×bothOFF/bothON,16 warmup frames then4096 primary,12-byte IFG and full drain. DDR ready/delay laws are absolute-cycle-driven and identical between arms. The delay argument is not an observed packet ACK latency.

TierA host arguments: `length frames ack_delay service_law axis [mutation]`; service0 is always-ready,1 periodic request-ready,2 deterministic request/reply stalls. Common MAC runs use axis0; the separately emitted100MHz AXIS model uses axis1. Do not call AXIS rates above1Gb/s physical wire performance.

## Measured boundaries

Each4096-frame performance result has16 warmup frames. “Fixed” counts only primary-cohort successful completions during the offered window; accepted frames completing in drain are not drops. Through-drain rates include descriptor reclaim/repost and final obligations.1514-byte bodies correspond to1500-byte payload and1538 wire byte-times, giving984.395Mb/s theoretical body ceiling.

- Common125MHz ideal sink, ACK argument4/observed5: old879.610Mb/s through drain with433 drops; DMA-only984.169, MAC-only984.243, both984.287, each zero drops. Single changes both suffice under this service law; gains do not multiply.
- Actual125/100MHz network clocks, ideal sink ACK1: fixed old831.064, MAC-only904.605, DMA-only984.155, both984.155Mb/s. DMA-only/both each complete4096 with zero drops. This differs from the common-clock attribution.
- Selected-aligned coherent memory, common125MHz,1514bytes: fixed OFF→both at DDR delay4 is270.853→313.391Mb/s; delay32 is137.950→148.044; delay64 is87.961→92.287. Drops remain substantial.
- Selected Home stages measure packet owners3, request buffer2, Home scalar write1, AXI write1. Home admission is the first measured serialization point. Configured4 packet credits cannot manufacture parallel Home write service. These tests do not qualify a future64-byte line-write path.

All12 selected-Home primary cases passed byte, generation, POST/POP, relevant-B, response and drain checks. Original non-selected DmaPacketStop-profile short runs are retained separately and are not relabeled as selected-profile throughput. No result establishes Linux/TCP throughput, the running FPGA image, PHY operation, synthesis resource use or routed timing. Separate CDC-ideal-sink and common-clock real-Home results must not be combined into an unexecuted end-to-end board claim.
