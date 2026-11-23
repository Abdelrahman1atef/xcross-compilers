#!/usr/bin/env python3
"""Proves a built compiler makes the same iOS code as Flutter's own.

    python3 tool/verify.py --compiler gen_snapshot --reference ref/

<reference> comes from the macOS job (tool/reference.sh): the app.dill a real
`flutter build ios` compiled, the exact gen_snapshot arguments flutter_tools
used (flags.json), and the SHA-256 of the assembly Flutter's official macOS
compiler wrote from it (official.sha256). The built compiler gets the same
input and arguments; its assembly must be byte-identical.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile


def sha256(path):
    with open(path, 'rb') as source:
        return hashlib.sha256(source.read()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--record', help='build-*.json to note the verified SHA-256 in')
    args = parser.parse_args()

    reference = os.path.abspath(args.reference)
    with open(os.path.join(reference, 'flags.json'), encoding='utf-8') as flags_file:
        flags = json.load(flags_file)
    with open(os.path.join(reference, 'official.sha256'), encoding='utf-8') as expected_file:
        expected = expected_file.read().split()[0].strip().lower()
    dill = os.path.join(reference, 'app.dill')

    with tempfile.TemporaryDirectory() as work:
        assembly = os.path.join(work, 'snapshot_assembly.S')
        command = [os.path.abspath(args.compiler), *flags, f'--assembly={assembly}', dill]
        print('+ ' + ' '.join(command), flush=True)
        subprocess.run(command, check=True)
        actual = sha256(assembly)

    print(f'official: {expected}')
    print(f'built:    {actual}')
    if actual != expected:
        raise SystemExit('The built compiler does not match Flutter\'s official compiler.')
    print('Identical to Flutter\'s official compiler.')
    if args.record:
        with open(args.record, encoding='utf-8') as record_file:
            record = json.load(record_file)
        record['verified_sha256'] = actual
        with open(args.record, 'w', encoding='utf-8') as record_file:
            json.dump(record, record_file, indent=2)


if __name__ == '__main__':
    sys.exit(main())
