# Linux 桌面分类排查手册

## 目录

1. 会话与桌面基线
2. 显示、GPU 与外接显示器
3. 登录、桌面环境与合成器
4. 输入设备、布局与输入法
5. 音频、蓝牙音频与摄像头
6. 电源、休眠、电池与温控
7. Wi-Fi 与蓝牙
8. 本地应用、沙盒与 Portal

以下命令是候选集合，不要整页执行。按当前假设选取 1–3 项，并确认工具存在。

## 1. 会话与桌面基线

从故障用户的图形终端获取：

```bash
cat /etc/os-release
uname -a
printf 'desktop=%s session=%s display=%s wayland=%s\n' "$XDG_CURRENT_DESKTOP" "$XDG_SESSION_TYPE" "$DISPLAY" "$WAYLAND_DISPLAY"
loginctl list-sessions
```

针对实际 session：

```bash
loginctl show-session <SESSION_ID> -p Name,User,Seat,Type,Class,State,Remote,Desktop
```

软件变更查询使用发行版包管理器的历史/日志，限定故障窗口。确认桌面包是 deb/rpm、Flatpak、Snap 还是 AppImage。

## 2. 显示、GPU 与外接显示器

### 硬件、驱动和内核层

```bash
lspci -nnk | grep -A3 -Ei 'VGA|3D|Display'
lsmod | grep -E 'nvidia|nouveau|amdgpu|i915|xe'
journalctl -k -b | grep -Ei 'drm|nvidia|nouveau|amdgpu|i915|xe|firmware|gpu|edid'
```

- `lsmod` 无输出只说明这些模块名未加载，不自动证明驱动故障；结合 `lspci -k` 的 `Kernel driver in use`。
- NVIDIA 同时检查当前内核、驱动包、`dkms status`、Secure Boot/module signature 记录和 `nvidia-smi`（若工具存在）。
- Mesa/开源驱动问题检查应用实际使用的 renderer；`glxinfo -B` 主要适用于 OpenGL/X11 环境，Vulkan 使用 `vulkaninfo --summary`（若存在）。
- 混合显卡检查实际 render offload/provider，不把集显负责扫描输出误判为独显未工作。

### connector、显示服务器和合成器

```bash
for connector in /sys/class/drm/card*-*/status; do printf '%s: ' "$connector"; cat "$connector"; done
```

- X11 可使用 `xrandr --verbose`；仅在 X11 图形会话中执行。
- KDE 可使用 `kscreen-doctor -o`（若存在）；Wayland/GNOME 优先查 compositor/user journal 和设置层，不假设 `xrandr` 能管理输出。
- 扩展坞/USB-C 同时检查 USB/Thunderbolt 枚举、DisplayPort Alt Mode、MST、供电、线缆和固件。
- EDID、链路训练或 hotplug 错误需结合内核日志；先用另一线缆/端口/屏幕做单变量对照。

### 黑屏阶段定位

- 能看到 boot splash/登录界面但登录后黑屏：优先用户会话、合成器、扩展和应用自启动。
- 登录界面也无显示但 TTY/SSH 可用：优先 DRM/KMS、display manager、驱动和显示拓扑。
- 连 TTY/SSH/网络都不可用：将系统/内核/启动设为主路径，并读取 [系统排查手册](system-triage-playbook.md) 的相关章节。

Xorg 日志位置可能在 journal、`~/.local/share/xorg/` 或 `/var/log/`，不要只检查固定 `/var/log/Xorg.0.log`。

## 3. 登录、桌面环境与合成器

系统级显示管理器：

```bash
systemctl status display-manager --no-pager --full
journalctl -u display-manager -b --no-pager
```

用户会话：

```bash
systemctl --user --failed --no-pager
journalctl --user -b -p warning..alert --no-pager
coredumpctl list --since today
```

- 登录循环检查 home 空间/inode、home/关键授权文件权限、shell、PAM、session 启动日志和桌面进程 core。
- GNOME 扩展、KWin/Plasma 脚本或主题问题先读取版本和错误，再用“禁用单个/全部扩展”做可回滚对照。
- GNOME `Alt+F2` 后输入 `r` 只适用于部分 Xorg 会话，不适用于 Wayland，也不是固定修复。
- 用新用户对照可区分系统级与用户配置，但创建用户属于状态变更；获得授权后才做。
- 重置 dconf/KDE 配置前导出/备份并优先重命名单个可疑配置，避免整套桌面恢复出厂。

## 4. 输入设备、布局与输入法

### 枚举与内核层

```bash
grep -E 'Name=|Handlers=' /proc/bus/input/devices
lspci -nnk
lsusb
journalctl -k -b | grep -Ei 'hid|i2c|touchpad|keyboard|mouse|input'
```

- `libinput list-devices`（若存在）提供设备/seat/能力；实时 `libinput debug-events` 可能需要 root 且会输出输入事件，按敏感调试处理。
- `xinput` 只适用于 X11/Xwayland 视图；Wayland 使用 compositor 设置或 `wev` 等工具（若已安装）。
- I2C-HID 超时需结合 ACPI、内核版本和 resume 时间线，不能仅凭 grep 就建议内核参数。

### 布局、手势和输入法

- 检查系统/桌面布局、当前输入源及是否只影响单应用。
- 输入法区分 IBus、Fcitx5、应用原生 IME、XIM 与 Wayland text-input 协议；检查对应用户服务和环境变量。
- Electron/Chromium、Flatpak/Snap 内输入问题可能来自 Ozone/Wayland、Portal 或沙盒，而非物理键盘。
- 剪贴板在 X11 与 Wayland 的所有权和权限模型不同；先确认只影响某应用、某格式还是所有会话。

## 5. 音频、蓝牙音频与摄像头

### 音频栈

```bash
systemctl --user status pipewire pipewire-pulse wireplumber --no-pager
wpctl status
pactl info
aplay -l
journalctl --user -b | grep -Ei 'pipewire|wireplumber|pulse|alsa'
```

只运行实际存在的命令/服务：

- ALSA 不识别设备：检查 PCI/USB 枚举、驱动、SOF/其他固件和内核日志。
- ALSA 有设备但 PipeWire/PulseAudio 无节点：检查 session manager、profile、权限和用户服务。
- 节点存在但应用无声：检查默认 sink/source、mute、音量、stream route 和应用沙盒。
- HDMI 音频同时依赖 GPU/DRM connector 和音频 profile；显示链路变化会改变节点。
- 蓝牙耳机还涉及 codec/profile（A2DP/HFP）、BlueZ 与 WirePlumber 规则。
- `alsamixer` 会改变状态；读取状态可用 `amixer`，解除静音/切 profile 需记录原值并获授权。

### 摄像头

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
journalctl -k -b | grep -Ei 'uvc|video|camera|firmware'
```

确认设备节点、占用进程、PipeWire/Portal、应用权限和摄像头隐私开关。不要把用户加入 `video` 组作为默认方案。

## 6. 电源、休眠、电池与温控

```bash
cat /sys/power/state
cat /sys/power/mem_sleep
systemd-inhibit --list
upower -e
journalctl -b -1 | grep -Ei 'suspend|resume|sleep|ACPI|PM:|wakeup|gpu|nvme'
```

- 当前系统未重启时查看本 boot 的故障窗口；唤醒后自动重启时优先上次 boot。
- 区分未进入睡眠、进入后立即唤醒、唤醒后只有显示失败、整机挂死和设备单独未恢复。
- `/proc/acpi/wakeup` 是候选唤醒源信息，不应无证据地切换条目。
- 外设/驱动 resume 失败结合 USB、GPU、NVMe、Wi-Fi 等同一时间窗口日志。
- 电池与温控读取 upower、power_supply、thermal/hwmon 和厂商工具；写充电阈值、切 governor 或风扇策略属于状态变更。
- `systemctl suspend` 会中断会话，仅在用户明确授权、有恢复通道和日志方案时复现。
- 不推荐 `acpi=off`；任何内核参数必须针对已证实机制，先单次启动验证并保留回滚入口。

## 7. Wi-Fi 与蓝牙

### Wi-Fi

```bash
nmcli general status
nmcli device status
nmcli radio
rfkill list
lspci -nnk | grep -A3 -Ei 'Network|Wireless'
lsusb
journalctl -u NetworkManager -b --no-pager
```

- 先区分未枚举、驱动/固件、rfkill、NetworkManager 未管理、关联/认证、DHCP、路由、DNS和应用层。
- `rfkill unblock` 是状态变更；硬阻断不能由软件解除。
- 固件日志中的版本回退/缺失要匹配发行版内核与 `linux-firmware` 包，不盲目安装最新固件。
- 频繁断连记录 BSSID、频段、信号、驱动事件和电源管理；避免把 AP/射频问题误判为客户端驱动。

### 蓝牙

```bash
systemctl status bluetooth --no-pager
rfkill list bluetooth
bluetoothctl show
bluetoothctl devices
journalctl -u bluetooth -b --no-pager
```

- 区分控制器未枚举、软硬阻断、BlueZ 服务、扫描、配对/信任、profile 和音频路由。
- `bluetoothctl scan on` 会主动扫描并泄露附近设备标识，需限定时间且说明隐私。
- 删除配对、重置控制器或修改 `/etc/bluetooth/main.conf` 都是状态变更，不作为首轮检查。

## 8. 本地应用、沙盒与 Portal

### 应用退出与依赖

```bash
journalctl --user -b --since 'YYYY-MM-DD HH:MM:SS' --no-pager
coredumpctl list <APP-OR-PID>
readelf -d <TRUSTED_BINARY>
```

- 区分原生包、Flatpak、Snap、AppImage 和自带 runtime；同名应用可能运行不同二进制。
- core、调试器和环境变量含敏感信息，按 L1 处理。
- GUI 应用黑屏/闪退可能来自 GPU 加速、Wayland/X11 backend、Portal、字体/主题或应用配置；用一次只改变一个变量的对照实验。

### Flatpak/Snap 与 Portal

```bash
flatpak info --show-permissions <APP_ID>
flatpak override --show <APP_ID>
snap connections <SNAP_NAME>
systemctl --user status 'xdg-desktop-portal*' --no-pager
journalctl --user -b | grep -Ei 'xdg-desktop-portal|flatpak|snap'
```

- 文件选择器、截图、屏幕共享、摄像头和打开 URL 通常经过 Portal；检查桌面对应 backend 是否匹配且没有重复冲突。
- 权限修复使用最小 filesystem/device/socket/interface 范围；记录当前 override，避免 `--filesystem=host`。
- `/dev/dri` 问题检查 render node、udev/logind ACL、session seat 和沙盒 device 权限；不要默认修改用户组。
- restart Portal/用户服务会影响当前应用和未保存操作，获得授权后执行，并验证服务依赖与应用重启需求。
