#!/usr/bin/env python3
"""Run in Docker: see scripts/build_ram_image.ps1. Download and verify release inputs."""
import hashlib
import lzma
import os
from pathlib import Path
import struct
import subprocess
import tarfile
import tempfile
import urllib.request
import zlib

ROOT = Path('/work')
BASE = 'https://downloads.openwrt.org/releases/25.12.6/targets/ramips/mt7621/'
IB = 'openwrt-imagebuilder-25.12.6-ramips-mt7621.Linux-x86_64.tar.zst'
IMAGE = 'openwrt-25.12.6-ramips-mt7621-totolink_x5000r-initramfs-kernel.bin'
LINUX = 'linux-6.12.112.tar.xz'
INPUTS = [(BASE + IB, IB, '4c8b3874b686077372839bc246d5f40e822a0082747dfbb181940e158089c2d5'),
          (BASE + IMAGE, IMAGE, '3cf58a77ea376641edce5b2934d291d103b4a816d1660265d2c5c42f87e14420'),
          ('https://cdn.kernel.org/pub/linux/kernel/v6.x/' + LINUX, LINUX, '164dc9d1f6c93c61a15e1f071c48379b467f2b17c469cce7223471968208ed03')]

def digest(data): return hashlib.sha256(data).hexdigest()
def run(*args, **kwargs): subprocess.run(args, check=True, **kwargs)
def uimage_check(data):
    assert len(data) >= 64
    magic, hcrc, timestamp, size, load, entry, dcrc = struct.unpack('>7I', data[:28])
    assert magic == 0x27051956 and size == len(data)-64
    h = bytearray(data[:64]); h[4:8] = b'\0'*4
    assert zlib.crc32(h) == hcrc and zlib.crc32(data[64:]) == dcrc
    assert (load, entry, data[28:32]) == (0x80001000, 0x80001000, bytes([5, 5, 2, 3]))

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for url, name, expected in INPUTS:
        target = ROOT / 'build' / name
        target.parent.mkdir(exist_ok=True)
        cached = target
        if cached.is_file() and digest(cached.read_bytes()) == expected:
            pass
        else:
            print('Downloading', url, flush=True)
            urllib.request.urlretrieve(url, target)
        assert digest(target.read_bytes()) == expected, f'Bad SHA-256: {name}'
        print('Verified', name, expected, flush=True)
    # Extract only the release's mt7621.dtsi, and Linux's binding headers.
    dtsi = 'openwrt-imagebuilder-25.12.6-ramips-mt7621.Linux-x86_64/target/linux/ramips/dts/mt7621.dtsi'
    run('tar', '--zstd', '-xf', str(ROOT / 'build' / IB), '-C', str(tmp), dtsi)
    with tarfile.open(ROOT / 'build' / LINUX, 'r:xz') as tar:
        members = [m for m in tar.getmembers() if (m.name.startswith('linux-6.12.112/include/dt-bindings/') or m.name == 'linux-6.12.112/include/uapi/linux/input-event-codes.h') and m.isfile()]
        for member in members:
            destination = tmp / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(tar.extractfile(member).read())
    (tmp / 'linux-6.12.112/include/dt-bindings/input/linux-event-codes.h').write_bytes(
        (tmp / 'linux-6.12.112/include/uapi/linux/input-event-codes.h').read_bytes())
    source = ROOT / 'dts/mt7621_ineauto_yod1800.dts'
    preprocessed, dtb = tmp / 'device.dts', tmp / 'device.dtb'
    run('cpp', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp',
        '-I', str((tmp / dtsi).parent), '-I', str(tmp / 'linux-6.12.112/include'),
        str(source), '-o', str(preprocessed))
    run('dtc', '-I', 'dts', '-O', 'dtb', '-o', str(dtb), str(preprocessed))
    original = (ROOT / 'build' / IMAGE).read_bytes(); uimage_check(original)
    kernel = lzma.decompress(original[64:], format=lzma.FORMAT_ALONE)
    # Select a structurally valid trailing FDT, not an incidental magic in kernel data.
    candidates = []
    for i in range(len(kernel)-40):
        if kernel[i:i+4] == b'\xd0\x0d\xfe\xed':
            size = struct.unpack_from('>I', kernel, i+4)[0]
            if size >= 40 and i + size == len(kernel): candidates.append(i)
    assert len(candidates) == 1, f'Expected one trailing FDT: {candidates}'
    offset = candidates[0]
    old = tmp / 'original.dtb'; old.write_bytes(kernel[offset:])
    run('dtc', '-I', 'dtb', '-O', 'dts', '-o', os.devnull, str(old))
    combined = kernel[:offset] + dtb.read_bytes()
    packed = lzma.compress(combined, format=lzma.FORMAT_ALONE, filters=[{'id': lzma.FILTER_LZMA1, 'lc': 1, 'lp': 2, 'pb': 2, 'dict_size': 8388608}])
    payload = tmp / 'payload.lzma'; payload.write_bytes(packed)
    output = ROOT / 'bin/YOD1800-ram-v2.bin'; output.parent.mkdir(exist_ok=True)
    # mkimage timestamp is controlled for reproducible output.
    env = dict(os.environ, SOURCE_DATE_EPOCH='0')
    run('mkimage', '-A', 'mips', '-O', 'linux', '-T', 'kernel', '-C', 'lzma', '-a', '0x80001000', '-e', '0x80001000', '-n', 'C8343R-9999', '-d', str(payload), str(output), env=env)
    result = output.read_bytes(); uimage_check(result)
    rebuilt = lzma.decompress(result[64:], format=lzma.FORMAT_ALONE)
    assert rebuilt[:offset] == kernel[:offset] and rebuilt[offset:] == dtb.read_bytes()
    decoded = subprocess.check_output(['dtc', '-I', 'dtb', '-O', 'dts', str(dtb)], text=True)
    assert 'ineauto,yod1800' in decoded and 'label = "firmware";' in decoded
    assert 'read-only;' in decoded.split('label = "firmware";', 1)[1].split('};', 1)[0]
    print('Kernel bytes preserved:', offset)
    print('Output SHA-256:', digest(result), 'size:', len(result))
