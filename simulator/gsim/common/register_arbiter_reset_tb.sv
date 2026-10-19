`timescale 1ns/1ps
// Independent external-port scoreboard. No DUT hierarchy reads, forces, binds,
// random initialization, generated-RTL edits, or implementation-state oracle.
module register_arbiter_reset_tb;
    reg clock = 0;
    reg reset = 0;
    reg [1:0] req_valid = 0;
    wire [1:0] req_ready;
    reg [63:0] req_address [0:1];
    reg [63:0] req_data [0:1];
    reg [1:0] rsp_ready = 0;
    wire [1:0] rsp_valid;
    wire [63:0] rsp_data [0:1];
    wire [1:0] rsp_error;
    wire down_req_valid, down_req_write;
    reg down_req_ready = 0;
    wire [63:0] down_req_address, down_req_data;
    wire [2:0] down_req_size;
    wire [7:0] down_req_byte_enable;
    reg down_rsp_valid = 0;
    wire down_rsp_ready;
    reg [63:0] down_rsp_data = 0;
    reg down_rsp_error = 0;

    TwoMasterRegisterArbiter dut (
        .clock(clock), .reset(reset),
        .io_masters_0_request_valid(req_valid[0]), .io_masters_0_request_ready(req_ready[0]),
        .io_masters_0_request_bits_address(req_address[0]), .io_masters_0_request_bits_data(req_data[0]),
        .io_masters_0_request_bits_write(1'b1), .io_masters_0_request_bits_size(3'd2),
        .io_masters_0_request_bits_byteEnable(8'h0f),
        .io_masters_1_request_valid(req_valid[1]), .io_masters_1_request_ready(req_ready[1]),
        .io_masters_1_request_bits_address(req_address[1]), .io_masters_1_request_bits_data(req_data[1]),
        .io_masters_1_request_bits_write(1'b1), .io_masters_1_request_bits_size(3'd2),
        .io_masters_1_request_bits_byteEnable(8'h0f),
        .io_masters_0_response_valid(rsp_valid[0]), .io_masters_0_response_ready(rsp_ready[0]),
        .io_masters_0_response_bits_data(rsp_data[0]), .io_masters_0_response_bits_error(rsp_error[0]),
        .io_masters_1_response_valid(rsp_valid[1]), .io_masters_1_response_ready(rsp_ready[1]),
        .io_masters_1_response_bits_data(rsp_data[1]), .io_masters_1_response_bits_error(rsp_error[1]),
        .io_downstream_request_valid(down_req_valid), .io_downstream_request_ready(down_req_ready),
        .io_downstream_request_bits_address(down_req_address),
        .io_downstream_request_bits_data(down_req_data), .io_downstream_request_bits_write(down_req_write),
        .io_downstream_request_bits_size(down_req_size),
        .io_downstream_request_bits_byteEnable(down_req_byte_enable),
        .io_downstream_response_valid(down_rsp_valid), .io_downstream_response_ready(down_rsp_ready),
        .io_downstream_response_bits_data(down_rsp_data),
        .io_downstream_response_bits_error(down_rsp_error)
    );

    integer owners [0:255];
    reg [63:0] identities [0:255];
    integer head = 0, tail = 0, count = 0;
    integer cycles = 0, accepted = 0, returned = 0, discarded = 0;
    integer last_accept = -1, streak = 0, max_streak = 0;
    integer stalls = 0, response_stalls = 0, epochs = 0;
    integer i, n, owner, before_accept, before_return;
    integer per_owner [0:1];
    reg previous_stall = 0;
    reg [63:0] held_address, held_data;
    reg [1:0] accepts;

    task tick;
        integer k;
        integer selected;
        begin
            // Sample settled combinational signals before the real rising edge.
            #4;
            cycles = cycles + 1;
            if (cycles > 500) $fatal(1, "ORACLE_TIMEOUT");
            for (k=0; k<2; k=k+1)
                if (req_valid[k] && req_ready[k] !== 1'b0 && req_ready[k] !== 1'b1)
                    $fatal(1, "ORACLE_UNKNOWN_REQUEST_READY client=%0d cycle=%0d downstream_valid=%b downstream_ready=%b", k, cycles, down_req_valid, down_req_ready);
            if (down_req_valid !== 1'b0 && down_req_valid !== 1'b1)
                $fatal(1, "ORACLE_UNKNOWN_DOWNSTREAM_VALID cycle=%0d", cycles);
            accepts = req_valid & req_ready;
            if (accepts == 2'b11 || ((|accepts) !== (down_req_valid && down_req_ready)))
                $fatal(1, "ORACLE_ACCEPTANCE_MISMATCH inputs=%b output=%b", accepts, down_req_valid && down_req_ready);
            if (previous_stall && (!down_req_valid || down_req_address !== held_address || down_req_data !== held_data))
                $fatal(1, "ORACLE_LOCKED_REQUEST_CHANGED");
            previous_stall = down_req_valid && !down_req_ready;
            held_address = down_req_address;
            held_data = down_req_data;
            if (previous_stall) stalls = stalls + 1;

            if (down_rsp_valid) begin
                if (count == 0) $fatal(1, "ORACLE_RESPONSE_WITHOUT_ACCEPTANCE");
                selected = owners[head];
                if (rsp_valid !== (selected == 0 ? 2'b01 : 2'b10))
                    $fatal(1, "ORACLE_RESPONSE_OWNER expected=%0d actual=%b", selected, rsp_valid);
                if (rsp_data[selected] !== down_rsp_data || rsp_error[selected] !== down_rsp_error)
                    $fatal(1, "ORACLE_RESPONSE_PAYLOAD");
                if (down_rsp_ready !== rsp_ready[selected]) $fatal(1, "ORACLE_RESPONSE_READY_OWNER");
                if (down_rsp_ready) begin
                    $display("RESPONSE cycle=%0d owner=%0d identity=%0d data=%h error=%b", cycles, selected, identities[head], down_rsp_data, down_rsp_error);
                    head = head + 1;
                    count = count - 1;
                    returned = returned + 1;
                end else response_stalls = response_stalls + 1;
            end else if (rsp_valid !== 2'b00) $fatal(1, "ORACLE_SPURIOUS_RESPONSE");
            if (count == 0 && !down_rsp_valid && down_rsp_ready !== 1'b0)
                $fatal(1, "ORACLE_EMPTY_OWNER_READY");

            last_accept = -1;
            if (|accepts) begin
                selected = accepts[1] ? 1 : 0;
                if (down_req_address !== req_address[selected] || down_req_data !== req_data[selected] ||
                    down_req_write !== 1'b1 || down_req_size !== 3'd2 || down_req_byte_enable !== 8'h0f)
                    $fatal(1, "ORACLE_MSI_ADDRESS_IDENTITY owner=%0d address=%h data=%h", selected, down_req_address, down_req_data);
                if (down_req_address !== (selected == 0 ? 64'h24000000 : 64'h28000000))
                    $fatal(1, "ORACLE_MSI_DOMAIN_ADDRESS");
                owners[tail] = selected;
                identities[tail] = down_req_data;
                tail = tail + 1;
                count = count + 1;
                if (count > 8) $fatal(1, "ORACLE_OWNER_CAPACITY_EXCEEDED");
                accepted = accepted + 1;
                last_accept = selected;
                streak = streak + 1;
                if (streak > max_streak) max_streak = streak;
                $display("REQUEST cycle=%0d owner=%0d address=%h identity=%0d outstanding=%0d", cycles, selected, down_req_address, down_req_data, count);
            end else streak = 0;
            #1 clock = 1;
            #5 clock = 0;
        end
    endtask

    task common_reset;
        begin
            // Assert from a known zero, take real edges, then deassert. Producers
            // cancel only during common reset; no input is withdrawn while locked.
            if (reset !== 1'b0) $fatal(1, "ORACLE_RESET_TRANSITION");
            #2 reset = 1;
            req_valid = 0;
            down_rsp_valid = 0;
            down_req_ready = 0;
            rsp_ready = 0;
            #5 clock = 1;
            #5 clock = 0;
            #5 clock = 1;
            #5 clock = 0;
            discarded = discarded + count;
            head = 0; tail = 0; count = 0;
            previous_stall = 0; streak = 0;
            epochs = epochs + 1;
            #2 reset = 0;
            tick();
        end
    endtask

    task prepare_response;
        begin
            if (count == 0) $fatal(1, "ORACLE_TEST_NO_PENDING_RESPONSE");
            down_rsp_valid = 1;
            down_rsp_data = 64'h5a00000000000000 | identities[head];
            down_rsp_error = identities[head][0];
        end
    endtask

    task drain;
        integer bounded;
        begin
            rsp_ready = 2'b11;
            bounded = 0;
            while (count != 0) begin
                prepare_response();
                tick();
                bounded = bounded + 1;
                if (bounded > 32) $fatal(1, "ORACLE_DRAIN_BOUND");
            end
            down_rsp_valid = 0;
            tick();
        end
    endtask

    initial begin
        req_address[0] = 64'h24000000; req_address[1] = 64'h28000000;
        req_data[0] = 11; req_data[1] = 19;
        common_reset();

        // Critical cold-start counterexample: only producer 1 is active. The
        // unchanged legacy RR fails the exact same oracle here, before clocking
        // the inconsistent downstream acceptance into its owner queue.
        req_valid = 2'b10; down_req_ready = 1;
        tick();
        if (last_accept != 1 || count != 1) $fatal(1, "ORACLE_FIRST_CLIENT1");
        req_valid = 0;
        prepare_response(); rsp_ready = 2'b01;
        repeat (16) tick();
        if (returned != 0 || count != 1) $fatal(1, "ORACLE_WRONG_OWNER_EARLY_RESPONSE");
        rsp_ready = 2'b11; tick(); down_rsp_valid = 0; tick();
        $display("CHECKPOINT cold_client1=1 supervisor_response_backpressure=16");

        // A newcomer cannot steal a selected stalled M-domain request.
        req_valid = 2'b01; down_req_ready = 0;
        tick(); req_valid = 2'b11;
        repeat (32) tick();
        down_req_ready = 1; tick();
        if (last_accept != 0) $fatal(1, "ORACLE_LOCKED_OWNER_STOLEN");
        req_valid[0] = 0; tick();
        if (last_accept != 1) $fatal(1, "ORACLE_WAITING_CLIENT_NOT_SERVED");
        req_valid = 0; drain();
        $display("CHECKPOINT request_lock=1 request_backpressure=33");

        common_reset();
        // Eight consecutive actual acceptances, with both producers requesting,
        // must alternate. A full owner FIFO must stop the ninth acceptance.
        req_data[0] = 40; req_data[1] = 80;
        req_valid = 2'b11; down_req_ready = 1;
        per_owner[0] = 0; per_owner[1] = 0;
        before_accept = accepted; before_return = returned;
        for (n=0; n<8; n=n+1) begin
            tick();
            owner = (n % 2 == 0) ? 1 : 0;
            if (last_accept != owner) $fatal(1, "ORACLE_DUAL_PRODUCER_FAIRNESS_OR_II1 beat=%0d owner=%0d", n, last_accept);
            per_owner[owner] = per_owner[owner] + 1;
            req_data[owner] = req_data[owner] + 1;
            if (per_owner[owner] == 4) req_valid[owner] = 0;
        end
        if (count != 8 || accepted-before_accept != 8 || returned != before_return)
            $fatal(1, "ORACLE_EIGHT_OWNER_FILL");
        req_valid = 2'b10; req_data[1] = 99;
        repeat (24) begin
            tick();
            if (last_accept != -1 || count != 8) $fatal(1, "ORACLE_FULL_OWNER_BACKPRESSURE");
        end
        // Reply #1 is blocked on its actual owner while the other source is
        // ready; no fabricated acknowledgement may release owner credit.
        prepare_response(); rsp_ready = 2'b01;
        repeat (9) tick();
        if (count != 8 || returned != before_return) $fatal(1, "ORACLE_FULL_OWNER_FALSE_CREDIT");
        rsp_ready = 2'b11; tick();
        if (last_accept != -1 || count != 7) $fatal(1, "ORACLE_FULL_FIFO_PIPE_POLICY");
        down_rsp_valid = 0; tick();
        if (last_accept != 1 || count != 8) $fatal(1, "ORACLE_NINTH_ACCEPTANCE_AFTER_REAL_RESPONSE");
        req_valid = 0;
        // Stagger the remaining real replies and backpressure each owner.
        while (count != 0) begin
            prepare_response(); rsp_ready = owners[head] == 0 ? 2'b10 : 2'b01;
            repeat (3) tick();
            rsp_ready = 2'b11; tick(); down_rsp_valid = 0; tick();
        end
        if (returned-before_return != 9 || accepted-before_accept != 9 || max_streak < 8)
            $fatal(1, "ORACLE_EIGHT_OWNER_COMPLETION");
        $display("CHECKPOINT eight_owner=1 real_replies=9 fair_ii1=8 full_backpressure=24");

        // Clear both a queued owner and a selected stalled offer together.
        req_valid = 2'b01; req_data[0] = 101; tick();
        if (last_accept != 0 || count != 1) $fatal(1, "ORACLE_RESET_SETUP_OWNER");
        req_valid = 2'b10; req_data[1] = 103; down_req_ready = 0;
        repeat (8) tick();
        if (!previous_stall) $fatal(1, "ORACLE_RESET_SETUP_LOCK");
        common_reset();
        repeat (4) tick();
        if (down_req_valid !== 0 || rsp_valid !== 0 || down_rsp_ready !== 0)
            $fatal(1, "ORACLE_COMMON_RESET_STALE_TRANSACTION");
        // The canceled locked producer was S; prove M can now be accepted.
        req_valid = 2'b01; req_data[0] = 111; down_req_ready = 1; tick();
        if (last_accept != 0) $fatal(1, "ORACLE_COMMON_RESET_LOCK_RETAINED");
        req_valid = 0; drain();
        req_valid = 2'b10; req_data[1] = 113; tick();
        if (last_accept != 1) $fatal(1, "ORACLE_POST_RESET_CLIENT1");
        req_valid = 0; drain();
        if (count != 0 || accepted != returned+discarded || discarded != 1)
            $fatal(1, "ORACLE_FINAL_CONSERVATION");
        $display("REGISTER_ARBITER_RESET_PASS cycles=%0d accepted=%0d responses=%0d reset_discarded=%0d epochs=%0d cold_client1=1 eight_owner=1 fair_ii1=8 reset_clear=1 request_stalls=%0d response_stalls=%0d", cycles, accepted, returned, discarded, epochs, stalls, response_stalls);
        $finish;
    end
endmodule
