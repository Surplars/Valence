package soc.bus.tilelink

import chisel3._
import chisel3.util._

// Rocket风格多主多从Xbar，A通道按slave仲裁，D通道按master仲裁。
class TLXbar(
    params: TLParams,
    nMasters: Int,
    nSlaves: Int,
    addrMap: Seq[UInt => Bool],
    supportsRelease: Seq[Boolean] = Seq.empty
) extends Module {
    require(nMasters > 0, "nMasters must be positive")
    require(nSlaves > 0, "nSlaves must be positive")
    require(addrMap.length == nSlaves, "addrMap size must equal nSlaves")
    require(supportsRelease.isEmpty || supportsRelease.length == nSlaves, "supportsRelease size must equal nSlaves")

    private val masterTagBits = if (nMasters <= 1) 0 else log2Ceil(nMasters)
    private val slaveParams = params.copy(sourceBits = params.sourceBits + masterTagBits)
    private val releaseCaps = if (supportsRelease.isEmpty) Seq.fill(nSlaves)(false) else supportsRelease

    val io = IO(new Bundle {
        val masters = Vec(nMasters, Flipped(new TLBundle(params)))
        val slaves  = Vec(nSlaves, new TLBundle(slaveParams))
    })

    private def expandSource(master: Int, source: UInt): UInt = {
        if (masterTagBits == 0) source else Cat(master.U(masterTagBits.W), source)
    }

    private def shrinkSource(source: UInt): UInt = {
        if (masterTagBits == 0) source else source(params.sourceBits - 1, 0)
    }

    private def decodeMaster(source: UInt): UInt = {
        if (masterTagBits == 0) 0.U else source(slaveParams.sourceBits - 1, params.sourceBits)
    }

    val routeHits = Seq.tabulate(nMasters, nSlaves) { (m, s) =>
        addrMap(s)(io.masters(m).a.bits.address)
    }
    val routeHitVecs = Seq.tabulate(nMasters) { m => VecInit(routeHits(m)) }
    val routeHasHit = routeHitVecs.map(_.asUInt.orR)

    val releaseHits = Seq.tabulate(nMasters, nSlaves) { (m, s) =>
        releaseCaps(s).B && addrMap(s)(io.masters(m).c.bits.address)
    }
    val releaseHitVecs = Seq.tabulate(nMasters) { m => VecInit(releaseHits(m)) }
    val releaseHasHit = releaseHitVecs.map(_.asUInt.orR)

    val localAErrValid  = RegInit(VecInit(Seq.fill(nMasters)(false.B)))
    val localAErrOpcode = RegInit(VecInit(Seq.fill(nMasters)(TLOpcode.AccessAck)))
    val localAErrParam  = RegInit(VecInit(Seq.fill(nMasters)(0.U(3.W))))
    val localAErrSize   = RegInit(VecInit(Seq.fill(nMasters)(0.U(params.sizeBits.W))))
    val localAErrSource = RegInit(VecInit(Seq.fill(nMasters)(0.U(params.sourceBits.W))))

    val localCErrValid  = RegInit(VecInit(Seq.fill(nMasters)(false.B)))
    val localCErrOpcode = RegInit(VecInit(Seq.fill(nMasters)(TLOpcode.ReleaseAck)))
    val localCErrSize   = RegInit(VecInit(Seq.fill(nMasters)(0.U(params.sizeBits.W))))
    val localCErrSource = RegInit(VecInit(Seq.fill(nMasters)(0.U(params.sourceBits.W))))

    val aArbs = Seq.fill(nSlaves)(Module(new RRArbiter(new TLBundleA(slaveParams), nMasters)))
    for (s <- 0 until nSlaves) {
        for (m <- 0 until nMasters) {
            aArbs(s).io.in(m).valid := io.masters(m).a.valid && routeHits(m)(s)
            aArbs(s).io.in(m).bits.opcode := io.masters(m).a.bits.opcode
            aArbs(s).io.in(m).bits.param := io.masters(m).a.bits.param
            aArbs(s).io.in(m).bits.size := io.masters(m).a.bits.size
            aArbs(s).io.in(m).bits.source := expandSource(m, io.masters(m).a.bits.source)
            aArbs(s).io.in(m).bits.address := io.masters(m).a.bits.address
            aArbs(s).io.in(m).bits.mask := io.masters(m).a.bits.mask
            aArbs(s).io.in(m).bits.data := io.masters(m).a.bits.data
            aArbs(s).io.in(m).bits.corrupt := io.masters(m).a.bits.corrupt
        }
        io.slaves(s).a <> aArbs(s).io.out
    }

    for (m <- 0 until nMasters) {
        val readyVec = (0 until nSlaves).map(s => routeHits(m)(s) && aArbs(s).io.in(m).ready)
        when(io.masters(m).a.valid) {
            assert(PopCount(routeHitVecs(m)) <= 1.U, "TLXbar: address overlaps multiple slaves")
        }
        val routedReady = readyVec.reduceOption(_ || _).getOrElse(false.B)
        val localErrReady = !routeHasHit(m) && !localAErrValid(m)
        io.masters(m).a.ready := routedReady || localErrReady

        when(io.masters(m).a.valid && io.masters(m).a.ready && !routeHasHit(m)) {
            localAErrValid(m)  := true.B
            localAErrOpcode(m) := TLOpcode.responseOpcodeForA(io.masters(m).a.bits.opcode)
            localAErrParam(m)  := TLOpcode.responseParamForA(io.masters(m).a.bits.opcode, io.masters(m).a.bits.param)
            localAErrSize(m)   := io.masters(m).a.bits.size
            localAErrSource(m) := io.masters(m).a.bits.source
        }
    }

    val cArbs = Seq.fill(nSlaves)(Module(new RRArbiter(new TLBundleC(slaveParams), nMasters)))
    for (s <- 0 until nSlaves) {
        for (m <- 0 until nMasters) {
            cArbs(s).io.in(m).valid := io.masters(m).c.valid && releaseHits(m)(s)
            cArbs(s).io.in(m).bits.opcode := io.masters(m).c.bits.opcode
            cArbs(s).io.in(m).bits.param := io.masters(m).c.bits.param
            cArbs(s).io.in(m).bits.size := io.masters(m).c.bits.size
            cArbs(s).io.in(m).bits.source := expandSource(m, io.masters(m).c.bits.source)
            cArbs(s).io.in(m).bits.address := io.masters(m).c.bits.address
            cArbs(s).io.in(m).bits.data := io.masters(m).c.bits.data
            cArbs(s).io.in(m).bits.corrupt := io.masters(m).c.bits.corrupt
        }
        io.slaves(s).c <> cArbs(s).io.out
    }

    for (m <- 0 until nMasters) {
        val readyVec = (0 until nSlaves).map(s => releaseHits(m)(s) && cArbs(s).io.in(m).ready)
        when(io.masters(m).c.valid) {
            assert(PopCount(releaseHitVecs(m)) <= 1.U, "TLXbar: release address overlaps multiple slaves")
        }
        val routedReady = readyVec.reduceOption(_ || _).getOrElse(false.B)
        val localErrReady = !releaseHasHit(m) && !localCErrValid(m)
        io.masters(m).c.ready := routedReady || localErrReady

        when(io.masters(m).c.valid && io.masters(m).c.ready && !releaseHasHit(m)) {
            localCErrValid(m)  := true.B
            localCErrOpcode(m) := TLOpcode.responseOpcodeForC(io.masters(m).c.bits.opcode)
            localCErrSize(m)   := io.masters(m).c.bits.size
            localCErrSource(m) := io.masters(m).c.bits.source
        }
    }

    val dArbs = Seq.fill(nMasters)(Module(new RRArbiter(new TLBundleD(params), nSlaves + 2)))
    for (m <- 0 until nMasters) {
        for (s <- 0 until nSlaves) {
            val respToMaster = decodeMaster(io.slaves(s).d.bits.source) === m.U
            dArbs(m).io.in(s).valid := io.slaves(s).d.valid && respToMaster
            dArbs(m).io.in(s).bits.opcode := io.slaves(s).d.bits.opcode
            dArbs(m).io.in(s).bits.param := io.slaves(s).d.bits.param
            dArbs(m).io.in(s).bits.size := io.slaves(s).d.bits.size
            dArbs(m).io.in(s).bits.source := shrinkSource(io.slaves(s).d.bits.source)
            dArbs(m).io.in(s).bits.sink := io.slaves(s).d.bits.sink
            dArbs(m).io.in(s).bits.denied := io.slaves(s).d.bits.denied
            dArbs(m).io.in(s).bits.data := io.slaves(s).d.bits.data
            dArbs(m).io.in(s).bits.corrupt := io.slaves(s).d.bits.corrupt
        }
        dArbs(m).io.in(nSlaves).valid := localAErrValid(m)
        dArbs(m).io.in(nSlaves).bits.opcode := localAErrOpcode(m)
        dArbs(m).io.in(nSlaves).bits.param := localAErrParam(m)
        dArbs(m).io.in(nSlaves).bits.size := localAErrSize(m)
        dArbs(m).io.in(nSlaves).bits.source := localAErrSource(m)
        dArbs(m).io.in(nSlaves).bits.sink := 0.U
        dArbs(m).io.in(nSlaves).bits.denied := true.B
        dArbs(m).io.in(nSlaves).bits.data := 0.U
        dArbs(m).io.in(nSlaves).bits.corrupt := false.B
        when(dArbs(m).io.in(nSlaves).fire) {
            localAErrValid(m) := false.B
        }
        dArbs(m).io.in(nSlaves + 1).valid := localCErrValid(m)
        dArbs(m).io.in(nSlaves + 1).bits.opcode := localCErrOpcode(m)
        dArbs(m).io.in(nSlaves + 1).bits.param := 0.U
        dArbs(m).io.in(nSlaves + 1).bits.size := localCErrSize(m)
        dArbs(m).io.in(nSlaves + 1).bits.source := localCErrSource(m)
        dArbs(m).io.in(nSlaves + 1).bits.sink := 0.U
        dArbs(m).io.in(nSlaves + 1).bits.denied := true.B
        dArbs(m).io.in(nSlaves + 1).bits.data := 0.U
        dArbs(m).io.in(nSlaves + 1).bits.corrupt := false.B
        when(dArbs(m).io.in(nSlaves + 1).fire) {
            localCErrValid(m) := false.B
        }
        io.masters(m).d <> dArbs(m).io.out
    }

    for (s <- 0 until nSlaves) {
        if (nMasters == 1) {
            io.slaves(s).d.ready := dArbs.head.io.in(s).ready
        } else {
            val readyCases = (0 until nMasters).map { m =>
                (decodeMaster(io.slaves(s).d.bits.source) === m.U) -> dArbs(m).io.in(s).ready
            }
            io.slaves(s).d.ready := MuxCase(false.B, readyCases)
        }
    }

    // TL-C migration step: A/D and C/D now route through the xbar. Probe and
    // GrantAck still need a coherence hub/directory before they can be useful.
    for (m <- 0 until nMasters) {
        io.masters(m).b.valid := false.B
        io.masters(m).b.bits := 0.U.asTypeOf(io.masters(m).b.bits)
        io.masters(m).e.ready := true.B
    }
    for (s <- 0 until nSlaves) {
        io.slaves(s).b.ready := true.B
        io.slaves(s).e.valid := false.B
        io.slaves(s).e.bits := 0.U.asTypeOf(io.slaves(s).e.bits)
    }
}

class TLSystemXbar(params: TLParams, nMasters: Int = 2) extends Module {
    private val tagBits = log2Ceil(nMasters)
    private val slaveParams = params.copy(sourceBits = params.sourceBits + tagBits)

    val io = IO(new Bundle {
        val masters = Vec(nMasters, Flipped(new TLBundle(params)))
        val slave   = new TLBundle(slaveParams)
    })

    private def expandSource(master: Int, source: UInt): UInt =
        if (tagBits == 0) source else Cat(master.U(tagBits.W), source)

    private def shrinkSource(source: UInt): UInt =
        if (tagBits == 0) source else source(params.sourceBits - 1, 0)

    private def decodeMaster(source: UInt): UInt =
        if (tagBits == 0) 0.U else source(slaveParams.sourceBits - 1, params.sourceBits)

    val aArb = Module(new RRArbiter(new TLBundleA(slaveParams), nMasters))
    val cArb = Module(new RRArbiter(new TLBundleC(slaveParams), nMasters))
    val eArb = Module(new RRArbiter(new TLBundleE(slaveParams), nMasters))

    for (m <- 0 until nMasters) {
        aArb.io.in(m).valid := io.masters(m).a.valid
        aArb.io.in(m).bits.opcode := io.masters(m).a.bits.opcode
        aArb.io.in(m).bits.param := io.masters(m).a.bits.param
        aArb.io.in(m).bits.size := io.masters(m).a.bits.size
        aArb.io.in(m).bits.source := expandSource(m, io.masters(m).a.bits.source)
        aArb.io.in(m).bits.address := io.masters(m).a.bits.address
        aArb.io.in(m).bits.mask := io.masters(m).a.bits.mask
        aArb.io.in(m).bits.data := io.masters(m).a.bits.data
        aArb.io.in(m).bits.corrupt := io.masters(m).a.bits.corrupt
        io.masters(m).a.ready := aArb.io.in(m).ready

        cArb.io.in(m).valid := io.masters(m).c.valid
        cArb.io.in(m).bits.opcode := io.masters(m).c.bits.opcode
        cArb.io.in(m).bits.param := io.masters(m).c.bits.param
        cArb.io.in(m).bits.size := io.masters(m).c.bits.size
        cArb.io.in(m).bits.source := expandSource(m, io.masters(m).c.bits.source)
        cArb.io.in(m).bits.address := io.masters(m).c.bits.address
        cArb.io.in(m).bits.data := io.masters(m).c.bits.data
        cArb.io.in(m).bits.corrupt := io.masters(m).c.bits.corrupt
        io.masters(m).c.ready := cArb.io.in(m).ready

        eArb.io.in(m).valid := io.masters(m).e.valid
        eArb.io.in(m).bits.sink := io.masters(m).e.bits.sink
        io.masters(m).e.ready := eArb.io.in(m).ready

        val dToMaster = decodeMaster(io.slave.d.bits.source) === m.U
        io.masters(m).d.valid := io.slave.d.valid && dToMaster
        io.masters(m).d.bits.opcode := io.slave.d.bits.opcode
        io.masters(m).d.bits.param := io.slave.d.bits.param
        io.masters(m).d.bits.size := io.slave.d.bits.size
        io.masters(m).d.bits.source := shrinkSource(io.slave.d.bits.source)
        io.masters(m).d.bits.sink := io.slave.d.bits.sink
        io.masters(m).d.bits.denied := io.slave.d.bits.denied
        io.masters(m).d.bits.data := io.slave.d.bits.data
        io.masters(m).d.bits.corrupt := io.slave.d.bits.corrupt

        val bToMaster = decodeMaster(io.slave.b.bits.source) === m.U
        io.masters(m).b.valid := io.slave.b.valid && bToMaster
        io.masters(m).b.bits.opcode := io.slave.b.bits.opcode
        io.masters(m).b.bits.param := io.slave.b.bits.param
        io.masters(m).b.bits.size := io.slave.b.bits.size
        io.masters(m).b.bits.source := shrinkSource(io.slave.b.bits.source)
        io.masters(m).b.bits.address := io.slave.b.bits.address
        io.masters(m).b.bits.mask := io.slave.b.bits.mask
        io.masters(m).b.bits.data := io.slave.b.bits.data
        io.masters(m).b.bits.corrupt := io.slave.b.bits.corrupt
    }

    io.slave.a <> aArb.io.out
    io.slave.c <> cArb.io.out
    io.slave.e <> eArb.io.out

    if (nMasters == 1) {
        io.slave.d.ready := io.masters.head.d.ready
        io.slave.b.ready := io.masters.head.b.ready
    } else {
        val dReadyCases = (0 until nMasters).map { m =>
            (decodeMaster(io.slave.d.bits.source) === m.U) -> io.masters(m).d.ready
        }
        val bReadyCases = (0 until nMasters).map { m =>
            (decodeMaster(io.slave.b.bits.source) === m.U) -> io.masters(m).b.ready
        }
        io.slave.d.ready := MuxCase(false.B, dReadyCases)
        io.slave.b.ready := MuxCase(false.B, bReadyCases)
    }
}
