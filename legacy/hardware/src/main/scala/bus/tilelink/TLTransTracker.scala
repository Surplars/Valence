package soc.bus.tilelink

import chisel3._
import chisel3.util._
import soc.memory.MmioMaster

class TLTransTracker(params: TLParams, maxInFlight: Int = 1) extends Module {
    require(maxInFlight > 0, "maxInFlight must be positive")
    require(maxInFlight <= (1 << params.sourceBits), "maxInFlight exceeds source ID space")

    val io = IO(new Bundle {
        // 用户侧接口
        val master = Flipped(new MmioMaster(params))
        // TileLink 侧接口
        val tl = new TLBundle(params)
    })
    TLBundle.tieoffMasterCoherence(io.tl)

    // source池，记录哪些source可分配（true=可分配）
    val sourcePool = RegInit(VecInit(Seq.fill(maxInFlight)(true.B)))
    private val sourceIdxBits = math.max(1, log2Ceil(maxInFlight))

    // inflight表，记录每个source对应的请求信息
    class InflightEntry extends Bundle {
        val valid   = Bool()
        val addr    = UInt(params.addrWidth.W)
        val size    = UInt(params.sizeBits.W)
        val isWrite = Bool()
        val userTag = UInt(8.W) // 可扩展，用户自定义tag
    }
    val inflight = RegInit(VecInit(Seq.fill(maxInFlight)(0.U.asTypeOf(new InflightEntry))))

    // 分配source (PriorityEncoder消除组合环)
    val allocIdx = Wire(UInt(sourceIdxBits.W))
    val allocValid = Wire(Bool())
    val freeVec = sourcePool.asUInt
    allocValid := freeVec.orR
    if (maxInFlight == 1) {
        allocIdx := 0.U
    } else {
        allocIdx := PriorityEncoder(freeVec)
    }

    // 请求发射条件遵循Decoupled：valid不能依赖ready
    val reqValid = allocValid && io.master.req_valid
    val canSend = reqValid && io.tl.a.ready
    io.master.req_ready := allocValid && io.tl.a.ready

    // 生成A通道
    io.tl.a.valid := reqValid
    io.tl.a.bits.opcode  := io.master.req_cmd
    io.tl.a.bits.param   := 0.U
    io.tl.a.bits.size    := io.master.req_size
    io.tl.a.bits.source  := allocIdx
    io.tl.a.bits.address := io.master.req_addr
    io.tl.a.bits.mask    := io.master.req_mask
    io.tl.a.bits.data    := io.master.req_data
    io.tl.a.bits.corrupt := false.B

    // 发射时，分配source并记录inflight表
    when(canSend) {
        sourcePool(allocIdx) := false.B
        inflight(allocIdx).valid   := true.B
        inflight(allocIdx).addr    := io.master.req_addr
        inflight(allocIdx).size    := io.master.req_size
        inflight(allocIdx).isWrite := (io.master.req_cmd === TLOpcode.PutFullData || io.master.req_cmd === TLOpcode.PutPartialData)
        inflight(allocIdx).userTag := 0.U // 可扩展
    }

    // D通道响应打一拍后再送给LSU，避免resp_valid和resp_data存在组合竞争
    val respValidReg  = RegInit(false.B)
    val respDataReg   = RegInit(0.U(params.dataWidth.W))
    val respCmdReg    = RegInit(0.U(3.W))
    val respSourceReg = RegInit(0.U(params.sourceBits.W))
    val respErrReg    = RegInit(false.B)

    io.tl.d.ready := !respValidReg
    val d_source = io.tl.d.bits.source
    val d_fire   = io.tl.d.fire

    io.master.resp_valid  := respValidReg
    io.master.resp_data   := respDataReg
    io.master.resp_cmd    := respCmdReg
    io.master.resp_source := respSourceReg
    io.master.resp_err    := respErrReg

    when(respValidReg) {
        respValidReg := false.B
    }

    // 响应时释放source
    when(d_fire && inflight(d_source).valid) {
        respValidReg := true.B
        respDataReg := io.tl.d.bits.data
        respCmdReg := io.tl.d.bits.opcode
        respSourceReg := d_source
        respErrReg := io.tl.d.bits.denied
        sourcePool(d_source) := true.B
        inflight(d_source).valid := false.B
    }

    when(d_fire) {
        assert(inflight(d_source).valid, "TLTransTracker: received response for non-inflight source")
    }

    // io.tl.b <> DontCare
    // io.tl.c <> DontCare
    // io.tl.e <> DontCare
    // 可扩展更多功能
}
