import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time


DIRECTORY = Path('/var/lib/liuqin-clock-floor')
STATE = DIRECTORY / 'utc-floor.json'
MINIMUM = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
MAXIMUM = int(datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp())
ENVIRONMENT = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/root'}


def trusted(path, directory=False):
    details = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(details.st_mode) or details.st_uid != 0 or details.st_mode & 0o022:
        raise RuntimeError('Untrusted root-managed clock path: ' + str(path))
    for parent in path.parents:
        details = parent.lstat()
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != 0 or details.st_mode & 0o022:
            raise RuntimeError('Untrusted clock-state parent')
    return path


def load(serial):
    trusted(DIRECTORY, directory=True)
    if trusted(STATE).stat().st_size > 4096:
        raise RuntimeError('Unexpected clock-state size')
    state = json.loads(STATE.read_text())
    if state.get('version') != 1 or state.get('serial') != serial:
        raise RuntimeError('Clock floor belongs to a different review or device')
    epoch = state.get('epoch')
    if type(epoch) is not int or not MINIMUM <= epoch < MAXIMUM:
        raise RuntimeError('Invalid reviewed UTC lower bound')
    return epoch


def save(serial, epoch):
    if not MINIMUM <= epoch < MAXIMUM:
        raise RuntimeError('Clock is outside the reviewed supported epoch range')
    trusted(DIRECTORY, directory=True)
    if STATE.exists() or STATE.is_symlink():
        trusted(STATE)
    with tempfile.NamedTemporaryFile(dir=DIRECTORY, prefix='.utc-floor.', delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            os.fchmod(temporary.fileno(), 0o600)
            temporary.write((json.dumps({'version': 1, 'serial': serial, 'epoch': epoch}) + '\n').encode())
            temporary.flush()
            os.fsync(temporary.fileno())
            os.replace(temporary_path, STATE)
            directory_descriptor = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary_path.unlink(missing_ok=True)


def synchronized():
    result = subprocess.run(['/usr/bin/chronyc', 'tracking'], capture_output=True, text=True,
                            env=ENVIRONMENT, timeout=5)
    return result.returncode == 0 and bool(re.search(r'^Leap status\s*:\s*Normal\s*$', result.stdout, re.M))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('initialise', 'restore', 'save', 'status'))
    parser.add_argument('--profile', type=Path, default=Path('/usr/local/libexec/liuqin-dual/dual-switch.json'))
    parser.add_argument('--epoch', type=int)
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Authorized local administrator required')
    config = json.loads(trusted(arguments.profile).read_text())
    serial = config.get('serial')
    if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9]{1,64}', serial):
        raise RuntimeError('A reviewed per-device serial is required')
    subprocess.run(['/usr/bin/bash', str(Path(__file__).resolve().with_name('verify-native.sh'))],
                   check=True, stdin=subprocess.DEVNULL,
                   env=dict(ENVIRONMENT, LIUQIN_EXPECTED_SERIAL=serial), timeout=30)
    if arguments.action == 'initialise':
        if arguments.epoch is None or not MINIMUM <= arguments.epoch < MAXIMUM:
            raise RuntimeError('Supply UTC Unix seconds from a separately reviewed trusted clock')
        if DIRECTORY.exists() or DIRECTORY.is_symlink():
            trusted(DIRECTORY, directory=True)
        else:
            trusted(DIRECTORY.parent, directory=True)
            DIRECTORY.mkdir(mode=0o700)
        if STATE.exists() or STATE.is_symlink():
            raise RuntimeError('Existing reviewed clock state preserved')
        save(serial, arguments.epoch)
        print('Initialised a software UTC lower bound; not NTP or hardware RTC repair')
        return
    floor = load(serial)
    current = int(time.time())
    if arguments.action == 'restore':
        advanced = current < floor
        if advanced:
            time.clock_settime(time.CLOCK_REALTIME, floor)
        print(json.dumps({'clock_advanced_to_saved_floor': advanced, 'ntp_sync_claimed': False,
                          'hardware_RTC_written': False}))
    elif arguments.action == 'save':
        if current < floor:
            raise RuntimeError('Regressed clock not persisted; restore or independently synchronize first')
        if current - floor > 2 * 86400 and not synchronized():
            raise RuntimeError('Large unsynchronized jump not persisted')
        save(serial, current)
        print('Saved valid local UTC lower bound; powered-off elapsed time remains unknown')
    else:
        print(json.dumps({'saved_utc_floor': floor, 'current_clock_not_below_floor': current >= floor,
                          'ntp_synchronized': synchronized(), 'hardware_RTC_repair_claimed': False}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        sys.exit(1)
