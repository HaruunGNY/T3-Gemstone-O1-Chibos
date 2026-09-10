#pragma once

#include <AP_HAL/AP_HAL.h>
#include "AP_HAL_ChibiOS_K3_Namespace.h"

/*
  Polled, register-level UARTDriver for MAIN_UART6 (GPS's UART, base
  0x02860000 -- see AM67_UART6_BASE in hal_serial_lld.h).

  This does NOT go through the SD1-style ChibiOS SerialDriver/VIM-interrupt
  framework that ChibiOS_K3::UARTDriver wraps: that would need a VIM line
  number for this instance, and unlike UART1_IRQ (211, found empirically)
  there is no confirmed number for UART6. Guessing one and registering a
  handler on it risks silently colliding with whatever real peripheral
  already owns that line -- a wrong THRE workaround is a stalled TX queue,
  a wrong VIM handler is a corrupted, unrelated interrupt path. Polled-only
  sidesteps the question entirely, the same choice already made for SPI0
  (spi_lld_polled_exchange) once its interrupt turned out not to be routed
  to this core at all.

  RX is drained into a small software ring buffer by update(), called once
  per main-loop tick from HAL_ChibiOS_K3::run() (same shape as
  ChibiOS_K3::RCInput::update() for iBus) rather than left to be read
  byte-by-byte straight off the 64-byte hardware FIFO on whatever cadence
  AP_GPS happens to call read(). A burst that lands between two update()
  calls is still captured up to the ring's depth instead of only whatever
  was still sitting in the FIFO when read() next runs.

  TX is a bounded, blocking-per-byte poll of LSR THRE, mirroring the already
  hardware-verified am67_uart1_poll_tx() -- there is no software output
  queue here at all, unlike ChibiOS_K3::UARTDriver, because there is no
  THRE-interrupt-driven drain path to feed one and GPS TX traffic (UBX
  configuration messages) is small and infrequent.
*/
class ChibiOS_K3::GPSUARTDriver : public AP_HAL::UARTDriver
{
public:
    GPSUARTDriver();

    bool is_initialized() override;
    bool tx_pending() override;
    uint32_t txspace() override;

    /*
      Must be overridden, not left to AP_HAL::UARTDriver's `return 0` default.
      AP_GPS's baud auto-detection asks the port what it is currently running
      at before it starts stepping through _baudrates[] (AP_GPS.cpp, the
      `if (dstate->probe_baud == 0) probe_baud = port->get_baud_rate();`
      branch). A driver that answers 0 there wedges detection permanently:
      probe_baud stays 0, so that same branch is taken again on every pass,
      begin(0) is called forever and the table is never reached. Cost one
      hardware session to find -- the symptom is "gps: uart6 begin #N baud=0"
      repeating in the trace with bytes=0 next to it.
    */
    uint32_t get_baud_rate() const override
    {
        return _baudrate;
    }

    // Drains whatever the hardware RX FIFO currently holds into the
    // software ring buffer. Call once per main-loop tick, same as
    // ChibiOS_K3::RCInput::update().
    void update();

    // Cumulative bytes pulled off the hardware RX FIFO since boot, and how
    // many of those were dropped because the software ring was full.
    // Mirrors ChibiOS_K3::RCInput::bytes_seen() -- diff over a reporting
    // window for a live byte rate, health-line material later.
    uint32_t bytes_seen() const
    {
        return _bytes_seen;
    }
    uint32_t overflow_count() const
    {
        return _overflow_count;
    }
    // Hardware RX-FIFO overruns (LSR OE). Distinct from overflow_count():
    // this one means update() is not draining often enough for the line
    // rate, which loses bytes before software ever sees them.
    uint32_t overrun_count() const
    {
        return _overrun_count;
    }

protected:
    void _begin(uint32_t baud, uint16_t rxSpace, uint16_t txSpace) override;
    size_t _write(const uint8_t *buffer, size_t size) override;
    ssize_t _read(uint8_t *buffer, uint16_t count) override;
    void _end() override;
    void _flush() override;
    uint32_t _available() override;
    bool _discard_input() override;

private:
    // 512B: SERIAL_BUFFERS_SIZE-sized, matching the RCInput/iBus queue depth
    // for the same reason -- comfortably more than one main-loop tick's
    // worth of GPS traffic at any baud this port would plausibly use
    // (38400 baud measured working on the Linux-side path -> ~3.8KB/s,
    // ~77 bytes per 20ms SCHED_LOOP_RATE=50 tick).
    static constexpr uint16_t RING_SIZE = 512;

    uint8_t _ring[RING_SIZE];
    volatile uint16_t _head;   // next slot update() will write
    volatile uint16_t _tail;   // next slot _read() will take
    uint32_t _baudrate;        // last non-zero baud actually programmed
    bool _initialized;
    uint32_t _bytes_seen;
    uint32_t _overflow_count;
    uint32_t _overrun_count;
    uint8_t _begin_count;

    void _ring_push(uint8_t b);
    uint16_t _ring_count() const;
};
