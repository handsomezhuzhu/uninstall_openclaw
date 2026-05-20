# uninstall_openclaw

OpenClaw / Moltbot / Clawdbot / ClawBot full uninstaller for Windows, Linux, and WSL.

The script is intentionally conservative:

- Default mode is `DRY-RUN`; it prints what would happen and does not delete files.
- Real cleanup requires `--yes`.
- `--quarantine` moves files aside instead of permanently deleting them.
- Shared workspaces, shared `~/.agents/skills`, cache folders, VS Code extensions, Docker/Podman artifacts, shell profiles, Windows registry cleanup, and system services require explicit flags or `--everything`.
- Dangerous paths such as drive roots, home roots, system folders, and broad non-OpenClaw paths are refused.

## Quick start

Preview only:

```powershell
py -3 openclaw_full_uninstall.py
```

Apply cleanup and move files to quarantine:

```powershell
py -3 openclaw_full_uninstall.py --yes --quarantine
```

Aggressive cleanup:

```powershell
py -3 openclaw_full_uninstall.py --yes --quarantine --everything
```

Write a transcript and JSON report:

```powershell
py -3 openclaw_full_uninstall.py --yes --quarantine --log-file .\uninstall.log --report-json .\uninstall-report.json
```

On Linux/WSL:

```bash
python3 openclaw_full_uninstall.py
python3 openclaw_full_uninstall.py --yes --quarantine --purge-docker --scan-source
```

## Common flags

| Flag | Meaning |
| --- | --- |
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

## Notes

- Run as the same OS user that installed OpenClaw.
- On Windows, run as Administrator only when you need services, HKLM registry keys, or machine environment variables removed.
- On WSL, run the script inside each WSL distro and also on Windows if a native Windows install exists.
- Review dry-run output before using `--yes`.

## Test

```powershell
py -3 -m unittest discover -s tests
```

