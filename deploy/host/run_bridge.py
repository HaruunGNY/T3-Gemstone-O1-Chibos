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
import os
import selectors
import socket
import struct
import subprocess
import sys
import time

# Tried in order, first one that answers wins. USB-C gadget first: ~0.3ms
# vs ~10ms over WiFi, and it is up whenever the cable is plugged in.
# gem-o1-harun.local is mDNS. The board's avahi name is pinned in its
# /etc/avahi/avahi-daemon.conf: the default 'gemstone' collides with
# other Gemstone boards on this network, so avahi kept renaming itself
# to gemstone-2/-3 and the plain name resolved to someone else's board.
# The pinned name follows the WiFi DHCP lease wherever the router puts
# it. Override with GEM_BOARD_HOSTS (comma-separated) if neither fits.
BOARD_HOSTS = [
    h.strip() for h in os.environ.get(
        "GEM_BOARD_HOSTS", "192.168.7.2,gem-o1-harun.local"
    ).split(",") if h.strip()
]
BOARD_USER = "gemstone"
BOARD_PASS = "gem"
REMOTE_SCRIPT = "/home/gemstone/gem_mavbridge.py"
UDP_HOST = "127.0.0.1"
UDP_PORT = 14550
RECONNECT_DELAY_S = 3


def pick_host():
    """First reachable entry of BOARD_HOSTS, or None. Probing every
    candidate each reconnect means unplugging the USB cable mid-flight
    just falls through to WiFi on the next retry (and back again when
    it is plugged in), with no config change."""
    for host in BOARD_HOSTS:
        r = subprocess.run(
            ["sshpass", "-p", BOARD_PASS, "ssh", "-T",
             "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3",
             f"{BOARD_USER}@{host}", "echo UP"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            return host
    return None


def run_session(sock, host):
    """One connection attempt. Returns normally when the session ends
    (board rebooted, script crashed, etc.) so the caller can retry."""
    proc = subprocess.Popen(
        ["sshpass", "-p", BOARD_PASS,
         "ssh", "-T", "-o", "StrictHostKeyChecking=no",
         "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2",
         f"{BOARD_USER}@{host}", f"sudo -S python3 {REMOTE_SCRIPT}"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
        bufsize=0,
    )
    proc.stdin.write((BOARD_PASS + "\n").encode())
    proc.stdin.flush()

    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, "ssh")
    sel.register(sock, selectors.EVENT_READ, "udp")

    fwd_count = 0
    print(f"[bridge] session up via {host}, forwarding to {UDP_HOST}:{UDP_PORT}", file=sys.stderr)

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
        host = pick_host()
        if host is None:
            print(f"[bridge] board unreachable on {'/'.join(BOARD_HOSTS)}, "
                  "retrying...", file=sys.stderr)
            time.sleep(RECONNECT_DELAY_S)
            continue
        try:
            run_session(sock, host)
        except Exception as e:
            print(f"[bridge] session error: {e}", file=sys.stderr)
        print(f"[bridge] reconnecting in {RECONNECT_DELAY_S}s...", file=sys.stderr)
        time.sleep(RECONNECT_DELAY_S)


if __name__ == "__main__":
    main()
