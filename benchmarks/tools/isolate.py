#!/usr/bin/env python3
"""Run local benchmark commands with Landlock file boundaries and no sockets.

Linux x86_64, Landlock ABI >= 3. This launcher is for local execution tools;
model API transport stays in the trusted orchestrator, outside this process.
"""
import argparse
import ctypes as C
import errno
import os
from pathlib import Path
import platform
import sys


def restrict(project, runtime):
    if platform.machine() != 'x86_64':
        raise RuntimeError('this launcher supports Linux x86_64 only')
    libc = C.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError('Landlock ABI >= 3 is required; refusing unisolated execution')
    all_fs = (1 << 15) - 1
    read = (1 << 0) | (1 << 2) | (1 << 3)
    class Ruleset(C.Structure):
        _fields_ = [('fs', C.c_uint64)]
    class PathRule(C.Structure):
        _pack_ = 1
        _fields_ = [('access', C.c_uint64), ('parent', C.c_int)]
    def check(value):
        if value < 0:
            raise OSError(C.get_errno(), os.strerror(C.get_errno()))
        return value
    attr = Ruleset(all_fs)
    fd = check(libc.syscall(444, C.byref(attr), C.sizeof(attr), 0))
    def allow(path, access):
        path = Path(path)
        if not path.exists():
            return
        if not path.is_dir():
            access &= (1 << 0) | (1 << 1) | (1 << 2) | (1 << 14)
        parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            rule = PathRule(access, parent)
            check(libc.syscall(445, fd, 1, C.byref(rule), 0))
        finally:
            os.close(parent)
    for path in ['/usr', '/bin', '/sbin', '/lib', '/lib64', runtime,
                 '/etc/ld.so.cache', '/etc/localtime', '/etc/nsswitch.conf',
                 '/etc/passwd', '/etc/group', '/proc/cpuinfo', '/proc/meminfo',
                 '/sys/devices/system/cpu', '/dev/urandom', '/dev/random']:
        allow(path, read)
    allow('/dev/null', read | (1 << 1))
    allow(project, all_fs)
    check(libc.prctl(38, 1, 0, 0, 0))  # no_new_privs
    check(libc.syscall(446, fd, 0))
    os.close(fd)
    # Deny new socket() calls; no model/network credentials enter this process.
    class Filter(C.Structure):
        _fields_ = [('code', C.c_ushort), ('jt', C.c_ubyte), ('jf', C.c_ubyte), ('k', C.c_uint)]
    class Program(C.Structure):
        _fields_ = [('length', C.c_ushort), ('filters', C.POINTER(Filter))]
    # Enforce x86_64, reject socket and x32 ABI; socketpair remains available.
    rules = (Filter * 8)(Filter(0x20, 0, 0, 4), Filter(0x15, 1, 0, 0xc000003e),
        Filter(0x06, 0, 0, 0x80000000), Filter(0x20, 0, 0, 0),
        Filter(0x35, 1, 0, 0x40000000), Filter(0x15, 0, 1, 41),
        Filter(0x06, 0, 0, 0x00050000 | errno.EPERM), Filter(0x06, 0, 0, 0x7fff0000))
    check(libc.prctl(22, 2, C.byref(Program(len(rules), rules)), 0, 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    runtime = Path(__file__).resolve().parents[1] / '.runtime'
    command = args.command
    if command[:1] == ['--']:
        command = command[1:]
    if not command:
        parser.error('provide a command after the project path')
    for name in ['.home', '.tmp']:
        (project / name).mkdir(exist_ok=True)
    os.chdir(project)
    env = {'PATH': f'{runtime}/python/bin:{runtime}/cmake/bin:/usr/bin:/bin',
           'HOME': str(project / '.home'), 'TMPDIR': str(project / '.tmp'),
           'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONNOUSERSITE': '1',
           'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
           'MPLCONFIGDIR': str(project / '.home/matplotlib'),
           'PYTHONPATH': ':'.join(str(project / p) for p in
               ['source/src/deepstack', 'source/src/tilesight', 'source/tests'])}
    restrict(project, runtime)
    os.execvpe(command[0], command, env)


if __name__ == '__main__':
    main()
