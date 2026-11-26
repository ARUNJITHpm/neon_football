# ESP32 sensor bench scaffold

`neon_sensors/neon_sensors.ino` supplies a proposed one-board-per-goal implementation with two ADXL345 sensors: net and frame. **It has not been compiled or flashed.** No Arduino CLI, PlatformIO or C++ toolchain was found in this workspace. Select the actual board, pin the Arduino-ESP32 package/toolchain and record the first build result before treating it as firmware acceptance.

Example pins for a classic ESP32 board; check the selected board and mounting before wiring:

| Signal | Net | Frame |
| --- | --- | --- |
| CS | GPIO25 | GPIO26 |
| INT1 | GPIO32 | GPIO33 |
| SCLK / MISO / MOSI | GPIO18 / GPIO19 / GPIO23 | Shared bus |

Use compatible 3.3 V logic/common ground and confirm the actual breakout power circuitry. Review the datasheet's shared-SPI guidance for the selected wiring. Define a distinct `NEON_DEVICE_ID` and `NEON_GOAL_END` (0 or 1) for each board. Never bind two boards to one ID. Update host device/end configuration accordingly.

Acquisition uses DEVID/readback checks, normal-power 800 Hz, full-resolution ±16 g, stream FIFO, watermark 16, overrun interrupts and atomic XYZ bursts. The loop checks interrupt level as well as the ISR flag. It drains stored samples instead of repeatedly labelling register reads as fresh 1 kHz data. Missing devices are rechecked through heartbeat polling. Saturation, overrun, sensor reinitialization and TX pressure are flagged. Native ADC sample loss from FIFO overrun is unknown, rather than an invented exact count.

Each sensor has separate sample/packet sequences. Timestamps reconstruct FIFO phase from device time and nominal period; the declared 2.5 ms uncertainty is unverified. Actual SPI/FIFO servicing can produce sample-time discontinuities reported by the host. Boot ID changes at restart. Heartbeats carry no data. UART is configured for 460800 baud with bounded TX buffering; insufficient available space drops the packet and leaves a sticky loss flag. Sequence progression exposes that loss. This behavior, USB-UART throughput and shutdown/overflow must be bench-tested.

For 16-sample batches, the format uses 152 bytes/packet. Two 800 Hz channels produce approximately 15,200 bytes/s before health frames; 460800-baud 8N1 nominal capacity is 46,080 bytes/s. This is arithmetic, not a measured fresh-sample or serial capacity result. Capture actual rates, jitter, overflow, voltage and signal clipping on the selected board.

[Protocol and host integration](../../docs/sensor-protocol.md) define explicit little-endian bytes and CRC. The host tests verify 248-byte maximum packets, byte order, CRC, fragmentation and loss recovery. They do **not** compile/execute this serializer. The Arduino serializer uses the same 46-byte header and CRC over length plus payload; compare emitted bytes with host decode at the bench.

Record this for each of the four physical sensors before a match:

| Measurement | Value to fill at venue |
| --- | --- |
| Device / end / role / sensor serial | Pending |
| Mounting position, axis orientation and attachment | Pending |
| ODR, FIFO/IRQ service and measured fresh-sample rate | Pending |
| Quiet baseline RMS, scale/offset, rail clipping and physical self-test | Pending |
| Per-boot marker mapping and measured sample-time uncertainty | Pending |
| UART drops, disconnect/reboot and loose-mount behavior | Pending |

Keep raw UART bytes and receipt indexes for all labelled trials. Post-and-in events must remain possible goals; these sensors cannot establish or reject a whole-ball crossing. Source references: [Analog Devices ADXL345 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/adxl345.pdf), [Espressif device timer](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/esp_timer.html).
