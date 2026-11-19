"""Linux, Python 3.10+. Benchmark three independent Ganak builds on unpacked Track 1 inputs."""
import argparse
import csv
import hashlib
import lzma
import os
from pathlib import Path
import random
import re
import resource
import shutil
import signal
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

FIELDS = 'year id rep cpu mode limit status wall cpu_seconds rss_kib count'.split()

def run_case(job):
    year, instance, source, core, repetition, cutoff, builds, memory_bytes = job
    os.sched_setaffinity(0, {core})
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    order = list(builds)
    random.Random(110937 + year * 91 + instance).shuffle(order)
    if repetition % 2:
        order.reverse()
    results = []
    answers = set()
    with tempfile.TemporaryDirectory() as directory:
        cnf = Path(directory) / 'input.cnf'
        with lzma.open(source) as compressed, cnf.open('wb') as plain:
            shutil.copyfileobj(compressed, plain)
        for mode in order:
            exe, libraries = builds[mode]
            env = os.environ.copy()
            if libraries:
                env['LD_LIBRARY_PATH'] = libraries + ':' + env.get('LD_LIBRARY_PATH', '')
            command = [exe, '--threads', '1', '--prob', '0', '--verb', '1']
            if mode != 'stock':
                command += ['--frontierstates', '8192', '--groupedsweep', '0']
            with tempfile.TemporaryFile(dir=directory) as log:
                started = time.monotonic()
                with subprocess.Popen(command + [cnf], env=env, stdout=log, stderr=subprocess.STDOUT) as process:
                    expired = False
                    def on_timeout(*args):
                        nonlocal expired
                        expired = True
                        process.kill()
                    old_handler = signal.signal(signal.SIGALRM, on_timeout)
                    signal.alarm(cutoff)
                    try:
                        _, status, usage = os.wait4(process.pid, 0)
                    finally:
                        signal.alarm(0)
                        signal.signal(signal.SIGALRM, old_handler)
                    process.returncode = os.waitstatus_to_exitcode(status)
                elapsed = time.monotonic() - started
                log.seek(0)
                text = log.read().decode(errors='replace')
            exact = re.search(r'^c s exact arb int (\d+)\s*$', text, re.M)
            if expired:
                state = 'timeout'
            elif exact and process.returncode in (0, 10, 20):
                state = 'solved'
            elif re.search(r'bad_alloc|out of memory|cannot allocate memory|bad_array_new_length', text, re.I):
                state = 'memory'
            else:
                raise RuntimeError(f'{year}/{instance:03} {mode} exited {process.returncode}\n{text[-2000:]}')
            count = exact[1] if state == 'solved' else ''
            if count:
                answers.add(count)
            results.append([year, instance, repetition, core, mode, cutoff, state, round(elapsed,5),
                            round(usage.ru_utime + usage.ru_stime,5), usage.ru_maxrss, count])
    if len(answers) > 1:
        raise RuntimeError(f'Exact counts disagree on {year}/{instance:03}')
    return results

if __name__ == '__main__':
    import json
    import sys
    key = sys.argv[1]
    meta = json.loads(Path('pilot/cases.json').read_text())[key]
    path = Path('inputs') / (key + '.cnf.xz')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == meta['sha256']
    builds = {name: (Path(name).resolve() / 'ganak', str(Path(name).resolve()))
              for name in ('stock', 'previous', 'pushed')}
    year, _, number = key.split('_')
    rows = run_case((int(year[2:]), int(number), path, min(os.sched_getaffinity(0)),
                     0, 3600, builds, 9_000_000_000))
    with Path(key + '.csv').open('w') as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    for row in rows:
        print(row[:10], flush=True)
        if meta['count'] is not None and row[6] == 'solved':
            assert row[-1] == meta['count'], key
