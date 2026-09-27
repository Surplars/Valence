package soc.debug

import chisel3._
import chisel3.util._

class JtagIO extends Bundle {
    val tms = Input(Bool())
    val tck = Input(Bool())
    val tdi = Input(Bool())
    val tdo = Output(Bool())
}

object JtagInstruction {
    def idcode(irLen: Int): UInt = 1.U(irLen.W)
    def dtmcs(irLen: Int): UInt = 0x10.U(irLen.W)
    def dmi(irLen: Int): UInt = 0x11.U(irLen.W)
    def bypass(irLen: Int): UInt = ((BigInt(1) << irLen) - 1).U(irLen.W)
}

class JtagTap(val irLen: Int = 5, val drLen: Int = 64, val idcode: BigInt = 0x10e31913L, val dmiAddrBits: Int = 7) extends Module {
    require(drLen >= dmiAddrBits + 34, "JTAG DMI data register must fit addr + data + op")

    val io = IO(new Bundle {
        val jtag = new JtagIO

        val dr_in  = Input(UInt(drLen.W))
        val dr_out = Output(UInt(drLen.W))

        val ir_out   = Output(UInt(irLen.W))
        val sel_inst = Output(UInt(irLen.W))

        val capture_dr = Output(Bool())
        val shift_dr   = Output(Bool())
        val update_dr  = Output(Bool())
        val capture_ir = Output(Bool())
        val shift_ir   = Output(Bool())
        val update_ir  = Output(Bool())
    })

    val (
        testLogicReset :: runTestIdle :: selectDRScan :: captureDR :: shiftDR :: exit1DR ::
        pauseDR :: exit2DR :: updateDR :: selectIRScan :: captureIR :: shiftIR ::
        exit1IR :: pauseIR :: exit2IR :: updateIR :: Nil
    ) = Enum(16)

    val state = RegInit(testLogicReset)
    val instr = RegInit(JtagInstruction.idcode(irLen))
    val irShift = RegInit(JtagInstruction.idcode(irLen))
    val drShift = RegInit(0.U(drLen.W))
    val drUpdate = RegInit(0.U(drLen.W))
    val bypassBit = RegInit(false.B)

    // This first-stage TAP is synchronous to the SoC clock and detects TCK
    // edges. A production debug port can replace this with a true TCK clock
    // domain plus CDC around DMI without changing the external pin contract.
    val tckPrev = RegNext(io.jtag.tck, false.B)
    val tckRise = io.jtag.tck && !tckPrev

    def nextState(cur: UInt, tms: Bool): UInt = {
        MuxLookup(cur, testLogicReset)(
            Seq(
                testLogicReset -> Mux(tms, testLogicReset, runTestIdle),
                runTestIdle    -> Mux(tms, selectDRScan, runTestIdle),
                selectDRScan   -> Mux(tms, selectIRScan, captureDR),
                captureDR      -> Mux(tms, exit1DR, shiftDR),
                shiftDR        -> Mux(tms, exit1DR, shiftDR),
                exit1DR        -> Mux(tms, updateDR, pauseDR),
                pauseDR        -> Mux(tms, exit2DR, pauseDR),
                exit2DR        -> Mux(tms, updateDR, shiftDR),
                updateDR       -> Mux(tms, selectDRScan, runTestIdle),
                selectIRScan   -> Mux(tms, testLogicReset, captureIR),
                captureIR      -> Mux(tms, exit1IR, shiftIR),
                shiftIR        -> Mux(tms, exit1IR, shiftIR),
                exit1IR        -> Mux(tms, updateIR, pauseIR),
                pauseIR        -> Mux(tms, exit2IR, pauseIR),
                exit2IR        -> Mux(tms, updateIR, shiftIR),
                updateIR       -> Mux(tms, selectDRScan, runTestIdle)
            )
        )
    }

    val stateNext = nextState(state, io.jtag.tms)
    val idcodeData = idcode.U(drLen.W)
    val dtmcsData = (((1 << 12) | (dmiAddrBits << 4) | 1) & 0xffffffffL).U(drLen.W)
    val bypassSelected = instr === JtagInstruction.bypass(irLen)
    val idcodeSelected = instr === JtagInstruction.idcode(irLen)
    val dtmcsSelected = instr === JtagInstruction.dtmcs(irLen)
    val dmiSelected = instr === JtagInstruction.dmi(irLen)

    when(tckRise) {
        state := stateNext
        when(stateNext === testLogicReset) {
            instr := JtagInstruction.idcode(irLen)
        }

        switch(state) {
            is(captureIR) {
                irShift := Cat(0.U((irLen - 2).W), "b01".U(2.W))
            }
            is(shiftIR) {
                irShift := Cat(io.jtag.tdi, irShift(irLen - 1, 1))
            }
            is(updateIR) {
                instr := irShift
            }
            is(captureDR) {
                when(bypassSelected) {
                    bypassBit := false.B
                    drShift := 0.U
                }.elsewhen(idcodeSelected) {
                    drShift := idcodeData
                }.elsewhen(dtmcsSelected) {
                    drShift := dtmcsData
                }.otherwise {
                    drShift := io.dr_in
                }
            }
            is(shiftDR) {
                when(bypassSelected) {
                    bypassBit := io.jtag.tdi
                }.elsewhen(dtmcsSelected) {
                    drShift := Cat(0.U((drLen - 32).W), io.jtag.tdi, drShift(31, 1))
                }.elsewhen(idcodeSelected) {
                    drShift := Cat(0.U((drLen - 32).W), io.jtag.tdi, drShift(31, 1))
                }.elsewhen(dmiSelected) {
                    drShift := Cat(0.U((drLen - dmiAddrBits - 34).W), io.jtag.tdi, drShift(dmiAddrBits + 33, 1))
                }.otherwise {
                    drShift := Cat(io.jtag.tdi, drShift(drLen - 1, 1))
                }
            }
            is(updateDR) {
                when(dmiSelected) {
                    drUpdate := drShift
                }
            }
        }
    }

    io.jtag.tdo := Mux(
        state === shiftIR,
        irShift(0),
        Mux(state === shiftDR, Mux(bypassSelected, bypassBit, drShift(0)), false.B)
    )
    io.dr_out := drUpdate
    io.ir_out := instr
    io.sel_inst := instr
    io.capture_dr := state === captureDR
    io.shift_dr := state === shiftDR
    io.update_dr := tckRise && state === updateDR
    io.capture_ir := state === captureIR
    io.shift_ir := state === shiftIR
    io.update_ir := tckRise && state === updateIR
}
