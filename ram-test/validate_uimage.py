#!/usr/bin/env python3
"""Validate the YOD1800 RAM uImage and the device tree embedded in its kernel."""
import argparse
import hashlib
import lzma
import json
import struct
import sys
import zlib
from pathlib import Path


def need(condition, message):
    if not condition:
        raise ValueError(message)


def tree(blob):
    need(len(blob) >= 40, 'truncated FDT header')
    h = struct.unpack_from('>10I', blob)
    magic, total, off_struct, off_strings, _, version, _, _, strings_len, struct_len = h
    need(magic == 0xd00dfeed and version >= 17 and total <= len(blob), 'invalid FDT header')
    need(off_struct + struct_len <= total and off_strings + strings_len <= total, 'invalid FDT bounds')
    strings = blob[off_strings:off_strings + strings_len]
    pos, end, stack, nodes = off_struct, off_struct + struct_len, [], {}
    while pos + 4 <= end:
        token = struct.unpack_from('>I', blob, pos)[0]; pos += 4
        if token == 1:
            stop = blob.find(b'\0', pos, end); need(stop >= 0, 'invalid FDT node')
            name = blob[pos:stop].decode('ascii'); pos = (stop + 4) & ~3
            stack.append(name); nodes['/' + '/'.join(stack[1:])] = {}
        elif token == 2:
            need(bool(stack), 'unbalanced FDT'); stack.pop()
        elif token == 3:
            need(pos + 8 <= end and stack, 'invalid FDT property')
            size, nameoff = struct.unpack_from('>II', blob, pos); pos += 8
            stop = strings.find(b'\0', nameoff); need(stop >= 0 and pos + size <= end, 'invalid FDT property bounds')
            nodes['/' + '/'.join(stack[1:])][strings[nameoff:stop].decode('ascii')] = blob[pos:pos + size]
            pos = (pos + size + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            need(not stack, 'unbalanced FDT'); return nodes
        else:
            raise ValueError('unknown FDT token')
    raise ValueError('missing FDT end')


def cells(data):
    need(len(data) % 4 == 0, 'invalid cells')
    return struct.unpack('>' + 'I' * (len(data) // 4), data)


def main(path, installation_profile=False, sysupgrade=False):
    data = path.read_bytes(); need(len(data) >= 64, 'truncated uImage')
    magic, hcrc, timestamp, size, load, entry, dcrc, os_, arch, typ, comp, name = struct.unpack('>7I4B32s', data[:64])
    need(magic == 0x27051956, 'not a legacy uImage')
    header = bytearray(data[:64]); header[4:8] = b'\0' * 4
    need(zlib.crc32(header) == hcrc, 'uImage header CRC mismatch')
    kernel_end = 64 + size
    if sysupgrade:
        need(len(data) <= 0xf70000, 'image exceeds the firmware partition')
        need(data[kernel_end:kernel_end + 4] == b'hsqs', 'missing SquashFS after uImage')
        fs_size, = struct.unpack_from('<Q', data, kernel_end + 40)
        need(96 <= fs_size <= len(data) - kernel_end, 'invalid SquashFS extent')
        magic, _, kind, length = struct.unpack('>4sIB3xI', data[-16:])
        need(magic == b'FWx0' and kind == 1 and 24 <= length <= len(data) - kernel_end - fs_size, 'invalid fwtool metadata trailer')
        metadata = json.loads(data[-length + 8:-16])
        need(metadata['supported_devices'] == ['ineauto,yod1800'], 'unexpected supported devices')
        print('SquashFS extent, partition fit and supported devices OK')
    else:
        need(len(data) == kernel_end, 'uImage data size mismatch or trailing bytes')
    payload = data[64:kernel_end]; need(zlib.crc32(payload) == dcrc, 'uImage data CRC mismatch')
    need((os_, arch, typ, comp) == (5, 5, 2, 3), 'expected Linux MIPS LZMA kernel uImage')
    kernel = lzma.decompress(payload, format=lzma.FORMAT_ALONE)
    print(f'uImage CRCs OK; load=0x{load:08x}, entry=0x{entry:08x}, sha256={hashlib.sha256(data).hexdigest()}')
    trees = []
    for off in range(len(kernel)):
        if kernel[off:off+4] == b'\xd0\x0d\xfe\xed':
            try:
                t = tree(kernel[off:])
                if b'ineauto,yod1800\0' in t.get('/', {}).get('compatible', b''):
                    trees.append((off, t))
            except (ValueError, UnicodeDecodeError, struct.error):
                continue
    need(len(trees) == 1, f'expected one YOD1800 embedded DTB, found {len(trees)}')
    off, nodes = trees[0]; print(f'YOD1800 DTB found at decompressed offset 0x{off:x}')
    phandles = {cells(p['phandle'])[0]: (n, p) for n, p in nodes.items() if 'phandle' in p}
    def find(compatible):
        found = [(n,p) for n,p in nodes.items() if compatible.encode() + b'\0' in p.get('compatible', b'')]
        need(len(found) == 1, f'expected one {compatible}, found {len(found)}'); return found[0]
    sysname, sysc = find('mediatek,mt7621-sysc')
    need(cells(sysc.get('#reset-cells', b'')) == (1,), 'syscon is not a reset provider')
    def reset(path, expected):
        vals = cells(nodes[path].get('resets', b'')); need(len(vals) == len(expected)*2, f'{path}: invalid resets')
        for i, number in enumerate(expected):
            handle, actual = vals[2*i:2*i+2]
            need(handle in phandles and phandles[handle][0] == sysname and actual == number, f'{path}: wrong reset provider or ID')
    spi, _ = find('ralink,mt7621-spi'); reset(spi, [18])
    eth, _ = find('mediatek,mt7621-eth'); reset(eth, [6, 23])
    pcie, _ = find('mediatek,mt7621-pci')
    for i in range(3): reset(f'{pcie}/pcie@{i},0', [24+i])
    print('SPI, Ethernet, PCIe reset providers and IDs OK')
    parts = {p.get('label', b'').rstrip(b'\0').decode(): p for n,p in nodes.items() if '/partitions/partition@' in n and '/' not in n.split('/partitions/partition@', 1)[1]}
    for label, reg, readonly in [('u-boot',(0,0x30000),True),('u-boot-env',(0x30000,0x10000),True),('factory',(0x50000,0x40000),True),('firmware',(0x90000,0xf70000),not installation_profile)]:
        need(label in parts and cells(parts[label].get('reg', b'')) == reg and ('read-only' in parts[label]) == readonly, f'{label} partition mismatch')
    need(len(parts) == 4, 'unexpected partition map')
    factory = next(n for n,p in nodes.items() if p is parts['factory'])
    for child, reg in [('eeprom@0',(0,0xe00)), ('macaddr@4',(4,6)), ('macaddr@e000',(0xe000,6)), ('macaddr@e006',(0xe006,6))]:
        need(cells(nodes.get(factory + '/nvmem-layout/' + child, {}).get('reg', b'')) == reg, f'factory {child} mismatch')
    wifi, wp = find('mediatek,mt76'); refs = cells(wp.get('nvmem-cells', b''))
    need(len(refs) == 1 and refs[0] in phandles and phandles[refs[0]][0] == factory + '/nvmem-layout/eeprom@0' and wp.get('nvmem-cell-names') == b'eeprom\0', 'Wi-Fi calibration reference mismatch')
    print('Partition offsets, sizes, read-only flags, factory cells and Wi-Fi calibration reference OK')
    print('PASS: structural checks only; device behavior and calibration data still require hardware verification')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--installation-initramfs', action='store_true')
    mode.add_argument('--sysupgrade', action='store_true')
    args = parser.parse_args()
    try: main(args.image, args.installation_initramfs or args.sysupgrade, args.sysupgrade)
    except (OSError, ValueError, lzma.LZMAError, struct.error) as exc:
        print(f'FAIL: {exc}', file=sys.stderr); sys.exit(1)
