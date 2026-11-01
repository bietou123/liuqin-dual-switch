#!/usr/bin/env bash
set -euo pipefail
result="$(mktemp)"
trap 'rm -f -- "$result"' EXIT
if [[ "${1:-}" == --android ]]; then
    action=android
else
action="$(zenity --list --title='平板双系统工具' --width=760 --height=360 \
    --column='操作' --column='说明' --hide-column=1 --print-column=1 \
    check '状态检查（不重启、不刷写）' \
    android '切换到 Android（安卓内有返回 Ubuntu 按钮）' \
    ubuntu '固定 Ubuntu（仅临时救援启动后需要）' \
    help '查看安全切换与配置说明')" || exit 0
fi
case "$action" in
    help)
        zenity --text-info --title='双系统使用说明' --width=850 --height=650 \
            --filename=/usr/local/share/liuqin-dual/使用说明.txt
        exit 0
        ;;
    android)
        zenity --question --title='切换到 Android' --width=720 \
            --text=$'保存工作后再继续。平板将校验镜像、写回 boot_a 并重启进入 Android。\n不清数据、不改分区、不改 B 槽。正常返回时打开 Android 内的“返回 Ubuntu”。\n若维护、镜像或返程配置检查不通过，工具会停止。现在切换？' || exit 0
        arguments=(android --ack ANDROID-ROOT-RETURN)
        ;;
    ubuntu)
        zenity --question --title='固定 Ubuntu 启动' --width=720 \
            --text=$'这会把经过校验的 Ubuntu 镜像写回 boot_a，核对后重启。\n不改分区、不改 B 槽；请先保存工作。是否继续？' || exit 0
        arguments=(ubuntu --ack UBUNTU-REBOOT)
        ;;
    check) arguments=(check) ;;
    *) exit 1 ;;
esac
if pkexec /usr/local/sbin/liuqin-dual-switch "${arguments[@]}" >"$result" 2>&1; then
    title='双系统工具结果'
else
    title='已停止：未通过切换检查'
fi
zenity --text-info --title="$title" --width=850 --height=650 --filename="$result"
