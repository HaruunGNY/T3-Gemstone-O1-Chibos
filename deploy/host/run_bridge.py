#!/usr/bin/env python3
"""
Host-side half of the gem-mavbridge equivalent: launches gem_mavbridge.py
on the board over ssh (sudo -S consumes exactly one password line from
its stdin, then the rest of the pipe flows straight through to the
python script -- no NOPASSWD sudoers change needed), and shuttles
length-prefixed blocks from its stdout to UDP for QGroundControl, and
UDP datagrams received FROM QGC into its stdin for the RX ring.

Runs forever: if the board reboots (ssh session drops, or the ipc ring
isn't valid yet because ArduCopter hasn't reached ipc_ring_init() during
its own boot), this reconnects automatically instead of exiting -- meant
to run as a long-lived service (see gem-mavbridge.service), not a
one-shot script.
"""
import selectors
import socket
import struct
import subprocess
import sys
import time

BOARD_HOST = "gemstone@192.168.7.2"
BOARD_PASS = "gem"
REMOTE_SCRIPT = "/home/gemstone/gem_mavbridge.py"
UDP_HOST = "127.0.0.1"
UDP_PORT = 14550
RECONNECT_DELAY_S = 3


def board_reachable():
    r = subprocess.run(
        ["sshpass", "-p", BOARD_PASS, "ssh", "-T",
         "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3",
         BOARD_HOST, "echo UP"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def run_session(sock):
    """One connection attempt. Returns normally when the session ends
    (board rebooted, script crashed, etc.) so the caller can retry."""
    proc = subprocess.Popen(
        ["sshpass", "-p", BOARD_PASS,
         "ssh", "-T", "-o", "StrictHostKeyChecking=no",
         "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2",
         BOARD_HOST, f"sudo -S python3 {REMOTE_SCRIPT}"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
        bufsize=0,
    )
    proc.stdin.write((BOARD_PASS + "\n").encode())
    proc.stdin.flush()

    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, "ssh")
    sel.register(sock, selectors.EVENT_READ, "udp")

    fwd_count = 0
    print(f"[bridge] session up, forwarding to {UDP_HOST}:{UDP_PORT}", file=sys.stderr)

    buf = b""
    try:
        while True:
            for key, _ in sel.select(timeout=1.0):
                if key.data == "ssh":
                    chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(65536)
                    if not chunk:
                        print("[bridge] ssh session ended", file=sys.stderr)
                        return
                    buf += chunk
                    while len(buf) >= 4:
                        (n,) = struct.unpack_from("<I", buf, 0)
                        if len(buf) < 4 + n:
                            break
                        payload = buf[4:4 + n]
                        buf = buf[4 + n:]
                        sock.sendto(payload, (UDP_HOST, UDP_PORT))
                        fwd_count += 1
                        if fwd_count % 50 == 0:
                            print(f"[bridge] fwd {fwd_count} blocks to QGC", file=sys.stderr)
                elif key.data == "udp":
                    try:
                        data, addr = sock.recvfrom(65536)
                    except BlockingIOError:
                        continue
                    proc.stdin.write(data)
                    proc.stdin.flush()
                    if proc.poll() is not None:
                        print("[bridge] remote process exited", file=sys.stderr)
                        return
                if proc.poll() is not None:
                    print("[bridge] remote process exited", file=sys.stderr)
                    return
    finally:
        sel.close()
        if proc.poll() is None:
            proc.terminate()


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)

    while True:
        if not board_reachable():
            print("[bridge] board unreachable, retrying...", file=sys.stderr)
            time.sleep(RECONNECT_DELAY_S)
            continue
        try:
            run_session(sock)
        except Exception as e:
            print(f"[bridge] session error: {e}", file=sys.stderr)
        print(f"[bridge] reconnecting in {RECONNECT_DELAY_S}s...", file=sys.stderr)
        time.sleep(RECONNECT_DELAY_S)


if __name__ == "__main__":
    main()
