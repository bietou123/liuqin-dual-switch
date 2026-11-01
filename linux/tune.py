import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


BASE = Path('/var/lib/liuqin-dual-tuning')
STATE = BASE / 'state.json'
SWAP = BASE / 'swapfile'
SWAP_BYTES = 2 * 1024 ** 3
JOURNAL = Path('/etc/systemd/journald.conf.d/90-liuqin-tuning.conf')
SYSCTL = Path('/etc/sysctl.d/90-liuqin-tuning.conf')
FSTAB = Path('/etc/fstab')
ENVIRONMENT = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/root'}


@contextmanager
def tuning_lock():
    descriptor = os.open('/run/liuqin-dual-tuning.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != 0 or details.st_mode & 0o022:
            raise RuntimeError('Untrusted tuning lock')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another tuning transaction is active') from error
        yield
    finally:
        os.close(descriptor)


def trusted(path, directory=False):
    details = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(details.st_mode) or details.st_uid != 0 or details.st_mode & 0o022:
        raise RuntimeError('Untrusted local root-managed path: ' + str(path))
    for parent in path.parents:
        details = parent.lstat()
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != 0 or details.st_mode & 0o022:
            raise RuntimeError('Untrusted parent directory: ' + str(parent))
    return path


def command(arguments, timeout=60):
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, env=ENVIRONMENT, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Local command failed: ' + ' '.join(arguments) + '\n' + result.stderr[-1500:])
    return result.stdout


def atomic_write(path, content, mode=0o600):
    trusted(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        trusted(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            os.fchmod(temporary.fileno(), mode)
            temporary.write(content.encode('utf-8'))
            temporary.flush()
            os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary_path.unlink(missing_ok=True)


def save(state):
    atomic_write(STATE, json.dumps(state, indent=2) + '\n')


def active_swap():
    return any(line.split()[0] == str(SWAP) for line in Path('/proc/swaps').read_text().splitlines()[1:])


def inspect(serial):
    if not BASE.exists():
        return None
    trusted(BASE, directory=True)
    if not STATE.exists():
        if any(BASE.iterdir()):
            raise RuntimeError('Existing untracked tuning files are preserved')
        return None
    state = json.loads(trusted(STATE).read_text())
    if state.get('version') != 1 or state.get('serial') != serial:
        raise RuntimeError('Tuning state belongs to a different review or device')
    return state


def snapshot(path):
    if path.exists() or path.is_symlink():
        original = trusted(path).read_text()
        mode = path.stat().st_mode & 0o777
    else:
        trusted(path.parent, directory=True)
        original = None
        mode = 0o644
    return {'before': original, 'mode': mode, 'after_sha256': None}


def configure(state, path, content):
    state['files'][str(path)]['after_sha256'] = hashlib.sha256(content.encode()).hexdigest()
    save(state)
    atomic_write(path, content, mode=0o644)


def swap_identity(state):
    details = trusted(SWAP).stat()
    recorded = state.get('swap_identity')
    if not recorded or [details.st_dev, details.st_ino] != recorded or details.st_nlink != 1:
        raise RuntimeError('Owned swapfile was replaced; automatic removal refused')


def apply(serial):
    if not Path('/proc/swaps').is_file():
        raise RuntimeError('This kernel does not expose native swap support')
    previous = inspect(serial)
    if previous:
        raise RuntimeError('Existing tuning state is preserved; inspect status before any change')
    if SWAP.exists() or SWAP.is_symlink():
        raise RuntimeError('Existing swapfile is not owned by this transaction')
    available = os.statvfs('/var/lib')
    if available.f_bavail * available.f_frsize < SWAP_BYTES + 4 * 1024 ** 3:
        raise RuntimeError('Insufficient filesystem headroom for optional swap')
    for directory in (JOURNAL.parent, SYSCTL.parent):
        if not directory.exists():
            trusted(directory.parent, directory=True)
            directory.mkdir(mode=0o755)
        trusted(directory, directory=True)
    original_fstab = trusted(FSTAB).read_text()
    if str(SWAP) in original_fstab:
        raise RuntimeError('An existing swap entry must not be overwritten')
    trusted(BASE.parent, directory=True)
    BASE.mkdir(mode=0o700, exist_ok=True)
    trusted(BASE, directory=True)
    state = {'version': 1, 'serial': serial, 'phase': 'applying', 'swap_identity': None,
             'previous_swappiness': int(Path('/proc/sys/vm/swappiness').read_text()),
             'files': {str(path): snapshot(path) for path in (JOURNAL, SYSCTL, FSTAB)}}
    save(state)
    descriptor = os.open(SWAP, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        details = os.fstat(descriptor)
        state['swap_identity'] = [details.st_dev, details.st_ino]
        save(state)
        os.posix_fallocate(descriptor, 0, SWAP_BYTES)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    command(['/usr/sbin/mkswap', str(SWAP)])
    command(['/usr/sbin/swapon', '--priority', '-10', str(SWAP)])
    configure(state, FSTAB, original_fstab.rstrip('\n') + '\n' + str(SWAP) + ' none swap sw,pri=-10,nofail 0 0\n')
    configure(state, JOURNAL, '[Journal]\nSystemMaxUse=256M\nRuntimeMaxUse=64M\nSystemKeepFree=1G\nMaxRetentionSec=14day\n')
    configure(state, SYSCTL, 'vm.swappiness=10\n')
    command(['/usr/sbin/sysctl', '-w', 'vm.swappiness=10'])
    command(['/usr/bin/systemctl', 'daemon-reload'])
    command(['/usr/bin/systemctl', 'try-restart', 'systemd-journald.service'])
    if not active_swap() or int(Path('/proc/sys/vm/swappiness').read_text()) != 10:
        raise RuntimeError('Runtime tuning did not pass the actual postcondition')
    state['phase'] = 'applied'
    save(state)
    print('Applied 2 GiB swap and bounded logs; original configuration retained for rollback')


def rollback(serial):
    state = inspect(serial)
    if not state or state.get('phase') == 'rolled_back':
        raise RuntimeError('No active owned tuning transaction')
    for filename, details in state['files'].items():
        path = Path(filename)
        if path.exists() or path.is_symlink():
            current = trusted(path).read_text()
            expected = details['after_sha256']
            if current != details['before'] and hashlib.sha256(current.encode()).hexdigest() != expected:
                raise RuntimeError('Later configuration changes preserved: ' + filename)
        elif details['before'] is not None and details['after_sha256'] is not None:
            raise RuntimeError('Configuration removed externally; manual review required: ' + filename)
    if SWAP.exists():
        swap_identity(state)
    if active_swap():
        memory = {line.split(':', 1)[0]: int(line.split()[1]) * 1024
                  for line in Path('/proc/meminfo').read_text().splitlines() if line.split(':', 1)[0] in {'MemAvailable', 'SwapTotal', 'SwapFree'}}
        if memory['MemAvailable'] < memory['SwapTotal'] - memory['SwapFree'] + 256 * 1024 ** 2:
            raise RuntimeError('Not enough memory for safe swapoff; close applications first')
        command(['/usr/sbin/swapoff', str(SWAP)], timeout=120)
    for filename, details in state['files'].items():
        path = Path(filename)
        if details['before'] is None:
            if path.exists():
                trusted(path).unlink()
        else:
            atomic_write(path, details['before'], mode=details['mode'])
    command(['/usr/sbin/sysctl', '-w', 'vm.swappiness=' + str(state['previous_swappiness'])])
    command(['/usr/bin/systemctl', 'daemon-reload'])
    command(['/usr/bin/systemctl', 'try-restart', 'systemd-journald.service'])
    if SWAP.exists():
        swap_identity(state)
        SWAP.unlink()
    state['phase'] = 'rolled_back'
    save(state)
    print('Restored owned configuration; backup record retained, no partition or boot changes')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('status', 'apply', 'rollback'))
    parser.add_argument('--profile', type=Path, default=Path('/usr/local/libexec/liuqin-dual/dual-switch.json'))
    parser.add_argument('--dry-run', action='store_true')
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Authorized local administrator required')
    config = json.loads(trusted(arguments.profile).read_text())
    serial = config.get('serial')
    if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9]{1,64}', serial):
        raise RuntimeError('A reviewed per-device serial is required')
    verifier = Path(__file__).resolve().with_name('verify-native.sh')
    subprocess.run(['/usr/bin/bash', str(verifier)], check=True, stdin=subprocess.DEVNULL,
                   env=dict(ENVIRONMENT, LIUQIN_EXPECTED_SERIAL=serial), timeout=30)
    if arguments.dry_run:
        print('Dry run only: native identity passed; planned 2 GiB swap, swappiness 10, journal 256 MiB; no writes')
        return
    with tuning_lock():
        if arguments.action == 'apply':
            apply(serial)
        elif arguments.action == 'rollback':
            rollback(serial)
        else:
            state = inspect(serial)
            print(json.dumps({'phase': state.get('phase') if state else 'not_applied',
                              'owned_swap_active': active_swap(), 'owned_swap_bytes': SWAP.stat().st_size if SWAP.exists() else 0,
                              'swappiness': int(Path('/proc/sys/vm/swappiness').read_text()),
                              'windows_network_modified': False, 'boot_modified': False}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        sys.exit(1)
