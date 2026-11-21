#!/usr/bin/env bash
set -euo pipefail

revision=64900e756efa667774214f9c6b17c113222e01f7
if [[ ! -d openwrt/.git ]]; then
    git clone --depth 1 --branch v25.12.6 https://github.com/openwrt/openwrt.git openwrt
fi
cd openwrt
test "$(git rev-parse HEAD)" = "$revision"

python3 - <<'PY'
from pathlib import Path

root = Path('target/linux/ramips')
source = Path('/work/dts/mt7621_ineauto_yod1800.dts').read_text()
source = source.replace('"ineauto,yod1800", "totolink,x5000r",', '"ineauto,yod1800",')
marker = 'label = "firmware";\n\t\t\t\treg = <0x90000 0xf70000>;\n\t\t\t\tread-only;'
assert source.count(marker) == 1, 'Unexpected firmware partition definition'
(root / 'dts/mt7621_ineauto_yod1800.dts').write_text(source.replace(marker, marker.rsplit('\n', 1)[0]))

profiles = root / 'image/mt7621.mk'
recipe = """
define Device/ineauto_yod1800
  IMAGE_SIZE := 15808k
  UIMAGE_NAME := C8343R-9999
  DEVICE_VENDOR := INEAUTO
  DEVICE_MODEL := YOD1800
  DEVICE_PACKAGES := kmod-mt7915-firmware
endef
TARGET_DEVICES += ineauto_yod1800
"""
if 'define Device/ineauto_yod1800\n' not in profiles.read_text():
    with profiles.open('a') as out:
        out.write(recipe)

network = root / 'mt7621/base-files/etc/board.d/02_network'
rule = '\tineauto,yod1800)\n\t\tucidef_set_interfaces_lan_wan "lan1 lan2" "wan"\n\t\t;;\n'
config = network.read_text()
if rule not in config:
    case = 'case $board in\n'
    assert case in config, 'Unknown board configuration layout'
    network.write_text(config.replace(case, case + rule, 1))
PY

cat > .config <<'CONFIG'
CONFIG_TARGET_ramips=y
CONFIG_TARGET_ramips_mt7621=y
CONFIG_TARGET_ramips_mt7621_DEVICE_ineauto_yod1800=y
CONFIG_TARGET_ROOTFS_SQUASHFS=y
CONFIG_TARGET_ROOTFS_INITRAMFS=y
CONFIG
make defconfig
grep -qx 'CONFIG_TARGET_ramips_mt7621_DEVICE_ineauto_yod1800=y' .config
make -j8
mkdir -p /work/bin/install-candidate
cp bin/targets/ramips/mt7621/*ineauto_yod1800*.bin /work/bin/install-candidate/
