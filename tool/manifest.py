#!/usr/bin/env python3
"""Writes a release's manifest.json in the format xcross reads (schema 1).

    python3 tool/manifest.py --flutter 3.47.8 --engine <hash> --dart <hash> \\
        --builds dist/ --out dist/manifest.json

Every asset is listed with the SHA-256 of its zip and of the executable in
it; xcross checks both before it uses a compiler.
"""

import argparse
import glob
import json
import os
import sys

HOSTS = ['linux-x64', 'linux-arm64', 'windows-x64', 'windows-arm64']
MODES = ['release', 'profile']


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--flutter', required=True)
    parser.add_argument('--engine', required=True)
    parser.add_argument('--dart', required=True)
    parser.add_argument('--builds', required=True, help='folder with build-*.json')
    parser.add_argument('--out', required=True)
    parser.add_argument('--require-all', action='store_true',
                        help='fail unless every host and mode is there')
    args = parser.parse_args()

    assets = {}
    verification = {}
    for path in sorted(glob.glob(os.path.join(args.builds, '**', 'build-*.json'), recursive=True)):
        with open(path, encoding='utf-8') as record_file:
            record = json.load(record_file)
        assets[record['asset']] = {
            'sha256': record['sha256'],
            'executable_sha256': record['executable_sha256'],
            'size': record['size'],
        }
        if 'verified_sha256' in record:
            verification[record['asset']] = record['verified_sha256']
    if not assets:
        raise SystemExit(f'No build-*.json in {args.builds}')
    if args.require_all:
        missing = [f'gen_snapshot-{m}-{h}.zip' for m in MODES for h in HOSTS
                   if f'gen_snapshot-{m}-{h}.zip' not in assets]
        if missing:
            raise SystemExit('Missing: ' + ', '.join(missing))

    manifest = {
        'schema': 1,
        'flutter': args.flutter,
        'engine': args.engine,
        'dart': args.dart,
        'assets': assets,
        'verification': {
            'reference_app': 'flutter create (iOS), built by Flutter on macOS',
            'assembly_sha256': verification,
        },
    }
    with open(args.out, 'w', encoding='utf-8') as out_file:
        json.dump(manifest, out_file, indent=2)
        out_file.write('\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    sys.exit(main())
