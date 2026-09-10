#include <AP_HAL/AP_HAL.h>

#if CONFIG_HAL_BOARD == HAL_BOARD_CHIBIOS_K3

#include "GPSUARTDriver.h"
#include <hal.h>   // AM67_UART6_BASE/CLOCK and the UART_* register macros (TI/AM67/hal_serial_lld.h)
#include "hwdef/boot/trace.h"

using namespace ChibiOS_K3;

// Same register-access convention as hal_serial_lld.c's u_getreg()/u_putreg():
// every register on this IP is 32-bit at stride 4 and must be accessed as
// such (K3 interconnect requirement), so these are not reused verbatim only
// because hal_serial_lld.c keeps them file-static.
static inline uint32_t u6_getreg(uint32_t offset)
{
    return *(volatile uint32_t *)(AM67_UART6_BASE + offset);
}

static inline void u6_putreg(uint32_t offset, uint32_t value)
{
    *(volatile uint32_t *)(AM67_UART6_BASE + offset) = value;
}

GPSUARTDriver::GPSUARTDriver() :
    _head(0),
    _tail(0),
    _baudrate(0),
    _initialized(false),
    _bytes_seen(0),
    _overflow_count(0),
    _overrun_count(0),
    _begin_count(0)
{
}

void GPSUARTDriver::_ring_push(uint8_t b)
{
    const uint16_t next = (uint16_t)((_head + 1) % RING_SIZE);
    if (next == _tail) {
        // Ring full: drop the incoming byte rather than the oldest one
        // already queued -- AP_RCProtocol-style "keep old data, drop new"
        // would still corrupt whatever partial NMEA/UBX frame is being
        // assembled either way, and counting drops here at least makes an
        // overrun (main loop starved for too long) visible on the health
        // line rather than silently desyncing the parser.
        _overflow_count++;
        return;
    }
    _ring[_head] = b;
    _head = next;
}

uint16_t GPSUARTDriver::_ring_count() const
{
    return (uint16_t)((_head + RING_SIZE - _tail) % RING_SIZE);
}

void GPSUARTDriver::_begin(uint32_t baud, uint16_t rxSpace, uint16_t txSpace)
{
    (void)rxSpace;
    (void)txSpace;

    /*
      baud == 0 means "reopen, keep the current rate" -- the AP_HAL
      convention every other backend implements (AP_HAL_ChibiOS keeps
      _baudrate untouched in that case). It must never reach the divisor
      maths: (clock + 0) / 0 is a division by zero, which on this Cortex-R5
      quietly returns 0 rather than trapping, and a 0 written into DLL/DLM
      stops the baud generator dead -- the UART then receives nothing at all,
      with no error anywhere to say why.
    */
    if (baud > 0) {
        _baudrate = baud;
    }
    if (_baudrate == 0) {
        // Nothing valid has ever been programmed. Leave the hardware exactly
        // as it is rather than inventing a rate, and say so: this can only
        // happen if something calls begin(0) before AP_SerialManager's first
        // real begin(SERIAL3_BAUD), which would itself be the bug to fix.
        trace_printf("AP-K3: gps: uart6 begin(0) with no prior baud -- "
                     "hardware left untouched\n");
        return;
    }

    // Same sequence as hal_serial_lld.c's uart_init(): disable, reset FIFOs,
    // program the divisor with DLAB open, close DLAB, re-enable FIFOs, mode
    // select written last (the UART is inert until then, TI-specific).
    // Deliberately no IER bits set -- see the class comment for why this
    // driver never touches the VIM at all.
    const uint32_t divisor =
        (AM67_UART6_CLOCK + (8U * _baudrate)) / (16U * _baudrate);

    u6_putreg(UART_MDR1_OFFSET, UART_MDR1_MODE_DISABLE);
    u6_putreg(UART_FCR_OFFSET, UART_FCR_RXRST | UART_FCR_TXRST);
    u6_putreg(UART_LCR_OFFSET, UART_LCR_8N1 | UART_LCR_DLAB);
    u6_putreg(UART_DLM_OFFSET, (divisor >> 8) & 0xFFU);
    u6_putreg(UART_DLL_OFFSET, divisor & 0xFFU);
    u6_putreg(UART_LCR_OFFSET, UART_LCR_8N1);
    u6_putreg(UART_FCR_OFFSET, UART_FCR_FIFOEN | UART_FCR_RXRST |
                                UART_FCR_TXRST | UART_FCR_RXTRIGGER_8);
    u6_putreg(UART_IER_OFFSET, 0U);
    u6_putreg(UART_MDR1_OFFSET, UART_MDR1_MODE_UART16X);

    _head = 0;
    _tail = 0;
    _initialized = true;

    if (_begin_count < 255) {
        _begin_count++;
    }
    trace_printf("AP-K3: gps: uart6 begin #%u baud=%u divisor=%u\n",
                 (uint32_t)_begin_count, _baudrate, divisor);
}

void GPSUARTDriver::update()
{
    if (!_initialized) {
        return;
    }

    // Bounded like RCInput::update()'s RX_DRAIN_MAX_BYTES: drains a full
    // ring's worth per call at most, so a wedged LSR (stuck reporting DR)
    // cannot turn this into an unbounded loop that starves the rest of the
    // main-loop tick.
    uint16_t drained = 0;
    while (drained < RING_SIZE) {
        const uint32_t lsr = u6_getreg(UART_LSR_OFFSET);

        /*
          Hardware overrun. Counted separately from the software ring's
          overflow because the two mean completely different things and
          only this one was invisible before: OE is the 64-byte RX FIFO
          having been overwritten before update() got to it -- i.e. this
          drain is not running often enough for the line rate -- whereas
          _overflow_count is the ring filling because the CONSUMER
          (AP_GPS) is not reading. Reporting only the latter made a real
          FIFO loss look like a clean link: bytes flowed and a fix even
          appeared, while dropped messages quietly kept the satellite
          count at 0 and the GPS health flag false.
        */
        if ((lsr & UART_LSR_OE) != 0U) {
            _overrun_count++;
        }
        if ((lsr & UART_LSR_DR) == 0U) {
            break;
        }
        const uint8_t b = (uint8_t)(u6_getreg(UART_RBR_OFFSET) & 0xFFU);
        _ring_push(b);
        _bytes_seen++;
        drained++;
    }
}

ssize_t GPSUARTDriver::_read(uint8_t *buffer, uint16_t count)
{
    uint16_t n = 0;
    while (n < count && _tail != _head) {
        buffer[n] = _ring[_tail];
        _tail = (uint16_t)((_tail + 1) % RING_SIZE);
        n++;
    }
    return (ssize_t)n;
}

uint32_t GPSUARTDriver::_available()
{
    return (uint32_t)_ring_count();
}

bool GPSUARTDriver::_discard_input()
{
    _tail = _head;
    return true;
}

size_t GPSUARTDriver::_write(const uint8_t *buffer, size_t size)
{
    // Bounded blocking poll of LSR THRE per byte, mirroring the
    // hardware-verified am67_uart1_poll_tx() -- GPS TX traffic (UBX
    // configuration messages) is small and infrequent, so there is no
    // software output queue to feed here, unlike ChibiOS_K3::UARTDriver.
    size_t i;
    for (i = 0; i < size; i++) {
        uint32_t tries = 0;
        while ((u6_getreg(UART_LSR_OFFSET) & UART_LSR_THRE) == 0U) {
            if (++tries > 100000U) {
                return i;
            }
        }
        u6_putreg(UART_THR_OFFSET, (uint32_t)buffer[i]);
    }
    return i;
}

void GPSUARTDriver::_flush()
{
    // Nothing queued in software to push (see _write()); just wait, bounded,
    // for the transmitter to actually go idle so a caller that flushes
    // before e.g. a baud-rate change does not race the last byte still in
    // the shift register.
    uint32_t tries = 0;
    while ((u6_getreg(UART_LSR_OFFSET) & (UART_LSR_THRE | UART_LSR_TEMT)) !=
           (UART_LSR_THRE | UART_LSR_TEMT)) {
        if (++tries > 100000U) {
            break;
        }
    }
}

void GPSUARTDriver::_end()
{
    u6_putreg(UART_IER_OFFSET, 0U);
    u6_putreg(UART_MDR1_OFFSET, UART_MDR1_MODE_DISABLE);
    _initialized = false;
}

bool GPSUARTDriver::is_initialized()
{
    return _initialized;
}

bool GPSUARTDriver::tx_pending()
{
    return (u6_getreg(UART_LSR_OFFSET) & (UART_LSR_THRE | UART_LSR_TEMT)) !=
           (UART_LSR_THRE | UART_LSR_TEMT);
}

uint32_t GPSUARTDriver::txspace()
{
    // No software output queue (see _write()) -- writes block, bounded, on
    // the hardware directly, so there is no backlog depth to report. A
    // generous constant keeps GCS/AP_GPS callers that check this before
    // writing from ever being told to defer a short UBX configuration
    // message.
    return 128;
}

#endif // CONFIG_HAL_BOARD == HAL_BOARD_CHIBIOS_K3
