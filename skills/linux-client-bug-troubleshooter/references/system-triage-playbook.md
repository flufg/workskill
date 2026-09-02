# Linux 分类排查手册

## 目录

1. 通用基线
2. 资源与调度
3. 进程与服务
4. 网络与 DNS/TLS
5. 存储与文件系统
6. 内核与硬件
7. 权限与安全策略
8. 配置与依赖
9. 启动与引导
10. 容器、namespace 与 cgroup

以下命令为候选，不要整页执行。按假设选择最小集合，并根据发行版和工具可用性替换。

## 1. 通用基线

先统一时间和启动边界：

```bash
date -Is
uptime -s
uname -a
cat /etc/os-release
```

systemd 主机可查看失败 unit 和限定时间窗口的高优先级日志：

```bash
systemctl --failed --no-pager
journalctl --since 'YYYY-MM-DD HH:MM:SS' --until 'YYYY-MM-DD HH:MM:SS' -p err..alert --no-pager
```

如果系统最近重启，比较本次与上次启动：

```bash
journalctl --list-boots
journalctl -b -1 -p warning..alert --no-pager
```

## 2. 资源与调度

### CPU、load 与调度

```bash
uptime
vmstat 1 5
ps -eo pid,ppid,stat,ni,psr,pcpu,pmem,wchan:24,comm --sort=-pcpu | head -30
```

- load 高但 CPU 不高：检查 `D` 状态、I/O、锁和不可中断等待。
- CPU 高：确认单核还是全核、user/system/steal/iowait；虚拟机注意 steal。
- 若有 sysstat，使用 `mpstat -P ALL 1 5`、`pidstat -dur 1 5` 获取趋势。
- 检查 PSI：`cat /proc/pressure/cpu`、`memory`、`io`。

### 内存与 OOM

```bash
free -h
cat /proc/meminfo
ps -eo pid,ppid,rss,vsz,pmem,stat,comm --sort=-rss | head -30
journalctl -k --since 'YYYY-MM-DD HH:MM:SS' | grep -Ei 'oom|out of memory|killed process'
```

- 区分主机内存充足但 cgroup 达限的情况；读取目标 cgroup 的 `memory.current`、`memory.max`、`memory.events`。
- OOM 日志中的被杀进程不一定是泄漏源；结合增长趋势、分配模式和 cgroup 归属。
- swap 活跃不等于故障，结合 major fault、PSI 和延迟判断。

### FD、线程与进程数

针对具体 PID：

```bash
cat /proc/<PID>/limits
ls -1 /proc/<PID>/fd | wc -l
grep -E 'Threads|FDSize' /proc/<PID>/status
cat /proc/sys/fs/file-nr
```

- 不把全系统 `lsof` 数量与单进程 `ulimit -n` 直接比较。
- 确认限制来自 shell、systemd `LimitNOFILE`、容器 runtime 还是应用自身。
- FD 增长时按类型抽样 `/proc/<PID>/fd`，不要默认全量 `lsof`。

### 空间与 inode

```bash
df -hT
df -ih
findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS
```

先定位挂载点，再在同一文件系统内使用受限 `du -x` 查目录；注意已删除但仍被进程打开的文件可导致 `df` 与 `du` 不一致。

## 3. 进程与服务

### systemd 服务失败或重启循环

```bash
systemctl status <UNIT> --no-pager --full
systemctl show <UNIT> -p ActiveState,SubState,Result,ExecMainCode,ExecMainStatus,NRestarts
journalctl -u <UNIT> --since 'YYYY-MM-DD HH:MM:SS' --no-pager
systemctl cat <UNIT>
```

- 检查 unit 实际生效内容、drop-in、环境文件、工作目录、用户、capability、sandbox 和启动超时。
- `status` 只显示有限日志，根因通常需要目标时间窗口的 unit journal。
- 重启循环先保存退出码和日志，避免手动反复 restart 覆盖证据或放大故障。

### 崩溃与 core

```bash
coredumpctl list <EXE-OR-PID>
coredumpctl info <EXE-OR-PID>
journalctl -k --since 'YYYY-MM-DD HH:MM:SS' | grep -Ei 'segfault|general protection|trap'
```

- core、调试符号和精确二进制版本必须匹配。
- core 含敏感内存；导出或调试前按 L1 处理。
- 没有 core 时检查 `ulimit -c`、systemd `LimitCORE`、`kernel.core_pattern` 和存储策略，但启用 core 属于状态变更。

### 卡死、死锁与僵尸

```bash
ps -o pid,ppid,stat,etime,wchan:32,cmd -p <PID>
cat /proc/<PID>/stack
```

- `/proc/<PID>/stack` 常需 `sudo`，只显示内核栈；用户态栈需要匹配工具和符号。
- `strace -p`、调试器 attach 会扰动时序，属于 L1。
- 僵尸进程本身不能被 kill；定位父进程未 `wait` 的原因。必要时重启父服务属于 L2。

## 4. 网络与 DNS/TLS

按层拆分：监听 → 本机路由 → DNS → 传输 → TLS/应用。

```bash
ss -lntup
ip -br address
ip route get <DESTINATION-IP>
getent ahosts <HOSTNAME>
```

目标连接可使用受限超时：

```bash
curl -v --connect-timeout 3 --max-time 10 https://<HOST>:<PORT>/health
```

- `connection refused` 通常表示路径到达但端口无监听或被主动拒绝；`timeout` 需要区分 DNS、路由、防火墙、队列和应用超时。
- `ping` 只验证 ICMP 路径，失败不能证明 TCP/UDP 不通。
- DNS 检查结合 `/etc/resolv.conf`、`resolvectl status`（若存在）、`getent` 和应用实际 resolver 行为。
- TLS 检查证书时间、SNI、信任链和协议版本；主机时间错误会伪装成证书故障。
- 防火墙优先读取 `nft list ruleset` 或发行版实际后端；不要刷新规则做排除。
- `tcpdump` 会捕获敏感数据，必须限定接口、host/port、包数/时间和 snaplen，按 L1 处理。

## 5. 存储与文件系统

```bash
findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,ROTA,RO
df -hT
df -ih
journalctl -k --since 'YYYY-MM-DD HH:MM:SS' | grep -Ei 'i/o error|buffer error|ext4|xfs|btrfs|nvme|scsi|blk_update'
```

若有 sysstat：

```bash
iostat -xz 1 5
```

- 只读挂载可能是保护性结果，继续写入测试会放大损坏；先查首次底层错误。
- `df` 满、inode 满、配额、LVM thin pool、容器 overlay 和已删除开放文件是不同原因。
- SMART/NVMe 健康读取通常需要 `sudo`，属于只读但可能含设备信息；长测属于 L1/L2。
- 不用写盘 `dd` 作为初筛；需要基准时在批准的测试路径使用受限 `fio`，并确认空间、同步语义和清理。
- 修复前确认文件系统类型、挂载状态、备份/快照和冗余。ext 文件系统使用对应 fsck，XFS 使用 `xfs_repair`；都不能在已挂载生产文件系统上盲目执行。

## 6. 内核与硬件

```bash
uname -a
cat /proc/sys/kernel/tainted
journalctl -k --since 'YYYY-MM-DD HH:MM:SS' --no-pager
systemctl status kdump --no-pager
```

- 收集 panic/oops 前后完整上下文、调用栈、模块列表、内核命令行、taint、内核和符号版本。
- soft lockup、hung task 可能由 CPU 饥饿、I/O 卡死、驱动或锁引起，不能仅凭最后一个栈帧定责。
- 硬件事件优先使用平台已有的 rasdaemon、EDAC、BMC/IPMI、NVMe/SMART 和厂商日志；`mcelog` 并非所有现代平台都适用。
- vmcore 需要匹配 `vmlinux`/debuginfo，且可能含敏感数据。
- 内核回滚、固件/BIOS 更新和重启属于高影响修复，先确认控制台、启动项与回滚路径。

## 7. 权限与安全策略

### Unix 权限、ACL 与 capability

```bash
id
namei -l <PATH>
getfacl -p <PATH>
getcap <BINARY>
```

- 检查每一级目录执行权限、属主/组、ACL、只读挂载、umask 和 systemd 运行用户。
- 容器内 root 不等于宿主机 root；检查 user namespace、映射、capability 和 seccomp。

### SELinux

```bash
getenforce
ausearch -m AVC,USER_AVC -ts recent
```

### AppArmor

```bash
aa-status
journalctl -k --since 'YYYY-MM-DD HH:MM:SS' | grep -i apparmor
```

- 不默认关闭 enforcing/profile。利用 denial 记录确认主体、对象、操作和策略，再设计最小规则。
- `audit2allow` 输出不能未经审核直接加载；先用 `audit2why`/语义分析并排除错误标签和错误路径。
- PAM/sudo/登录问题根据发行版查看 auth journal、`/var/log/secure` 或 `/var/log/auth.log`，注意日志包含账号信息。

## 8. 配置与依赖

- 优先使用应用自带的配置验证命令，例如 `nginx -t`、`sshd -t`；验证前确认它不会连接外部系统或写状态。
- 比较 systemd 实际环境与交互 shell：运行用户、`WorkingDirectory`、`EnvironmentFile`、PATH、locale、umask、limits 和 sandbox。
- 动态依赖安全检查：

```bash
readelf -d <BINARY>
objdump -p <BINARY>
ldconfig -p
```

- 对可信二进制可用 `ldd` 辅助，但不对不受信任二进制运行。
- 检查 RPATH/RUNPATH、架构、动态加载器、符号版本和目标 glibc/libstdc++ 基线。
- 包版本冲突时使用发行版包管理器的只读查询/校验；安装、降级、重装和仓库变更属于 L2/L3。
- 证书故障检查有效期、主机时间、链、中间证书、SNI、权限和 reload 行为。

## 9. 启动与引导

可启动到 systemd 或 emergency shell 时：

```bash
systemctl --failed --no-pager
journalctl -b -p warning..alert --no-pager
systemd-analyze critical-chain
findmnt --verify --verbose
blkid
cat /proc/cmdline
```

- 对照 `/etc/fstab` 的 UUID、文件系统类型、选项和网络依赖；不要直接编辑前先保存副本。
- 区分固件/UEFI、bootloader、kernel/initramfs、根文件系统和 userspace/systemd 阶段。
- `journalctl -b -1` 可分析上次失败启动，前提是 journal 持久化且记录尚在。
- GRUB/initramfs 修复高度依赖发行版、UEFI/BIOS、加密、LVM/RAID 和 Secure Boot；只在具备控制台/Live 环境、备份和恢复路径后给出目标化步骤。

## 10. 容器、namespace 与 cgroup

- 同时获取容器内与宿主机视图：PID、网络、挂载、时间、资源限制和内核日志属于不同 namespace/权限域。
- 检查容器退出码、OOMKilled、restart policy、limits/requests、cgroup `memory.events`、CPU throttling 和 ephemeral storage。
- Docker/Podman/Kubernetes 日志和 inspect/status 输出可能包含环境变量和 secret 引用，分享前脱敏。
- 容器内 `free`、`df` 或进程数可能不能代表 cgroup/宿主机真实限制。
- 需要进入 namespace、使用 `nsenter`、调试容器或 ephemeral container 时说明权限和影响，按 L1/L2 管理。
