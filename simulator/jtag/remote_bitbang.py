#!/usr/bin/env python3
"""Loopback-only OpenOCD remote_bitbang to native SV simulation; never hardware."""
import argparse
from pathlib import Path
import os
import shutil
import socket
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]

class Simulation:
    def __init__(self, build):
        compiler=shutil.which(os.environ.get("IVERILOG","iverilog"))
        runtime=shutil.which(os.environ.get("VVP","vvp"))
        if not compiler or not runtime: raise RuntimeError("Icarus/vvp are required; this script never installs tools")
        build.mkdir(parents=True,exist_ok=True)
        binary=build/"remote-bitbang.vvp"
        subprocess.run([compiler,"-g2012","-s","remote_bitbang_tb","-o",str(binary),
                        str(ROOT/"src/main/resources/debug/ValenceJtagDebugPort.sv"),
                        str(ROOT/"simulator/jtag/remote_bitbang_tb.sv")],check=True)
        self.process=subprocess.Popen([runtime,str(binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                      text=True,bufsize=1)
    def command(self,code,value=0):
        self.process.stdin.write(f"{code} {value}\n");self.process.stdin.flush()
        line=self.process.stdout.readline().strip().split()
        if len(line)!=3 or line[0]!="S" or line[1] not in ("0","1"):
            raise RuntimeError(f"simulation response invalid: {line}")
        return int(line[1])
    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=3)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=9824)
    args=parser.parse_args()
    sim=Simulation(ROOT/"build/jtag/remote-bitbang")
    try:
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            server.bind(("127.0.0.1",args.port));server.listen(1)
            print(f"JTAG simulation only; fail-only DM endpoint; listening 127.0.0.1:{server.getsockname()[1]}",flush=True)
            connection,_=server.accept()
            with connection:
                connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                while data:=connection.recv(4096):
                    for c in data:
                        if ord('0')<=c<=ord('7'):sim.command(0,c-ord('0'))
                        elif c==ord('R'):connection.sendall(str(sim.command(2)).encode())
                        elif ord('r')<=c<=ord('u'):sim.command(1,c-ord('r'))
                        elif c in (ord('B'),ord('b')):pass
                        elif c==ord('z'):sim.command(3,1000)
                        elif c==ord('Z'):sim.command(3,1000000)
                        elif c==ord('Q'):return
                        else:raise RuntimeError(f"Unsupported remote_bitbang byte {c}; JTAG only")
    finally:sim.close()

if __name__=="__main__":main()
