import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


SETTINGS = {
    'org.gnome.desktop.interface/enable-animations': 'false',
    'org.gnome.settings-daemon.plugins.power/sleep-inactive-ac-type': "'nothing'",
}


def setting(identifier, value=None):
    schema, key = identifier.split('/', 1)
    arguments = ['gsettings', 'get' if value is None else 'set', schema, key]
    if value is not None:
        arguments.append(value)
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError('Local desktop setting failed: ' + result.stderr[-1000:])
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('status', 'apply', 'rollback'))
    parser.add_argument('--serial', required=True)
    arguments = parser.parse_args()
    if os.geteuid() == 0 or not re.fullmatch(r'[A-Za-z0-9]{1,64}', arguments.serial):
        raise RuntimeError('Use the logged-in normal user and independently reviewed serial')
    environment = dict(os.environ, LIUQIN_EXPECTED_SERIAL=arguments.serial)
    subprocess.run(['/usr/bin/bash', str(Path(__file__).resolve().with_name('verify-native.sh'))],
                   check=True, env=environment, timeout=30)
    os.environ['XDG_RUNTIME_DIR'] = '/run/user/' + str(os.getuid())
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + os.environ['XDG_RUNTIME_DIR'] + '/bus'
    current = {identifier: setting(identifier) for identifier in SETTINGS}
    if arguments.action == 'status':
        print(json.dumps(current, indent=2))
        return
    home = Path.home().resolve()
    directory = home / '.local/state/liuqin-dual'
    state_path = directory / 'desktop-tuning.json'
    if not directory.resolve().is_relative_to(home) or state_path.is_symlink():
        raise RuntimeError('Untrusted desktop backup path')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state_path.exists():
        details = state_path.stat()
        if details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise RuntimeError('Desktop backup must be user-owned and private')
        state = json.loads(state_path.read_text())
        if state.get('version') != 1 or set(state.get('before', {})) != set(SETTINGS):
            raise RuntimeError('Unexpected desktop backup layout')
    else:
        if arguments.action == 'rollback':
            raise RuntimeError('No owned desktop tuning backup')
        state = {'version': 1, 'before': current}
        descriptor = os.open(state_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as backup:
            json.dump(state, backup, indent=2)
            backup.write('\n')
    for identifier, wanted in SETTINGS.items():
        if arguments.action == 'rollback':
            if current[identifier] not in {wanted, state['before'][identifier]}:
                raise RuntimeError('Later user preference preserved: ' + identifier)
            wanted = state['before'][identifier]
        setting(identifier, wanted)
        if setting(identifier) != wanted:
            raise RuntimeError('Desktop setting postcondition failed: ' + identifier)
    print('Desktop tuning ' + arguments.action + ' verified; battery suspend, locking and remote services unchanged')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        sys.exit(1)
