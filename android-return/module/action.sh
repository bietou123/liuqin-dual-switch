#!/system/bin/sh
set -eu
export PATH=/system/bin:/system/xbin
guard=/data/adb/modules/liuqin_dual_return
module=/data/adb/modules/liuqin_boot_ubuntu
. "$guard/common.sh"
action=${1:-check}
case "$action" in check|return) ;; *) die 'Unsupported operation' ;; esac
profile
[ "$(getprop sys.boot_completed)" = 1 ] || die 'Android 尚未启动完成'
for flag in disable remove; do
    [ ! -e "$module/$flag" ] && [ ! -e "$guard/$flag" ] || die '返程模块停用或待移除'
done
for input in "$module/system/bin/boot-ubuntu" "$module/system/bin/liuqin-switch" "$module/service.sh"; do trusted "$input"; done
[ "$(checksum "$module/system/bin/boot-ubuntu")" = "$entry_sha256" ] || die '上游返程入口变化'
[ "$(checksum "$module/system/bin/liuqin-switch")" = "$switcher_sha256" ] || die '上游切换程序变化'
[ "$(checksum "$module/service.sh")" = "$service_sha256" ] || die '上游 OTA 防护脚本变化'
ota_frozen || die 'Android OTA 未冻结，不能切换'
capacity=
for battery in /sys/class/power_supply/*; do
    [ "$(cat "$battery/type" 2>/dev/null || true)" = Battery ] || continue
    value=$(cat "$battery/capacity" 2>/dev/null || true)
    case "$value" in ''|*[!0-9]*) continue ;; esac
    if [ -z "$capacity" ] || [ "$value" -lt "$capacity" ]; then capacity=$value; fi
done
[ -n "$capacity" ] && [ "$capacity" -ge 30 ] || die '电量无法确认或不足 30%'
boot_a=/dev/block/by-name/boot_a
boot_b=/dev/block/by-name/boot_b
for partition in "$boot_a" "$boot_b"; do
    [ -b "$partition" ] && [ "$(blockdev --getsize64 "$partition")" = 201326592 ] || die '启动分区身份或容量不匹配'
done
[ "$(checksum "$boot_b")" = "$fallback_sha256" ] || die 'Ubuntu fallback 已变化'
[ "$(checksum "$boot_a")" = "$android_sha256" ] || die 'boot_a 不是独立核验的正式 Android 镜像'
sh "$module/system/bin/boot-ubuntu" -n || die 'Ubuntu 镜像或只读存储核验失败'
printf 'Root、设备、A 槽、镜像、fallback、电量与 OTA 防护检查通过。\n'
[ "$action" = return ] || exit 0
lock=/dev/.liuqin-dual-return-lock
mkdir "$lock" 2>/dev/null || die '已有返程操作进行中'
trap 'rmdir "$lock" 2>/dev/null || true' EXIT
printf '已确认返回 Ubuntu；写入 boot_a、完整回读核验后重启。\n'
sh "$module/system/bin/boot-ubuntu" -y
