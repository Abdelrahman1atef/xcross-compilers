#!/usr/bin/env python3
"""Runs a compiler on the reference app.dill with the flow-graph printer on.

    python3 tool/trace_compile.py --compiler gen_snapshot --reference ref/ \\
        [--filter <function>] --out trace.txt

Investigation only (profile compilers: the printer is not in product
builds). Without --filter, writes one line per printed flow graph: the
function and the deopt ids of its Suspend instructions, so two hosts'
traces can be diffed. With --filter, writes the whole printed flow graph of
the matching functions.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--filter', default='')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    reference = os.path.abspath(args.reference)
    with open(os.path.join(reference, 'command.json'), encoding='utf-8') as command_file:
        command = json.load(command_file)
    extra = ['--print-flow-graph', '--print-flow-graph-optimized']
    if args.filter:
        extra.append(f'--print-flow-graph-filter={args.filter}')
    with tempfile.TemporaryDirectory() as out:
        os.makedirs(os.path.join(out, 'App.framework'), exist_ok=True)
        words = [a.replace('{dill}', os.path.join(reference, 'app.dill'))
                 .replace('{out}/', '').replace('{out}', '.') for a in command['args']]
        dill = words.pop()  # The input stays last.
        result = subprocess.run([os.path.abspath(args.compiler), *words, *extra, dill],
                                cwd=out, capture_output=True, text=True, errors='replace')
    text = result.stdout + result.stderr
    print(f'exit {result.returncode}, {len(text.splitlines())} lines printed')

    with open(args.out, 'w', encoding='utf-8') as out_file:
        if args.filter:
            out_file.write(text)
            return
        # Graph headers (*** BEGIN/END CFG, the pass name, ==== function)
        # and every line with a Suspend, nothing else.
        keep = re.compile(r'^\s*(\*\*\*|====)|Suspend')
        previous = ''
        for line in text.splitlines():
            if keep.search(line):
                out_file.write(line + '\n')
            elif previous.lstrip().startswith('*** BEGIN CFG'):
                out_file.write(line + '\n')  # The pass name.
            previous = line


if __name__ == '__main__':
    sys.exit(main())
