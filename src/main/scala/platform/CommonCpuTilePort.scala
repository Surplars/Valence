package soc.platform

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.ip.bus.RegisterPort
import soc.ip.memory.{NativeMemoryRequest, NativeMemoryResponse}
import soc.ip.tilelink.LineGrant

/** Version-one tile boundary requirements, not a claim that both adapters exist.
  * Fixed client numbering: 0=instruction cache, 1=data cache. A1 leaves coherent
  * client 0 inactive and retains its private noncoherent instruction cache.
  * Home capacity is independent of the per-client source space; no singleton
  * token or shared FIFO is permitted to replace these independent channels.
  */
case class CommonCpuTilePortParams(
    coherent: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1),
    homeAcquireEntries: Int = 2,
    homeWritebackEntries: Int = 2,
    scalarOwnerBits: Int = 4,
    maintenanceEpochBits: Int = 8,
    runtimeMaintenance: Boolean = false,
    runtimeCancellation: Boolean = false
) {
    require(coherent.addrWidth == 64 && coherent.dataWidth == 64 && coherent.sourceBits >= 3)
    require(homeAcquireEntries >= 2 && homeWritebackEntries >= 2)
    require((BigInt(1) << coherent.sinkBits) >= homeAcquireEntries)
    require(scalarOwnerBits >= 2 && maintenanceEpochBits >= 2)
    require(!runtimeCancellation || runtimeMaintenance)
    val coherentClients = 2
    val scalarPorts = 2
    val lineBytes = 64
    // Existing A1 instruction-cache path has four source bits; it must not
    // inherit the narrower coherent-client source namespace during extraction.
    val instruction: TLParams = coherent.copy(sourceBits = 4)
}

/** Physical request or an ordered reservation-clear event. Every accepted entry
  * owns one response with the SAME owner and kind. A clear completion occurs only
  * after all older physical/atomic operations on this lane have really completed;
  * newer LR/SC cannot pass it. No lossy pulse or independent clear mailbox.
  * needsCoherenceLookup is explicit: CPU origin does NOT mean "skip probe".
  * In particular I1 instruction bypass and atomics must inspect dirty D owners.
  */
class CommonTileScalarRequest(p: CommonCpuTilePortParams) extends Bundle {
    val owner = UInt(p.scalarOwnerBits.W)
    val clearReservation = Bool()
    val needsCoherenceLookup = Bool()
    val memory = new NativeMemoryRequest
}
class CommonTileScalarResponse(p: CommonCpuTilePortParams) extends Bundle {
    val owner = UInt(p.scalarOwnerBits.W)
    val clearReservation = Bool()
    val memory = new NativeMemoryResponse
}
class CommonTileScalarPort(p: CommonCpuTilePortParams) extends Bundle {
    val request = Decoupled(new CommonTileScalarRequest(p))
    val response = Flipped(Decoupled(new CommonTileScalarResponse(p)))
}

/** Maintenance messages carry an epoch, never a one-cycle pulse. Prepare means
  * stop new architectural work and flush dirty private caches while accepted
  * traffic and B/C/D/E continue. Tile-ready alone is NOT Home/DDR drained.
  * Fabric completion additionally requires all crossing owners/held replies,
  * probes, GrantAck sinks, DMA and downstream responses; only then may the tile
  * invalidate fetch state and acknowledge this epoch. Cold reset cancels all
  * owners in both domains. Optional runtime hold/resume names the external
  * epoch without claiming a full clock-gate acknowledgement. Warm reset is unsupported.
  */
class CommonTileMaintenanceCommand(p: CommonCpuTilePortParams) extends Bundle {
    val epoch = UInt(p.maintenanceEpochBits.W)
    val invalidateInstructions = Bool()
    val invalidateTranslations = Bool()
}
class CommonTileMaintenanceStatus(p: CommonCpuTilePortParams) extends Bundle {
    val epoch = UInt(p.maintenanceEpochBits.W)
    val privateOwnersDrained = Bool()
    val dirtyWritebackCompleted = Bool()
    val fetchQuiescent = Bool()
    val invalidationsCompleted = Bool()
    // Only an externally prepared epoch may retain Home admission after completion.
    val holdUntilResume = if (p.runtimeMaintenance) Some(Bool()) else None
}

/** Terminal proof for an externally owned runtime epoch. This reports actual
  * drain and tile release, not a clock-open or clock-manager acknowledgement.
  */
class CommonRuntimeCompletion(p: CommonCpuTilePortParams) extends Bundle {
    val epoch = UInt(p.maintenanceEpochBits.W)
    val canceled = Bool()
}

/** CPU-facing side. A selected tile implements this contract; the public fabric
  * is instantiated once, outside the CPU profile switch. CDC is a separate
  * explicit Held-II1 boundary. Bundles do not establish CDC/drain correctness.
  */
class CommonCpuTilePort(p: CommonCpuTilePortParams) extends Bundle {
    // A1 noncoherent I-cache keeps its independent Get/response owner space.
    // I1 leaves this inactive and uses coherent client 0 plus scalar port 0.
    val instructionFetch = new TLBundle(p.instruction)
    val coherent = Vec(p.coherentClients, new TLBundle(p.coherent))
    val lineGrant = Vec(p.coherentClients, Flipped(Decoupled(new LineGrant(p.coherent))))
    val scalar = Vec(p.scalarPorts, new CommonTileScalarPort(p))
    val msi = Flipped(new RegisterPort)
    val timerInterrupt = Input(Bool())
    val softwareInterrupt = Input(Bool())
    val timeSnapshot = Input(UInt(64.W))
    val maintenance = Flipped(Decoupled(new CommonTileMaintenanceCommand(p)))
    val maintenanceStatus = Decoupled(new CommonTileMaintenanceStatus(p))
    val fabricDrainedEpoch = Flipped(Decoupled(UInt(p.maintenanceEpochBits.W)))
    val maintenanceResume = if (p.runtimeMaintenance)
        Some(Flipped(Decoupled(UInt(p.maintenanceEpochBits.W)))) else None
    val maintenanceResumed = if (p.runtimeCancellation)
        Some(Decoupled(UInt(p.maintenanceEpochBits.W))) else None
}
