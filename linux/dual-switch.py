import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import subprocess
import sys


DIRECTORY = Path('/usr/local/libexec/liuqin-dual')
SWITCHER = Path('/usr/local/sbin/liuqin-switch')
STORE = Path('/var/lib/liuqin/switch')
ENVIRONMENT = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/root'}
PACKAGE_LOCKS = (
    '/var/lib/dpkg/lock-frontend',
    '/var/lib/dpkg/lock',
    '/var/cache/apt/archives/lock',
)


def trusted_file(path):
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_uid != 0 or details.st_mode & 0o022:
        raise RuntimeError(f'拒绝使用非 root 管理的普通文件：{path}')
    for parent in path.parents:
        details = parent.lstat()
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != 0 or details.st_mode & 0o022:
            raise RuntimeError(f'文件目录可被修改或为链接：{parent}')
    return path


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def run(arguments, timeout=90):
    return subprocess.run(
        arguments, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding='utf-8', errors='replace', env=ENVIRONMENT, timeout=timeout,
    )


def running_slot(cmdline):
    values = [word.split('=', 1)[1] for word in cmdline.split()
              if word.startswith(('androidboot.slot_suffix=', 'slot_suffix='))]
    if not values or set(values) != {'_a'}:
        raise RuntimeError('当前不是一致确认的 A 槽；不改槽位，不操作 fallback B 槽')
    return 'a'


@contextmanager
def package_locks():
    descriptors = []
    try:
        for filename in PACKAGE_LOCKS:
            try:
                descriptor = os.open(filename, os.O_RDWR | os.O_NOFOLLOW)
            except FileNotFoundError as error:
                raise RuntimeError(f'维护锁文件缺失，无法可靠保护切换：{filename}') from error
            descriptors.append(descriptor)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RuntimeError(f'软件维护锁不是普通文件：{filename}')
            try:
                fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('APT/dpkg 正在操作软件；请等它结束，不删除锁、不中断升级') from error
        yield
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def maintenance_reasons():
    reasons = []
    packagekit_running = False
    for process in Path('/proc').glob('[0-9]*'):
        try:
            name = (process / 'comm').read_text().strip()
        except (OSError, UnicodeError):
            continue
        if name in {'apt', 'apt-get', 'dpkg', 'unattended-upgr', 'unattended-upgrades'}:
            try:
                command = (process / 'cmdline').read_bytes().split(b'\0')
            except OSError:
                command = []
            if name in {'unattended-upgr', 'unattended-upgrades'} and command == [
                b'/usr/bin/python3',
                b'/usr/share/unattended-upgrades/unattended-upgrade-shutdown',
                b'--wait-for-signal', b'',
            ]:
                continue
            reasons.append(f'软件维护进程正在运行：{name}，PID {process.name}')
        packagekit_running = packagekit_running or name == 'packagekitd'
    if packagekit_running:
        try:
            transactions = run([
                '/usr/bin/busctl', 'call', 'org.freedesktop.PackageKit',
                '/org/freedesktop/PackageKit', 'org.freedesktop.PackageKit', 'GetTransactionList',
            ], timeout=10)
            if transactions.returncode or transactions.stdout.strip() != 'ao 0':
                reasons.append('PackageKit 有事务或事务状态无法确认')
        except (OSError, subprocess.TimeoutExpired):
            reasons.append('无法确认 PackageKit 是否空闲')
    return reasons


def audit_reasons():
    audit = run(['/usr/bin/dpkg', '--audit'])
    if audit.returncode or audit.stdout.strip() or audit.stderr.strip():
        return ['软件包配置尚未完成；先修复并完成当前安装，再切换系统']
    return []


def collect_report(config):
    trusted_file(DIRECTORY / 'verify-native.sh')
    environment = dict(ENVIRONMENT, LIUQIN_EXPECTED_SERIAL=config['serial'])
    native = subprocess.run(
        ['/usr/bin/bash', str(DIRECTORY / 'verify-native.sh')],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=environment, timeout=30,
    )
    if native.returncode:
        raise RuntimeError('原生平板身份检查失败：' + (native.stderr or native.stdout).strip())
    running_slot(Path('/proc/cmdline').read_text())
    blockers = []
    for system in ('ubuntu', 'android'):
        image = trusted_file(STORE / system / 'boot.img')
        sums = trusted_file(STORE / system / 'SHA256SUMS').read_text().split()
        if sums != [config[f'{system}_sha256'], 'boot.img'] or image.stat().st_size > 201326592:
            blockers.append(f'{system} 启动镜像不再符合已审阅版本；不能直接切换')
    trusted_file(SWITCHER)
    switcher_verified = digest(SWITCHER) == config['switcher_sha256']
    boot_store_verified = False
    current = 'unknown'
    if not switcher_verified:
        blockers.append('上游切换程序已变化，需重新审阅；未运行它')
    else:
        verification = run([str(SWITCHER), 'verify', '--dry-run', '--read-only-store'])
        boot_store_verified = verification.returncode == 0
        if not boot_store_verified:
            blockers.append('上游两套镜像/当前 boot_a 回读验证失败：' + verification.stdout.strip())
        for line in verification.stdout.splitlines():
            if line == 'boot_a holds: the Ubuntu image from the store':
                current = 'ubuntu'
            elif line == 'boot_a holds: the Android image from the store':
                current = 'android'
    fallback = Path('/dev/disk/by-partlabel/boot_b').resolve(strict=True)
    fallback_size = run(['/usr/sbin/blockdev', '--getsize64', str(fallback)])
    fallback_verified = (
        stat.S_ISBLK(fallback.stat().st_mode)
        and fallback_size.returncode == 0 and fallback_size.stdout.strip() == '201326592'
        and digest(fallback) == config['boot_b_sha256']
    )
    if not fallback_verified:
        blockers.append('Ubuntu boot_b fallback 与已核验备份不符；不自动修复或改槽')
    capacities = []
    for battery in Path('/sys/class/power_supply').iterdir():
        try:
            if (battery / 'type').read_text().strip() == 'Battery':
                capacities.append(int((battery / 'capacity').read_text()))
        except (OSError, ValueError):
            continue
    capacity = min(capacities) if capacities else None
    if capacity is None or capacity < 30:
        blockers.append('电量无法确认或不足 30%；暂不切换')
    busy = maintenance_reasons()
    blockers.extend(busy)
    try:
        with package_locks():
            if not busy:
                blockers.extend(audit_reasons())
    except (OSError, RuntimeError) as error:
        blockers.append(str(error))
    if config.get('android_return_ready') is not True:
        blockers.append('Android 返程尚未由操作者完成安装和独立验收；默认禁止离开 Ubuntu')
    return {
        'serial': config['serial'], 'running_os': 'ubuntu', 'running_slot': 'a',
        'boot_a_image': current, 'boot_store_verified': boot_store_verified,
        'fallback_verified': fallback_verified, 'battery_percent': capacity,
        'android_return_reviewed': config['android_return_ready'],
        'blocked_by': list(dict.fromkeys(blockers)), 'switch_executed': False,
    }


def report_text(report):
    lines = [
        '小米 Pad 6 Pro 双系统安全检查',
        f"当前运行 Ubuntu；A 槽；下次启动镜像：{report['boot_a_image']}",
        f"两套镜像核验：{report['boot_store_verified']}；B 槽 fallback 核验：{report['fallback_verified']}",
        f"电量：{report['battery_percent']}%",
        f"操作者已独立验收 Android Root 返程：{report['android_return_reviewed']}",
    ]
    if report['blocked_by']:
        lines.append('当前禁止切换：')
        lines.extend('- ' + reason for reason in report['blocked_by'])
    else:
        lines.append('只读检查通过；真实切换仍需保存工作、明确确认并通过管理员认证。')
    lines.append('检查没有刷写、重启、改槽或改电脑网络。')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('check', 'android', 'ubuntu'))
    parser.add_argument('--ack')
    parser.add_argument('--json', action='store_true')
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('请通过桌面入口的管理员授权运行')
    config = json.loads(trusted_file(DIRECTORY / 'dual-switch.json').read_text())
    if not isinstance(config, dict):
        raise RuntimeError('设备配置必须是 root 管理的 JSON 对象')
    serial = config.get('serial')
    if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9]{1,64}', serial):
        raise RuntimeError('请先按本机实际设备填写私有序列号；空模板不可运行')
    for key in ('ubuntu_sha256', 'android_sha256', 'boot_b_sha256', 'switcher_sha256'):
        value = config.get(key)
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
            raise RuntimeError('本机镜像或上游程序 SHA256 未完成审阅：' + key)
    if type(config.get('android_return_ready')) is not bool:
        raise RuntimeError('必须明确填写 Android 返程独立验收状态')
    acknowledgements = {'android': 'ANDROID-ROOT-RETURN', 'ubuntu': 'UBUNTU-REBOOT'}
    if arguments.action != 'check' and arguments.ack != acknowledgements[arguments.action]:
        raise RuntimeError('缺少切换/重启确认；没有运行任何切换命令')
    report = collect_report(config)
    print(json.dumps(report, ensure_ascii=False, indent=2) if arguments.json else report_text(report), flush=True)
    if arguments.action == 'check':
        return 0
    if report['blocked_by']:
        raise RuntimeError('安全检查有阻碍；没有运行任何切换命令')
    with package_locks():
        reasons = maintenance_reasons() + audit_reasons()
        if reasons:
            raise RuntimeError('；'.join(reasons))
        print('开始已确认的真实切换：写入 boot_a，回读核验后重启；不是只读检查。', flush=True)
        completed = subprocess.run(
            [str(SWITCHER), 'to-' + arguments.action], stdin=subprocess.DEVNULL, env=ENVIRONMENT,
        )
        return completed.returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        sys.exit(2)
