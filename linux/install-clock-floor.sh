#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

[[ "$EUID" -eq 0 && "$#" -eq 3 && "$1" == --install && "$2" == --epoch && "$3" =~ ^[0-9]+$ ]] || { printf 'Use sudo bash linux/install-clock-floor.sh --install --epoch REVIEWED_UTC_UNIX_SECONDS\n' >&2; exit 2; }
directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
profile=/usr/local/libexec/liuqin-dual/dual-switch.json
serial="$(python3 -I -c 'import json,re; config=json.load(open("/usr/local/libexec/liuqin-dual/dual-switch.json")); serial=config["serial"]; assert re.fullmatch("[A-Za-z0-9]{1,64}",serial); print(serial)')"
export LIUQIN_EXPECTED_SERIAL="$serial"
bash "$directory/verify-native.sh"
destination=/usr/local/libexec/liuqin-clock-floor
[[ ! -e "$destination" && ! -L "$destination" && ! -e /var/lib/liuqin-clock-floor ]] || { printf 'Existing clock installation preserved\n' >&2; exit 1; }
for unit in liuqin-clock-floor.service liuqin-clock-floor-save.service liuqin-clock-floor-save.timer; do
    [[ ! -e "/etc/systemd/system/$unit" && ! -L "/etc/systemd/system/$unit" ]] || { printf 'Existing unit preserved\n' >&2; exit 1; }
done
install -d -m 0755 "$destination"
install -m 0644 "$directory/clock-floor.py" "$directory/verify-native.sh" "$destination/"
python3 -I "$destination/clock-floor.py" initialise --epoch "$3" --profile "$profile"
for unit in liuqin-clock-floor.service liuqin-clock-floor-save.service liuqin-clock-floor-save.timer; do install -m 0644 "$directory/$unit" "/etc/systemd/system/$unit"; done
systemd-analyze verify /etc/systemd/system/liuqin-clock-floor.service /etc/systemd/system/liuqin-clock-floor-save.service /etc/systemd/system/liuqin-clock-floor-save.timer
systemctl daemon-reload
systemctl enable --now liuqin-clock-floor.service liuqin-clock-floor-save.timer
printf 'Software lower-bound persistence installed; not accurate offline wall time, NTP synchronization or hardware RTC repair.\n'
