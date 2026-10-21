`timescale 1ns/1ps
module tb;
    `include "signals.svh"
    integer cycles = 0;
    integer accepted = 0, issued = 0, consumed = 0;
    integer accepts_by_id [0:1][0:63];
    integer issues_by_id [0:1][0:63];
    reg [63:0] owners_id [0:255];
    reg [63:0] owners_address [0:255];
    reg held = 0;
    reg [63:0] held_id, held_address;
    integer negative_ledger, negative_payload, negative_pending;
    integer n, f, ident, before_count, before_issued;
    reg [63:0] value;
    reg [63:0] expected_machine;

    task check(input bit condition, input string reason);
        if (!condition) $fatal(1, "%s cycle=%0d accepted=%0d issued=%0d consumed=%0d", reason, cycles,
            accepted, issued, consumed);
    endtask

    // Independent accepted-owner FIFO and counters observe actual interface FIRE,
    // not internal APLIC/IMSIC state. Consumption is the source-side terminal edge.
    always @(posedge clock) begin
        cycles = cycles + 1;
        if (reset) begin
            accepted = 0; issued = 0; consumed = 0; held = 0;
            for (integer ff = 0; ff < 2; ff = ff + 1)
                for (integer ii = 0; ii < 64; ii = ii + 1) begin
                    accepts_by_id[ff][ii] = 0; issues_by_id[ff][ii] = 0;
                end
        end else begin
            check(io_idle === (accepted == consumed), "owner idle oracle mismatch");
            if (negative_ledger && accepted > consumed)
                check(1'b0, "negative owner ledger oracle mismatch");
            check(!(io_stop && io_accepted), "admission crossed stop boundary");
            if (held) check(io_destinationValid && io_destinationIdentity === held_id &&
                io_destinationAddress === held_address, "advertised MSI request withdrawn or changed");
            held = io_destinationValid && !io_destinationReady;
            held_id = io_destinationIdentity; held_address = io_destinationAddress;
            if (io_accepted) begin
                check(accepted - consumed < 2, "MSI admission credit overflow");
                check(accepted < 256, "test FIFO capacity exceeded");
                owners_id[accepted] = io_acceptedIdentity;
                owners_address[accepted] = io_acceptedAddress;
                f = io_acceptedAddress == 64'h28000000;
                check(io_acceptedAddress == 64'h24000000 || io_acceptedAddress == 64'h28000000,
                    "non-IMSIC request address");
                check(io_acceptedIdentity > 0 && io_acceptedIdentity < 64, "invalid APLIC identity");
                accepts_by_id[f][io_acceptedIdentity] = accepts_by_id[f][io_acceptedIdentity] + 1;
                accepted = accepted + 1;
            end
            if (io_issued) begin
                check(issued < accepted, "MSI issue without admitted owner");
                check(io_destinationIdentity === (owners_id[issued] ^ (negative_payload ? 64'd1 : 64'd0)) &&
                    io_destinationAddress === owners_address[issued], "MSI ordered payload oracle mismatch");
                f = io_destinationAddress == 64'h28000000;
                issues_by_id[f][io_destinationIdentity] = issues_by_id[f][io_destinationIdentity] + 1;
                issued = issued + 1;
            end
            if (io_consumed) begin
                check(consumed < issued, "MSI reply before issued owner");
                consumed = consumed + 1;
            end
            check(consumed <= issued && issued <= accepted && accepted - consumed <= 2,
                "MSI independent bounded ledger mismatch");
            check(!io_msiError, "real APLIC observed an MSI error");
        end
    end

    task step;
        begin #4; clock = 1; #1; clock = 0; #5; end
    endtask
    task wait_cycles(input integer count);
        for (integer k = 0; k < count; k = k + 1) step();
    endtask
    task reset_all;
        begin
            reset = 1; io_sources = 0; io_stop = 0;
            io_allowRequest = 1; io_allowReply = 1; io_allowTerminal = 1;
            io_machineRegisters_request_valid = 0; io_supervisorRegisters_request_valid = 0;
            io_machineRegisters_response_ready = 0; io_supervisorRegisters_response_ready = 0;
            io_csrRequest_valid = 0; io_csrResponse_ready = 0;
            wait_cycles(3); reset = 0; wait_cycles(3);
            check(io_idle && !io_destinationValid && !io_sourceReplyValid, "coordinated reset retained owners");
        end
    endtask

    task aplic_access(input bit supervisor, input bit write_access, input integer offset,
        input reg [63:0] data, output reg [63:0] result);
        integer timeout;
        begin
            if (supervisor) begin
                io_supervisorRegisters_request_bits_address = 64'h0c004000 + offset;
                io_supervisorRegisters_request_bits_write = write_access;
                io_supervisorRegisters_request_bits_size = 2;
                io_supervisorRegisters_request_bits_data = data;
                io_supervisorRegisters_request_bits_byteEnable = 15;
                io_supervisorRegisters_request_valid = 1;
            end else begin
                io_machineRegisters_request_bits_address = 64'h0c000000 + offset;
                io_machineRegisters_request_bits_write = write_access;
                io_machineRegisters_request_bits_size = 2;
                io_machineRegisters_request_bits_data = data;
                io_machineRegisters_request_bits_byteEnable = 15;
                io_machineRegisters_request_valid = 1;
            end
            #1; timeout = 0;
            while (!(supervisor ? io_supervisorRegisters_request_ready : io_machineRegisters_request_ready)) begin
                step(); timeout = timeout + 1; check(timeout < 100, "APLIC MMIO request timeout");
            end
            step();
            if (supervisor) io_supervisorRegisters_request_valid = 0;
            else io_machineRegisters_request_valid = 0;
            #1; timeout = 0;
            while (!(supervisor ? io_supervisorRegisters_response_valid : io_machineRegisters_response_valid)) begin
                step(); timeout = timeout + 1; check(timeout < 100, "APLIC MMIO response timeout");
            end
            result = supervisor ? io_supervisorRegisters_response_bits_data : io_machineRegisters_response_bits_data;
            check(!(supervisor ? io_supervisorRegisters_response_bits_error : io_machineRegisters_response_bits_error),
                "APLIC MMIO error");
            if (supervisor) io_supervisorRegisters_response_ready = 1;
            else io_machineRegisters_response_ready = 1;
            step(); io_machineRegisters_response_ready = 0; io_supervisorRegisters_response_ready = 0;
        end
    endtask
    task wr(input bit supervisor, input integer offset, input reg [63:0] data);
        reg [63:0] unused;
        aplic_access(supervisor, 1, offset, data, unused);
    endtask
    task csr(input integer file_index, input integer selector, input bit topei, input integer operation,
        input reg [63:0] data, output reg [63:0] result);
        integer timeout;
        begin
            io_csrRequest_bits_file = file_index; io_csrRequest_bits_selector = selector;
            io_csrRequest_bits_topei = topei; io_csrRequest_bits_operation = operation;
            io_csrRequest_bits_data = data; io_csrRequest_valid = 1;
            #1; timeout = 0;
            while (!io_csrRequest_ready) begin step(); timeout = timeout + 1;
                check(timeout < 100, "IMSIC CSR request timeout"); end
            step(); io_csrRequest_valid = 0; #1; timeout = 0;
            while (!io_csrResponse_valid) begin step(); timeout = timeout + 1;
                check(timeout < 100, "IMSIC CSR response timeout"); end
            result = io_csrResponse_bits_data;
            check(!io_csrResponse_bits_error, "IMSIC CSR error");
            // Exercise the independent CSR observer's response backpressure too.
            wait_cycles(2);
            check(io_csrResponse_valid && io_csrResponse_bits_data === result,
                "IMSIC CSR reply changed under backpressure");
            io_csrResponse_ready = 1; step(); io_csrResponse_ready = 0;
        end
    endtask
    task pending(input integer file_index, input reg [63:0] expected);
        reg [63:0] observed;
        begin
            csr(file_index, 'h80, 0, 0, 0, observed);
            check(observed === (expected ^ (negative_pending ? 64'h8000000000000000 : 64'd0)),
                "IMSIC architectural pending oracle mismatch");
        end
    endtask
    task claim(input integer file_index, input integer expected);
        reg [63:0] observed;
        begin
            csr(file_index, 0, 1, 1, 0, observed);
            check(observed === ((64'(expected) << 16) | 64'(expected)),
                "IMSIC architectural claim oracle mismatch");
        end
    endtask
    task configure;
        reg [63:0] unused;
        begin
            for (integer ss = 1; ss <= 8; ss = ss + 1) begin
                wr(0, ss * 4, ss == 4 ? 'h400 : (ss == 3 ? 6 : 4));
                if (ss != 4) begin
                    wr(0, 'h3000 + ss * 4, 10 + ss);
                    wr(0, 'h1edc, ss);
                end
            end
            wr(1, 4 * 4, 4); wr(1, 'h3010, 21); wr(1, 'h1edc, 4);
            for (integer ff = 0; ff < 2; ff = ff + 1) begin
                csr(ff, 'hc0, 0, 1, 64'hfffffffffffffffe, unused);
                csr(ff, 'h70, 0, 1, 1, unused);
            end
            wr(0, 0, 'h100); wr(1, 0, 'h100);
        end
    endtask
    task drain(input integer expected_total);
        integer timeout;
        begin
            timeout = 0;
            while (consumed < expected_total || !io_idle) begin
                step(); timeout = timeout + 1; check(timeout < 300, "accepted owner drain timeout");
            end
            wait_cycles(15);
            check(accepted == expected_total && issued == expected_total && consumed == expected_total && io_idle,
                "unexpected duplicate or missing MSI episode");
        end
    endtask

    initial begin
        `include "initialize.svh"
        negative_ledger = $test$plusargs("negative_ledger");
        negative_payload = $test$plusargs("negative_payload");
        negative_pending = $test$plusargs("negative_pending");
        reset_all(); configure();
        // An accepted request has been advertised but not issued before STOP.
        io_allowRequest = 0; io_sources = 1; step(); io_sources = 0; wait_cycles(7);
        check(accepted == 1 && issued == 0 && !io_idle && io_destinationValid,
            "pre-stop advertised owner missing");
        io_stop = 1;
        // Sources 2/3/4 occur after hold. Keep source 3 level-high throughout.
        io_sources = 'h0e; step(); io_sources = 'h04; wait_cycles(8);
        io_sources = 'hf4; step(); io_sources = 'h04; wait_cycles(8);
        check(accepted == 1 && io_upstreamPending, "held unaccepted MSI lost or admitted");
        aplic_access(0, 0, 'h1c00, 0, value);
        check((value & 'h1e0) != 0, "real APLIC pending bitmap lost blocked source events");
        io_allowReply = 0; io_allowRequest = 1; wait_cycles(8);
        check(issued == 1 && consumed == 0 && !io_idle, "held issued owner did not remain live");
        pending(0, 64'd1 << 11); pending(1, 0);
        io_allowTerminal = 0; io_allowReply = 1; wait_cycles(8);
        check(io_sourceReplyValid && !io_idle && consumed == 0, "terminal response backpressure lost owner");
        io_allowTerminal = 1; drain(1);
        check(io_stop && io_upstreamPending && io_idle, "unaccepted APLIC event incorrectly blocks idle");
        claim(0, 11); claim(0, 0); pending(0, 0);
        // A canceled stop is just resume: one reopened acceptance then another
        // stop cannot revoke the newly admitted owner or its stable egress.
        io_allowRequest = 0; before_count = accepted; io_stop = 0; step(); io_stop = 1;
        wait_cycles(5); check(accepted == before_count + 1 && !io_idle,
            "resume/stop boundary did not capture exactly one owner");
        io_allowRequest = 1; drain(2); io_stop = 0; drain(8);
        expected_machine = (64'd1 << 12) | (64'd1 << 13) | (64'd1 << 15) |
            (64'd1 << 16) | (64'd1 << 17) | (64'd1 << 18);
        pending(0, expected_machine); pending(1, 64'd1 << 21);
        claim(0, 12); claim(0, 13); claim(0, 15); claim(0, 16); claim(0, 17); claim(0, 18); claim(0, 0);
        claim(1, 21); claim(1, 0); pending(0, 0); pending(1, 0);
        wait_cycles(40); check(accepted == 8, "persistent high level generated duplicate episode");
        for (integer ss = 1; ss <= 8; ss = ss + 1)
            if (ss != 4) check(issues_by_id[0][10 + ss] == 1, "machine source exactly-once oracle mismatch");
        check(issues_by_id[1][21] == 1, "delegated supervisor exactly-once oracle mismatch");
        // Re-arm level source and add an edge while stopped, then repeatedly
        // resume and cancel the decision without resetting interrupt state.
        io_stop = 1; io_sources = 0; step(); io_sources = 5; step(); io_sources = 4;
        wait_cycles(10); check(io_idle && accepted == 8 && io_upstreamPending,
            "held rearmed episodes incorrectly counted as admitted");
        for (integer rr = 0; rr < 6; rr = rr + 1) begin io_stop = 0; step(); io_stop = 1; wait_cycles(3); end
        io_stop = 0; drain(10); pending(0, (64'd1 << 11) | (64'd1 << 13));
        claim(0, 11); claim(0, 13); claim(0, 0);
        // Fill both admission credits with downstream and terminal pressure.
        io_sources = 0; step(); io_allowTerminal = 0; io_sources = 'hff; step(); io_sources = 4;
        wait_cycles(30); check(accepted - consumed == 2 && io_upstreamPending,
            "bounded admission credits were not exercised");
        io_stop = 1; before_count = accepted; wait_cycles(8);
        check(accepted == before_count && !io_idle, "held saturated owner ledger changed");
        io_allowTerminal = 1; drain(before_count);
        check(io_idle && io_upstreamPending, "held credit drain lost upstream pending work");
        io_stop = 0; drain(18);
        pending(0, expected_machine | (64'd1 << 11)); pending(1, 64'd1 << 21);
        claim(0, 11); claim(0, 12); claim(0, 13); claim(0, 15); claim(0, 16); claim(0, 17); claim(0, 18);
        claim(0, 0); claim(1, 21); claim(1, 0);
        // Coordinated reset while one request is captured and other events live
        // starts a new empty epoch. No old request/reply may escape afterward.
        io_allowRequest = 0; io_sources = 0; step(); io_sources = 3; step(); io_sources = 0;
        wait_cycles(8); check(!io_idle && io_destinationValid, "reset-live fixture lacked owner");
        reset_all(); wait_cycles(15); check(accepted == 0 && issued == 0 && consumed == 0,
            "coordinated reset leaked old epoch");
        pending(0, 0); pending(1, 0); configure();
        io_sources = 8; step(); io_sources = 0; drain(1);
        pending(0, 0); pending(1, 64'd1 << 21); claim(1, 21); claim(1, 0);
        check(issues_by_id[1][21] == 1, "cold reset supervisor-first transaction failed");
        // Reset an issued owner whose actual IMSIC reply is terminal-stalled.
        io_allowTerminal = 0; io_sources = 1; step(); io_sources = 0; wait_cycles(12);
        check(issued == 2 && consumed == 1 && io_sourceReplyValid && !io_idle,
            "reset-issued fixture lacked terminal-stalled owner");
        reset_all(); pending(0, 0); pending(1, 0); wait_cycles(12);
        check(accepted == 0 && issued == 0 && consumed == 0 && io_idle,
            "coordinated reset retained issued/reply owner");
        $display("MSI_ADMISSION_REAL_APLIC_IMSIC_PASS cycles=%0d", cycles); $finish;
    end
endmodule
