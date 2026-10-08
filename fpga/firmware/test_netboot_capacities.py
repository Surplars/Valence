#!/usr/bin/env python3
"""Bounded native firmware capacity matrix; no RTL/board/kernel execution."""
import argparse,json,os,subprocess,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
BODY=r'''
#define main unused_original_board_main
#include "test_netboot_board.c"
#undef main
int main(void) {
    reset_hw(); hw.queue_cap=HW_SLOTS; hw.mac_slots=MAC_SLOTS;
    active=1; hw.control=11;
    assert(start_posted_rx());
    assert(posted_count==EXPECT_SLOTS && negotiated_window_cap==EXPECT_WINDOW);
    unsigned frames=2*EXPECT_SLOTS+1; hw.frames=frames; hw.frame_bytes=64;
    for(unsigned i=0;i<frames;++i) {
        assert(recv(0,1000)==64);
        for(unsigned b=0;b<64;++b) assert(received_frame(0)[b]==(uint8_t)(0x31+i));
    }
    assert(board_netboot_quiet() && !posted_owned && !posted_mode && !active);
    printf("NETBOOT_CAPACITY_CASE sw=%u block=%u requested=%u hw=%u mac=%u active=%u window=%u copy_and_stop=1\n",
           NETBOOT_RX_SLOTS,NETBOOT_BLOCK_BYTES,NETBOOT_WINDOW,HW_SLOTS,MAC_SLOTS,EXPECT_SLOTS,EXPECT_WINDOW);
    return 0;
}
'''
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--cc',default='cc');ap.add_argument('--out',type=Path);args=ap.parse_args()
    # Explicit expected capacity, independently tabulated from the contract.
    matrix=[(4,1024,4,1,1,1,1),(4,1024,4,2,4,2,2),(4,1024,4,4,2,4,2),
            (4,1024,4,8,8,4,4),(4,1024,4,16,0,4,1),(1,1024,1,4,4,1,1),
            (2,512,2,2,2,2,2),(3,512,3,4,4,3,3),(7,512,7,8,8,7,7),
            (7,512,5,16,2,7,2)]
    logs=[]
    with tempfile.TemporaryDirectory(prefix='nb-capacity-') as td:
        p=Path(td);(p/'test.c').write_text(BODY)
        for n,row in enumerate(matrix):
            defines=dict(zip(('NETBOOT_RX_SLOTS','NETBOOT_BLOCK_BYTES','NETBOOT_WINDOW','HW_SLOTS','MAC_SLOTS','EXPECT_SLOTS','EXPECT_WINDOW'),row))
            subprocess.run([args.cc,'-std=c11','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                '-Wall','-Wextra','-Werror','-I'+str(HERE),*[f'-D{k}={v}' for k,v in defines.items()],
                p/'test.c',HERE/'netboot.c',HERE/'crc32.c','-o',p/'run'],check=True)
            result=subprocess.run([p/'run'],capture_output=True,text=True,timeout=30,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
            if result.returncode:raise RuntimeError(str(row)+'\n'+result.stdout+result.stderr)
            logs.append(result.stdout);print(result.stdout,end='')
    for flags in (['--netboot-rx-slots','8','--netboot-window','8','--netboot-block-bytes','512'],
                  ['--netboot-rx-slots','2','--netboot-window','4'],['--netboot-rx-slots','17']):
        result=subprocess.run(['python3',HERE/'build.py','--ddr','--netboot','--netboot-posted-rx',*flags],capture_output=True,text=True)
        assert result.returncode==2 and ('scratch budget' in result.stderr or 'window must fit' in result.stderr)
    receipt={'status':'passed','native_cases':len(matrix),'invalid_cli_cases':3,'matrix':matrix,'summary':logs,'scope':__doc__}
    if args.out:
        args.out.mkdir(parents=True,exist_ok=False);(args.out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('NETBOOT_CAPACITY_MATRIX_PASS cases=10 invalid_cli=3')
if __name__=='__main__':main()
