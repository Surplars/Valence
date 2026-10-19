`timescale 1ns/1ps
// Component-only, native independent-edge digital transport oracle.
// No DUT hierarchy, FIFO pointer, RAM slot or synchronized idle flag is used
// to decide which payload should arrive or whether an owner is finished.
module tilelink_boundary_tb;
    reg cpuClock=0, fabricClock=0, commonColdReset=0;
    integer cpu_half=3, fabric_half=7, phase_ps=1300;
    integer fifo_depth=4, held_response=0, stress_count=24, new_epoch_count=24;
    integer cpu_cycles=0, fabric_cycles=0, cpu_release_edges=0, fabric_release_edges=0;
    initial begin
        if ($value$plusargs("cpu_half=%d",cpu_half)) begin end
        forever #(cpu_half) cpuClock=~cpuClock;
    end
    initial begin
        if ($value$plusargs("fabric_half=%d",fabric_half)) begin end
        if ($value$plusargs("phase_ps=%d",phase_ps)) begin end
        // Delayed initial clock startup tests peer release, not clock gating.
        #(200.0+phase_ps/1000.0);
        forever #(fabric_half) fabricClock=~fabricClock;
    end
    reg [4:0] source_valid=0;
    wire [4:0] source_ready, destination_valid, destination_ready;
    reg [148:0] source_bits[0:4];
    wire [148:0] destination_bits[0:4];
    reg [4:0] service=0;
    reg throttle=0;
    wire cpuTransportEmpty, fabricTransportEmpty, cpuLinkReady, fabricLinkReady;
    genvar g;
    generate for(g=0;g<5;g=g+1) begin: ready_pattern
        if(g==1 || g==3)
            assign destination_ready[g]=service[g] && (!throttle || ((cpu_cycles+g)%7>1));
        else
            assign destination_ready[g]=service[g] && (!throttle || ((fabric_cycles+g)%7>1));
    end endgenerate
    assign destination_bits[2][148:141]=0;
    assign destination_bits[3][148:79]=0;
    assign destination_bits[4][148:1]=0;
    TileLinkClockDomainBoundary dut(
        .cpuClock(cpuClock),
        .fabricClock(fabricClock),
        .commonColdReset(commonColdReset),
        .cpuTransportEmpty(cpuTransportEmpty),
        .fabricTransportEmpty(fabricTransportEmpty),
        .cpuLinkReady(cpuLinkReady),
        .fabricLinkReady(fabricLinkReady),
        .cpu_a_valid(source_valid[0]),
        .cpu_a_ready(source_ready[0]),
        .fabric_a_valid(destination_valid[0]),
        .fabric_a_ready(destination_ready[0]),
        .cpu_a_bits_opcode(source_bits[0][148:146]),
        .fabric_a_bits_opcode(destination_bits[0][148:146]),
        .cpu_a_bits_param(source_bits[0][145:143]),
        .fabric_a_bits_param(destination_bits[0][145:143]),
        .cpu_a_bits_size(source_bits[0][142:140]),
        .fabric_a_bits_size(destination_bits[0][142:140]),
        .cpu_a_bits_source(source_bits[0][139:137]),
        .fabric_a_bits_source(destination_bits[0][139:137]),
        .cpu_a_bits_address(source_bits[0][136:73]),
        .fabric_a_bits_address(destination_bits[0][136:73]),
        .cpu_a_bits_mask(source_bits[0][72:65]),
        .fabric_a_bits_mask(destination_bits[0][72:65]),
        .cpu_a_bits_data(source_bits[0][64:1]),
        .fabric_a_bits_data(destination_bits[0][64:1]),
        .cpu_a_bits_corrupt(source_bits[0][0]),
        .fabric_a_bits_corrupt(destination_bits[0][0]),
        .fabric_b_valid(source_valid[1]),
        .fabric_b_ready(source_ready[1]),
        .cpu_b_valid(destination_valid[1]),
        .cpu_b_ready(destination_ready[1]),
        .fabric_b_bits_opcode(source_bits[1][148:146]),
        .cpu_b_bits_opcode(destination_bits[1][148:146]),
        .fabric_b_bits_param(source_bits[1][145:143]),
        .cpu_b_bits_param(destination_bits[1][145:143]),
        .fabric_b_bits_size(source_bits[1][142:140]),
        .cpu_b_bits_size(destination_bits[1][142:140]),
        .fabric_b_bits_source(source_bits[1][139:137]),
        .cpu_b_bits_source(destination_bits[1][139:137]),
        .fabric_b_bits_address(source_bits[1][136:73]),
        .cpu_b_bits_address(destination_bits[1][136:73]),
        .fabric_b_bits_mask(source_bits[1][72:65]),
        .cpu_b_bits_mask(destination_bits[1][72:65]),
        .fabric_b_bits_data(source_bits[1][64:1]),
        .cpu_b_bits_data(destination_bits[1][64:1]),
        .fabric_b_bits_corrupt(source_bits[1][0]),
        .cpu_b_bits_corrupt(destination_bits[1][0]),
        .cpu_c_valid(source_valid[2]),
        .cpu_c_ready(source_ready[2]),
        .fabric_c_valid(destination_valid[2]),
        .fabric_c_ready(destination_ready[2]),
        .cpu_c_bits_opcode(source_bits[2][140:138]),
        .fabric_c_bits_opcode(destination_bits[2][140:138]),
        .cpu_c_bits_param(source_bits[2][137:135]),
        .fabric_c_bits_param(destination_bits[2][137:135]),
        .cpu_c_bits_size(source_bits[2][134:132]),
        .fabric_c_bits_size(destination_bits[2][134:132]),
        .cpu_c_bits_source(source_bits[2][131:129]),
        .fabric_c_bits_source(destination_bits[2][131:129]),
        .cpu_c_bits_address(source_bits[2][128:65]),
        .fabric_c_bits_address(destination_bits[2][128:65]),
        .cpu_c_bits_data(source_bits[2][64:1]),
        .fabric_c_bits_data(destination_bits[2][64:1]),
        .cpu_c_bits_corrupt(source_bits[2][0]),
        .fabric_c_bits_corrupt(destination_bits[2][0]),
        .fabric_d_valid(source_valid[3]),
        .fabric_d_ready(source_ready[3]),
        .cpu_d_valid(destination_valid[3]),
        .cpu_d_ready(destination_ready[3]),
        .fabric_d_bits_opcode(source_bits[3][78:76]),
        .cpu_d_bits_opcode(destination_bits[3][78:76]),
        .fabric_d_bits_param(source_bits[3][75:73]),
        .cpu_d_bits_param(destination_bits[3][75:73]),
        .fabric_d_bits_size(source_bits[3][72:70]),
        .cpu_d_bits_size(destination_bits[3][72:70]),
        .fabric_d_bits_source(source_bits[3][69:67]),
        .cpu_d_bits_source(destination_bits[3][69:67]),
        .fabric_d_bits_sink(source_bits[3][66]),
        .cpu_d_bits_sink(destination_bits[3][66]),
        .fabric_d_bits_denied(source_bits[3][65]),
        .cpu_d_bits_denied(destination_bits[3][65]),
        .fabric_d_bits_data(source_bits[3][64:1]),
        .cpu_d_bits_data(destination_bits[3][64:1]),
        .fabric_d_bits_corrupt(source_bits[3][0]),
        .cpu_d_bits_corrupt(destination_bits[3][0]),
        .cpu_e_valid(source_valid[4]),
        .cpu_e_ready(source_ready[4]),
        .fabric_e_valid(destination_valid[4]),
        .fabric_e_ready(destination_ready[4]),
        .cpu_e_bits_sink(source_bits[4][0]),
        .fabric_e_bits_sink(destination_bits[4][0]));

    localparam LIMIT=2048;
    reg [148:0] expected[0:4][0:LIMIT-1];
    reg [148:0] ones[0:4], zeros[0:4], held_source[0:4], held_destination[0:4];
    reg source_stalled[0:4], destination_stalled[0:4];
    integer head[0:4], tail[0:4], accepted[0:4], delivered[0:4];
    integer source_stalls[0:4], destination_stalls[0:4], epoch_dropped[0:4];
    integer phase_delivered[0:4], perf_first[0:4], perf_last[0:4];
    integer blocked_capacity[0:4], local_first[0:4], local_last[0:4];
    integer latency_begin_edge[0:4], latency_edges[0:4];
    realtime latency_begin_ns[0:4], latency_ns[0:4];
    integer scenario=0, epoch=0, reset_count=0, startup_refusals=0;
    integer before_response=0, outstanding=0, max_outstanding=0;
    integer remaining[0:7], response_order[0:7], completed_grants=0, completed_acks=0;
    integer active_source=-1;
    reg [1:0] owed_e=0, issued_e=0;
    reg first_response=0, negative_used=0;
    reg quiet_after_reset=0;
    integer local_empty_checks=0, empty_owner_checks=0;

    function automatic [148:0] width_mask(input integer channel);
        begin
            case(channel)
                0,1:width_mask={149{1'b1}};
                2:width_mask={{8{1'b0}},{141{1'b1}}};
                3:width_mask={{70{1'b0}},{79{1'b1}}};
                default:width_mask=149'd1;
            endcase
        end
    endfunction
    function automatic [148:0] pattern(input integer channel,input integer serial,input integer generation);
        reg [2:0] op,par,sz,src;
        reg [63:0] address,data;
        reg [7:0] mask;
        reg corrupt,denied,sink;
        begin
            op=serial; par=serial>>1; sz=serial>>2; src=serial^generation;
            address=64'hfedc0123456789ab^(serial*64'h9e3779b97f4a7c15)^(generation*64'hbadce12354ace809);
            data=64'h8001020408102040^(serial*64'hd1342543de82ef95)^(generation*64'hf1e2d3c4b5a69788);
            mask=(serial*37)^8'h96; corrupt=serial; denied=serial>>1; sink=(serial^generation);
            case(channel)
                0,1:pattern={op,par,sz,src,address,mask,data,corrupt};
                2:pattern={op,par,sz,src,address,data,corrupt};
                3:pattern={op,par,sz,src,sink,denied,data,corrupt};
                default:pattern=sink;
            endcase
            // Raw transport probes deliberately include every bit low/high.
            // They are not claimed to be legal full TileLink transactions.
            if(serial==0)pattern=0;
            if(serial==1)pattern=width_mask(channel);
        end
    endfunction
    function automatic [148:0] acquire(input integer source);
        reg [2:0] id; reg [63:0] address;
        begin id=source; address=64'h8123000000001000+source*64;
            acquire={3'd6,3'd1,3'd6,id,address,8'hff,64'd0,1'b0}; end
    endfunction
    function automatic [148:0] grant(input integer source,input integer sink,input integer beat);
        reg [2:0] id; reg sk; reg [63:0] data;
        begin id=source;sk=sink;data=64'hf00d800000000000^(source*64'h123456789ab)^(beat*64'hcafebeef);
            grant={3'd5,3'd0,3'd6,id,sk,1'b0,data,1'b0};end
    endfunction

    task automatic source_tick(input integer channel);
        integer id; begin
            if(source_stalled[channel] && (!source_valid[channel] || source_bits[channel]!==held_source[channel]))
                $fatal(1,"TL_CDC_DRIVER_HOLD channel=%0d",channel);
            source_stalled[channel]=source_valid[channel]&&!source_ready[channel];
            held_source[channel]=source_bits[channel];
            if(source_valid[channel]&&!source_ready[channel])source_stalls[channel]=source_stalls[channel]+1;
            if(source_valid[channel]&&source_ready[channel])begin
                if(tail[channel]>=LIMIT)$fatal(1,"TL_CDC_ORACLE_CAPACITY");
                expected[channel][tail[channel]]=source_bits[channel];tail[channel]=tail[channel]+1;
                accepted[channel]=accepted[channel]+1;
                if(scenario==8)begin
                    latency_begin_ns[channel]=$realtime;
                    latency_begin_edge[channel]=(channel==1||channel==3)?cpu_cycles:fabric_cycles;
                end
                ones[channel]=ones[channel]|source_bits[channel];
                zeros[channel]=zeros[channel]|(~source_bits[channel]&width_mask(channel));
                if(scenario==1 && channel==0)begin
                    if(!first_response)before_response=before_response+1;
                    outstanding=outstanding+1;
                    if(outstanding>max_outstanding)max_outstanding=outstanding;
                end
                if(scenario==1 && channel==4)begin
                    id=source_bits[channel][0];
                    if(!owed_e[id] || issued_e[id])$fatal(1,"TL_CDC_E_BEFORE_WHOLE_GRANT sink=%0d",id);
                    issued_e[id]=1;
                end
            end
        end
    endtask
    task automatic destination_tick(input integer channel,input integer cycle);
        reg [148:0] observed;
        integer id,sink,index;
        begin
            if(destination_stalled[channel] && (!destination_valid[channel] || destination_bits[channel]!==held_destination[channel]))
                $fatal(1,"TL_CDC_OUTPUT_HOLD channel=%0d",channel);
            destination_stalled[channel]=destination_valid[channel]&&!destination_ready[channel];
            held_destination[channel]=destination_bits[channel];
            if(destination_stalled[channel])destination_stalls[channel]=destination_stalls[channel]+1;
            if(quiet_after_reset && destination_valid[channel])$fatal(1,"TL_CDC_EPOCH_REPLAY channel=%0d",channel);
            if(destination_valid[channel]&&destination_ready[channel])begin
                observed=destination_bits[channel];
                if($test$plusargs("bad_payload")&&!negative_used&&channel==0)begin
                    observed[37]=~observed[37];negative_used=1;
                end
                if($test$plusargs("bad_source")&&!negative_used&&channel==3)begin
                    observed[69]=~observed[69];negative_used=1;
                end
                if($test$plusargs("bad_sink")&&!negative_used&&channel==4)begin
                    observed[0]=~observed[0];negative_used=1;
                end
                if(head[channel]>=tail[channel])$fatal(1,"TL_CDC_UNEXPECTED_OUTPUT channel=%0d epoch=%0d",channel,epoch);
                if(observed!==expected[channel][head[channel]])
                    $fatal(1,"TL_CDC_PAYLOAD_ORACLE channel=%0d beat=%0d expected=%h observed=%h",channel,head[channel],expected[channel][head[channel]],observed);
                head[channel]=head[channel]+1;delivered[channel]=delivered[channel]+1;
                phase_delivered[channel]=phase_delivered[channel]+1;
                if(scenario==6)begin
                    if(phase_delivered[channel]==16)perf_first[channel]=cycle;
                    if(phase_delivered[channel]==112)perf_last[channel]=cycle;
                end
                if(scenario==7)begin
                    if(phase_delivered[channel]==3)local_first[channel]=cycle;
                    if(phase_delivered[channel]==fifo_depth-1)local_last[channel]=cycle;
                end
                if(scenario==8)begin
                    latency_ns[channel]=$realtime-latency_begin_ns[channel];
                    latency_edges[channel]=cycle-latency_begin_edge[channel];
                end
                if(scenario==1 && channel==0)begin
                    id=observed[139:137];
                    if(remaining[id]!=0)$fatal(1,"TL_CDC_A_SOURCE_REUSE");
                    remaining[id]=8;
                end
                if(scenario==1 && channel==3)begin
                    if(!first_response && before_response<4)$fatal(1,"TL_CDC_SINGLE_OUTSTANDING");
                    first_response=1;id=observed[69:67];sink=observed[66];
                    if(remaining[id]<=0 || observed[78:76]!=5 || observed[72:70]!=6)
                        $fatal(1,"TL_CDC_GRANT_OWNER");
                    if(active_source<0)begin
                        if(id!=response_order[completed_grants] || sink!=(completed_grants%2) || owed_e[sink])
                            $fatal(1,"TL_CDC_REORDER_OR_SINK_OWNER");
                        active_source=id;
                    end else if(id!=active_source)$fatal(1,"TL_CDC_MULTIBEAT_INTERLEAVE");
                    remaining[id]=remaining[id]-1;
                    if(remaining[id]==0)begin
                        active_source=-1;completed_grants=completed_grants+1;owed_e[sink]=1;
                        outstanding=outstanding-1;
                    end
                end
                if(scenario==1 && channel==4)begin
                    sink=observed[0];
                    if(!owed_e[sink] || !issued_e[sink])$fatal(1,"TL_CDC_E_SINK_OWNER");
                    owed_e[sink]=0;issued_e[sink]=0;completed_acks=completed_acks+1;
                end
            end
        end
    endtask
    task automatic check_admission;
        begin
            if(cpu_release_edges<3 || fabric_release_edges<3)begin
                if(source_ready!==0 || destination_valid!==0 || cpuLinkReady || fabricLinkReady)
                    $fatal(1,"TL_CDC_PEER_RELEASE_ADMISSION cpu=%0d fabric=%0d",cpu_release_edges,fabric_release_edges);
                if(|source_valid)startup_refusals=startup_refusals+1;
            end
            if(!cpuLinkReady && (source_ready[0]||source_ready[2]||source_ready[4]||destination_valid[1]||destination_valid[3]))
                $fatal(1,"TL_CDC_CPU_ADMISSION");
            if(!fabricLinkReady && (source_ready[1]||source_ready[3]||destination_valid[0]||destination_valid[2]||destination_valid[4]))
                $fatal(1,"TL_CDC_FABRIC_ADMISSION");
        end
    endtask
    always @(posedge cpuClock)begin
        cpu_cycles=cpu_cycles+1;
        if(!commonColdReset)begin
            check_admission();
            source_tick(0);source_tick(2);source_tick(4);
            destination_tick(1,cpu_cycles);destination_tick(3,cpu_cycles);
            cpu_release_edges=cpu_release_edges+1;
        end
    end
    always @(posedge fabricClock)begin
        fabric_cycles=fabric_cycles+1;
        if(!commonColdReset)begin
            check_admission();
            source_tick(1);source_tick(3);
            destination_tick(0,fabric_cycles);destination_tick(2,fabric_cycles);destination_tick(4,fabric_cycles);
            fabric_release_edges=fabric_release_edges+1;
        end
    end
    always @(posedge commonColdReset)begin
        cpu_release_edges=0;fabric_release_edges=0;reset_count=reset_count+1;
        for(integer ch=0;ch<5;ch=ch+1)begin
            if(reset_count>1)epoch_dropped[ch]=tail[ch]-head[ch];
            head[ch]=0;tail[ch]=0;source_stalled[ch]=0;destination_stalled[ch]=0;
        end
        #0.1;
        if(source_ready!==0 || destination_valid!==0 || cpuLinkReady || fabricLinkReady)
            $fatal(1,"TL_CDC_ASYNC_RESET_ADMISSION");
    end

    task automatic source_negedge(input integer channel);
        begin if(channel==1||channel==3)@(negedge fabricClock);else @(negedge cpuClock);end
    endtask
    task automatic destination_negedge(input integer channel);
        begin if(channel==1||channel==3)@(negedge cpuClock);else @(negedge fabricClock);end
    endtask
    task automatic source_posedge(input integer channel);
        begin if(channel==1||channel==3)@(posedge fabricClock);else @(posedge cpuClock);end
    endtask
    task automatic send(input integer channel,input [148:0] value);
        begin
            source_negedge(channel);source_bits[channel]=value;source_valid[channel]=1;
            source_posedge(channel);while(!source_ready[channel])source_posedge(channel);
            source_negedge(channel);source_valid[channel]=0;
        end
    endtask
    task automatic stream(input integer channel,input integer count,input integer base,input integer generation);
        begin
            source_negedge(channel);source_valid[channel]=1;
            for(integer n=0;n<count;n=n+1)begin
                source_bits[channel]=pattern(channel,base+n,generation);
                source_posedge(channel);while(!source_ready[channel])source_posedge(channel);
                source_negedge(channel);
            end
            source_valid[channel]=0;
        end
    endtask
    task automatic clear_phase_counts;
        begin for(integer ch=0;ch<5;ch=ch+1)phase_delivered[ch]=0;end
    endtask
    task automatic drain;
        reg all_done; begin
            all_done=0;
            while(!all_done)begin
                @(negedge cpuClock);all_done=cpuTransportEmpty&&fabricTransportEmpty;
                for(integer ch=0;ch<5;ch=ch+1)if(head[ch]!=tail[ch])all_done=0;
            end
            // Settle both sides, making duplicate outputs observable too.
            repeat(8)@(negedge cpuClock);repeat(8)@(negedge fabricClock);
        end
    endtask

    initial begin: exercise
        integer before_a,before_d,id,sk;
        real rate;
        if($value$plusargs("fifo_depth=%d",fifo_depth))begin end
        if($value$plusargs("held_response=%d",held_response))begin end
        if((held_response==0 && fifo_depth!=4) || (held_response==1 && fifo_depth!=16) || held_response>1)
            $fatal(1,"TL_CDC_PROFILE_ARGUMENTS");
        stress_count=2*fifo_depth+16;new_epoch_count=fifo_depth+20;
        for(integer ch=0;ch<5;ch=ch+1)begin
            source_bits[ch]=0;head[ch]=0;tail[ch]=0;accepted[ch]=0;delivered[ch]=0;
            ones[ch]=0;zeros[ch]=0;source_stalled[ch]=0;destination_stalled[ch]=0;
            source_stalls[ch]=0;destination_stalls[ch]=0;epoch_dropped[ch]=0;
            phase_delivered[ch]=0;perf_first[ch]=0;perf_last[ch]=0;
            blocked_capacity[ch]=0;local_first[ch]=0;local_last[ch]=0;
            latency_begin_edge[ch]=0;latency_edges[ch]=0;latency_begin_ns[ch]=0;latency_ns[ch]=0;
        end
        for(integer n=0;n<8;n=n+1)remaining[n]=0;
        response_order[0]=5;response_order[1]=2;response_order[2]=7;response_order[3]=0;
        response_order[4]=6;response_order[5]=1;response_order[6]=4;response_order[7]=3;
        #1;commonColdReset=1;#39;commonColdReset=0;
        // Valid is offered while the remote clock has not started. Hold it
        // until acceptance; no pre-release beat may sneak into a FIFO.
        service=31;scenario=1;
        send(0,acquire(0));
        for(integer n=1;n<8;n=n+1)send(0,acquire(n));
        drain();
        if(before_response!=8 || max_outstanding!=8 || outstanding!=8 || !cpuTransportEmpty || !fabricTransportEmpty)
            $fatal(1,"TL_CDC_MULTI_OWNER_SETUP");
        // Both queues empty can coexist with eight external response owners.
        empty_owner_checks=empty_owner_checks+1;
        if($test$plusargs("bad_empty") && cpuTransportEmpty && fabricTransportEmpty && outstanding!=0)
            $fatal(1,"TL_CDC_EMPTY_NOT_OWNER_DRAIN_ORACLE");
        throttle=1;
        for(integer n=0;n<8;n=n+1)begin
            id=response_order[n];sk=n%2;
            for(integer beat=0;beat<8;beat=beat+1)send(3,grant(id,sk,beat));
            wait(completed_grants==n+1);
            send(4,sk);wait(completed_acks==n+1);
        end
        drain();
        if(outstanding!=0 || owed_e!=0 || issued_e!=0 || completed_grants!=8 || completed_acks!=8)
            $fatal(1,"TL_CDC_OWNER_COMPLETION");
        $display("TL_CDC_MULTIOWNER accepted_before_first_D=%0d max_outstanding=%0d whole_grants=%0d beats_per_grant=8 E_acks=%0d response_order=5,2,7,0,6,1,4,3",before_response,max_outstanding,completed_grants,completed_acks);

        scenario=2;service=0;clear_phase_counts();
        before_a=delivered[0];before_d=delivered[3];
        fork
            stream(0,stress_count,0,1);
            stream(1,stress_count,0,1);
            stream(2,stress_count,0,1);
            stream(3,stress_count,0,1);
            stream(4,stress_count,0,1);
            begin
                repeat(80)@(negedge cpuClock);repeat(80)@(negedge fabricClock);
                for(integer ch=0;ch<5;ch=ch+1)begin
                    blocked_capacity[ch]=tail[ch]-head[ch];
                    if(blocked_capacity[ch]!=fifo_depth+1 || !source_stalled[ch] || !destination_stalled[ch])
                        $fatal(1,"TL_CDC_FULL_FIFO_COVERAGE channel=%0d pending=%0d depth=%0d",ch,blocked_capacity[ch],fifo_depth);
                    $display("TL_CDC_CAPACITY channel=%0d ram_depth=%0d accepted_while_blocked=%0d",ch,fifo_depth,blocked_capacity[ch]);
                end
                // A and D stay full/blocked while B, C and E finish independently.
                service=5'b10110;
                wait(phase_delivered[1]==stress_count && phase_delivered[2]==stress_count && phase_delivered[4]==stress_count);
                if(delivered[0]!=before_a || delivered[3]!=before_d || source_ready[0] || source_ready[3])
                    $fatal(1,"TL_CDC_CHANNEL_INDEPENDENCE");
                $display("TL_CDC_CHANNEL_INDEPENDENCE B=%0d C=%0d E=%0d while_A_D_blocked=1",stress_count,stress_count,stress_count);
                service=31;
            end
        join
        drain();
        for(integer ch=0;ch<5;ch=ch+1)
            if((ones[ch]&zeros[ch])!==width_mask(ch))$fatal(1,"TL_CDC_BIT_COVERAGE channel=%0d",ch);

        // Source-side pointer idle is explicitly NOT remote output empty.
        scenario=3;throttle=0;service=5'b11110;
        send(0,pattern(0,71,2));
        wait(destination_valid[0]);wait(cpuTransportEmpty);
        repeat(8)@(negedge cpuClock);
        if(!destination_valid[0] || fabricTransportEmpty || head[0]==tail[0])$fatal(1,"TL_CDC_LOCAL_CPU_EMPTY");
        local_empty_checks=local_empty_checks+1;
        service=31;drain();service=5'b10111;
        send(3,pattern(3,72,2));wait(destination_valid[3]);wait(fabricTransportEmpty);
        repeat(8)@(negedge fabricClock);
        if(!destination_valid[3] || cpuTransportEmpty || head[3]==tail[3])$fatal(1,"TL_CDC_LOCAL_FABRIC_EMPTY");
        local_empty_checks=local_empty_checks+1;service=31;drain();
        $display("TL_CDC_LOCAL_EMPTY remote_held_checks=%0d both_empty_with_external_owners=%0d",local_empty_checks,empty_owner_checks);

        // Empty-queue end-to-end latency: external accept to external delivery.
        // It includes independent phase and the real peer synchronizers.
        scenario=8;
        for(integer ch=0;ch<5;ch=ch+1)begin
            send(ch,pattern(ch,800+ch,7));drain();
            if(latency_ns[ch]<=0 || latency_edges[ch]<=0)$fatal(1,"TL_CDC_LATENCY_COVERAGE");
            $display("TL_CDC_LATENCY channel=%0d accept_to_delivery_ns=%0.3f destination_edges=%0d",ch,latency_ns[ch],latency_edges[ch]);
        end

        // Common cold reset intentionally discards every channel's old epoch.
        scenario=4;service=0;clear_phase_counts();
        fork
            stream(0,fifo_depth,100,3);stream(1,fifo_depth,100,3);stream(2,fifo_depth,100,3);
            stream(3,fifo_depth,100,3);stream(4,fifo_depth,100,3);
        join
        wait(destination_valid==31);
        #1.7;commonColdReset=1;source_valid=0;epoch=epoch+1;
        #(10*(cpu_half+fabric_half));commonColdReset=0;
        wait(cpuLinkReady&&fabricLinkReady);quiet_after_reset=1;service=31;
        repeat(16)@(negedge cpuClock);repeat(16)@(negedge fabricClock);
        quiet_after_reset=0;scenario=5;throttle=1;
        for(integer ch=0;ch<5;ch=ch+1)
            if(epoch_dropped[ch]!=fifo_depth)$fatal(1,"TL_CDC_RESET_DROP_COVERAGE channel=%0d",ch);
        fork
            stream(0,new_epoch_count,300,4);stream(1,new_epoch_count,300,4);stream(2,new_epoch_count,300,4);
            stream(3,new_epoch_count,300,4);stream(4,new_epoch_count,300,4);
        join
        drain();
        $display("TL_CDC_EPOCH old_beats_discarded=%0d clean_new_beats=%0d common_reset_only=1",5*fifo_depth,5*new_epoch_count);

        // Raw transport measurement. Interior 96 gaps exclude pipeline fill
        // and tail. Slow sources can limit rate; no protocol/board rate claim.
        scenario=6;throttle=0;clear_phase_counts();
        fork
            stream(0,128,500,5);stream(1,128,500,5);stream(2,128,500,5);
            stream(3,128,500,5);stream(4,128,500,5);
        join
        drain();
        for(integer ch=0;ch<5;ch=ch+1)begin
            if(perf_last[ch]<=perf_first[ch])$fatal(1,"TL_CDC_RATE_COVERAGE");
            rate=96.0/(perf_last[ch]-perf_first[ch]);
            $display("TL_CDC_RATE channel=%0d beats=96 destination_cycles=%0d beats_per_destination_cycle=%0.6f source_half_ns=%0d destination_half_ns=%0d",ch,perf_last[ch]-perf_first[ch],rate,(ch==1||ch==3)?fabric_half:cpu_half,(ch==1||ch==3)?cpu_half:fabric_half);
            if(phase_delivered[ch]!=128 || head[ch]!=tail[ch] || source_stalls[ch]==0 || destination_stalls[ch]==0)
                $fatal(1,"TL_CDC_FINAL_COVERAGE channel=%0d",ch);
        end
        if(held_response==1)begin
            // A local backlog proves II=1 independently of source clock rate.
            // This is kept separate from sustained end-to-end rates above.
            scenario=7;
            for(integer ch=0;ch<5;ch=ch+1)begin
                clear_phase_counts();service[ch]=0;
                stream(ch,fifo_depth+1,1000+ch*32,8);
                wait(destination_valid[ch]);wait(!source_ready[ch]);
                if(tail[ch]-head[ch]!=fifo_depth+1)$fatal(1,"TL_CDC_LOCAL_BACKLOG");
                destination_negedge(ch);service[ch]=1;
                drain();
                if(phase_delivered[ch]!=fifo_depth+1 || local_last[ch]-local_first[ch]!=fifo_depth-4)
                    $fatal(1,"TL_CDC_II_ONE_WINDOW channel=%0d gaps=%0d cycles=%0d",ch,fifo_depth-4,local_last[ch]-local_first[ch]);
                $display("TL_CDC_LOCAL_RATE channel=%0d preloaded_beats=%0d measured_gaps=%0d destination_cycles=%0d beats_per_destination_cycle=1.000000",ch,fifo_depth+1,fifo_depth-4,local_last[ch]-local_first[ch]);
            end
        end
        if(startup_refusals<3 || reset_count!=2 || local_empty_checks!=2)$fatal(1,"TL_CDC_STARTUP_COVERAGE");
        $display("TILELINK_BOUNDARY_NATIVE_CDC_PASS cpu_half=%0d fabric_half=%0d phase_ps=%0d startup_refusals=%0d all_payload_bits_both_values=1 ram_depth=%0d held_response=%0d",cpu_half,fabric_half,phase_ps,startup_refusals,fifo_depth,held_response);
        $finish;
    end
    initial begin #2000000;$fatal(1,"TL_CDC_TIMEOUT scenario=%0d head=%0d,%0d,%0d,%0d,%0d tail=%0d,%0d,%0d,%0d,%0d",scenario,head[0],head[1],head[2],head[3],head[4],tail[0],tail[1],tail[2],tail[3],tail[4]);end
endmodule
