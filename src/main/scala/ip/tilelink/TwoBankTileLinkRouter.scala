package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

/** TL-UL address router for two adjacent RAM banks. D may return from either bank first. */
class TwoBankTileLinkRouter(
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    base: BigInt = BigInt("80010000", 16),
    bankBytes: BigInt = 2048,
    secondBankBytes: BigInt = 0,
    prefixAddressDecode: Boolean = false,
    rawResponseMetadata: Boolean = false
) extends Module {
    require(params.dataWidth == 64 && params.addrWidth >= 32 && params.addrWidth <= 64)
    require(params.sourceBits >= 1 && params.sourceBits <= 6)
    require(bankBytes >= 16 && isPow2(bankBytes) && base >= 0 && base % bankBytes == 0)
    private val secondBytes = if (secondBankBytes == 0) bankBytes else secondBankBytes
    require(secondBytes >= 16 && isPow2(secondBytes))
    require(base + bankBytes + secondBytes < (BigInt(1) << params.addrWidth))
    val io = IO(new Bundle {
        val host  = Flipped(new TLBundle(params))
        val banks = Vec(2, new TLBundle(params))
    })

    val address = io.host.a.bits.address
    val hit = if (prefixAddressDecode) {
        val decoder = Module(new TwoBankAddressDecoder(params.addrWidth, base, bankBytes, secondBytes))
        decoder.io.address := address
        VecInit((0 until 2).map(i => decoder.io.hitMask(i)))
    } else VecInit((0 until 2).map { i =>
        val start = (base + (if (i == 0) 0 else bankBytes)).U(params.addrWidth.W)
        val end   = (base + bankBytes + (if (i == 0) 0 else secondBytes)).U(params.addrWidth.W)
        address >= start && address < end
    })
    val unmapped = !hit.asUInt.orR
    val sourceCount = 1 << params.sourceBits
    val occupied = RegInit(VecInit(Seq.fill(sourceCount)(false.B)))
    // One-hot owner facts let each bank check its own row in parallel with the
    // source decode, instead of reading a binary owner then comparing it.
    val owner = Reg(Vec(sourceCount, UInt(3.W)))
    val aBurst = RegInit(false.B)
    val aTarget = Reg(UInt(2.W))
    val aSource = Reg(UInt(params.sourceBits.W))
    val aAddress = Reg(UInt(params.addrWidth.W))
    val aSize = Reg(UInt(params.sizeBits.W))
    val aOpcode = Reg(UInt(3.W))
    val aParam = Reg(UInt(3.W))
    val aRemaining = Reg(UInt(TLBurst.beats(0.U(params.sizeBits.W), params).getWidth.W))
    val dBurst = RegInit(false.B)
    val dSelected = Reg(UInt(2.W))
    val dSource = Reg(UInt(params.sourceBits.W))
    val dSize = Reg(UInt(params.sizeBits.W))
    val dOpcode = Reg(UInt(3.W))
    val dRemaining = Reg(UInt(aRemaining.getWidth.W))
    val errorValid  = RegInit(false.B)
    val errorSource = Reg(UInt(params.sourceBits.W))
    val errorSize   = Reg(UInt(params.sizeBits.W))
    val errorOpcode = Reg(UInt(3.W))
    val errorRemaining = Reg(UInt(aRemaining.getWidth.W))

    for (i <- 0 until 2) {
        io.banks(i).a.valid := io.host.a.valid && hit(i)
        io.banks(i).a.bits  := io.host.a.bits
        io.banks(i).b.ready := false.B
        io.banks(i).c.valid := false.B
        io.banks(i).c.bits  := 0.U.asTypeOf(io.banks(i).c.bits)
        io.banks(i).e.valid := false.B
        io.banks(i).e.bits  := 0.U.asTypeOf(io.banks(i).e.bits)
        when(io.banks(i).b.valid) {
            assert(false.B, "Two-bank TileLink router cannot accept coherence probes")
        }
    }
    io.host.a.ready := Mux(hit(0), io.banks(0).a.ready,
        Mux(hit(1), io.banks(1).a.ready, aBurst || !errorValid))
    io.host.b.valid := false.B
    io.host.b.bits  := 0.U.asTypeOf(io.host.b.bits)
    io.host.c.ready := false.B
    io.host.e.ready := false.B
    when(io.host.c.valid || io.host.e.valid) {
        assert(false.B, "Two-bank TileLink router does not accept coherence messages")
    }

    val newSource = Mux(io.host.a.valid, io.host.a.bits.source, 0.U)
    when(io.host.a.fire) {
        val a = io.host.a.bits
        val target = Mux(hit(0), 0.U, Mux(hit(1), 1.U, 2.U))
        when(aBurst) {
            assert(newSource === aSource && target === aTarget && a.address === aAddress &&
                a.size === aSize && a.opcode === aOpcode && a.param === aParam,
                "TileLink routed A burst changed control, source or bank")
            when(aRemaining === 1.U) { aBurst := false.B }
                .otherwise { aRemaining := aRemaining - 1.U }
        }.otherwise {
            assert(!occupied(newSource), "Two-bank TileLink source reused before response")
            occupied(newSource) := true.B
            owner(newSource) := UIntToOH(target, 3)
            when(unmapped) {
                errorValid  := true.B
                errorSource := newSource
                errorSize   := a.size
                errorOpcode := TLOpcode.responseOpcodeForA(a.opcode)
                errorRemaining := Mux(TLBurst.hasDataOnD(TLOpcode.responseOpcodeForA(a.opcode)),
                    TLBurst.beats(a.size, params), 1.U)
            }
            val beats = TLBurst.beats(a.size, params)
            when(TLBurst.hasDataOnA(a.opcode) && beats > 1.U) {
                aBurst := true.B
                aTarget := target
                aSource := newSource
                aAddress := a.address
                aSize := a.size
                aOpcode := a.opcode
                aParam := a.param
                aRemaining := beats - 1.U
            }
        }
    }

    val replies = Module(new RRArbiter(new TLBundleD(params), 3))
    for (i <- 0 until 2) {
        val source = if (rawResponseMetadata) io.banks(i).d.bits.source
            else Mux(io.banks(i).d.valid, io.banks(i).d.bits.source, 0.U)
        val owners = VecInit((0 until sourceCount).map(s => occupied(s) && owner(s)(i))).asUInt
        val belongs = (owners & UIntToOH(source, sourceCount)).orR
        val justAccepted = io.host.a.fire && hit(i) && newSource === source
        replies.io.in(i).valid := io.banks(i).d.valid && belongs && (!dBurst || dSelected === i.U)
        replies.io.in(i).bits  := io.banks(i).d.bits
        io.banks(i).d.ready    := replies.io.in(i).ready && belongs && (!dBurst || dSelected === i.U)
        when(io.banks(i).d.valid) {
            assert(belongs || justAccepted, "TileLink bank response has no matching source")
        }
    }
    val errorBurstIncomplete = aBurst && aTarget === 2.U && aSource === errorSource
    replies.io.in(2).valid        := errorValid && !errorBurstIncomplete && (!dBurst || dSelected === 2.U)
    replies.io.in(2).bits         := 0.U.asTypeOf(replies.io.in(2).bits)
    replies.io.in(2).bits.opcode  := errorOpcode
    replies.io.in(2).bits.size    := errorSize
    replies.io.in(2).bits.source  := errorSource
    replies.io.in(2).bits.denied  := true.B
    replies.io.in(2).bits.corrupt := errorOpcode === TLOpcode.AccessAckData
    io.host.d.valid      := replies.io.out.valid
    io.host.d.bits       := replies.io.out.bits
    replies.io.out.ready := io.host.d.ready
    when(replies.io.out.fire) {
        val source = Mux(replies.io.out.valid, replies.io.out.bits.source, 0.U)
        assert(occupied(source) && owner(source) === UIntToOH(replies.io.chosen, 3),
            "TileLink response routed from wrong bank")
        when(dBurst) {
            assert(replies.io.chosen === dSelected && source === dSource &&
                replies.io.out.bits.size === dSize && replies.io.out.bits.opcode === dOpcode,
                "TileLink D burst interleaved or changed control between banks")
            when(dRemaining === 1.U) {
                dBurst := false.B
                occupied(source) := false.B
            }.otherwise { dRemaining := dRemaining - 1.U }
        }.otherwise {
            val beats = TLBurst.beats(replies.io.out.bits.size, params)
            when(TLBurst.hasDataOnD(replies.io.out.bits.opcode) && beats > 1.U) {
                dBurst := true.B
                dSelected := replies.io.chosen
                dSource := source
                dSize := replies.io.out.bits.size
                dOpcode := replies.io.out.bits.opcode
                dRemaining := beats - 1.U
            }.otherwise { occupied(source) := false.B }
        }
        when(replies.io.chosen === 2.U) {
            when(errorRemaining === 1.U) { errorValid := false.B }
                .otherwise { errorRemaining := errorRemaining - 1.U }
        }
    }
}
