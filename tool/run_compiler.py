#!/usr/bin/env python3
"""Runs a gen_snapshot with a recorded command and hashes what it writes.

    python3 tool/run_compiler.py --command ref/command.json \\
        --compiler gen_snapshot --dill ref/app.dill --out work/ \\
        --record work/result.json

command.json comes from tool/reference_command.py: "{dill}" becomes the
input and "{out}" the output folder. The record lists the SHA-256 of every
output file, by its name (App.framework/App, app.o, ...).
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys


def sha256(path):
    with open(path, 'rb') as source:
        return hashlib.sha256(source.read()).hexdigest()


def run(command, compiler, dill, out):
    os.makedirs(out, exist_ok=True)
    for name in command['outputs']:
        os.makedirs(os.path.dirname(os.path.join(out, name)) or out, exist_ok=True)
    args = [a.replace('{dill}', dill).replace('{out}', out) for a in command['args']]
    print('+ ' + ' '.join([compiler, *args]), flush=True)
    subprocess.run([compiler, *args], check=True)
    return {name: sha256(os.path.join(out, name)) for name in command['outputs']}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--command', required=True)
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--dill', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--record', required=True)
    args = parser.parse_args()
    with open(args.command, encoding='utf-8') as command_file:
        command = json.load(command_file)
    outputs = run(command, os.path.abspath(args.compiler), os.path.abspath(args.dill),
                  os.path.abspath(args.out))
    with open(args.record, 'w', encoding='utf-8') as record_file:
        json.dump({'outputs': outputs}, record_file, indent=2)
    print(json.dumps(outputs, indent=2))


if __name__ == '__main__':
    sys.exit(main())
