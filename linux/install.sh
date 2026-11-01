#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

[[ "${1:-}" == --install && "$#" -eq 1 && "$EUID" -eq 0 ]] || { printf 'Use sudo bash linux/install.sh --install\n' >&2; exit 2; }
directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
profile="$directory/dual-switch.json"
[[ -f "$profile" && ! -L "$profile" ]] || { printf 'Fill the private per-device JSON profile first\n' >&2; exit 1; }
serial="$(python3 -I -c 'import json,re,sys; config=json.load(open(sys.argv[1])); serial=config["serial"]; assert isinstance(serial,str) and re.fullmatch("[A-Za-z0-9]{1,64}",serial); print(serial)' "$profile")"
export LIUQIN_EXPECTED_SERIAL="$serial"
bash "$directory/verify-native.sh"
for tool in python3 zenity pkexec blockdev sha256sum; do command -v "$tool" >/dev/null; done
[[ -x /usr/local/sbin/liuqin-switch ]] || { printf 'Reviewed upstream switcher is required\n' >&2; exit 1; }
destination=/usr/local/libexec/liuqin-dual
for target in "$destination" /usr/local/share/liuqin-dual /usr/local/sbin/liuqin-dual-switch /usr/local/bin/liuqin-dual-menu /usr/share/applications/liuqin-dual-switch.desktop /usr/share/polkit-1/actions/io.github.bietou123.liuqin-dual.policy; do
    [[ ! -e "$target" && ! -L "$target" ]] || { printf 'Existing installation preserved: %s\n' "$target" >&2; exit 1; }
done
for input in dual-switch.py verify-native.sh dual-menu.sh liuqin-dual-switch liuqin-dual-switch.desktop liuqin-dual.policy; do
    [[ -f "$directory/$input" && ! -L "$directory/$input" ]] || { printf 'Unexpected source file\n' >&2; exit 1; }
done
install -d -m 0755 "$destination" /usr/local/share/liuqin-dual
install -m 0644 "$directory/dual-switch.py" "$directory/verify-native.sh" "$destination/"
install -m 0600 "$profile" "$destination/dual-switch.json"
install -m 0755 "$directory/liuqin-dual-switch" /usr/local/sbin/liuqin-dual-switch
install -m 0755 "$directory/dual-menu.sh" /usr/local/bin/liuqin-dual-menu
install -m 0644 "$directory/liuqin-dual-switch.desktop" /usr/share/applications/liuqin-dual-switch.desktop
install -m 0644 "$directory/liuqin-dual.policy" /usr/share/polkit-1/actions/io.github.bietou123.liuqin-dual.policy
install -m 0644 "$directory/../README.md" /usr/local/share/liuqin-dual/使用说明.txt
printf 'Installed safety UI; no boot write, reboot, Root installation, package upgrade or network change performed.\n'
