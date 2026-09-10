#!/usr/bin/env python3
"""
Board-native daemon for AP_HAL_ChibiOS_K3's storage IPC -- see
ardupilot-emirhan/libraries/AP_HAL_ChibiOS_K3/hwdef/boot/ipc_storage.h for
the wire contract this mirrors ("gem-storaged" in that file's comments).

Runs ON THE BOARD ITSELF as a systemd service (gem-storaged.service,
started at sysinit.target, see deploy/systemd-board/) -- NOT launched
over SSH from the host. Unlike gem_mavbridge.py (which genuinely is
host-side), this one must have zero network/SSH dependency: an earlier
SSH-triggered version raced ArduCopter's 60-second storage-wait window
after reboot and once permanently destroyed a real calibration by
persisting a blank image over it. See the README for the full story.

Without this, AP_HAL_ChibiOS_K3 falls back to Empty::Storage: every
parameter/calibration write is silently discarded, and everything resets
to defaults on the next boot -- exactly the "ARMING_CHECK isn't in the
parameters, my calibration disappeared after reboot" symptom this fixes.

Persists to a file ON THE BOARD (not the host) -- gem_storage.bin next to
this script, /home/gemstone/, survives reboots and matches the wire
contract's own reasoning ("a file on eMMC" -- the vehicle's own storage,
not something tied to whichever dev host happens to be plugged in).

Protocol: bulk sync, not incremental. The R5F bumps dirty_seq after any
change to the shared 16 KiB image; this daemon notices, reads the WHOLE
image back, writes it to disk, then publishes saved_seq = that dirty_seq.
Simpler than the MAVLink ring (no wraparound), and per ipc_storage.h's own
reasoning a 16 KiB write costs about a millisecond and parameter writes
are rare/bursty, so there is no need for anything smarter.

Same /dev/mem alignment rule as gem_mavbridge.py applies (see that file's
read_aligned/write_aligned docstring) -- reused verbatim here.
"""
import mmap
import os
import struct
import sys
import time

IPC_RING_BASE = 0xA1120000
IPC_STORAGE_CTRL_OFFSET = 0x5000
IPC_STORAGE_DATA_OFFSET = 0x6000
IPC_STORAGE_MAGIC = 0x47535452  # 'GSTR'
IPC_STORAGE_VERSION = 1
IPC_STORAGE_SIZE = 16384
MAP_LEN = 0x10000  # whole 64 KiB ipc window, storage lives inside it

STORAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gem_storage.bin")

# Control block field offsets from IPC_STORAGE_CTRL_OFFSET (all uint32 LE)
OFF_MAGIC = 0
OFF_VERSION = 4
OFF_SIZE = 8
OFF_HOST_READY = 12
OFF_LOAD_SEQ = 16
OFF_DIRTY_SEQ = 20
OFF_SAVED_SEQ = 24
OFF_HOST_ALIVE = 28
OFF_WRITE_ERRS = 32


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
    write_aligned(mm, off, struct.pack("<I", value & 0xFFFFFFFF))


def ctrl(off):
    return IPC_STORAGE_CTRL_OFFSET + off


def load_or_init_image():
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE, "rb") as f:
            data = f.read()
        if len(data) == IPC_STORAGE_SIZE:
            return data
        sys.stderr.write(f"gem_storage.bin wrong size ({len(data)}), reinitializing\n")
    # Fresh/erased EEPROM convention is 0xFF, not 0x00 -- matches what a
    # real never-written EEPROM reads back as, which is what AP_Param's
    # used-bitmap logic expects to see the first time.
    data = bytes([0xFF]) * IPC_STORAGE_SIZE
    with open(STORAGE_FILE, "wb") as f:
        f.write(data)
    return data


def main():
    fd = os.open("/dev/mem", os.O_RDWR)
    mm = mmap.mmap(fd, MAP_LEN, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=IPC_RING_BASE)
    os.close(fd)

    magic = read_u32(mm, ctrl(OFF_MAGIC))
    version = read_u32(mm, ctrl(OFF_VERSION))
    if magic != IPC_STORAGE_MAGIC or version != IPC_STORAGE_VERSION:
        sys.stderr.write(f"storage ipc not valid yet (magic={magic:#x} version={version})\n")
        sys.exit(1)

    image = load_or_init_image()
    write_aligned(mm, IPC_STORAGE_DATA_OFFSET, image)

    load_seq = 1
    write_u32(mm, ctrl(OFF_LOAD_SEQ), load_seq)
    write_u32(mm, ctrl(OFF_HOST_READY), 1)
    print(f"[storaged] loaded {len(image)} bytes from {STORAGE_FILE}, published ready", file=sys.stderr)

    last_saved_seq = -1
    alive = 0
    write_errs = 0
    while True:
        dirty_seq = read_u32(mm, ctrl(OFF_DIRTY_SEQ))
        if dirty_seq != last_saved_seq:
            data = read_aligned(mm, IPC_STORAGE_DATA_OFFSET, IPC_STORAGE_SIZE)
            try:
                tmp = STORAGE_FILE + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, STORAGE_FILE)
                last_saved_seq = dirty_seq
                write_u32(mm, ctrl(OFF_SAVED_SEQ), dirty_seq)
                print(f"[storaged] synced dirty_seq={dirty_seq}", file=sys.stderr)
            except OSError as e:
                write_errs += 1
                write_u32(mm, ctrl(OFF_WRITE_ERRS), write_errs)
                sys.stderr.write(f"write failed: {e}\n")

        alive += 1
        write_u32(mm, ctrl(OFF_HOST_ALIVE), alive)
        time.sleep(0.3)


if __name__ == "__main__":
    main()
