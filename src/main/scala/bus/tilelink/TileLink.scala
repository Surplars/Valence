package soc.bus.tilelink

import chisel3._
import chisel3.util._

object TLOpcode {
    // Channel A (Request)
    val PutFullData    = 0.U(3.W) // 写请求 (全覆盖)
    val PutPartialData = 1.U(3.W) // 写请求 (带掩码)
    val ArithmeticData = 2.U(3.W) // 原子操作 (MIN, MAX, ADD...)
    val LogicalData    = 3.U(3.W) // 原子操作 (XOR, OR...)
    val Get            = 4.U(3.W) // 读请求
    val Intent         = 5.U(3.W) // 预取 Hint
    val AcquireBlock   = 6.U(3.W) // (TL-C) 申请缓存块
    val AcquirePerm    = 7.U(3.W) // (TL-C) 申请权限

    // Channel D (Response)
    val AccessAck     = 0.U(3.W) // 写响应 (无数据)
    val AccessAckData = 1.U(3.W) // 读响应 (有数据)
    val HintAck       = 2.U(3.W)
    val Grant         = 4.U(3.W) // (TL-C) 授权
    val GrantData     = 5.U(3.W) // (TL-C) 授权带数据
    val ReleaseAck    = 6.U(3.W) // (TL-C) 释放确认

    // Channel B (Probe)
    val ProbeBlock = 6.U(3.W)
    val ProbePerm  = 7.U(3.W)

    // Channel C (Release / ProbeAck)
    val ProbeAck      = 4.U(3.W)
    val ProbeAckData  = 5.U(3.W)
    val Release       = 6.U(3.W)
    val ReleaseData   = 7.U(3.W)

    def hasDataResponse(opcode: UInt): Bool =
        opcode === Get || opcode === AcquireBlock

    def isAcquire(opcode: UInt): Bool =
        opcode === AcquireBlock || opcode === AcquirePerm

    def isRelease(opcode: UInt): Bool =
        opcode === Release || opcode === ReleaseData

    def responseOpcodeForA(opcode: UInt): UInt = MuxLookup(opcode, AccessAck)(
        Seq(
            Get -> AccessAckData,
            AcquireBlock -> GrantData,
            AcquirePerm -> Grant
        )
    )

    def responseParamForA(opcode: UInt, param: UInt): UInt =
        Mux(isAcquire(opcode), param, 0.U)

    def responseOpcodeForC(opcode: UInt): UInt =
        ReleaseAck
}

/** Number of data beats in a TileLink message. Control-only messages always use one beat. */
object TLBurst {
    def beats(size: UInt, params: TLParams): UInt = {
        require(params.dataWidth >= 8 && isPow2(params.dataWidth / 8))
        val beatLog = log2Ceil(params.dataWidth / 8)
        val maxSize = (1 << params.sizeBits) - 1
        require(maxSize >= beatLog && maxSize - beatLog <= 8)
        val width = maxSize - beatLog + 2
        MuxLookup(size, 1.U(width.W))(
            (beatLog + 1 to maxSize).map(n => n.U -> (1 << (n - beatLog)).U(width.W))
        )
    }

    def hasDataOnA(opcode: UInt): Bool =
        opcode === TLOpcode.PutFullData || opcode === TLOpcode.PutPartialData ||
            opcode === TLOpcode.ArithmeticData || opcode === TLOpcode.LogicalData

    def hasDataOnD(opcode: UInt): Bool =
        opcode === TLOpcode.AccessAckData || opcode === TLOpcode.GrantData
}

object TLPermissions {
    val toT = 0.U(3.W)
    val toB = 1.U(3.W)
    val toN = 2.U(3.W)

    val nToB = 0.U(3.W)
    val nToT = 1.U(3.W)
    val bToT = 2.U(3.W)

    val tToB = 0.U(3.W)
    val tToN = 1.U(3.W)
    val bToN = 2.U(3.W)
}

case class TLParams(
    addrWidth: Int = 32,
    dataWidth: Int = 64,
    sourceBits: Int = 4,
    sinkBits: Int = 1,
    sizeBits: Int = 3
)

// Chinnel A: 主设备发起的请求
class TLBundleA(params: TLParams) extends Bundle {
    val opcode  = UInt(3.W)                      // 操作类型
    val param   = UInt(3.W)                      // 操作参数，具体含义取决于opcode
    val size    = UInt(params.sizeBits.W)        // 2^size字节数
    val source  = UInt(params.sourceBits.W)      // 请求来源ID
    val address = UInt(params.addrWidth.W)       // 访问地址
    val mask    = UInt((params.dataWidth / 8).W) // 字节掩码，1表示对应字节有效
    val data    = UInt(params.dataWidth.W)       //	写数据，只有在写请求时有效
    val corrupt = Bool()                         // 数据是否损坏，通常由从设备设置以指示错误
}
// Channel B: Probe (Master <- Slave/Hub)
// 用于一致性：Hub 问 L1 Cache "你有这个数据吗？有的话交出来/作废掉"
class TLBundleB(params: TLParams) extends Bundle {
    val opcode  = UInt(3.W)                // Probe, Intent
    val param   = UInt(3.W)                // toT, toB, toN (状态转换方向)
    val size    = UInt(params.sizeBits.W)
    val source  = UInt(params.sourceBits.W)
    val address = UInt(params.addrWidth.W)
    val mask    = UInt((params.dataWidth / 8).W)
    val data    = UInt(params.dataWidth.W) // 甚至 Probe 也可以带数据(虽然少见)
    val corrupt = Bool()
}
// Channel C: Release (Master -> Slave/Hub)
// 用于一致性：L1 Cache 主动写回脏数据(Evict) 或响应 Probe
class TLBundleC(params: TLParams) extends Bundle {
    val opcode  = UInt(3.W)                // ProbeAck, ProbeAckData, Release, ReleaseData
    val param   = UInt(3.W)
    val size    = UInt(params.sizeBits.W)
    val source  = UInt(params.sourceBits.W)
    val address = UInt(params.addrWidth.W)
    val data    = UInt(params.dataWidth.W) // 写回的数据
    val corrupt = Bool()
}
// Channel D: 从设备返回的响应
class TLBundleD(params: TLParams) extends Bundle {
    val opcode  = UInt(3.W)                 // AccessAck, AccessAckData
    val param   = UInt(3.W)
    val size    = UInt(params.sizeBits.W)
    val source  = UInt(params.sourceBits.W) // 对应 A 通道的 ID
    val sink    = UInt(params.sinkBits.W)
    val denied  = Bool()                    // 是否被拒绝
    val data    = UInt(params.dataWidth.W)
    val corrupt = Bool()
}
// Channel E: GrantAck (Master -> Slave/Hub)
// 用于一致性：L1 Cache 告诉 Hub "我收到你的 Grant 数据了，交易结束" (这是为了序列化网络，防止死锁)
class TLBundleE(params: TLParams) extends Bundle {
    val sink = UInt(params.sinkBits.W) // 对应 D 通道的 sink
}

class TLBundle(params: TLParams) extends Bundle {
    val a = Decoupled(new TLBundleA(params))          // Request
    val d = Flipped(Decoupled(new TLBundleD(params))) // Response
    val b = Flipped(Decoupled(new TLBundleB(params))) // Probe
    val c = Decoupled(new TLBundleC(params))          // Release / ProbeAck
    val e = Decoupled(new TLBundleE(params))          // GrantAck
}

object TLBundle {
    // Tie off TL-C coherence channels for a TL-UL-like master. The master never
    // emits C/E and is always ready to drop probes because current masters do
    // not hold coherent permissions.
    def tieoffMasterCoherence(tl: TLBundle): Unit = {
        tl.b.ready := true.B
        tl.c.valid := false.B
        tl.c.bits := 0.U.asTypeOf(tl.c.bits)
        tl.e.valid := false.B
        tl.e.bits := 0.U.asTypeOf(tl.e.bits)
    }

    // Tie off TL-C coherence channels for a TL-UL-like manager. The manager
    // never sends probes and always consumes unexpected C/E beats.
    def tieoffSlaveCoherence(tl: TLBundle): Unit = {
        tl.b.valid := false.B
        tl.b.bits := 0.U.asTypeOf(tl.b.bits)
        tl.c.ready := true.B
        tl.e.ready := true.B
    }
}
