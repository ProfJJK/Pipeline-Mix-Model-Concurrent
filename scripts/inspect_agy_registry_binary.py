"""Read the reviewed PE/Go binary without loading or executing provider code.

This records the instruction anchors used for the 2026-10-13 manual review.
It is not a general disassembler or a native isolation acceptance test.
"""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import struct

PIN = '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
BINARY = Path(r'C:\Program Files\CoChem\Native4.2.7-windows-20261006\agy.exe')
PREFIX = 'google3/third_party/jetski/cli/printmode/printmode.'


def inspect(path=BINARY):
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if hashlib.sha256(data).hexdigest() != PIN:
            raise ValueError('Only the exact reviewed Agy 1.3.1 executable is supported')
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        count = struct.unpack_from('<H', data, pe + 6)[0]
        optional = struct.unpack_from('<H', data, pe + 20)[0]
        sections = []
        for i in range(count):
            h = pe + 24 + optional + 40 * i
            _, va, size, raw = struct.unpack_from('<IIII', data, h + 8)
            sections.append((data[h:h + 8].rstrip(b'\0'), va, size, raw))

        def offset(address):
            return next(raw + address - va for _, va, size, raw in sections if va <= address < va + size)

        text = next(va for name, va, _, _ in sections if name == b'.text')
        table = data.find(b'\xf1\xff\xff\xff\0\0\x01\x08')
        nfunc, _, _, names, _, _, _, funcs = struct.unpack_from('<8Q', data, table + 8)
        entries = {}
        for i in range(nfunc):
            entry, meta = struct.unpack_from('<II', data, table + funcs + i * 8)
            name_offset = struct.unpack_from('<i', data, table + funcs + meta + 4)[0]
            start = table + names + name_offset
            entries[text + entry] = data[start:data.find(b'\0', start)].decode('utf-8')
        addresses = sorted(entries)
        bodies = {}
        evidence = []
        for short in ('buildInitPayload', 'advertisedTools'):
            address = next(a for a, name in entries.items() if name == PREFIX + short)
            end = addresses[addresses.index(address) + 1]
            body = data[offset(address):offset(end)]
            bodies[short] = (address, body)
            evidence.append(dict(function=short, rva=hex(address), bytes=len(body),
                                 sha256=hashlib.sha256(body).hexdigest()))
        caller, _ = bodies['buildInitPayload']
        callee, _ = bodies['advertisedTools']
        if (caller, callee) != (0x2f84340, 0x2f84760):
            raise ValueError('Reviewed function addresses differ')
        # Caller: compare a six-byte mode string to "jetski", set AL to the
        # comparison result (or zero), then CALL advertisedTools.
        mode_test = bytes.fromhex('48837c2478067518488b4c247081396a657473750b668179046b690f94c0eb0231c0')
        if data[offset(0x2f84430):offset(0x2f84452)] != mode_test:
            raise ValueError('Reviewed mode argument instructions differ')
        if data[offset(0x2f84452):offset(0x2f84457)] != bytes.fromhex('e809030000'):
            raise ValueError('Reviewed advertisedTools call differs')
        # Callee: save the Boolean AL argument, then MOV RDX,[RIP+disp32].
        # The registry comes from a fixed global address, not an agent argument.
        if data[offset(0x2f8477d):offset(0x2f8478b)] != bytes.fromhex('88842438010000488b15653d2908'):
            raise ValueError('Reviewed global registry load differs')
        global_registry = 0x2f8478b + struct.unpack_from('<i', data, offset(0x2f84787))[0]
        return dict(schema='cochem-agy-registry-static-review/1', executable_sha256=PIN,
                    method='PE and Go metadata plus manually reviewed x64 instruction anchors',
                    functions=evidence, global_registry_rva=hex(global_registry),
                    caller_argument='Boolean comparison of execution mode with jetski',
                    registry_source='global runner map, not selected-agent tool allowlist',
                    provider_executed=False, protected_state_modified=False,
                    selected_agent_tool_exclusion_host_accepted=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = inspect()
    with args.output.open('x', encoding='utf-8') as out:
        json.dump(value, out, indent=2)
        out.write('\n')
    print(json.dumps(value))
