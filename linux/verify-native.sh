#!/usr/bin/env bash
set -euo pipefail

verify_native_tablet() {
    source /etc/os-release
    [[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 26.04 && "${VERSION_CODENAME:-}" == resolute ]] || {
        printf 'REFUSED: expected Ubuntu 26.04/resolute\n' >&2
        return 1
    }
    [[ "$(uname -m)" == aarch64 && "$(dpkg --print-architecture)" == arm64 ]] || {
        printf 'REFUSED: expected native ARM64\n' >&2
        return 1
    }
    local actual_serial expected_serial model compatible root_source root_label
    expected_serial="${LIUQIN_EXPECTED_SERIAL:?A reviewed per-device serial is required}"
    actual_serial="$(tr ' ' '\n' </proc/cmdline | sed -n 's/^androidboot.serialno=//p')"
    [[ "$actual_serial" == "$expected_serial" ]] || {
        printf 'REFUSED: tablet hardware serial does not match\n' >&2
        return 1
    }
    [[ -r /sys/firmware/devicetree/base/model && -r /sys/firmware/devicetree/base/compatible ]] || {
        printf 'REFUSED: native device tree missing\n' >&2
        return 1
    }
    model="$(tr -d '\0' </sys/firmware/devicetree/base/model)"
    compatible="$(tr '\0' '\n' </sys/firmware/devicetree/base/compatible)"
    if ! grep -Fxq 'xiaomi,liuqin' <<<"$compatible"; then
        [[ "$model" == 'Liuqin based on Qualcomm Technologies, Inc SM8475' ]] && grep -Fxq 'qcom,cape-mtp' <<<"$compatible" || {
            printf 'REFUSED: device tree is not a verified liuqin variant\n' >&2
            return 1
        }
    fi
    [[ "$(cat /proc/1/comm)" == systemd && "$(findmnt -n -o FSTYPE /)" == ext4 ]] || {
        printf 'REFUSED: expected installed systemd/ext4 Linux\n' >&2
        return 1
    }
    if systemd-detect-virt --container --quiet; then
        printf 'REFUSED: container is not the native target\n' >&2
        return 1
    fi
    root_source="$(findmnt -n -o SOURCE / | cut -d '[' -f1)"
    root_label="$(lsblk -d -n -o LABEL "$root_source")"
    [[ "$root_label" == LIUQIN_ROOT ]] || {
        printf 'REFUSED: native root partition label does not match\n' >&2
        return 1
    }
    printf 'Verified serial-bound native liuqin Ubuntu/resolute ARM64; graphical and reboot acceptance are separate\n'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    verify_native_tablet
fi
