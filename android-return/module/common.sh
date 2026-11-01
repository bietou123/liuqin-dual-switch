#!/system/bin/sh

die() { printf '已停止：%s\n' "$*" >&2; exit 1; }
checksum() { sha256sum "$1" | cut -d ' ' -f 1; }
trusted() {
    [ -f "$1" ] && [ ! -L "$1" ] || die '预期文件缺失或为链接'
    [ "$(stat -c %u "$1")" = 0 ] || die '文件不是 Root 管理'
    mode=$(stat -c %a "$1")
    [ "$((0$mode & 022))" = 0 ] || die '文件可被非 Root 修改'
}
profile() {
    [ "$(id -u)" = 0 ] || die '需要 KernelSU 超级用户权限'
    trusted "$guard/config.txt"
    [ "$(stat -c '%u:%g:%a' "$guard/config.txt")" = 0:0:600 ] || die '设备配置必须为 root:root 0600'
    serial= android_sha256= fallback_sha256= entry_sha256= switcher_sha256= service_sha256= ota_approved=
    seen='|'
    while IFS='=' read -r key value || [ -n "$key" ]; do
        case "$seen" in *"|$key|"*) die '重复配置项' ;; esac
        seen="$seen$key|"
        case "$key" in
            SERIAL) serial=$value ;;
            ANDROID_SHA256) android_sha256=$value ;;
            BOOT_B_SHA256) fallback_sha256=$value ;;
            RETURN_ENTRY_SHA256) entry_sha256=$value ;;
            SWITCHER_SHA256) switcher_sha256=$value ;;
            UPSTREAM_SERVICE_SHA256) service_sha256=$value ;;
            OTA_FREEZE_APPROVED) ota_approved=$value ;;
            *) die '未知配置项' ;;
        esac
    done <"$guard/config.txt"
    case "$serial" in ''|*[!A-Za-z0-9]*) die '设备序列号尚未填写' ;; esac
    [ "${#serial}" -le 64 ] || die '序列号格式错误'
    for value in "$android_sha256" "$fallback_sha256" "$entry_sha256" "$switcher_sha256" "$service_sha256"; do
        [ "${#value}" = 64 ] || die '本机哈希尚未填写'
        case "$value" in *[!a-f0-9]*) die '哈希必须是小写 SHA256' ;; esac
    done
    [ "$ota_approved" = 1 ] || die '尚未明确同意冻结 Android OTA'
    [ "$(getprop ro.serialno)" = "$serial" ] || die '设备序列号不匹配'
    [ "$(getprop ro.product.device)" = liuqin ] || die '不是小米 Pad 6 Pro'
    [ "$(getprop ro.boot.slot_suffix)" = _a ] || die '当前不是 A 槽，不改槽位'
}
ota_frozen() {
    packages=$(pm list packages -u --user 0) || die '无法读取 Android 软件包状态'
    if printf '%s\n' "$packages" | grep -qx 'package:com.android.updater'; then
        disabled=$(pm list packages -d --user 0) || die '无法读取更新器停用状态'
        updater=$(dumpsys package com.android.updater) || die '无法核验更新器隐藏状态'
        if ! printf '%s\n' "$disabled" | grep -qx 'package:com.android.updater'; then
            printf '%s\n' "$updater" | grep -Eq '^[[:space:]]*User 0:.*[[:space:]]hidden=true([[:space:]]|$)' || return 1
        fi
    fi
}
