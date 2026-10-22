`timescale 1ns/1ps
// Focused responder test through unmodified emitted production MdioClause22.
// This test does not replace actual-manager startup/debounce composition tests.
module rtl8211f_pin_model_tb;
    reg clk=0, reset=1;
    always #2 clk=~clk;
    reg command_valid=0, command_write=0, response_ready=0;
    reg [4:0] command_phy=1, command_register=0;
    reg [15:0] command_data=0;
    wire command_ready, response_valid, response_no_ack;
    wire [15:0] response_data;
    wire mdc, mdio_out, mdio_oe, mdio_in;
    reg wire_link=1, full_duplex=1, an_complete=1, remote_fault=0, inject_no_ack=0;
    reg [1:0] wire_speed=2;
    wire in_transaction, configuration_complete;
    wire [15:0] page;
    wire [31:0] transaction_count, read_count, write_count, status_count, bmsr_count, no_ack_count;
    integer tested=0, n;
    MdioClause22 engine(
        .clock(clk), .reset(reset), .io_command_ready(command_ready),
        .io_command_valid(command_valid), .io_command_bits_phy(command_phy),
        .io_command_bits_register(command_register), .io_command_bits_write(command_write),
        .io_command_bits_data(command_data), .io_response_ready(response_ready),
        .io_response_valid(response_valid), .io_response_bits_data(response_data),
        .io_response_bits_noAck(response_no_ack), .io_mdc(mdc), .io_mdioIn(mdio_in),
        .io_mdioOut(mdio_out), .io_mdioOe(mdio_oe));
    rtl8211f_pin_model phy(
        .clk(clk), .reset(reset), .mdc(mdc), .mdio_out(mdio_out), .mdio_oe(mdio_oe), .mdio_in(mdio_in),
        .wire_link(wire_link), .wire_speed(wire_speed), .full_duplex(full_duplex),
        .an_complete(an_complete), .remote_fault(remote_fault), .inject_no_ack(inject_no_ack),
        .in_transaction(in_transaction), .page(page), .transaction_count(transaction_count),
        .read_count(read_count), .write_count(write_count), .status_count(status_count),
        .bmsr_count(bmsr_count), .no_ack_count(no_ack_count), .configuration_complete(configuration_complete));
    task automatic transfer(input bit wr, input [4:0] regno, input [15:0] value,
        input [15:0] expected, input bit noack);
        begin
            @(negedge clk);
            while (!command_ready) @(negedge clk);
            command_valid=1; command_write=wr; command_register=regno; command_data=value;
            @(negedge clk); command_valid=0;
            wait(response_valid);
            // Hold engine response for several control cycles: PHY must have
            // finished the physical frame and must not produce a second one.
            repeat(5) @(negedge clk);
            if (response_data !== expected || response_no_ack !== noack)
                $fatal(1, "PIN_MODEL readback reg=%0d write=%b got=%h/%b expected=%h/%b", regno, wr,
                    response_data, response_no_ack, expected, noack);
            if (mdc || mdio_oe || in_transaction)
                $fatal(1, "PIN_MODEL frame not released with held response");
            tested=tested+1;
            if(transaction_count != tested) $fatal(1, "PIN_MODEL frame count");
            response_ready=1;
            @(negedge clk); response_ready=0;
        end
    endtask
    task automatic wr(input [4:0] regno, input [15:0] value);
        transfer(1, regno, value, value, 0);
    endtask
    task automatic rd(input [4:0] regno, input [15:0] expected);
        transfer(0, regno, 0, expected, 0);
    endtask
    initial begin
        repeat(4) @(negedge clk); reset=0;
        wr(31,0); rd(31,0); rd(2,$test$plusargs("inject_expected_mismatch") ? 16'h001d : 16'h001c); rd(3,16'hc916);
        wr(31,16'h0d08); rd(31,16'h0d08);
        rd(17,16'hf377); wr(17,16'hf277); rd(17,16'hf277);
        rd(21,16'h7890); wr(21,16'h7898); rd(21,16'h7898);
        wr(31,0); rd(31,0); wr(13,7); wr(14,60); wr(13,16'h4007); wr(14,0); rd(14,0);
        wr(4,16'h0141); rd(4,16'h0141); rd(9,16'h0700); wr(9,16'h0600); rd(9,16'h0600);
        rd(0,16'h1140); wr(0,16'h1340); rd(0,16'h1140);
        if (!configuration_complete) $fatal(1, "PIN_MODEL configuration witness absent");
        rd(1,16'h0020); rd(1,16'h0024); rd(5,16'h4141); rd(10,16'h7800);
        wr(31,16'h0a43); rd(31,16'h0a43); rd(26,16'h102c); rd(26,16'h102c);
        wire_speed=1; rd(26,16'h101c); wire_speed=0; rd(26,16'h100c);
        wire_link=0; rd(26,16'h1008); wire_link=1; full_duplex=0; rd(26,16'h1004);
        full_duplex=1; wire_speed=3; rd(26,16'h103c); wire_speed=2;
        wr(31,0); an_complete=0; rd(1,0); rd(1,4);
        an_complete=1; remote_fault=1; rd(1,16'h30); rd(1,16'h34); remote_fault=0;
        // All arbiter-allowed base registers (<16) have deterministic replies.
        for(n=6;n<9;n=n+1) rd(n,0);
        rd(11,0); rd(12,0); rd(13,0); rd(15,0);
        @(negedge clk); inject_no_ack=1;
        @(negedge clk); inject_no_ack=0;
        // A write does not consume the one-shot read noAck injection.
        wr(31,0); transfer(0,2,0,16'hffff,1); rd(2,16'h001c);
        if(no_ack_count != 1) $fatal(1, "PIN_MODEL noAck not one-shot");
        command_phy=2; transfer(0,2,0,16'hffff,1); command_phy=1; rd(2,16'h001c);
        if(read_count+write_count != transaction_count || status_count != 7 || bmsr_count != 6)
            $fatal(1, "PIN_MODEL transaction accounting");
        // Reset cancels a frame and resets only this modeled PHY's state.
        @(negedge clk); command_valid=1; command_register=2;
        @(negedge clk); command_valid=0;
        wait(in_transaction); repeat(13) @(negedge clk); reset=1;
        repeat(3) @(negedge clk); reset=0; tested=0;
        rd(2,16'h001c);
        $display("RTL8211F_PIN_MODEL_PASS startup_readbacks=1 status_rates=4 bmsr_latched_low=1 software_reads=1 no_ack_once=1 reset_cancel=1");
        $finish;
    end
    initial begin #100000000; $fatal(1, "PIN_MODEL timeout"); end
endmodule
