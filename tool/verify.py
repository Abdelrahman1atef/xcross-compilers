#!/usr/bin/env python3
"""Proves a built compiler makes the same iOS code as Flutter's own.

    python3 tool/verify.py --compiler gen_snapshot --reference ref/ \\
        [--record dist/build-release-linux-x64.json]

<reference> comes from the macOS job (tool/reference.sh): the app.dill a real
`flutter build ios` compiled, the exact gen_snapshot command flutter_tools
ran (command.json), and the SHA-256 of every file Flutter's official
compiler wrote from it (official.json: App and app.o for Mach-O builds).
The built compiler runs the same command on the same input; every file it
writes must be byte-identical.
"""

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_compiler import run  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--record', help='build-*.json to note the verified SHA-256s in')
    args = parser.parse_args()

    reference = os.path.abspath(args.reference)
    with open(os.path.join(reference, 'command.json'), encoding='utf-8') as command_file:
        command = json.load(command_file)
    with open(os.path.join(reference, 'official.json'), encoding='utf-8') as official_file:
        expected = json.load(official_file)['outputs']

    with tempfile.TemporaryDirectory() as work:
        actual = run(command, os.path.abspath(args.compiler),
                     os.path.join(reference, 'app.dill'), os.path.join(work, 'out'))

    different = []
    for name, digest in expected.items():
        print(f'{name}\n  official: {digest}\n  built:    {actual.get(name)}')
        if actual.get(name) != digest:
            different.append(name)
    if different:
        raise SystemExit('Not identical to Flutter\'s official compiler: ' + ', '.join(different))
    print('Identical to Flutter\'s official compiler.')
    if args.record:
        with open(args.record, encoding='utf-8') as record_file:
            record = json.load(record_file)
        record['verified_sha256'] = actual
        with open(args.record, 'w', encoding='utf-8') as record_file:
            json.dump(record, record_file, indent=2)


if __name__ == '__main__':
    sys.exit(main())
