#!/usr/bin/env python3
"""
Host-side bridge for AP_HAL_ChibiOS_K3's IPCUARTDriver (see
ardupilot-emirhan/libraries/AP_HAL_ChibiOS_K3/hwdef/boot/ipc_ring.h for the
wire contract this mirrors). Runs ON THE BOARD (executed remotely by
run_bridge.py on the host, over ssh) since /dev/mem only exposes THIS
board's own physical memory.

Protocol: a 256-byte header (16 used uint32 fields) at IPC_RING_BASE,
followed by two independent byte rings (TX: R5F->host, RX: host->R5F),
each 8192 bytes, power-of-2 sized so a free-running 32-bit index masked
with (SIZE-1) gives the ring offset directly. Every mutable header field
has exactly one writer -- R5F owns tx_head/rx_tail/r5f_alive, this daemon
owns tx_tail/rx_head/host_alive -- so plain loads/stores plus a barrier
(DMB on the firmware side) are sufficient, no atomics needed here either.

Root-caused 2026-08-18 (see chibios_kurma.txt "Bilinen Hata 6"): raw
/dev/mem access on this board's reserved-memory carveouts SIGBUSes unless
every read/write is 8-byte aligned at both ends -- glibc's memcpy uses an
overlapping tail load/store for in-between sizes, which lands on a
non-8-byte-aligned address on what Linux maps as Device-type memory here.
read_aligned()/write_aligned() below round every access out to a multiple
of 8 and trim/splice back, exactly like ring_read.py's fix for the earlier
(now-superseded) mav_ring PoC.

Usage: gem_mavbridge.py <udp_host:udp_port> [--once]
Talks framed length-prefixed blocks over stdin/stdout so the host-side
run_bridge.py can pipe UDP datagrams through an SSH session without a
second network hop from the board.
"""
import mmap
import os
import struct
import sys
import time

IPC_RING_BASE = 0xA1120000
IPC_RING_MAGIC = 0x474D4156  # 'GMAV'
IPC_RING_VERSION = 1
IPC_RING_HDR_SIZE = 256
IPC_RING_DATA_SIZE = 8192
IPC_RING_TX_OFFSET = 0x1000
IPC_RING_RX_OFFSET = 0x3000
IPC_RING_TOTAL_SIZE = 0x10000

# Header field offsets (all uint32 LE, in ipc_ring_hdr_t order)
OFF_MAGIC = 0
OFF_VERSION = 4
OFF_TX_HEAD = 32
OFF_TX_TAIL = 36
OFF_RX_HEAD = 40
OFF_RX_TAIL = 44
OFF_HOST_ALIVE = 60


def read_aligned(mm, start, length):
    if length == 0:
        return b""
    aligned_start = (start // 8) * 8
    front_pad = start - aligned_start
    aligned_end = ((start + length + 7) // 8) * 8
    raw = bytes(mm[aligned_start:aligned_end])
    return raw[front_pad:front_pad + length]


def write_aligned(mm, start, data):
    length = len(data)
    if length == 0:
        return
    aligned_start = (start // 8) * 8
    front_pad = start - aligned_start
    aligned_end = ((start + length + 7) // 8) * 8
    if front_pad == 0 and (aligned_end - aligned_start) == length:
        mm[start:start + length] = data
        return
    buf = bytearray(read_aligned(mm, aligned_start, aligned_end - aligned_start))
    buf[front_pad:front_pad + length] = data
    mm[aligned_start:aligned_end] = bytes(buf)


def read_u32(mm, off):
    return struct.unpack_from("<I", read_aligned(mm, off, 4), 0)[0]


def write_u32(mm, off, value):
    write_aligned(mm, off, struct.pack("<I", value))


class Ring:
    def __init__(self):
        fd = os.open("/dev/mem", os.O_RDWR)
        self.mm = mmap.mmap(fd, IPC_RING_TOTAL_SIZE, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE, offset=IPC_RING_BASE)
        os.close(fd)
        self.our_tx_tail = read_u32(self.mm, OFF_TX_TAIL)
        self.our_rx_head = read_u32(self.mm, OFF_RX_HEAD)

    def valid(self):
        magic = read_u32(self.mm, OFF_MAGIC)
        version = read_u32(self.mm, OFF_VERSION)
        return magic == IPC_RING_MAGIC and version == IPC_RING_VERSION

    def drain_tx(self):
        """Bytes the R5F has queued for us (R5F->host)."""
        tx_head = read_u32(self.mm, OFF_TX_HEAD)
        avail = tx_head - self.our_tx_tail
        if avail == 0 or avail > IPC_RING_DATA_SIZE:
            if avail > IPC_RING_DATA_SIZE:
                # Resync: our tracked tail fell too far behind (another
                # reader raced us, or we were restarted). Must publish the
                # jump too, not just track it locally -- otherwise the R5F
                # still sees the OLD tail and believes the ring is full
                # forever, since it only trusts what's in the header.
                self.our_tx_tail = tx_head - IPC_RING_DATA_SIZE
                write_u32(self.mm, OFF_TX_TAIL, self.our_tx_tail & 0xFFFFFFFF)
            return b""
        mask = IPC_RING_DATA_SIZE - 1
        start = self.our_tx_tail & mask
        if start + avail <= IPC_RING_DATA_SIZE:
            data = read_aligned(self.mm, IPC_RING_TX_OFFSET + start, avail)
        else:
            part1 = IPC_RING_DATA_SIZE - start
            data = (read_aligned(self.mm, IPC_RING_TX_OFFSET + start, part1) +
                    read_aligned(self.mm, IPC_RING_TX_OFFSET, avail - part1))
        self.our_tx_tail = tx_head
        write_u32(self.mm, OFF_TX_TAIL, self.our_tx_tail & 0xFFFFFFFF)
        return data

    def feed_rx(self, data):
        """Bytes for the R5F to receive (host->R5F). Returns bytes accepted."""
        if not data:
            return 0
        rx_tail = read_u32(self.mm, OFF_RX_TAIL)
        used = self.our_rx_head - rx_tail
        if used > IPC_RING_DATA_SIZE:
            used = IPC_RING_DATA_SIZE
        space = IPC_RING_DATA_SIZE - used
        n = min(len(data), space)
        if n <= 0:
            return 0
        mask = IPC_RING_DATA_SIZE - 1
        start = self.our_rx_head & mask
        chunk = data[:n]
        if start + n <= IPC_RING_DATA_SIZE:
            write_aligned(self.mm, IPC_RING_RX_OFFSET + start, chunk)
        else:
            part1 = IPC_RING_DATA_SIZE - start
            write_aligned(self.mm, IPC_RING_RX_OFFSET + start, chunk[:part1])
            write_aligned(self.mm, IPC_RING_RX_OFFSET, chunk[part1:])
        self.our_rx_head += n
        write_u32(self.mm, OFF_RX_HEAD, self.our_rx_head & 0xFFFFFFFF)
        return n

    def tick_alive(self, value):
        write_u32(self.mm, OFF_HOST_ALIVE, value & 0xFFFFFFFF)


def main():
    ring = Ring()
    if not ring.valid():
        sys.stderr.write("ipc ring not valid (magic/version mismatch)\n")
        sys.exit(1)

    alive = 0
    out = sys.stdout.buffer
    inp = sys.stdin.buffer
    inp_fd = inp.fileno()
    os.set_blocking(inp_fd, False)

    while True:
        tx = ring.drain_tx()
        if tx:
            out.write(struct.pack("<I", len(tx)))
            out.write(tx)
            out.flush()

        try:
            incoming = os.read(inp_fd, 65536)
            if incoming:
                ring.feed_rx(incoming)
        except BlockingIOError:
            pass
        except OSError:
            pass

        alive += 1
        ring.tick_alive(alive)
        time.sleep(0.02)


if __name__ == "__main__":
    main()
