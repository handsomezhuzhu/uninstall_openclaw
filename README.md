# uninstall_openclaw

[中文](#中文) | [English](#english)

## 中文

OpenClaw / Moltbot / Clawdbot / ClawBot 的 Windows、Linux、WSL 完整卸载脚本。

这个脚本默认非常保守：

- 默认是 `DRY-RUN` 演练模式，只打印计划操作，不删除文件。
- 真正清理必须显式传入 `--yes`。
- `--quarantine` 会把文件移动到隔离目录，而不是永久删除。
- 外部工作区、共享 `~/.agents/skills`、缓存、VS Code 扩展、Docker/Podman 资源、shell profile、Windows 注册表、系统服务都需要显式参数或 `--everything`。
- 会拒绝删除磁盘根目录、用户根目录、系统目录和过宽的非 OpenClaw 路径。

### 语言选择

交互式终端中，如果不传 `--lang`，脚本启动时会提示选择语言：

```powershell
py -3 openclaw_full_uninstall.py
```

也可以直接指定语言，适合自动化脚本：

```powershell
py -3 openclaw_full_uninstall.py --lang zh
py -3 openclaw_full_uninstall.py --lang en
```

非交互环境没有传 `--lang` 时默认使用英文，避免脚本卡住等待输入。
脚本会在 Windows 和 Linux 终端中自动使用颜色和更清晰的分区输出；需要纯文本时可使用 `--no-color`，或设置环境变量 `NO_COLOR=1`。

### 快速开始

仅预览，不做任何改动：

```powershell
py -3 openclaw_full_uninstall.py --lang zh
```

执行清理，并把文件移动到隔离目录：

```powershell
py -3 openclaw_full_uninstall.py --lang zh --yes --quarantine
```

更激进的完整清理：

```powershell
py -3 openclaw_full_uninstall.py --lang zh --yes --quarantine --everything
```

输出日志和 JSON 报告：

```powershell
py -3 openclaw_full_uninstall.py --lang zh --yes --quarantine --log-file .\uninstall.log --report-json .\uninstall-report.json
```

Linux/WSL：

```bash
python3 openclaw_full_uninstall.py --lang zh
python3 openclaw_full_uninstall.py --lang zh --yes --quarantine --purge-docker --scan-source
```

### 常用参数

| 参数 | 含义 |
| --- | --- |
| `--lang zh\|en` | 输出语言。省略时，交互终端会提示选择；非交互环境默认英文。 |
| `--no-color` | 禁用 ANSI 颜色和终端样式，适合老终端或日志采集。 |
| `--yes` | 执行清理。没有这个参数时只做演练。 |
| `--quarantine` | 移动到隔离目录，而不是永久删除。 |
| `--backup-root PATH` | 指定隔离目录。 |
| `--purge-docker` | 删除匹配的 Docker/Podman 容器、镜像、卷和网络。 |
| `--scan-source` | 扫描常见项目目录，删除已确认的 OpenClaw 相关源码仓库。 |
| `--purge-external-workspaces` | 删除配置中发现的外部工作区。 |
| `--purge-shared-agent-skills` | 删除共享 `~/.agents/skills`；可能影响其他工具。 |
| `--purge-extra-skill-dirs` | 删除配置中的 `skills.load.extraDirs`。 |
| `--purge-caches` | 删除明显匹配 OpenClaw 名称的包管理器缓存项。 |
| `--purge-vscode-extensions` | 卸载 ID 匹配的 VS Code/Codium 扩展。 |
| `--clean-shell-rc` | 备份后清理 shell rc/profile 中的 OpenClaw 相关行。 |
| `--clean-registry` | 仅 Windows：清理匹配的卸载项、App Paths、Run 项和软件注册表项。 |
| `--clean-machine-env` | 仅 Windows：清理匹配的机器级环境变量。 |
| `--system-services` | 仅 Linux：清理匹配的系统级 systemd units。 |
| `--everything` | 启用全部可选清理项。 |

### 注意事项

- 请使用安装 OpenClaw 的同一个系统用户运行。
- Windows 上只有清理服务、HKLM 注册表项或机器级环境变量时才需要管理员权限。
- WSL 中请在每个 WSL 发行版内运行；如果 Windows 原生也安装过，还需要在 Windows 下运行一次。
- 使用 `--yes` 前请先检查 dry-run 输出。

### 测试

```powershell
py -3 -m unittest discover -s tests
```

## English

OpenClaw / Moltbot / Clawdbot / ClawBot full uninstaller for Windows, Linux, and WSL.

The script is intentionally conservative:

- Default mode is `DRY-RUN`; it prints what would happen and does not delete files.
- Real cleanup requires `--yes`.
- `--quarantine` moves files aside instead of permanently deleting them.
- External workspaces, shared `~/.agents/skills`, cache folders, VS Code extensions, Docker/Podman artifacts, shell profiles, Windows registry cleanup, and system services require explicit flags or `--everything`.
- Dangerous paths such as drive roots, home roots, system folders, and broad non-OpenClaw paths are refused.

### Language

In an interactive terminal, if `--lang` is omitted, the script asks you to choose a language at startup:

```powershell
py -3 openclaw_full_uninstall.py
```

You can also set the language explicitly, which is better for automation:

```powershell
py -3 openclaw_full_uninstall.py --lang en
py -3 openclaw_full_uninstall.py --lang zh
```

In non-interactive environments, the script defaults to English when `--lang` is omitted, so it will not block waiting for input.
The script automatically uses color and clearer section formatting on Windows and Linux terminals. Use `--no-color`, or set `NO_COLOR=1`, when plain text is preferred.

### Quick start

Preview only:

```powershell
py -3 openclaw_full_uninstall.py --lang en
```

Apply cleanup and move files to quarantine:

```powershell
py -3 openclaw_full_uninstall.py --lang en --yes --quarantine
```

Aggressive cleanup:

```powershell
py -3 openclaw_full_uninstall.py --lang en --yes --quarantine --everything
```

Write a transcript and JSON report:

```powershell
py -3 openclaw_full_uninstall.py --lang en --yes --quarantine --log-file .\uninstall.log --report-json .\uninstall-report.json
```

On Linux/WSL:

```bash
python3 openclaw_full_uninstall.py --lang en
python3 openclaw_full_uninstall.py --lang en --yes --quarantine --purge-docker --scan-source
```

### Common flags

| Flag | Meaning |
| --- | --- |
| `--lang zh\|en` | Output language. Omit it in an interactive terminal to choose at startup; non-interactive mode defaults to English. |
| `--no-color` | Disable ANSI colors and styled terminal output for older terminals or log capture. |
| `--yes` | Apply changes. Without it, the script is dry-run only. |
| `--quarantine` | Move files to a quarantine folder instead of deleting them permanently. |
| `--backup-root PATH` | Choose the quarantine folder. |
| `--purge-docker` | Remove matching Docker/Podman containers, images, volumes, and networks. |
| `--scan-source` | Scan common project folders for confirmed OpenClaw-related source checkouts. |
| `--purge-external-workspaces` | Remove workspace paths discovered in config even when outside OpenClaw state dirs. |
| `--purge-shared-agent-skills` | Remove shared `~/.agents/skills`; this can affect other tools. |
| `--purge-extra-skill-dirs` | Remove `skills.load.extraDirs` discovered in config. |
| `--purge-caches` | Remove package-manager cache entries that clearly match OpenClaw names. |
| `--purge-vscode-extensions` | Uninstall VS Code/Codium extensions whose IDs match OpenClaw-related names. |
| `--clean-shell-rc` | Remove OpenClaw-related lines from shell rc/profile files after backup. |
| `--clean-registry` | Windows only: remove matching registry uninstall/App Paths/Run/software entries. |
| `--clean-machine-env` | Windows only: remove matching machine-level environment variables. |
| `--system-services` | Linux only: remove matching system-wide systemd units. |
| `--everything` | Enable all optional purge flags. |

### Notes

- Run as the same OS user that installed OpenClaw.
- On Windows, run as Administrator only when you need services, HKLM registry keys, or machine environment variables removed.
- On WSL, run the script inside each WSL distro and also on Windows if a native Windows install exists.
- Review dry-run output before using `--yes`.

### Test

```powershell
py -3 -m unittest discover -s tests
```
