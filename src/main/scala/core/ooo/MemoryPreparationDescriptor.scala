package soc.core.ooo

import chisel3._
import chisel3.util._

/** Payload only: no permission, translation result, issue credit or exception authority. */
class MemoryPreparationDescriptor(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val source1 = UInt(p.physBits.W)
    val source2 = UInt(p.physBits.W)
    val immediate = UInt(64.W)
    val size = UInt(2.W)
    val saved = Bool()
    val savedAddress = UInt(64.W)
    val savedData = UInt(64.W)
}

/** Two speculative reservations, with replacement rather than FIFO head-of-line blocking.
  * Owner inputs are qualified by the caller's full token. This module owns no state.
  * Fresh ranking never depends on issued or same-cycle recovery. The caller applies
  * kill/context cancellation after selection and before state capture.
  */
class MemoryPreparationDescriptorSelector(p: OooParams, val earlyLoads: Boolean = false) extends Module {
    require(p.robEntries == 16)
    val io = IO(new Bundle {
        val eligible = Input(UInt(p.robEntries.W))
        val waitingLoads = if (earlyLoads) Some(Input(UInt(p.robEntries.W))) else None
        val enabled = Input(Bool())
        val head = Input(UInt(p.robBits.W))
        val headMask = Input(UInt(p.robEntries.W))
        val resident = Flipped(Valid(UInt(p.robBits.W)))
        val descriptor = Flipped(Valid(UInt(p.robBits.W)))
        val issued = Input(Bool())
        val freshOwner = Output(UInt(p.robEntries.W))
        val freshIndex = Output(UInt(p.robBits.W))
        val freshValid = Output(Bool())
        val capture = Output(Bool())
        val transfer = Output(Bool())
        val keepResident = Output(Bool())
        val keepDescriptor = Output(Bool())
        val nextDescriptorValid = if (earlyLoads) Some(Output(Bool())) else None
    })
    val residentOwner = Mux(io.resident.valid, UIntToOH(io.resident.bits, p.robEntries), 0.U)
    val descriptorOwner = Mux(io.descriptor.valid, UIntToOH(io.descriptor.bits, p.robEntries), 0.U)
    val pool = io.eligible & Fill(p.robEntries, io.enabled)
    val residentEligible = (pool & residentOwner).orR
    val descriptorEligible = (pool & descriptorOwner).orR
    val fresh = Module(new CircularIssueSelector(p, parallelRanks = true, predecodedHead = true))
    val readyFresh = pool & ~residentOwner & ~descriptorOwner
    // Waiting loads use idle metadata capacity only. They never enter the ready
    // pool or the store fallback/presence law, and never address a PRF port here.
    val waiting = io.waitingLoads.getOrElse(0.U(p.robEntries.W))
    val waitingFresh = waiting & ~residentOwner & ~descriptorOwner
    fresh.io.eligible := (if (earlyLoads) Mux(readyFresh.orR, readyFresh, waitingFresh) else readyFresh)
    fresh.io.head := io.head
    fresh.io.headMask.get := io.headMask
    io.freshOwner := fresh.io.first
    io.freshIndex := fresh.io.firstIndex
    io.freshValid := fresh.io.firstValid
    val freshAge = fresh.io.firstIndex - io.head
    val descriptorAge = io.descriptor.bits - io.head
    val residentAge = io.resident.bits - io.head
    val descriptorWaiting = (waiting & descriptorOwner).orR
    val replaceDescriptor = fresh.io.firstValid && (if (earlyLoads) {
        (!descriptorEligible && !descriptorWaiting) ||
            (descriptorEligible && readyFresh.orR && freshAge < descriptorAge) ||
            (descriptorWaiting && (readyFresh.orR || freshAge < descriptorAge))
    } else !descriptorEligible || freshAge < descriptorAge)
    val residentTransferCondition = !residentEligible || io.issued || descriptorAge < residentAge
    io.transfer := descriptorEligible && !replaceDescriptor && residentTransferCondition
    io.capture := fresh.io.firstValid && (replaceDescriptor || io.transfer)
    io.keepDescriptor := (descriptorEligible || descriptorWaiting) && !io.transfer && !io.capture
    io.keepResident := residentEligible && !io.issued && !io.transfer
    if (earlyLoads) {
        // A fresh owner always leaves Q occupied, whether retained or replaced.
        // With no fresh owner, replacement is impossible. Keep fresh rank/age
        // out of the valid-data cone; payload capture keeps the original law.
        io.nextDescriptorValid.get := fresh.io.firstValid ||
            ((descriptorEligible || descriptorWaiting) && !(descriptorEligible && residentTransferCondition))
        assert(io.nextDescriptorValid.get === (io.capture || io.keepDescriptor),
            "factored descriptor validity must preserve the selector transition")
        assert((waiting & pool) === 0.U, "waiting load pool must be disjoint from ready preparation")
        when(descriptorWaiting) { assert(!io.transfer, "waiting descriptor cannot capture operands") }
        when(descriptorEligible && !readyFresh.orR) {
            assert(!io.capture || io.transfer, "waiting fresh load cannot replace ready descriptor")
        }
    }
    assert(!(io.transfer && io.keepDescriptor))
    assert((io.freshOwner & (residentOwner | descriptorOwner)) === 0.U)
}

/** Assertion boundary reused by actual source owners and independent negative witnesses. */
class PreparationSourceLifetimeCheck(allowPendingLoad: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val active = Input(Bool())
        val mappingMatches = Input(Bool())
        val inRange = Input(Bool())
        val ready = Input(Bool())
        val reserved = Input(Bool())
        val written = Input(Bool())
        val waitingLoad = if (allowPendingLoad) Some(Input(Bool())) else None
        val acceptedProducerWrite = if (allowPendingLoad) Some(Input(Bool())) else None
    })
    when(io.active) {
        assert(io.mappingMatches, "preparation source mapping changed")
        assert(io.inRange, "preparation source outside physical capacity")
        assert(!io.reserved, "preparation source illegally reserved again")
        if (allowPendingLoad) {
            when(io.waitingLoad.get) {
                assert(!io.ready, "waiting preparation source must be registered unready")
                assert(!io.written || io.acceptedProducerWrite.get,
                    "waiting preparation source write must be its accepted producer wake")
            }.otherwise {
                assert(io.ready, "preparation source lost registered readiness")
                assert(!io.written, "preparation source illegally written again")
            }
        } else {
            assert(io.ready, "preparation source lost registered readiness")
            assert(!io.written, "preparation source illegally written again")
        }
    }
}
