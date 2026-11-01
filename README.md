# 小米 Pad 6 Pro：平板内双向系统切换

在原生 Ubuntu 内点按钮进入 Android，在 Android 内点“返回 Ubuntu”，日常切换不需要电脑。基于 [yzddmr6/xiaomipad-6pro-mainline](https://github.com/yzddmr6/xiaomipad-6pro-mainline) 的既有安装、启动镜像存储与返程模块，补充管理员确认、设备绑定、镜像校验与 OTA 防护。

这不是刷机工具、通用 Root 安装器或分区工具。**不自动安装 Ubuntu、不解锁、不清数据、不重分区、不切 A/B 槽，也不配置电脑网卡、VPN、代理或路由。**

## 边界与风险

- 仅适用于小米 Pad 6 Pro / liuqin / SM8475；当前 Linux 身份门禁限定原生 Ubuntu 26.04 / resolute / ARM64 / systemd / ext4 / `LIUQIN_ROOT`。
- 两个系统使用 `boot_a`，`boot_b` 只作已校验的 Ubuntu fallback。一次真实切换仍然会写 `boot_a` 并重启，不是无风险的普通应用操作。
- Android 必须具有与自己的原厂内核匹配的 KernelSU Root。Root 可能影响支付、DRM、设备完整性检查与更新；本项目不降低 SELinux、不开放 ADB shell Root、不绕过授权。
- Android OTA 必须冻结，否则可能覆盖启动镜像或破坏双系统布局。**冻结会阻止正常系统更新；安全更新需要人工审阅。**不卸载更新器、不清除其数据。
- 空模板默认拒绝运行。必须独立核验自己的设备、镜像和上游脚本，不可照抄另一台平板的序列号或哈希。
- 不包含固件、内核、原厂镜像、Root 二进制、密钥、私人设备证据、内部知识库或业务代码。

## 上游准备

先按上游文档完成原生 Linux 安装、数据备份与可用的双系统镜像存储。安装上游正式 KernelSU 返程模块 `liuqin_boot_ubuntu`，确认它的 `boot-ubuntu -n` 可以完成只读镜像核验。Root 准备必须按自己的原厂内核 KMI 进行，不能用其他设备的镜像。

本项目依赖 Linux 的 `/usr/local/sbin/liuqin-switch` 和 `/var/lib/liuqin/switch/`，以及 Android 上游模块内的 `boot-ubuntu`、`liuqin-switch`。**不分发或自动下载这些第三方内容。**建议固定自己审阅的上游版本，并记录完整 SHA256。

## Android 按钮

1. 使用 JDK 17、Android SDK platform 35 与 build-tools 35.0.0：设置 `JAVA_HOME`、`ANDROID_SDK_ROOT`，执行 `powershell -NoProfile -ExecutionPolicy Bypass -File android-return/build.ps1`。`Bypass` 仅对这个构建进程生效，不修改全局执行策略。
2. 输出为 `android-return/out/` 下的 APK 和安全模块模板 ZIP。默认 APK 使用本机生成的开发签名；生产发布应改用自己的签名，不能使用仓库之外他人的私有密钥。
3. 在 KernelSU 安装模板 ZIP。安装本身不刷启动分区，空配置也不会冻结 OTA。
4. 用已授权的 Root 方法填写 `/data/adb/modules/liuqin_dual_return/config.txt`，保持 root:root、0600。参考 `config.txt.example`，所有 SHA256 都来自本机独立核验；仅在理解更新风险后将 `OTA_FREEZE_APPROVED` 设为 `1`。
5. 正常重启 Android 激活模块，安装 APK。在 KernelSU 的超级用户界面仅授予“返回 Ubuntu”所需的 Root 权限。先点“检查返程环境”，保存工作后再点“返回 Ubuntu”并确认。

`ANDROID_SHA256` 和 `BOOT_B_SHA256` 是整个对应启动分区的哈希，而非未经填充的小镜像文件；两个分区必须都为 192 MiB。`RETURN_ENTRY_SHA256`、`SWITCHER_SHA256`、`UPSTREAM_SERVICE_SHA256` 分别对应上游模块的 `system/bin/boot-ubuntu`、`system/bin/liuqin-switch`、`service.sh`。

## Ubuntu 按钮

1. 将 `linux/dual-switch.json.example` 复制为同目录 `dual-switch.json`，填写自己的序列号、两套存储镜像及 fallback 和上游脚本哈希。此私有文件已被 `.gitignore` 排除。
2. **只有完成 Android 正常启动、Root 授权、镜像/OTA 校验及独立返程验收后**，才将 `android_return_ready` 改为 `true`。这是一项操作者验收声明，不是本项目自动验证另一个已关机系统的证明。
3. 在原生 Ubuntu 上运行 `sudo bash linux/install.sh --install`。桌面菜单需要 `zenity`、`pkexec`、Python 3 与现有 polkit 认证代理；安装器不会自动执行 APT 升级。
4. 打开“平板双系统切换”。状态检查不会刷写；真实操作必须保存工作、确认并通过管理员认证。APT/dpkg 或 PackageKit 忙、低电量、哈希/身份不匹配时会拒绝切换。

只读检查：`sudo /usr/local/sbin/liuqin-dual-switch check --json`。不要把带 `android` / `ubuntu` 和 `--ack` 的命令当成只读测试。底层写入、回读验证与重启由固定哈希的上游脚本完成。

## 可回滚优化

`linux/tune.py` 提供可选的 Linux 本机优化：日志上限、2 GiB swap、低 swappiness。须先完成同一台设备的私有配置，再执行 `sudo python3 linux/tune.py apply`；`status` 只读，`rollback` 还原备份。不会修改固件、内核、boot、分区布局或 Windows 网络，也不会开放机器人控制服务。

可选桌面优化：以已登录的普通用户运行 `python3 linux/tune-desktop.py apply --serial YOUR_REVIEWED_SERIAL`，关闭 GNOME 动画、禁止接电时自动休眠；电池休眠、锁屏与远程服务不变。原设置保存在自己的 `~/.local/state/liuqin-dual/`，`rollback` 可还原，`status` 只读。

远程软件配置不做无差别修改。发现应用泄漏时应定位具体进程，不通过全局提高 D-Bus 连接上限掩盖故障。硬件 RTC、WLAN、USB 拓展坞与 CAN 等仍需按具体设备独立验收；软件安装不等于车辆应用可用。

如果内核不能写硬件 RTC，可选 `linux/install-clock-floor.sh --install --epoch REVIEWED_UTC_UNIX_SECONDS`（需要 sudo）：在启动时恢复上次已核验 UTC 的软件下限，每 15 分钟和正常关机时保存。它**不知道断电时长、不等于准确离线时间，也不声称 NTP/RTC 已修复**；真实联网后仍应由 chrony 校时。不要向它提供未经核验的时间。

## 验证状态

参考部署已在一台授权平板上完成 Ubuntu 按钮 → 正式 Root Android → Android 按钮 → 原生 Ubuntu 的真实往返，保留 A 槽和 fallback。另完成原生 ROS 2 本地消息与 RViz/rqt 图形启动，图形为 freedreno / FD730。

公开版本已通过 JDK 17 / SDK 35 构建、APK v2/v3 签名核验、Python/XML/Bash 语法检查、8 项空配置/身份/OTA 审批拒绝测试，以及模块 ZIP 与源码逐成员比对。源码和解压后的发布产物通过私有标记检查。门禁测试不执行启动分区写入、切系统或 OTA 冻结。

开源版本移除了设备常量、私有证明与内部资料，采用独立包名及空配置模板；**不是该私人设备的配置备份，也不声称对其他设备、ROM 或未经填写的模板完成实机验收。**

## 贡献与许可

贡献者见 [CREDITS.md](CREDITS.md)。本仓库原创工具采用 MIT；上游内核、固件、KernelSU 与外部启动脚本按各自许可，不受本仓库 MIT 重新许可。
