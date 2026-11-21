# INEAUTO YOD1800 (CPE-AX1800 V3.0) — OpenWrt Documentation

Comprehensive documentation for OpenWrt device support and hardware enablement on the INEAUTO YOD1800 outdoor dual-band AX1800 access point / repeater. Observations and verified configurations apply to the retail hardware unit with PCB marking `CPE-AX1800 V3.0`.

---

## 1. Hardware Specifications

| Component | Specification | Evidence / Detection |
| :--- | :--- | :--- |
| **Model** | INEAUTO YOD1800 Outdoor Dual-Band AX1800 AP / Repeater | Retail unit housing & manufacturer spec sheet |
| **PCB Marking** | `CPE-AX1800 V3.0` | Silkscreen on internal circuit board |
| **SoC** | MediaTek MT7621AT (MIPS 1004Kc dual-core, 4 VPEs @ 880 MHz) | Bootloader banner & Linux CPU probe |
| **RAM** | 128 MiB DDR3 DRAM (MTK MT7621 DDR controller) | U-Boot DRAM probe & Linux `meminfo` |
| **Storage / Flash** | 16 MiB SPI NOR Flash (Winbond `w25q128bv` / compatible) | SPI bus probe & OEM MTD table |
| **Ethernet** | 2x Gigabit Ethernet ports (PoE-In WAN + LAN), internal MT7530 switch | DSA switch driver probe & link detection |
| **Wireless (Wi-Fi 6)** | MediaTek MT7915E (Dual-Band 802.11ax, 2.4 GHz + 5 GHz), PCIe slot 1 | Linux PCIe enumeration & `mt7915e` driver |
| **Antennas** | 4x external high-gain omnidirectional antennas (2x 2.4 GHz, 2x 5 GHz) | Hardware inspection & RF chain mappings |
| **Bootloader** | MediaTek U-Boot 2018.09 (build Jan 04 2025), boots legacy uImage | UART serial console output |
| **Serial Console** | 115200 8N1, pads labelled VCC / RX / TX / GND. Signal voltage unmeasured | Hardware test capture |
| **Original Firmware** | OpenWrt 23.05 fork (`r24012-d8dd03c46f`), Linux 5.15.162 | Extracted rootfs `/etc/openwrt_release` |

---

[PCB overview](review/media/ineauto-yod1800-pcb.jpg) · [UART close-up](review/media/ineauto-yod1800-uart.jpg) · [Wiki device draft](review/YOD1800-device.dokuwiki.txt) · [Wiki Techdata draft](review/YOD1800-techdata.dokuwiki.txt)

## 2. Flash Partition Layout (16 MiB SPI NOR)

Extracted from OEM V2.6 firmware and verified against running OEM kernel:

| Partition | Start Offset | End Offset | Size | Purpose / Notes |
| :--- | :---: | :---: | :---: | :--- |
| `u-boot` | `0x000000` | `0x030000` | 192 KiB | MediaTek U-Boot SPL + stage 2 bootloader |
| `u-boot-env` | `0x030000` | `0x040000` | 64 KiB | Non-volatile U-Boot environment variables |
| *Unassigned* | `0x040000` | `0x050000` | 64 KiB | Reserved alignment space |
| `factory` | `0x050000` | `0x090000` | 256 KiB | Calibration data, EEPROM, and base MAC addresses |
| `firmware` | `0x090000` | `0x1000000`| ~15.4 MiB | Kernel uImage + XZ squashfs payload |

### MAC Address Allocation
Stored at offset `0x4` in the `factory` partition:
- **Base MAC:** 2.4 GHz Wi-Fi (`phy0`)
- **Base MAC + 1:** 5 GHz Wi-Fi (`phy1`)
- **Base MAC + 2:** LAN Bridge (`br-lan`)
- **Base MAC + 3:** WAN Interface (Port 2 / PoE In)

### GPIO & LED Mappings
- `blue:sys`: GPIO 16 (active-low, system indicator)
- `yellow:status`: GPIO 17 (active-low, signal LED 1: 1–100%)
- `rssi2`: GPIO 8 (active-low, signal LED 2: 25–100%)
- `rssi3`: GPIO 6 (active-low, signal LED 3: 50–100%)
- `rssi4`: GPIO 13 (active-low, signal LED 4: 75–100%)
- `reset` button: GPIO 18 (active-low, `KEY_RESTART`)

---

## 3. Implemented OpenWrt Configurations

Custom board definitions created for OpenWrt 25.12.6 (`ramips/mt7621`):

- **Device Tree Source:** [`dts/mt7621_ineauto_yod1800.dts`](dts/mt7621_ineauto_yod1800.dts)
  - Uses upstream MediaTek MT7621 SoC definitions and Linux 6.12 binding headers.
  - Corrected PCIe reset controller phandles to resolve reset provider probe issues.
  - Declared read-only flags (`0x800` / `MTD_CAP_ROM`) for all flash partitions during development trials.
- **Build recipe:** [Source build script](scripts/build_flash_image.sh). It declares the board target, MT7915 firmware and legacy uImage name `C8343R-9999`.

---

## 4. RAM Boot & Transport Verification

Initial board bring-up used RAM boot at `0x81000000`. The permanent installation was tested later on the same unit.

### TFTP Transport Breakthrough
- **Symptom:** Initial TFTP attempts from U-Boot failed with `ARP Retry count exceeded` even though the physical Gigabit link was established.
- **Observed behavior:** The initial TFTP tests stopped before the server received a read request. Targeted ARP replies from the actual server NIC allowed subsequent transfers. The exact cause of the failed initial ARP exchange remains unverified.
- **Solution:** Injecting periodic ARP replies (`192.168.1.2 is at <PC MAC>`) directly onto the Ethernet interface enabled U-Boot to immediately resolve the server.
- **Benchmark:** The 7,804,787-byte initramfs image transferred in **~1.2 seconds at 6.5 MiB/s**.
- **Checksum Verification:**
  ```text
  => crc32 81000000 771773
  crc32 for 81000000 ... 81771772 ==> 4467d2cb
  ```
  Verified exact match with offline CRC32 `4467d2cb`.

---

## 5. Hardware Validation Results (Trial 2, Linux 6.12.112)

Booting the verified RAM image via `bootm 81000000` produced these hardware observations:

1. **Kernel & Board Identity:**
   - Linux identifies the board as `INEAUTO YOD1800` (`ineauto,yod1800`).
   - Clean boot to root console with zero errors in `dmesg`.
2. **Flash Protection:**
   - All four MTD partitions reported flags `0x800`, with the writable bit clear. SPI Flash remained completely untouched.
   - SPI controller probed cleanly (`spi-mt7621 1e000b00.spi: sys_freq: 220000000`), resolving earlier SPI reset errors.
3. **PCIe & Wireless Subsystem (MT7915E):**
   - Both PCIe endpoints enumerated without reset failures.
   - Bound to `mt7915e` (`0x14c3:0x7915`) and `mt7915e_hif` (`0x14c3:0x7916`).
   - Firmware loaded successfully (WM & WA DEV builds).
   - `phy0` (2.4 GHz): 802.11ax Band 1, Channels 1–14 (2412–2484 MHz), 20 dBm txpower.
   - `phy1` (5 GHz): 802.11ax Band 2, Channels 36–165 (5180–5825 MHz), DFS radar detection active, 20 dBm txpower.
4. **Ethernet & Internal Switch:**
   - Distributed Switch Architecture (DSA) Tree 0 initialized cleanly.
   - Prior `deferred probe` issues on `1e100000.ethernet` fully resolved.
   - `eth0` link operational at 1 Gbps Full Duplex (`carrier=1`).
5. **Functional Access Point (AP) Live Verification:**
   - Router configured in bridged Access Point mode (`br-lan` bridging `wan`, `lan1`, `lan2`, `phy0`, `phy1`).
   - Internal DHCP server disabled; bridge acting as DHCP client to upstream home router.
   - Both Wi-Fi networks (`YOD1800-2.4G` and `YOD1800-5G`) broadcasted simultaneously.
   - The RAM trial reported both SSIDs active. Record client association and throughput per band separately before presenting those as measured results.

---

## 6. Permanent installation tested on CPE-AX1800 V3.0

The native OpenWrt v25.12.6 source build produced a matching initramfs and a 7,667,983-byte squashfs sysupgrade image. The firmware image has legacy uImage name `C8343R-9999` and declares only `ineauto,yod1800` as supported. Build inputs and packaging are in [build_flash_image.sh](scripts/build_flash_image.sh) and [Dockerfile.flash](scripts/Dockerfile.flash).

- Initramfs SHA-256 `6885bfb4f81f12b089c7fe26e4fd57f67c1de8d0f840053df0d3e35e0c22debc`.
- Sysupgrade SHA-256 `02175a3fd287257ff2ee116269b213fec5547d980f4e4fd5669629d66e7b6d17`.

### Recorded procedure

1. Isolate the test device and PC from the home LAN. The native build starts as a router with a DHCP server on LAN. Keep serial access at 115200 8N1 available.
2. At the U-Boot prompt, use the RAM-only TFTP path to load the matching native initramfs to `0x81000000`. Check CRC32 `e4ec3a58` over `0x71e571` bytes before running `bootm 81000000`. These values apply to the artifact above.
3. After boot, confirm `ineauto,yod1800`, the flash map in section 2 and MTD flags. `u-boot`, `u-boot-env` and `factory` are read-only. `firmware` is writable and starts at `0x90000`. Copy the sysupgrade file to `/tmp/yod1800-sysupgrade.bin` and compare the device's SHA-256 to the value above.
4. Run `sysupgrade -T -n /tmp/yod1800-sysupgrade.bin` and require exit status 0. The configuration-preserving test from the earlier RAM trial rejected the transition from compatibility version 1.1 to 1.0. The tested migration uses fresh settings.
5. Run `sysupgrade -n /tmp/yod1800-sysupgrade.bin`. Keep power connected through erase, write and automatic reboot. The console should report completion and U-Boot should start the new image from SPI flash.
6. Verify the board ID, `/rom` on SquashFS, a writable JFFS2 `/overlay`, and the LAN connection. Configure the installed unit before attaching its LAN to a network with an existing DHCP server.

### Results

The first boot from flash identified `ineauto,yod1800` and ran Linux 6.12.112. The installed kernel and complete SquashFS (7,604,966 bytes) matched the build by SHA-256. The installed firmware partition differs from the whole transfer file after that extent, where the filesystem overlay and upgrade metadata reside. Bootloader, environment and factory partitions matched the stock backup byte for byte. Both Wi-Fi PHYs enumerated, and the PC reached the router at `192.168.1.1` over the isolated Ethernet link. A test file on JFFS2 survived a separate software reboot and was removed afterward.

The prior SPI and PCIe reset failures and the Ethernet deferred probe were absent. PCIe bridge BAR allocation warnings remained. The native initramfs also reported missing U-Boot environment configuration and an early NVMEM lookup failure. The observed Ethernet and radio MAC assignments matched the expected values from the factory partition despite these messages. A power-cycle test and client throughput measurements on the installed image remain open.

## 7. Stock backup and publication scope

The full 16 MiB V2.6 flash dump was rechecked against local SHA-256. Keep the dump private. It includes the original bootloader, environment and Wi-Fi calibration data. Entry into U-Boot over UART and starting a CRC-verified rescue initramfs by TFTP were tested. Stock flash write-back and boot were not tested. [INEAUTO lists a separate YOD1800 V1.9 update](https://ineauto.com/pages/firmware). The public guide should include the partition map and verification method, and omit raw dumps, packet captures, MAC addresses and credentials.

### DHCP on an existing home LAN

The installed build initially starts dnsmasq and odhcpd on LAN. Disable LAN DHCP and IPv6 router advertisements before connecting it to an existing LAN in access-point mode. On the tested unit, LAN DHCP was set to ignore, DHCPv6, RA and NDP were disabled, and dnsmasq and odhcpd were stopped and disabled at startup. Ports UDP 67 and 547 had no listeners after the change. The unit retains its static management address 192.168.1.1.
