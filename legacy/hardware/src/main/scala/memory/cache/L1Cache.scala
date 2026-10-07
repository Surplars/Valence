package soc.memory.cache

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.memory.CacheReq
import soc.memory.CacheResp

object CacheCmd extends ChiselEnum {
	val Read, Write = Value
}

class CacheCoreIO(params: TLParams) extends Bundle {
    val cpu = new Bundle {
        val req  = Flipped(Decoupled(new CacheReq(params.addrWidth, params.dataWidth)))
        val resp = Decoupled(new CacheResp(params.dataWidth))
    }
    // Whole-cache maintenance. Dirty lines are written back before invalidation,
    // so the same primitive is safe for ICache fence.i and future DCache flushes.
    val invalidate = Flipped(Decoupled(Bool()))
    val bus = new TLBundle(params)
}

trait HasCacheCoreIO { this: Module =>
    val params: TLParams
    val io: CacheCoreIO
}

class L1Cache(val params: TLParams, val nSets: Int = 512, val useTLCoherence: Boolean = true) extends Module with HasCacheCoreIO {
    val io = IO(new CacheCoreIO(params))
    io.bus.e.valid := false.B
    io.bus.e.bits := 0.U.asTypeOf(io.bus.e.bits)

    val offsetBits = log2Ceil(params.dataWidth / 8) // 64位=8字节 -> 3位
    val indexBits  = log2Ceil(nSets)              // 512行 -> 9位
    val tagBits    = params.addrWidth - indexBits - offsetBits

    // 分离地址
    def getIdx(addr: UInt) = addr(offsetBits + indexBits - 1, offsetBits)
    def getTag(addr: UInt) = addr(params.addrWidth - 1, offsetBits + indexBits)

    // SRAM 阵列 (简单起见，使用同步读写的 Mem)
    val validArray = RegInit(VecInit(Seq.fill(nSets)(false.B)))
    val dirtyArray = RegInit(VecInit(Seq.fill(nSets)(false.B)))
    val tagArray   = SyncReadMem(nSets, UInt(tagBits.W))
    val dataArray  = SyncReadMem(nSets, UInt(params.dataWidth.W))

    // 状态机
    val (
        sIdle :: sCompare :: sWriteBackReq :: sWriteBackWait :: sRefillReq :: sRefillWait :: sResp ::
        sFlushRead :: sFlushWriteBackReq :: sFlushWriteBackWait :: sFlushInvalidate ::
        sProbeLookup :: sProbeResp :: Nil
    ) = Enum(13)
    val state = RegInit(sIdle)

    // 锁存 CPU 请求
    val reqReg   = Reg(new CacheReq(params.addrWidth, params.dataWidth))
    val reqIdx   = getIdx(reqReg.addr)
    val reqTag   = getTag(reqReg.addr)
    val victimTagReg  = Reg(UInt(tagBits.W))
    val victimDataReg = Reg(UInt(params.dataWidth.W))
    val flushIdx = RegInit(0.U(indexBits.W))
    val flushTagReg = Reg(UInt(tagBits.W))
    val flushDataReg = Reg(UInt(params.dataWidth.W))
    val probeIdxReg = Reg(UInt(indexBits.W))
    val probeTagReg = Reg(UInt(tagBits.W))
    val probeSizeReg = Reg(UInt(params.sizeBits.W))
    val probeSourceReg = Reg(UInt(params.sourceBits.W))
    val probeAddrReg = Reg(UInt(params.addrWidth.W))
    val probeHitReg = RegInit(false.B)
    val probeDirtyReg = RegInit(false.B)
    val probeDataReg = RegInit(0.U(params.dataWidth.W))
    val hitBufferValid = RegInit(false.B)
    val hitBufferAddr  = RegInit(0.U((params.addrWidth - offsetBits).W))
    val hitBufferData  = RegInit(0.U(params.dataWidth.W))
    
    // 从 SRAM 读出的数据
    val readTag  = tagArray.read(getIdx(io.cpu.req.bits.addr), io.cpu.req.valid && state === sIdle)
    val readData = dataArray.read(getIdx(io.cpu.req.bits.addr), io.cpu.req.valid && state === sIdle)
    val flushReadTag = tagArray.read(flushIdx, state === sFlushRead)
    val flushReadData = dataArray.read(flushIdx, state === sFlushRead)
    val probeReadTag = tagArray.read(getIdx(io.bus.b.bits.address), io.bus.b.fire && useTLCoherence.B)
    val probeReadData = dataArray.read(getIdx(io.bus.b.bits.address), io.bus.b.fire && useTLCoherence.B)

    // Response data is registered so SyncReadMem outputs are never exposed
    // across CPU backpressure cycles.
    val refillReg = RegInit(0.U(params.dataWidth.W))
    val respErrReg = RegInit(false.B)
    private val lineBytes = params.dataWidth / 8
    private val fullMask = ((1 << lineBytes) - 1).U
    private val refillOpcode = if (useTLCoherence) TLOpcode.AcquireBlock else TLOpcode.Get
    private val refillParam = if (useTLCoherence) TLPermissions.nToT else 0.U
    private val writebackOpcode = if (useTLCoherence) TLOpcode.ReleaseData else TLOpcode.PutFullData
    private val writebackParam = if (useTLCoherence) TLPermissions.tToN else 0.U

    val hit = validArray(reqIdx) && (readTag === reqTag)
    val dirty = dirtyArray(reqIdx)

    val reqLineAddr = io.cpu.req.bits.addr(params.addrWidth - 1, offsetBits)
    val reqRegLineAddr = reqReg.addr(params.addrWidth - 1, offsetBits)
    val hitBufferMatchesReq = hitBufferValid && hitBufferAddr === reqRegLineAddr
    val hitBufferMatchesReqIdx = hitBufferValid && hitBufferAddr(indexBits - 1, 0) === reqIdx
    val hitBufferWriteHit =
        state === sIdle && io.cpu.req.valid && io.cpu.req.bits.cmd === CacheCmd.Write &&
            !io.cpu.req.bits.fence && !io.cpu.req.bits.fencei &&
            hitBufferValid && hitBufferAddr === reqLineAddr
    val hitBufferWriteData =
        (io.cpu.req.bits.wdata & FillInterleaved(8, io.cpu.req.bits.mask)) |
            (hitBufferData & ~FillInterleaved(8, io.cpu.req.bits.mask))
    val hitBufferReadHit =
        state === sIdle && io.cpu.req.valid && io.cpu.req.bits.cmd === CacheCmd.Read &&
            !io.cpu.req.bits.fence && !io.cpu.req.bits.fencei &&
            hitBufferValid && hitBufferAddr === reqLineAddr

    // 接口默认值
    val canAcceptProbe = useTLCoherence.B && state === sIdle && !io.invalidate.valid && !io.cpu.req.valid

    io.cpu.req.ready  := state === sIdle && !io.invalidate.valid && !io.bus.b.valid
    val compareHitReadData = WireDefault(readData)
    val compareHitResp = WireDefault(false.B)
    io.cpu.resp.valid := compareHitResp || hitBufferReadHit
    io.cpu.resp.bits.rdata := Mux(hitBufferReadHit, hitBufferData, Mux(compareHitResp, compareHitReadData, refillReg))
    io.cpu.resp.bits.err   := Mux(compareHitResp || hitBufferReadHit, false.B, respErrReg)
    // ready/fire only accepts the maintenance request. Completion is reported
    // later through cpu.resp, after all dirty writebacks and valid-bit clears.
    io.invalidate.ready := state === sIdle

    io.bus.a.valid := false.B
    io.bus.a.bits  := DontCare
    io.bus.b.ready := Mux(useTLCoherence.B, canAcceptProbe, true.B)
    io.bus.c.valid := false.B
    io.bus.c.bits  := DontCare
    io.bus.d.ready := false.B

    switch(state) {
        is(sIdle) {
            when(io.bus.b.fire && useTLCoherence.B) {
                probeIdxReg := getIdx(io.bus.b.bits.address)
                probeTagReg := getTag(io.bus.b.bits.address)
                probeSizeReg := io.bus.b.bits.size
                probeSourceReg := io.bus.b.bits.source
                probeAddrReg := Cat(io.bus.b.bits.address(params.addrWidth - 1, offsetBits), 0.U(offsetBits.W))
                state := sProbeLookup
            }.elsewhen(io.invalidate.fire) {
                respErrReg := false.B
                refillReg := 0.U
                when(io.invalidate.bits) {
                    validArray := VecInit(Seq.fill(nSets)(false.B))
                    dirtyArray := VecInit(Seq.fill(nSets)(false.B))
                    hitBufferValid := false.B
                    state := sResp
                }.otherwise {
                    flushIdx := 0.U
                    state := sFlushRead
                }
            }.elsewhen(io.cpu.req.valid && !hitBufferReadHit) {
                reqReg := io.cpu.req.bits
                respErrReg := false.B
                assert(!io.cpu.req.bits.device && io.cpu.req.bits.cacheable, "L1Cache: device/uncached request must bypass cache")
                assert(!io.cpu.req.bits.atomic, "L1Cache: atomic request not supported yet")
                when(hitBufferWriteHit) {
                    hitBufferData := hitBufferWriteData
                }
                when(io.cpu.req.bits.fence || io.cpu.req.bits.fencei) {
                    refillReg := 0.U
                    when(io.cpu.req.bits.fencei && !io.cpu.req.bits.fence) {
                        validArray := VecInit(Seq.fill(nSets)(false.B))
                        dirtyArray := VecInit(Seq.fill(nSets)(false.B))
                        hitBufferValid := false.B
                        state := sResp
                    }.otherwise {
                        flushIdx := 0.U
                        state := sFlushRead
                    }
                }.otherwise {
                    state := sCompare
                }
            }
        }
        is(sCompare) {
            when(hit) {
                val maskedData = (reqReg.wdata & FillInterleaved(8, reqReg.mask)) | (readData & ~FillInterleaved(8, reqReg.mask))
                val hitRespData = Mux(reqReg.cmd === CacheCmd.Write, maskedData, readData)
                compareHitResp := true.B
                compareHitReadData := hitRespData
                respErrReg := false.B
                when(reqReg.cmd === CacheCmd.Write) {
                    dataArray.write(reqIdx, maskedData)
                    dirtyArray(reqIdx) := true.B
                    // Keep the read bypass buffer coherent with write hits.
                    // A write to a different line leaves the buffered line valid.
                    when(hitBufferMatchesReq) {
                        hitBufferData := maskedData
                    }
                }.otherwise {
                    hitBufferValid := true.B
                    hitBufferAddr := reqRegLineAddr
                    hitBufferData := readData
                }
                when(!io.cpu.resp.ready) {
                    refillReg := hitRespData
                    state := sResp
                }.otherwise {
                    state := sIdle
                }
            }.otherwise {
                when(validArray(reqIdx) && dirty) {
                    victimTagReg  := readTag
                    victimDataReg := readData
                }
                // Miss处理：有脏数据必须先写出，否则直接抓新缓存行
                state := Mux(validArray(reqIdx) && dirty, sWriteBackReq, sRefillReq)
            }
        }
        is(sWriteBackReq) { // 阶段1: 向总线挤出写回请求
            when(useTLCoherence.B) {
                io.bus.c.valid         := true.B
                io.bus.c.bits.opcode   := writebackOpcode
                io.bus.c.bits.param    := writebackParam
                io.bus.c.bits.size     := offsetBits.U
                io.bus.c.bits.source   := 0.U
                io.bus.c.bits.address  := Cat(victimTagReg, reqIdx, 0.U(offsetBits.W))
                io.bus.c.bits.data     := victimDataReg
                io.bus.c.bits.corrupt  := false.B

                when(io.bus.c.fire) {
                    state := sWriteBackWait
                }
            }.otherwise {
                io.bus.a.valid         := true.B
                io.bus.a.bits.opcode   := writebackOpcode
                io.bus.a.bits.param    := writebackParam
                io.bus.a.bits.size     := offsetBits.U
                io.bus.a.bits.source   := 0.U
                io.bus.a.bits.address  := Cat(victimTagReg, reqIdx, 0.U(offsetBits.W))
                io.bus.a.bits.data     := victimDataReg
                io.bus.a.bits.mask     := fullMask
                io.bus.a.bits.corrupt  := false.B

                when(io.bus.a.fire) {
                    state := sWriteBackWait
                }
            }
        }
        is(sWriteBackWait) { // 阶段2: 纯等待内存接收完毕吐出 D 响应
            io.bus.d.ready := true.B
            when(io.bus.d.fire) {
                when(io.bus.d.bits.denied) {
                    respErrReg := true.B
                    refillReg := 0.U
                    state := sResp
                }.otherwise {
                    dirtyArray(reqIdx) := false.B
                    state := sRefillReq
                }
            }
        }
        is(sRefillReq) {   // 阶段3: 向总线扔出读新数片请求
            io.bus.a.valid         := true.B
            io.bus.a.bits.opcode   := refillOpcode
            io.bus.a.bits.param    := refillParam
            io.bus.a.bits.size     := offsetBits.U
            io.bus.a.bits.source   := 0.U
            io.bus.a.bits.address  := Cat(reqTag, reqIdx, 0.U(offsetBits.W))
            io.bus.a.bits.mask     := fullMask // TileLink 读请求掩码需为全1
            io.bus.a.bits.data     := 0.U
            io.bus.a.bits.corrupt  := false.B

            when(io.bus.a.fire) {
                state := sRefillWait
            }
        }
        is(sRefillWait) { // 阶段4: 阻塞挂起拿取真实数据返回
            io.bus.d.ready := true.B
            when(io.bus.d.fire) {
                val isWrite = (reqReg.cmd === CacheCmd.Write)
                val fetchedData = io.bus.d.bits.data
                
                // 如果恰好这是个 Write 请求引起的 Miss，则直接在进缓存前覆盖它
                val maskedData = (reqReg.wdata & FillInterleaved(8, reqReg.mask)) | (fetchedData & ~FillInterleaved(8, reqReg.mask))
                val writeToSram = Mux(isWrite, maskedData, fetchedData)

                respErrReg := io.bus.d.bits.denied
                when(io.bus.d.bits.denied) {
                    refillReg := 0.U
                    when(hitBufferMatchesReqIdx) {
                        hitBufferValid := false.B
                    }
                }.otherwise {
                    validArray(reqIdx) := true.B
                    dirtyArray(reqIdx) := isWrite
                    tagArray.write(reqIdx, reqTag)
                    dataArray.write(reqIdx, writeToSram)
                    when(!isWrite || hitBufferMatchesReq) {
                        hitBufferValid := true.B
                        hitBufferAddr := reqRegLineAddr
                        hitBufferData := writeToSram
                    }.elsewhen(hitBufferMatchesReqIdx) {
                        hitBufferValid := false.B
                    }

                    // 拦截写入寄存器以支持 Cache Bypass 当拍给流水线返回
                    refillReg := writeToSram
                }
                state := sResp
            }
        }
        is(sResp) { // 阶段5: Miss补偿响应期
            io.cpu.resp.valid := true.B
            // rdata 在顶层被上面 Mux 接走了 refillReg
            when(io.cpu.resp.ready) {
                state := sIdle
            }
        }
        is(sProbeLookup) {
            val probeHit = validArray(probeIdxReg) && probeReadTag === probeTagReg
            probeHitReg := probeHit
            probeDirtyReg := probeHit && dirtyArray(probeIdxReg)
            probeDataReg := probeReadData
            state := sProbeResp
        }
        is(sProbeResp) {
            io.bus.c.valid         := true.B
            io.bus.c.bits.opcode   := Mux(probeDirtyReg, TLOpcode.ProbeAckData, TLOpcode.ProbeAck)
            io.bus.c.bits.param    := TLPermissions.toN
            io.bus.c.bits.size     := probeSizeReg
            io.bus.c.bits.source   := probeSourceReg
            io.bus.c.bits.address  := probeAddrReg
            io.bus.c.bits.data     := Mux(probeDirtyReg, probeDataReg, 0.U)
            io.bus.c.bits.corrupt  := false.B

            when(io.bus.c.fire) {
                when(probeHitReg) {
                    validArray(probeIdxReg) := false.B
                    dirtyArray(probeIdxReg) := false.B
                    hitBufferValid := false.B
                }
                state := sIdle
            }
        }
        is(sFlushRead) {
            state := sFlushInvalidate
        }
        is(sFlushInvalidate) {
            when(validArray(flushIdx) && dirtyArray(flushIdx)) {
                flushTagReg := flushReadTag
                flushDataReg := flushReadData
                state := sFlushWriteBackReq
            }.otherwise {
                validArray(flushIdx) := false.B
                dirtyArray(flushIdx) := false.B
                hitBufferValid := false.B
                when(flushIdx === (nSets - 1).U) {
                    state := sResp
                }.otherwise {
                    flushIdx := flushIdx + 1.U
                    state := sFlushRead
                }
            }
        }
        is(sFlushWriteBackReq) {
            when(useTLCoherence.B) {
                io.bus.c.valid         := true.B
                io.bus.c.bits.opcode   := writebackOpcode
                io.bus.c.bits.param    := writebackParam
                io.bus.c.bits.size     := offsetBits.U
                io.bus.c.bits.source   := 0.U
                io.bus.c.bits.address  := Cat(flushTagReg, flushIdx, 0.U(offsetBits.W))
                io.bus.c.bits.data     := flushDataReg
                io.bus.c.bits.corrupt  := false.B

                when(io.bus.c.fire) {
                    state := sFlushWriteBackWait
                }
            }.otherwise {
                io.bus.a.valid         := true.B
                io.bus.a.bits.opcode   := writebackOpcode
                io.bus.a.bits.param    := writebackParam
                io.bus.a.bits.size     := offsetBits.U
                io.bus.a.bits.source   := 0.U
                io.bus.a.bits.address  := Cat(flushTagReg, flushIdx, 0.U(offsetBits.W))
                io.bus.a.bits.data     := flushDataReg
                io.bus.a.bits.mask     := fullMask
                io.bus.a.bits.corrupt  := false.B

                when(io.bus.a.fire) {
                    state := sFlushWriteBackWait
                }
            }
        }
        is(sFlushWriteBackWait) {
            io.bus.d.ready := true.B
            when(io.bus.d.fire) {
                respErrReg := io.bus.d.bits.denied
                when(!io.bus.d.bits.denied) {
                    validArray(flushIdx) := false.B
                    dirtyArray(flushIdx) := false.B
                }
                when(io.bus.d.bits.denied || flushIdx === (nSets - 1).U) {
                    state := sResp
                }.otherwise {
                    flushIdx := flushIdx + 1.U
                    state := sFlushRead
                }
            }
        }
    }
}
