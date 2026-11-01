#!/system/bin/sh
set -eu
export PATH=/system/bin:/system/xbin
guard=/data/adb/modules/liuqin_dual_return
. "$guard/common.sh"
profile
waited=0
while [ "$(getprop sys.boot_completed)" != 1 ]; do
    [ "$waited" -lt 600 ] || exit 1
    sleep 5
    waited=$((waited + 5))
done
if ! ota_frozen; then
    pm hide --user 0 com.android.updater >/dev/null
    ota_frozen || die '无法确认 OTA 冻结状态'
fi
printf 'OTA freeze verified; updater data preserved.\n'
