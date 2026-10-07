package soc.device.interrupt

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

object PLICMap {
    val PriorityBase: BigInt = 0x000000
    val PendingBase: BigInt = 0x001000
    val EnableBase: BigInt = 0x002000
    val EnableStride: BigInt = 0x000080
    val ContextBase: BigInt = 0x200000
    val ContextStride: BigInt = 0x001000
    val ThresholdOffset: BigInt = 0x0
    val ClaimCompleteOffset: BigInt = 0x4
}

class PLIC(params: TLParams, nSources: Int = 31, priorityWidth: Int = 3) extends Module {
    require(nSources > 0, "PLIC must expose at least one interrupt source")
    require(nSources <= 31, "this PLIC register subset packs sources into one 32-bit word")
    require(priorityWidth > 0, "priorityWidth must be positive")

    val io = IO(new Bundle {
        val tl      = Flipped(new TLBundle(params))
        val sources = Input(Vec(nSources + 1, Bool()))
        val meip    = Output(Bool())
        val seip    = Output(Bool())
    })
    TLBundle.tieoffSlaveCoherence(io.tl)

    private val beatBytes = params.dataWidth / 8
    private val beatOffsetBits = log2Ceil(beatBytes)
    private val sourceIdWidth = log2Ceil(nSources + 1).max(1)
    private val maxPriority = ((BigInt(1) << priorityWidth) - 1).U(priorityWidth.W)
    private val priorityAddrBits = log2Ceil((nSources + 1) * 4)
    private val nContexts = 2

    val priority = RegInit(VecInit(Seq.fill(nSources + 1)(0.U(priorityWidth.W))))
    val pending  = RegInit(VecInit(Seq.fill(nSources + 1)(false.B)))
    val gatewayBusy = RegInit(VecInit(Seq.fill(nSources + 1)(false.B)))
    val enable   = RegInit(VecInit(Seq.fill(nContexts)(0.U((nSources + 1).W))))
    val threshold = RegInit(VecInit(Seq.fill(nContexts)(0.U(priorityWidth.W))))

    priority(0) := 0.U
    pending(0) := false.B
    gatewayBusy(0) := false.B

    // Source 0 is reserved by the PLIC spec. External gateways feed source IDs
    // starting at 1. A level source is forwarded once, then held busy until
    // software completes that source. If the level is still high at completion,
    // the gateway immediately forwards a fresh pending request.
    for (id <- 1 to nSources) {
        when(io.sources(id) && !gatewayBusy(id)) {
            pending(id) := true.B
            gatewayBusy(id) := true.B
        }
    }

    private def maskBits: UInt = {
        Cat((0 until beatBytes).reverse.map(i => Fill(8, io.tl.a.bits.mask(i))))
    }

    private def laneShift: UInt = {
        Cat(io.tl.a.bits.address(beatOffsetBits - 1, 0), 0.U(3.W))
    }

    private def placeRead(value: UInt): UInt = {
        (value << laneShift)(params.dataWidth - 1, 0)
    }

    private def mergeLaneMasked(oldValue: UInt): UInt = {
        val oldBeat = (oldValue << laneShift)(params.dataWidth - 1, 0)
        ((oldBeat & ~maskBits) | (io.tl.a.bits.data & maskBits)) >> laneShift
    }

    private def selectBest(eligible: Vec[Bool]): (UInt, UInt) = {
        val selected = (1 to nSources).foldLeft((0.U(sourceIdWidth.W), 0.U(priorityWidth.W))) {
            case ((curId, curPriority), id) =>
                val take = eligible(id) && (priority(id) > curPriority || (priority(id) === curPriority && (curId === 0.U || id.U < curId)))
                (Mux(take, id.U(sourceIdWidth.W), curId), Mux(take, priority(id), curPriority))
        }
        selected
    }

    val notifyIds = Wire(Vec(nContexts, UInt(sourceIdWidth.W)))
    val claimIds = Wire(Vec(nContexts, UInt(sourceIdWidth.W)))
    for (ctx <- 0 until nContexts) {
        val notifyEligible = Wire(Vec(nSources + 1, Bool()))
        val claimEligible = Wire(Vec(nSources + 1, Bool()))
        for (id <- 0 to nSources) {
            notifyEligible(id) := pending(id) && enable(ctx)(id) && priority(id) > threshold(ctx)
            claimEligible(id) := pending(id) && enable(ctx)(id) && priority(id) =/= 0.U
        }
        val (notifyId, _) = selectBest(notifyEligible)
        val (claimId, _) = selectBest(claimEligible)
        notifyIds(ctx) := notifyId
        claimIds(ctx) := claimId
    }

    io.meip := notifyIds(0) =/= 0.U
    io.seip := notifyIds(1) =/= 0.U

    val respValid  = RegInit(false.B)
    val respData   = RegInit(0.U(params.dataWidth.W))
    val respOpcode = RegInit(TLOpcode.AccessAck)
    val respParam  = RegInit(0.U(3.W))
    val respSize   = RegInit(0.U(params.sizeBits.W))
    val respSource = RegInit(0.U(params.sourceBits.W))
    val respDenied = RegInit(false.B)

    io.tl.a.ready := !respValid

    val offset = io.tl.a.bits.address(25, 0)
    when(io.tl.a.fire) {
        val isRead = io.tl.a.bits.opcode === TLOpcode.Get
        val isWrite = io.tl.a.bits.opcode === TLOpcode.PutFullData ||
            io.tl.a.bits.opcode === TLOpcode.PutPartialData
        val isLegal = isRead || isWrite
        val wordOffset = offset(25, 2) << 2
        val readData = Wire(UInt(params.dataWidth.W))
        readData := 0.U

        when(isRead && wordOffset >= (PLICMap.PriorityBase + 4).U && wordOffset <= (PLICMap.PriorityBase + nSources * 4).U) {
            val id = wordOffset(priorityAddrBits - 1, 2)
            readData := placeRead(priority(id))
        }.elsewhen(isRead && wordOffset === PLICMap.PendingBase.U) {
            readData := placeRead(pending.asUInt)
        }.elsewhen(isRead && wordOffset === PLICMap.EnableBase.U) {
            readData := placeRead(enable(0))
        }.elsewhen(isRead && wordOffset === (PLICMap.EnableBase + PLICMap.EnableStride).U) {
            readData := placeRead(enable(1))
        }.elsewhen(isRead && wordOffset === (PLICMap.ContextBase + PLICMap.ThresholdOffset).U) {
            readData := placeRead(threshold(0))
        }.elsewhen(isRead && wordOffset === (PLICMap.ContextBase + PLICMap.ClaimCompleteOffset).U) {
            readData := placeRead(claimIds(0))
        }.elsewhen(isRead && wordOffset === (PLICMap.ContextBase + PLICMap.ContextStride + PLICMap.ThresholdOffset).U) {
            readData := placeRead(threshold(1))
        }.elsewhen(isRead && wordOffset === (PLICMap.ContextBase + PLICMap.ContextStride + PLICMap.ClaimCompleteOffset).U) {
            readData := placeRead(claimIds(1))
        }

        when(isWrite) {
            when(wordOffset >= (PLICMap.PriorityBase + 4).U && wordOffset <= (PLICMap.PriorityBase + nSources * 4).U) {
                val id = wordOffset(priorityAddrBits - 1, 2)
                val merged = mergeLaneMasked(priority(id))
                priority(id) := Mux(merged(priorityWidth - 1, 0) > maxPriority, maxPriority, merged(priorityWidth - 1, 0))
            }.elsewhen(wordOffset === PLICMap.EnableBase.U) {
                enable(0) := mergeLaneMasked(enable(0))(nSources, 0) & ~1.U((nSources + 1).W)
            }.elsewhen(wordOffset === (PLICMap.EnableBase + PLICMap.EnableStride).U) {
                enable(1) := mergeLaneMasked(enable(1))(nSources, 0) & ~1.U((nSources + 1).W)
            }.elsewhen(wordOffset === (PLICMap.ContextBase + PLICMap.ThresholdOffset).U) {
                val merged = mergeLaneMasked(threshold(0))
                threshold(0) := Mux(merged(priorityWidth - 1, 0) > maxPriority, maxPriority, merged(priorityWidth - 1, 0))
            }.elsewhen(wordOffset === (PLICMap.ContextBase + PLICMap.ContextStride + PLICMap.ThresholdOffset).U) {
                val merged = mergeLaneMasked(threshold(1))
                threshold(1) := Mux(merged(priorityWidth - 1, 0) > maxPriority, maxPriority, merged(priorityWidth - 1, 0))
            }.elsewhen(wordOffset === (PLICMap.ContextBase + PLICMap.ClaimCompleteOffset).U) {
                val completeId = mergeLaneMasked(0.U)(sourceIdWidth - 1, 0)
                when(completeId =/= 0.U && completeId <= nSources.U) {
                    when(io.sources(completeId)) {
                        pending(completeId) := true.B
                        gatewayBusy(completeId) := true.B
                    }.otherwise {
                        pending(completeId) := false.B
                        gatewayBusy(completeId) := false.B
                    }
                }
            }.elsewhen(wordOffset === (PLICMap.ContextBase + PLICMap.ContextStride + PLICMap.ClaimCompleteOffset).U) {
                val completeId = mergeLaneMasked(0.U)(sourceIdWidth - 1, 0)
                when(completeId =/= 0.U && completeId <= nSources.U) {
                    when(io.sources(completeId)) {
                        pending(completeId) := true.B
                        gatewayBusy(completeId) := true.B
                    }.otherwise {
                        pending(completeId) := false.B
                        gatewayBusy(completeId) := false.B
                    }
                }
            }
        }.elsewhen(isRead && wordOffset === (PLICMap.ContextBase + PLICMap.ClaimCompleteOffset).U && claimIds(0) =/= 0.U) {
            // Claim is a side-effecting read: it returns the selected source and
            // clears that pending bit so software can service it exactly once.
            pending(claimIds(0)) := false.B
        }.elsewhen(isRead && wordOffset === (PLICMap.ContextBase + PLICMap.ContextStride + PLICMap.ClaimCompleteOffset).U && claimIds(1) =/= 0.U) {
            pending(claimIds(1)) := false.B
        }

        respValid  := true.B
        respOpcode := TLOpcode.responseOpcodeForA(io.tl.a.bits.opcode)
        respParam  := TLOpcode.responseParamForA(io.tl.a.bits.opcode, io.tl.a.bits.param)
        respSize   := io.tl.a.bits.size
        respSource := io.tl.a.bits.source
        respData   := readData
        respDenied := !isLegal
    }

    io.tl.d.valid        := respValid
    io.tl.d.bits.opcode  := respOpcode
    io.tl.d.bits.param   := respParam
    io.tl.d.bits.size    := respSize
    io.tl.d.bits.source  := respSource
    io.tl.d.bits.sink    := 0.U
    io.tl.d.bits.denied  := respDenied
    io.tl.d.bits.data    := respData
    io.tl.d.bits.corrupt := false.B

    when(io.tl.d.fire) {
        respValid := false.B
    }
}
