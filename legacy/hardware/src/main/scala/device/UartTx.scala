package soc.device

import chisel3._
import chisel3.util._

import soc.bus.tilelink._

class UartTx(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
        val rx_valid = Input(Bool())
        val rx_byte  = Input(UInt(8.W))
        val tx_valid = Output(Bool())
        val tx_byte  = Output(UInt(8.W))
        val irq      = Output(Bool())
    })
    TLBundle.tieoffSlaveCoherence(io.tl)

    private val beatBytes = params.dataWidth / 8
    private val beatOffsetBits = log2Ceil(beatBytes)

    object UartReg {
        val RbrThrDll = 0
        val IerDlm    = 1
        val IirFcr    = 2
        val Lcr       = 3
        val Mcr       = 4
        val Lsr       = 5
        val Msr       = 6
        val Scr       = 7
    }

    val ier = RegInit(0.U(8.W))
    val fcr = RegInit(0.U(8.W))
    val lcr = RegInit(0.U(8.W))
    val mcr = RegInit(0.U(8.W))
    val scr = RegInit(0.U(8.W))
    val dll = RegInit(0.U(8.W))
    val dlm = RegInit(0.U(8.W))
    val rbr = RegInit(0.U(8.W))

    val rxReady       = RegInit(false.B)
    val overrunError  = RegInit(false.B)
    val thrIrqPending = RegInit(false.B)
    val setThrIrqNext = RegInit(false.B)

    val dlab = lcr(7)
    val rxIrq = ier(0) && rxReady
    val txIrq = ier(1) && thrIrqPending
    val irqPending = rxIrq || txIrq
    val iirValue = Wire(UInt(8.W))
    iirValue := Mux(
        rxIrq,
        "h04".U, // received data available
        Mux(txIrq, "h02".U, "h01".U) // THR empty, or no interrupt pending
    ) | Mux(fcr(0), "hc0".U, 0.U)
    // 16550 LSR bits: DR, OE, PE, FE, BI, THRE, TEMT, FIFOERR.
    // The simulator UART accepts a THR write every cycle, so THRE/TEMT are
    // permanently set. Standard 16550 drivers poll these bits before writing.
    val lsrValue = Cat(0.U(1.W), 1.U(1.W), 1.U(1.W), 0.U(3.W), overrunError, rxReady)

    private def laneShift: UInt = Cat(io.tl.a.bits.address(beatOffsetBits - 1, 0), 0.U(3.W))
    private def writeByte: UInt = (io.tl.a.bits.data >> laneShift)(7, 0)
    private def placeByte(value: UInt): UInt = (value << laneShift)(params.dataWidth - 1, 0)

    // TL response pipeline
    val respValid  = RegInit(false.B)
    val respOpcode = RegInit(TLOpcode.AccessAck)
    val respParam  = RegInit(0.U(3.W))
    val respSize   = RegInit(0.U(params.sizeBits.W))
    val respSource = RegInit(0.U(params.sourceBits.W))
    val respData   = RegInit(0.U(params.dataWidth.W))
    val respDenied = RegInit(false.B)

    // TX output (one-cycle pulse on write)
    val txValid = RegInit(false.B)
    val txByte  = RegInit(0.U(8.W))

    val canAccept = !respValid && !txValid
    io.tl.a.ready := canAccept

    when(io.rx_valid) {
        rbr := io.rx_byte
        overrunError := overrunError || rxReady
        rxReady := true.B
    }

    when(setThrIrqNext) {
        thrIrqPending := true.B
        setThrIrqNext := false.B
    }

    when(io.tl.a.fire) {
        val isRead = io.tl.a.bits.opcode === TLOpcode.Get
        val isWrite = io.tl.a.bits.opcode === TLOpcode.PutFullData ||
            io.tl.a.bits.opcode === TLOpcode.PutPartialData
        val isLegal = isRead || isWrite
        val regOffset = io.tl.a.bits.address(2, 0)
        val readByte = Wire(UInt(8.W))
        readByte := 0.U

        switch(regOffset) {
            is(UartReg.RbrThrDll.U) { readByte := Mux(dlab, dll, rbr) }
            is(UartReg.IerDlm.U)    { readByte := Mux(dlab, dlm, ier) }
            is(UartReg.IirFcr.U)    { readByte := iirValue }
            is(UartReg.Lcr.U)       { readByte := lcr }
            is(UartReg.Mcr.U)       { readByte := mcr }
            is(UartReg.Lsr.U)       { readByte := lsrValue }
            is(UartReg.Msr.U)       { readByte := 0.U }
            is(UartReg.Scr.U)       { readByte := scr }
        }

        txValid := false.B
        when(isWrite) {
            switch(regOffset) {
                is(UartReg.RbrThrDll.U) {
                    when(dlab) {
                        dll := writeByte
                    }.otherwise {
                        txValid       := true.B
                        txByte        := writeByte
                        thrIrqPending := false.B
                        setThrIrqNext := ier(1)
                    }
                }
                is(UartReg.IerDlm.U) {
                    when(dlab) {
                        dlm := writeByte
                    }.otherwise {
                        when(!ier(1) && writeByte(1)) {
                            thrIrqPending := true.B
                        }
                        ier := writeByte
                    }
                }
                is(UartReg.IirFcr.U) {
                    fcr := writeByte
                    when(writeByte(1)) {
                        rxReady := false.B
                        overrunError := false.B
                    }
                    when(writeByte(2)) {
                        thrIrqPending := false.B
                        setThrIrqNext := false.B
                    }
                }
                is(UartReg.Lcr.U)    { lcr := writeByte }
                is(UartReg.Mcr.U)    { mcr := writeByte }
                is(UartReg.Scr.U)    { scr := writeByte }
            }
        }.elsewhen(isRead) {
            when(regOffset === UartReg.RbrThrDll.U && !dlab) {
                rxReady := false.B
            }.elsewhen(regOffset === UartReg.IirFcr.U && txIrq) {
                thrIrqPending := false.B
            }.elsewhen(regOffset === UartReg.Lsr.U) {
                overrunError := false.B
            }
        }

        respValid := true.B
        respOpcode := TLOpcode.responseOpcodeForA(io.tl.a.bits.opcode)
        respParam  := TLOpcode.responseParamForA(io.tl.a.bits.opcode, io.tl.a.bits.param)
        respSize   := io.tl.a.bits.size
        respSource := io.tl.a.bits.source
        respData   := Mux(isRead, placeByte(readByte), 0.U)
        respDenied := !isLegal
    }

    // Release TX pulse after one cycle
    when(txValid) {
        txValid := false.B
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

    io.tx_valid := txValid
    io.tx_byte  := txByte
    io.irq      := irqPending
}
