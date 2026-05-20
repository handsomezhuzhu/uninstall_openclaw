#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw / Moltbot / Clawdbot / ClawBot full uninstaller for Windows and Linux.

Default mode is DRY-RUN. Nothing is deleted unless you pass --yes.
Run it as the same OS user that installed OpenClaw. On WSL, run it inside each WSL
Linux distro as well as in Windows if you also installed native Windows OpenClaw.

Examples:
  python openclaw_full_uninstall.py
  python openclaw_full_uninstall.py --yes --purge-docker --scan-source
  python openclaw_full_uninstall.py --yes --everything

Safety notes:
  - External workspaces and ~/.agents/skills may contain user work or be shared by
    other AgentSkills-compatible tools. They are only removed with explicit flags
    or --everything.
  - Shell rc files are only edited with --clean-shell-rc or --everything; backups
    are written next to the original files.
  - Nix store paths are never deleted directly; only profile entries are removed.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import fnmatch
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

__version__ = "0.2.0"

IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")
HOME = Path.home()
TIMESTAMP = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")

KEYWORDS = (
    "openclaw",
    "moltbot",
    "clawdbot",
    "clawbot",
    "clawd",
    "clawdock",
    "clawhub",
    "clawd",
)
CLI_NAMES = ("openclaw", "moltbot", "clawdbot", "clawbot")
PKG_EXACT = (
    "openclaw",
    "moltbot",
    "clawdbot",
    "clawbot",
    "clawhub",
)
ENV_PREFIXES = ("OPENCLAW_", "MOLTBOT_", "CLAWDBOT_", "CLAWBOT_", "CLAWDOCK_")
ENV_VALUE_KEYS = (
    "OPENCLAW", "MOLTBOT", "CLAWDBOT", "CLAWBOT", "CLAWDOCK", "CLAWHUB",
    "STATE_DIR", "CONFIG", "WORKSPACE", "SKILL", "PLUGIN", "GATEWAY",
)

SKIP_WALK_DIRS = {
    ".cache", ".git", ".hg", ".svn", "node_modules", ".npm", ".pnpm-store",
    ".cargo", ".rustup", ".venv", "venv", "env", "AppData", "Library",
    "$Recycle.Bin", "System Volume Information", "Windows", "Program Files",
    "Program Files (x86)", "ProgramData",
}


def lower(s: str) -> str:
    return s.lower()


def contains_keyword(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in KEYWORDS)


def env_key_interesting(key: str) -> bool:
    upper = key.upper()
    return upper in ("OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH", "OPENCLAW_HOME") or any(
        upper.startswith(prefix) for prefix in ENV_PREFIXES
    )


def env_value_path_like(key: str, value: str) -> bool:
    upper_key = key.upper()
    if env_key_interesting(upper_key):
        return True
    if not any(token in upper_key for token in ENV_VALUE_KEYS):
        return False
    if value.startswith(("http://", "https://", "git:", "npm:", "clawhub:")):
        return False
    if len(value) > 512 or "\n" in value:
        return False
    if contains_keyword(value):
        return True
    return bool(value.strip())


def process_env_value_path_like(key: str, value: str) -> bool:
    upper_key = key.upper()
    if env_key_interesting(upper_key):
        return True
    key_is_pathish = any(token in upper_key for token in ("DIR", "PATH", "HOME", "CONFIG", "WORKSPACE", "SKILL", "PLUGIN", "GATEWAY"))
    value_is_pathish = any(ch in value for ch in ("/", "\\", "~", "$", "%"))
    return (contains_keyword(upper_key) and key_is_pathish) or (contains_keyword(value) and value_is_pathish)


def quote_cmd(cmd: list[str]) -> str:
    return " ".join(shlex_quote(x) for x in cmd)


def shlex_quote(s: str) -> str:
    if IS_WINDOWS:
        if not s or re.search(r'[\s"&|<>^()]', s):
            return '"' + s.replace('"', '\\"') + '"'
        return s
    import shlex
    return shlex.quote(s)


def norm_path(p: Path) -> Path:
    try:
        return p.expanduser().resolve(strict=False)
    except Exception:
        return p.expanduser().absolute()


def resolve_command(cmd: list[str]) -> list[str]:
    if not cmd:
        return cmd
    exe = which(cmd[0])
    if exe:
        return [exe] + cmd[1:]
    return cmd


def run_read_plain(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    resolved = resolve_command(cmd)
    try:
        return subprocess.run(resolved, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except FileNotFoundError:
        return subprocess.CompletedProcess(resolved, 127, "", "not found")
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(resolved, 124, e.stdout or "", e.stderr or "timeout")
    except Exception as e:
        return subprocess.CompletedProcess(resolved, 1, "", str(e))


class Tee:
    def __init__(self, *streams: Any) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        for stream in self.streams:
            try:
                stream.write(data)
            except ValueError:
                pass
        return len(data)

    def flush(self) -> None:
        for stream in self.streams:
            try:
                stream.flush()
            except ValueError:
                pass


def setup_transcript(path: str) -> Optional[Any]:
    if not path:
        return None
    p = norm_path(Path(path))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fp = p.open("a", encoding="utf-8")
    except Exception as e:
        print(f"[WARN] could not open log file {p}: {e}")
        return None
    sys.stdout = Tee(sys.stdout, fp)  # type: ignore[assignment]
    sys.stderr = Tee(sys.stderr, fp)  # type: ignore[assignment]
    print(f"[LOG] transcript: {p}")
    return fp


def is_elevated() -> bool:
    if IS_WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    if hasattr(os, "geteuid"):
        try:
            return os.geteuid() == 0
        except Exception:
            return False
    return False


def emit_privilege_hint(args: argparse.Namespace) -> None:
    if IS_WINDOWS:
        if not is_elevated():
            print("[WARN] not running as Administrator; Windows services, HKLM registry keys, and machine environment variables may remain.")
        return
    if args.system_services and not is_elevated():
        print("[WARN] --system-services was requested but this process is not root; system unit removals may fail.")


def is_dangerous_path(p: Path) -> bool:
    p = norm_path(p)
    s = str(p)
    anchors = {Path(p.anchor)} if p.anchor else set()
    dangerous = {
        Path("/"), Path("/home"), Path("/Users"), Path("/usr"), Path("/usr/local"),
        Path("/opt"), Path("/etc"), Path("/var"), Path("/tmp"), HOME,
    }
    dangerous.update(anchors)
    if p in dangerous:
        return True
    if IS_WINDOWS:
        # Refuse drive roots and user root folders.
        if re.fullmatch(r"[A-Za-z]:\\?", s):
            return True
        try:
            if p == HOME or p == HOME.parent:
                return True
        except Exception:
            pass
    # Refuse paths that are too short and not clearly OpenClaw-related.
    parts = [part for part in p.parts if part not in (p.anchor, os.sep)]
    if len(parts) <= 1 and not contains_keyword(s):
        return True
    return False


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.dry_run = not args.yes
        self.seen_paths: set[str] = set()
        self.errors: list[str] = []
        self.removed: list[str] = []
        self.warned: list[str] = []
        self.quarantine_root: Optional[Path] = None
        if args.quarantine:
            root = Path(args.backup_root).expanduser() if args.backup_root else HOME / f"openclaw-uninstall-quarantine-{TIMESTAMP}"
            self.quarantine_root = norm_path(root)

    def info(self, msg: str) -> None:
        print(msg)

    def warn(self, msg: str) -> None:
        self.warned.append(msg)
        print(f"[WARN] {msg}")

    def err(self, msg: str) -> None:
        self.errors.append(msg)
        print(f"[ERR] {msg}")

    def run_read(self, cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return run_read_plain(cmd, timeout=timeout)

    def run_mutate(self, cmd: list[str], timeout: int = 120, ok_codes: Iterable[int] = (0,)) -> subprocess.CompletedProcess[str]:
        resolved = resolve_command(cmd)
        if self.dry_run:
            print(f"[DRY-RUN] run: {quote_cmd(resolved)}")
            return subprocess.CompletedProcess(resolved, 0, "", "")
        print(f"[RUN] {quote_cmd(resolved)}")
        try:
            cp = subprocess.run(resolved, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            if cp.returncode not in set(ok_codes):
                combined = (cp.stderr or cp.stdout or "").strip()
                if combined:
                    self.warn(f"command exited {cp.returncode}: {quote_cmd(resolved)} :: {combined[:400]}")
            return cp
        except FileNotFoundError:
            self.warn(f"command not found: {cmd[0]}")
            return subprocess.CompletedProcess(resolved, 127, "", "not found")
        except subprocess.TimeoutExpired as e:
            self.warn(f"command timed out: {quote_cmd(resolved)}")
            return subprocess.CompletedProcess(resolved, 124, e.stdout or "", e.stderr or "timeout")
        except Exception as e:
            self.warn(f"command failed: {quote_cmd(resolved)} :: {e}")
            return subprocess.CompletedProcess(resolved, 1, "", str(e))

    def remove_path(self, path: Path, reason: str, *, allow_without_keyword: bool = False) -> None:
        p = norm_path(path)
        key = str(p).lower()
        if key in self.seen_paths:
            return
        self.seen_paths.add(key)

        if not p.exists() and not p.is_symlink():
            return
        if is_dangerous_path(p):
            self.warn(f"skip dangerous path: {p} ({reason})")
            return
        if not allow_without_keyword and not contains_keyword(str(p)):
            self.warn(f"skip path without OpenClaw/Moltbot/Clawbot keyword: {p} ({reason})")
            return

        if self.dry_run:
            print(f"[DRY-RUN] delete: {p}  # {reason}")
            return

        try:
            if self.quarantine_root:
                dest = self._quarantine_dest(p)
                dest.parent.mkdir(parents=True, exist_ok=True)
                print(f"[MOVE] {p} -> {dest}  # {reason}")
                shutil.move(str(p), str(dest))
                self.removed.append(str(p))
                return
            print(f"[DELETE] {p}  # {reason}")
            if p.is_symlink() or p.is_file():
                p.unlink(missing_ok=True)
            else:
                shutil.rmtree(p, ignore_errors=False)
            self.removed.append(str(p))
        except Exception as e:
            self.err(f"failed to remove {p}: {e}")

    def _quarantine_dest(self, p: Path) -> Path:
        assert self.quarantine_root is not None
        try:
            rel = p.relative_to(HOME)
            return self.quarantine_root / "home" / rel
        except Exception:
            drive = "drive"
            if IS_WINDOWS and p.drive:
                drive = p.drive.replace(":", "")
            rel_parts = [part for part in p.parts if part not in (p.anchor, os.sep)]
            return self.quarantine_root / drive / Path(*rel_parts)


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Purge OpenClaw / Moltbot / Clawdbot / ClawBot from Windows or Linux. Default: dry-run.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--yes", action="store_true", help="actually perform removals; without this only prints a dry-run plan")
    ap.add_argument("--quarantine", action="store_true", help="move files to a quarantine directory instead of permanently deleting them")
    ap.add_argument("--backup-root", default="", help="quarantine directory when --quarantine is used")
    ap.add_argument("--log-file", default="", help="write a transcript to this file in addition to stdout")
    ap.add_argument("--report-json", default="", help="write a machine-readable summary report to this JSON file")
    ap.add_argument("--purge-docker", action="store_true", help="remove Docker/Podman containers, images, volumes and networks whose names/images match OpenClaw/Moltbot/Clawbot")
    ap.add_argument("--scan-source", action="store_true", help="scan common project folders for source checkouts and remove confirmed OpenClaw/Moltbot/Clawdbot repos")
    ap.add_argument("--purge-external-workspaces", action="store_true", help="delete workspace paths discovered in config even when outside OpenClaw state dirs")
    ap.add_argument("--purge-shared-agent-skills", action="store_true", help="delete ~/.agents/skills and related shared AgentSkills folders; can affect other tools")
    ap.add_argument("--purge-extra-skill-dirs", action="store_true", help="delete skills.load.extraDirs discovered in config; can affect other tools")
    ap.add_argument("--purge-caches", action="store_true", help="delete package-manager cache entries/folders that clearly match OpenClaw names; not whole npm/pnpm/bun caches")
    ap.add_argument("--purge-vscode-extensions", action="store_true", help="uninstall VS Code extensions whose IDs contain openclaw/moltbot/clawbot/clawdbot")
    ap.add_argument("--clean-shell-rc", action="store_true", help="remove OpenClaw-related lines from shell rc/profile files after making backups")
    ap.add_argument("--clean-registry", action="store_true", help="Windows only: delete OpenClaw-related uninstall, App Paths, Run/StartupApproved, and HKCU/HKLM software registry entries")
    ap.add_argument("--clean-machine-env", action="store_true", help="Windows only: also remove matching machine-level environment variables; requires Administrator for HKLM")
    ap.add_argument("--system-services", action="store_true", help="also try to remove system-wide Linux systemd units; use with sudo/root")
    ap.add_argument("--everything", action="store_true", help="enable all optional purge flags")
    ap.add_argument("--no-kill", action="store_true", help="do not terminate remaining OpenClaw/Moltbot/Clawbot processes")
    ap.add_argument("--no-npx", action="store_true", help="do not use npx fallback when the openclaw CLI is missing")
    args = ap.parse_args()
    if args.everything:
        args.purge_docker = True
        args.scan_source = True
        args.purge_external_workspaces = True
        args.purge_shared_agent_skills = True
        args.purge_extra_skill_dirs = True
        args.purge_caches = True
        args.purge_vscode_extensions = True
        args.clean_shell_rc = True
        args.clean_registry = True
        args.clean_machine_env = True
        args.system_services = True
    return args


def collect_env_overrides() -> list[Path]:
    paths: list[Path] = []
    for key, val in os.environ.items():
        if not val:
            continue
        if process_env_value_path_like(key, val):
            expanded = os.path.expandvars(os.path.expanduser(val))
            # PATH-like variables may contain separators. Treat only existing items.
            parts = [expanded]
            if os.pathsep in expanded and not Path(expanded).exists():
                parts = expanded.split(os.pathsep)
            for part in parts:
                if part:
                    paths.append(Path(part))
    return paths


def glob_existing(pattern: Path) -> list[Path]:
    try:
        return [p for p in pattern.parent.glob(pattern.name)]
    except Exception:
        return []


def collect_state_and_config_paths(args: argparse.Namespace) -> tuple[list[Path], list[Path]]:
    paths: list[Path] = []
    config_files: list[Path] = []

    # Home-state directories, including --profile variants.
    for pat in [
        ".openclaw", ".openclaw-*", ".moltbot", ".moltbot-*", ".clawdbot", ".clawdbot-*",
        ".clawbot", ".clawbot-*", ".clawd", ".clawd-*", ".clawdock", ".clawhub",
    ]:
        paths.extend(glob_existing(HOME / pat))

    # XDG locations on Linux/WSL.
    if not IS_WINDOWS:
        for base in [HOME / ".config", HOME / ".cache", HOME / ".local" / "share", HOME / ".local" / "state"]:
            for name in ["openclaw", "moltbot", "clawdbot", "clawbot", "clawdock", "clawhub"]:
                paths.append(base / name)
        paths.append(HOME / ".config" / "openclaw" / "gateway.env")
        # Wrapper scripts / locally prefixed installs.
        for bin_dir in [HOME / ".local" / "bin", HOME / "bin", HOME / ".npm-global" / "bin"]:
            for name in list(CLI_NAMES) + ["clawhub"]:
                paths.append(bin_dir / name)
            for helper in bin_dir.glob("clawdock-*") if bin_dir.exists() else []:
                paths.append(helper)
        for pkg in PKG_EXACT:
            paths.append(HOME / ".npm-global" / "lib" / "node_modules" / pkg)

    # Windows locations.
    if IS_WINDOWS:
        env_dirs = []
        for env_name in ["APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "ProgramFiles", "ProgramFiles(x86)"]:
            val = os.environ.get(env_name)
            if val:
                env_dirs.append(Path(val))
        app_names = ["OpenClaw", "openclaw", "MoltBot", "Moltbot", "moltbot", "Clawdbot", "ClawBot", "Clawbot", "clawbot", "ClawHub", "clawhub"]
        for base in env_dirs:
            for name in app_names:
                paths.append(base / name)
                paths.append(base / "Programs" / name)
        appdata = Path(os.environ.get("APPDATA", "")) if os.environ.get("APPDATA") else None
        if appdata:
            npm_bin = appdata / "npm"
            for name in list(CLI_NAMES) + ["clawhub"]:
                for suffix in ["", ".cmd", ".ps1"]:
                    paths.append(npm_bin / f"{name}{suffix}")
                paths.append(npm_bin / "node_modules" / name)
            startup = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            if startup.exists():
                for p in startup.iterdir():
                    if contains_keyword(p.name) or p.name.lower() == "gateway.cmd":
                        paths.append(p)

    # Env-based state/config overrides.
    for p in collect_env_overrides():
        paths.append(p)
        if p.is_file() and p.name.lower().endswith((".json", ".env")):
            config_files.append(p)
        elif p.is_dir():
            config_files.extend([p / "openclaw.json", p / ".env", p / "gateway.env"])

    # Config files from known state dirs.
    for p in list(paths):
        if p.is_dir():
            config_files.extend([p / "openclaw.json", p / ".env", p / "gateway.env"])
        elif p.name.lower() in ("openclaw.json", ".env", "gateway.env"):
            config_files.append(p)

    # Deduplicate while preserving order.
    paths = dedupe_paths(paths)
    config_files = dedupe_paths(config_files)
    return paths, config_files


def dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        if not p:
            continue
        np = norm_path(p)
        key = str(np).lower()
        if key not in seen:
            seen.add(key)
            out.append(np)
    return out


def load_json_file(path: Path) -> Optional[Any]:
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        if not path.exists() or not path.is_file():
            return values
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key:
                values[key] = value
    except Exception:
        return {}
    return values


def expand_config_path(value: str, base_dir: Path) -> Optional[Path]:
    if not value or not isinstance(value, str):
        return None
    if value.startswith("http://") or value.startswith("https://") or value.startswith("git:") or value.startswith("npm:") or value.startswith("clawhub:"):
        return None
    # Ignore obvious non-path strings.
    if len(value) > 512 or "\n" in value:
        return None
    v = os.path.expandvars(os.path.expanduser(value))
    p = Path(v)
    if not p.is_absolute():
        p = base_dir / p
    return norm_path(p)


def find_paths_in_env_config(path: Path) -> tuple[list[Path], list[Path], list[Path]]:
    workspaces: list[Path] = []
    managed: list[Path] = []
    extra_skills: list[Path] = []
    for key, value in parse_env_file(path).items():
        if not value or not env_value_path_like(key, value):
            continue
        p = expand_config_path(value, path.parent)
        if not p:
            continue
        full_key = key.lower()
        if "workspace" in full_key:
            workspaces.append(p)
        elif "extra" in full_key and "skill" in full_key:
            extra_skills.append(p)
        elif any(token in full_key for token in ("plugin", "skill", "dir", "path", "home", "config", "state", "gateway")):
            managed.append(p)
    return dedupe_paths(workspaces), dedupe_paths(managed), dedupe_paths(extra_skills)


def find_paths_in_config(obj: Any, base_dir: Path, args: argparse.Namespace) -> tuple[list[Path], list[Path], list[Path]]:
    """Return (workspaces, plugin_or_managed_dirs, extra_skill_dirs)."""
    workspaces: list[Path] = []
    managed: list[Path] = []
    extra_skills: list[Path] = []

    def walk(x: Any, key_path: list[str]) -> None:
        key = lower(key_path[-1]) if key_path else ""
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, key_path + [str(k)])
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, key_path + [str(i)])
        elif isinstance(x, str):
            p = expand_config_path(x, base_dir)
            if not p:
                return
            full_key = ".".join(lower(k) for k in key_path)
            if "workspace" in key or "workspace" in full_key:
                workspaces.append(p)
            elif "extradirs" in full_key or "extra_dirs" in full_key:
                extra_skills.append(p)
            elif "plugin" in full_key and ("dir" in full_key or "path" in full_key or p.exists()):
                managed.append(p)
            elif "skill" in full_key and ("dir" in full_key or "path" in full_key) and args.purge_extra_skill_dirs:
                extra_skills.append(p)

    walk(obj, [])
    return dedupe_paths(workspaces), dedupe_paths(managed), dedupe_paths(extra_skills)


def official_cli_uninstall(r: Runner) -> None:
    r.info("\n== Built-in CLI uninstall / gateway stop ==")
    found_any_cli = False
    for cmd in CLI_NAMES:
        exe = which(cmd)
        if not exe:
            continue
        found_any_cli = True
        r.run_mutate([cmd, "gateway", "stop"], ok_codes=(0, 1, 2, 127))
        r.run_mutate([cmd, "gateway", "uninstall"], ok_codes=(0, 1, 2, 127))
        r.run_mutate([cmd, "uninstall", "--all", "--yes", "--non-interactive"], ok_codes=(0, 1, 2, 127))

    # If the current OpenClaw CLI is missing, npx can run the official non-interactive uninstaller.
    # When a local CLI exists we avoid npx by default so the cleanup does not create a fresh npx cache.
    if not r.args.no_npx and which("npx") and (which("openclaw") is None or r.args.everything or not found_any_cli):
        r.run_mutate(["npx", "-y", "openclaw", "uninstall", "--all", "--yes", "--non-interactive"], ok_codes=(0, 1, 2, 127), timeout=180)


def linux_systemd_cleanup(r: Runner) -> None:
    if not IS_LINUX:
        return
    r.info("\n== Linux systemd user services ==")
    user_unit_dir = HOME / ".config" / "systemd" / "user"
    units: set[str] = {
        "openclaw-gateway.service", "moltbot-gateway.service", "clawdbot-gateway.service", "clawbot-gateway.service",
        "clawd-gateway.service", "openclaw.service", "moltbot.service", "clawdbot.service", "clawbot.service",
    }
    if user_unit_dir.exists():
        for p in user_unit_dir.iterdir():
            if p.is_file() and contains_keyword(p.name) and p.suffix in (".service", ".timer", ".socket", ".target"):
                units.add(p.name)
    for unit in sorted(units):
        r.run_mutate(["systemctl", "--user", "disable", "--now", unit], ok_codes=(0, 1, 2, 3, 4, 5, 127))
    for unit in sorted(units):
        r.remove_path(user_unit_dir / unit, "systemd user unit")
    if units:
        r.run_mutate(["systemctl", "--user", "daemon-reload"], ok_codes=(0, 1, 127))

    if r.args.system_services:
        r.info("\n== Linux systemd system services ==")
        system_dirs = [Path("/etc/systemd/system"), Path("/usr/lib/systemd/system"), Path("/lib/systemd/system")]
        sys_units: set[str] = set()
        for d in system_dirs:
            if d.exists():
                for p in d.iterdir():
                    if p.is_file() and contains_keyword(p.name) and p.suffix in (".service", ".timer", ".socket", ".target"):
                        sys_units.add(p.name)
        for unit in sorted(sys_units):
            r.run_mutate(["systemctl", "disable", "--now", unit], ok_codes=(0, 1, 2, 3, 4, 5, 127))
        for d in system_dirs:
            for unit in sorted(sys_units):
                r.remove_path(d / unit, "systemd system unit")
        if sys_units:
            r.run_mutate(["systemctl", "daemon-reload"], ok_codes=(0, 1, 127))


def windows_task_cleanup(r: Runner) -> None:
    if not IS_WINDOWS:
        return
    r.info("\n== Windows Scheduled Tasks ==")
    cp = r.run_read(["schtasks", "/Query", "/FO", "CSV", "/V"], timeout=60)
    task_names: set[str] = {"\\OpenClaw Gateway", "OpenClaw Gateway"}
    if cp.returncode == 0 and cp.stdout.strip():
        try:
            rows = csv.DictReader(cp.stdout.splitlines())
            for row in rows:
                name = row.get("TaskName") or row.get("Task Name") or ""
                if name and contains_keyword(name):
                    task_names.add(name)
        except Exception:
            pass
    for task in sorted(task_names):
        r.run_mutate(["schtasks", "/Delete", "/F", "/TN", task], ok_codes=(0, 1))


def windows_service_cleanup(r: Runner) -> None:
    if not IS_WINDOWS:
        return
    r.info("\n== Windows Services ==")
    ps = which("powershell") or which("powershell.exe") or which("pwsh")
    if not ps:
        return
    script = r"""
$items = Get-CimInstance Win32_Service | Where-Object {
  $_.Name -match 'openclaw|moltbot|clawdbot|clawbot|clawdock|clawhub' -or
  $_.DisplayName -match 'openclaw|moltbot|clawdbot|clawbot|clawdock|clawhub' -or
  $_.PathName -match 'openclaw|moltbot|clawdbot|clawbot|clawdock|clawhub'
} | Select-Object -ExpandProperty Name
$items | ConvertTo-Json -Compress
"""
    cp = r.run_read([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=60)
    names: list[str] = []
    if cp.returncode == 0 and cp.stdout.strip():
        try:
            data = json.loads(cp.stdout)
            if isinstance(data, str):
                names = [data]
            elif isinstance(data, list):
                names = [str(x) for x in data]
        except Exception:
            names = []
    for name in names:
        r.run_mutate(["sc.exe", "stop", name], ok_codes=(0, 1, 2, 1060, 1062))
        r.run_mutate(["sc.exe", "delete", name], ok_codes=(0, 1, 2, 1060))


def terminate_processes(r: Runner) -> None:
    if r.args.no_kill:
        return
    r.info("\n== Remaining process cleanup ==")
    current_pid = os.getpid()
    parent_pid = os.getppid()
    if IS_LINUX:
        cp = r.run_read(["ps", "-eo", "pid=,comm=,args="], timeout=30)
        if cp.returncode != 0:
            return
        pids: list[int] = []
        for line in cp.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=2)
            if len(parts) < 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            if pid in (current_pid, parent_pid):
                continue
            comm = parts[1]
            args_s = parts[2] if len(parts) > 2 else ""
            text = f"{comm} {args_s}".lower()
            strong = (
                comm.lower() in CLI_NAMES or
                "node_modules/openclaw" in text or "node_modules/moltbot" in text or
                "node_modules/clawdbot" in text or "node_modules/clawbot" in text or
                re.search(r"\b(openclaw|moltbot|clawdbot|clawbot)\s+gateway\b", text) is not None or
                (".openclaw" in text and "gateway" in text)
            )
            if strong:
                pids.append(pid)
        for pid in sorted(set(pids)):
            if r.dry_run:
                print(f"[DRY-RUN] terminate process pid={pid}")
            else:
                try:
                    print(f"[TERM] pid={pid}")
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except Exception as e:
                    r.warn(f"failed to terminate pid {pid}: {e}")
        if pids and not r.dry_run:
            time.sleep(2)
            for pid in sorted(set(pids)):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                try:
                    print(f"[KILL] pid={pid}")
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
    elif IS_WINDOWS:
        ps = which("powershell") or which("powershell.exe") or which("pwsh")
        if not ps:
            return
        script = r"""
$me = $PID
Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -ne $me -and (
    $_.Name -match '^(openclaw|moltbot|clawdbot|clawbot|clawhub)(\.exe)?$' -or
    $_.CommandLine -match 'node_modules[\\/](openclaw|moltbot|clawdbot|clawbot)' -or
    $_.CommandLine -match '\b(openclaw|moltbot|clawdbot|clawbot)\s+gateway\b' -or
    ($_.CommandLine -match '\.openclaw' -and $_.CommandLine -match 'gateway')
  )
} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress
"""
        cp = r.run_read([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=60)
        procs: list[dict[str, Any]] = []
        if cp.returncode == 0 and cp.stdout.strip():
            try:
                data = json.loads(cp.stdout)
                if isinstance(data, dict):
                    procs = [data]
                elif isinstance(data, list):
                    procs = [x for x in data if isinstance(x, dict)]
            except Exception:
                procs = []
        for proc in procs:
            pid = str(proc.get("ProcessId", ""))
            if not pid:
                continue
            r.run_mutate(["taskkill", "/PID", pid, "/T", "/F"], ok_codes=(0, 1, 128))


def discover_npm_global_packages() -> set[str]:
    pkgs: set[str] = set(PKG_EXACT)
    if which("npm"):
        cp = run_read_plain(["npm", "list", "-g", "--depth=0", "--json"], timeout=60)
        if cp.stdout.strip():
            try:
                data = json.loads(cp.stdout)
                deps = data.get("dependencies", {}) if isinstance(data, dict) else {}
                for name in deps:
                    if contains_keyword(name):
                        pkgs.add(name)
            except Exception:
                pass
    return pkgs


def discover_pnpm_global_packages() -> set[str]:
    pkgs: set[str] = set(PKG_EXACT)
    if which("pnpm"):
        cp = run_read_plain(["pnpm", "list", "-g", "--depth", "0", "--json"], timeout=60)
        if cp.stdout.strip():
            try:
                data = json.loads(cp.stdout)
                if isinstance(data, list):
                    for entry in data:
                        deps = entry.get("dependencies", {}) if isinstance(entry, dict) else {}
                        for name in deps:
                            if contains_keyword(name):
                                pkgs.add(name)
            except Exception:
                pass
    return pkgs


def package_manager_cleanup(r: Runner) -> None:
    r.info("\n== Package manager global uninstall ==")
    npm_pkgs = discover_npm_global_packages()
    pnpm_pkgs = discover_pnpm_global_packages()
    if which("npm"):
        for pkg in sorted(npm_pkgs):
            r.run_mutate(["npm", "rm", "-g", pkg], ok_codes=(0, 1, 127), timeout=180)
    if which("pnpm"):
        for pkg in sorted(pnpm_pkgs):
            r.run_mutate(["pnpm", "remove", "-g", pkg], ok_codes=(0, 1, 127), timeout=180)
    if which("bun"):
        for pkg in sorted(PKG_EXACT):
            r.run_mutate(["bun", "remove", "-g", pkg], ok_codes=(0, 1, 127), timeout=180)
    if which("yarn"):
        for pkg in sorted(PKG_EXACT):
            r.run_mutate(["yarn", "global", "remove", pkg], ok_codes=(0, 1, 127), timeout=180)
    # Common unofficial managers. Exact package names only; failures are harmless.
    if IS_WINDOWS:
        if which("scoop"):
            for pkg in sorted(PKG_EXACT):
                r.run_mutate(["scoop", "uninstall", pkg], ok_codes=(0, 1, 127), timeout=180)
        if which("choco"):
            for pkg in sorted(PKG_EXACT):
                r.run_mutate(["choco", "uninstall", pkg, "-y"], ok_codes=(0, 1, 127), timeout=300)
    else:
        if which("brew"):
            for pkg in sorted(PKG_EXACT):
                r.run_mutate(["brew", "uninstall", "--force", pkg], ok_codes=(0, 1, 127), timeout=300)


def nix_cleanup(r: Runner) -> None:
    if not which("nix") and not which("nix-env"):
        return
    r.info("\n== Nix profile cleanup ==")
    if which("nix"):
        cp = r.run_read(["nix", "profile", "list"], timeout=60)
        if cp.returncode == 0:
            indices: list[str] = []
            for line in cp.stdout.splitlines():
                if contains_keyword(line):
                    m = re.match(r"\s*(\d+)\s+", line)
                    if m:
                        indices.append(m.group(1))
                    else:
                        r.warn(f"Nix profile entry matches but index not parsed; remove manually: {line}")
            for idx in indices:
                r.run_mutate(["nix", "profile", "remove", idx], ok_codes=(0, 1, 127), timeout=180)
    if which("nix-env"):
        cp = r.run_read(["nix-env", "-q"], timeout=60)
        names: set[str] = set()
        if cp.returncode == 0:
            for line in cp.stdout.splitlines():
                if contains_keyword(line):
                    names.add(line.strip())
        for name in sorted(names):
            r.run_mutate(["nix-env", "-e", name], ok_codes=(0, 1, 127), timeout=180)


def docker_like_cleanup(r: Runner, tool: str) -> None:
    if not which(tool):
        return
    r.info(f"\n== {tool} containers/images/volumes/networks ==")
    # Containers.
    cp = r.run_read([tool, "container", "ls", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}"], timeout=60)
    if cp.returncode == 0:
        ids: list[str] = []
        for line in cp.stdout.splitlines():
            if contains_keyword(line):
                ids.append(line.split("\t", 1)[0])
        for cid in ids:
            r.run_mutate([tool, "rm", "-f", cid], ok_codes=(0, 1, 127), timeout=180)
    # Images.
    cp = r.run_read([tool, "image", "ls", "--format", "{{.ID}}\t{{.Repository}}:{{.Tag}}"], timeout=60)
    if cp.returncode == 0:
        ids = []
        for line in cp.stdout.splitlines():
            if contains_keyword(line):
                ids.append(line.split("\t", 1)[0])
        for iid in sorted(set(ids)):
            r.run_mutate([tool, "rmi", "-f", iid], ok_codes=(0, 1, 127), timeout=300)
    # Volumes.
    cp = r.run_read([tool, "volume", "ls", "--format", "{{.Name}}"], timeout=60)
    if cp.returncode == 0:
        for name in cp.stdout.splitlines():
            if contains_keyword(name):
                r.run_mutate([tool, "volume", "rm", "-f", name], ok_codes=(0, 1, 127), timeout=180)
    # Networks.
    cp = r.run_read([tool, "network", "ls", "--format", "{{.ID}}\t{{.Name}}"], timeout=60)
    if cp.returncode == 0:
        for line in cp.stdout.splitlines():
            if contains_keyword(line):
                nid = line.split("\t", 1)[0]
                r.run_mutate([tool, "network", "rm", nid], ok_codes=(0, 1, 127), timeout=180)


def docker_cleanup(r: Runner) -> None:
    if not r.args.purge_docker:
        return
    docker_like_cleanup(r, "docker")
    docker_like_cleanup(r, "podman")


def package_cache_paths() -> list[Path]:
    paths: list[Path] = []
    if IS_WINDOWS:
        bases = []
        for env in ["APPDATA", "LOCALAPPDATA", "USERPROFILE"]:
            if os.environ.get(env):
                bases.append(Path(os.environ[env]))
        for base in bases:
            for pat in ["npm-cache/_npx/*", "npm-cache/*", ".npm/_npx/*", ".bun/install/cache/*", "pnpm-store*/**/*"]:
                for p in base.glob(pat):
                    if contains_keyword(str(p)):
                        paths.append(p)
    else:
        for pat in [
            ".npm/_npx/*", ".npm/_cacache/index-v5/**/*", ".cache/pnpm/**/*", ".local/share/pnpm/store/**/*",
            ".bun/install/cache/*", ".cache/yarn/**/*",
        ]:
            for p in HOME.glob(pat):
                if contains_keyword(str(p)):
                    paths.append(p)
    return dedupe_paths(paths)


def remove_files(r: Runner, initial_paths: list[Path], config_files: list[Path]) -> None:
    r.info("\n== File and directory cleanup ==")
    # Parse configs before deleting them.
    discovered_workspaces: list[Path] = []
    discovered_managed: list[Path] = []
    discovered_extra_skills: list[Path] = []
    for cfg in config_files:
        if cfg.suffix.lower() == ".json" or cfg.name.lower().endswith(".json"):
            obj = load_json_file(cfg)
            if obj is None:
                continue
            ws, managed, extra = find_paths_in_config(obj, cfg.parent, r.args)
        else:
            ws, managed, extra = find_paths_in_env_config(cfg)
        discovered_workspaces.extend(ws)
        discovered_managed.extend(managed)
        discovered_extra_skills.extend(extra)

    # Include default state paths and managed plugin paths first.
    env_path_keys = {str(norm_path(p)).lower() for p in collect_env_overrides()}
    config_keys = {str(norm_path(p)).lower() for p in config_files}
    for p in dedupe_paths(initial_paths + discovered_managed):
        allow = str(norm_path(p)).lower() in env_path_keys or str(norm_path(p)).lower() in config_keys
        r.remove_path(p, "OpenClaw/Moltbot/Clawbot state/config/app/bin/plugin path", allow_without_keyword=allow)

    # Shared AgentSkills are deliberately separate.
    shared_agent_paths = [HOME / ".agents" / "skills"]
    if r.args.purge_shared_agent_skills:
        for p in shared_agent_paths:
            r.remove_path(p, "shared personal AgentSkills directory", allow_without_keyword=True)
    else:
        for p in shared_agent_paths:
            if p.exists():
                r.warn(f"left shared AgentSkills directory intact: {p}; use --purge-shared-agent-skills to remove it")

    # Workspaces: default state workspaces are already removed with state dir. External needs explicit flag.
    for ws in dedupe_paths(discovered_workspaces):
        under_state = any(is_subpath(ws, state) for state in initial_paths if state.exists() or contains_keyword(str(state)))
        if under_state or contains_keyword(str(ws)) or r.args.purge_external_workspaces:
            r.remove_path(ws, "workspace discovered in config", allow_without_keyword=r.args.purge_external_workspaces)
        else:
            r.warn(f"left external workspace intact: {ws}; use --purge-external-workspaces to remove it")

    if r.args.purge_extra_skill_dirs:
        for p in dedupe_paths(discovered_extra_skills):
            r.remove_path(p, "skills.load.extraDirs discovered in config", allow_without_keyword=True)
    else:
        for p in dedupe_paths(discovered_extra_skills):
            if p.exists():
                r.warn(f"left extra skill dir intact: {p}; use --purge-extra-skill-dirs to remove it")

    if r.args.purge_caches:
        for p in package_cache_paths():
            r.remove_path(p, "package-manager cache item")


def is_subpath(child: Path, parent: Path) -> bool:
    try:
        child = norm_path(child)
        parent = norm_path(parent)
        child.relative_to(parent)
        return True
    except Exception:
        return False


def scan_source_repos(r: Runner) -> None:
    if not r.args.scan_source:
        return
    r.info("\n== Source checkout scan ==")
    common_roots = [
        HOME, HOME / "Desktop", HOME / "Documents", HOME / "Downloads", HOME / "Projects", HOME / "projects",
        HOME / "Code", HOME / "code", HOME / "src", HOME / "workspace", HOME / "Work", HOME / "dev",
    ]
    exact_names = ["openclaw", "OpenClaw", "moltbot", "Moltbot", "clawdbot", "Clawdbot", "clawbot", "ClawBot", "clawdock"]
    candidates: set[Path] = set()
    for root in common_roots:
        for name in exact_names:
            p = root / name if root != HOME else HOME / name
            if p.exists() and p.is_dir():
                candidates.add(norm_path(p))

    # Limited walk for git repos. Avoid expensive system-wide scans.
    max_depth = 4
    max_dirs = 20000
    walked = 0
    for root in common_roots:
        if not root.exists() or not root.is_dir():
            continue
        root = norm_path(root)
        for dirpath, dirnames, filenames in os.walk(root):
            walked += 1
            if walked > max_dirs:
                r.warn("source scan stopped early after max directory limit")
                break
            dp = Path(dirpath)
            try:
                rel_depth = len(dp.relative_to(root).parts)
            except Exception:
                rel_depth = 0
            has_git = ".git" in dirnames or ".git" in filenames
            dirnames[:] = [d for d in dirnames if d not in SKIP_WALK_DIRS and not d.startswith(".")]
            if rel_depth >= max_depth:
                dirnames[:] = []
            if has_git:
                cfg = dp / ".git" / "config"
                if cfg.exists():
                    try:
                        text = cfg.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        text = ""
                    if re.search(r"github\.com[:/](openclaw/openclaw|moltbot/moltbot|.*clawdbot.*|.*clawbot.*)", text, re.I):
                        candidates.add(norm_path(dp))
                # Do not recurse into repo internals too deeply.
                if rel_depth >= 1:
                    dirnames[:] = [d for d in dirnames if d != ".git"]
        if walked > max_dirs:
            break

    for p in sorted(candidates, key=lambda x: str(x).lower()):
        if source_checkout_confirmed(p):
            r.remove_path(p, "confirmed source checkout")
        else:
            r.warn(f"candidate source folder not auto-removed because it is not confirmed as OpenClaw repo: {p}")


def source_checkout_confirmed(p: Path) -> bool:
    # Confirm via package.json name or git remote. Do not delete arbitrary folders just by name.
    pkg = p / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            name = str(data.get("name", ""))
            if contains_keyword(name):
                return True
            if name == "openclaw":
                return True
        except Exception:
            pass
    cfg = p / ".git" / "config"
    if cfg.exists():
        try:
            text = cfg.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"github\.com[:/](openclaw/openclaw|moltbot/moltbot|.*clawdbot.*|.*clawbot.*)", text, re.I):
                return True
        except Exception:
            pass
    return False


def clean_shell_rc(r: Runner) -> None:
    if not r.args.clean_shell_rc or IS_WINDOWS:
        return
    r.info("\n== Shell rc/profile cleanup ==")
    files = [
        HOME / ".bashrc", HOME / ".bash_profile", HOME / ".profile", HOME / ".zshrc", HOME / ".zprofile",
        HOME / ".config" / "fish" / "config.fish",
    ]
    patterns = ["OPENCLAW_", "MOLTBOT_", "CLAWDBOT_", "CLAWBOT_", "CLAWDOCK", "openclaw.ai", "clawdbot", "moltbot", "openclaw"]
    for f in files:
        if not f.exists() or not f.is_file():
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        except Exception as e:
            r.warn(f"could not read {f}: {e}")
            continue
        new_lines = [ln for ln in lines if not any(pat.lower() in ln.lower() for pat in patterns)]
        if len(new_lines) == len(lines):
            continue
        if r.dry_run:
            print(f"[DRY-RUN] edit shell rc: {f}  # remove {len(lines)-len(new_lines)} OpenClaw-related lines")
            continue
        backup = f.with_name(f.name + f".bak.openclaw-uninstall-{TIMESTAMP}")
        try:
            shutil.copy2(f, backup)
            f.write_text("".join(new_lines), encoding="utf-8")
            print(f"[EDIT] {f}; backup: {backup}")
        except Exception as e:
            r.err(f"failed to edit {f}: {e}")


def clean_windows_user_env(r: Runner) -> None:
    if not IS_WINDOWS:
        return
    r.info("\n== Windows user environment variables ==")
    ps = which("powershell") or which("powershell.exe") or which("pwsh")
    if not ps:
        return
    # Query user env vars by prefixes, then remove them.
    query = r"""
$keys = 'OPENCLAW_','MOLTBOT_','CLAWDBOT_','CLAWBOT_','CLAWDOCK_'
$vars = [Environment]::GetEnvironmentVariables('User').Keys | Where-Object {
  $k = [string]$_
  $keys | Where-Object { $k.StartsWith($_) }
}
$vars | ConvertTo-Json -Compress
"""
    cp = r.run_read([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", query], timeout=60)
    names: list[str] = []
    if cp.returncode == 0 and cp.stdout.strip():
        try:
            data = json.loads(cp.stdout)
            if isinstance(data, str):
                names = [data]
            elif isinstance(data, list):
                names = [str(x) for x in data]
        except Exception:
            pass
    for name in names:
        cmd = f"[Environment]::SetEnvironmentVariable('{name}', $null, 'User')"
        r.run_mutate([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd], ok_codes=(0, 1))


def clean_windows_machine_env(r: Runner) -> None:
    if not IS_WINDOWS or not r.args.clean_machine_env:
        return
    r.info("\n== Windows machine environment variables ==")
    ps = which("powershell") or which("powershell.exe") or which("pwsh")
    if not ps:
        return
    query = r"""
$keys = 'OPENCLAW_','MOLTBOT_','CLAWDBOT_','CLAWBOT_','CLAWDOCK_'
$vars = [Environment]::GetEnvironmentVariables('Machine').Keys | Where-Object {
  $k = [string]$_
  $keys | Where-Object { $k.StartsWith($_) }
}
$vars | ConvertTo-Json -Compress
"""
    cp = r.run_read([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", query], timeout=60)
    names: list[str] = []
    if cp.returncode == 0 and cp.stdout.strip():
        try:
            data = json.loads(cp.stdout)
            if isinstance(data, str):
                names = [data]
            elif isinstance(data, list):
                names = [str(x) for x in data]
        except Exception:
            pass
    for name in names:
        cmd = f"[Environment]::SetEnvironmentVariable('{name}', $null, 'Machine')"
        r.run_mutate([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd], ok_codes=(0, 1))


def clean_windows_powershell_profiles(r: Runner) -> None:
    if not IS_WINDOWS or not r.args.clean_shell_rc:
        return
    r.info("\n== Windows PowerShell profile cleanup ==")
    docs = Path(os.environ.get("USERPROFILE", str(HOME))) / "Documents"
    files = [
        HOME / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        HOME / "Documents" / "PowerShell" / "profile.ps1",
        HOME / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
        HOME / "Documents" / "WindowsPowerShell" / "profile.ps1",
        docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        docs / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
    ]
    patterns = ["OPENCLAW_", "MOLTBOT_", "CLAWDBOT_", "CLAWBOT_", "CLAWDOCK", "openclaw.ai", "clawdbot", "moltbot", "openclaw"]
    for f in dedupe_paths(files):
        if not f.exists() or not f.is_file():
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        except Exception as e:
            r.warn(f"could not read {f}: {e}")
            continue
        new_lines = [ln for ln in lines if not any(pat.lower() in ln.lower() for pat in patterns)]
        if len(new_lines) == len(lines):
            continue
        if r.dry_run:
            print(f"[DRY-RUN] edit PowerShell profile: {f}  # remove {len(lines)-len(new_lines)} OpenClaw-related lines")
            continue
        backup = f.with_name(f.name + f".bak.openclaw-uninstall-{TIMESTAMP}")
        try:
            shutil.copy2(f, backup)
            f.write_text("".join(new_lines), encoding="utf-8")
            print(f"[EDIT] {f}; backup: {backup}")
        except Exception as e:
            r.err(f"failed to edit {f}: {e}")


def query_reg_subkeys(root: str) -> list[str]:
    cp = run_read_plain(["reg.exe", "query", root], timeout=60)
    if cp.returncode != 0:
        return []
    out: list[str] = []
    for line in cp.stdout.splitlines():
        line = line.strip()
        if line.startswith(root + "\\"):
            out.append(line)
    return out


def reg_key_has_keyword(key: str) -> bool:
    cp = run_read_plain(["reg.exe", "query", key, "/s"], timeout=60)
    if cp.returncode != 0:
        return False
    return contains_keyword(key) or contains_keyword(cp.stdout) or contains_keyword(cp.stderr)


def clean_windows_registry(r: Runner) -> None:
    if not IS_WINDOWS or not r.args.clean_registry or not which("reg.exe"):
        return
    r.info("\n== Windows registry cleanup ==")
    exact_keys = [
        r"HKCU\Software\OpenClaw", r"HKCU\Software\MoltBot", r"HKCU\Software\Moltbot",
        r"HKCU\Software\Clawdbot", r"HKCU\Software\ClawBot", r"HKCU\Software\Clawbot",
        r"HKCU\Software\ClawHub", r"HKLM\Software\OpenClaw", r"HKLM\Software\MoltBot",
        r"HKLM\Software\Moltbot", r"HKLM\Software\Clawdbot", r"HKLM\Software\ClawBot",
        r"HKLM\Software\Clawbot", r"HKLM\Software\ClawHub",
    ]
    scan_roots = [
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths",
        r"HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths",
    ]
    keys: set[str] = {key for key in exact_keys if reg_key_has_keyword(key)}
    for root in scan_roots:
        for key in query_reg_subkeys(root):
            if reg_key_has_keyword(key):
                keys.add(key)
    for key in sorted(keys):
        r.run_mutate(["reg.exe", "delete", key, "/f"], ok_codes=(0, 1, 2))

    # Run/StartupApproved can contain many unrelated values, so remove values only.
    ps = which("powershell") or which("powershell.exe") or which("pwsh")
    if not ps:
        return
    script = r"""
$roots = @(
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run',
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
)
$hits = @()
foreach ($root in $roots) {
  if (-not (Test-Path $root)) { continue }
  $item = Get-ItemProperty -Path $root
  foreach ($prop in $item.PSObject.Properties) {
    if ($prop.Name -like 'PS*') { continue }
    $text = "$($prop.Name) $($prop.Value)"
    if ($text -match 'openclaw|moltbot|clawdbot|clawbot|clawdock|clawhub') {
      $hits += [pscustomobject]@{ Path = $root; Name = $prop.Name }
    }
  }
}
$hits | ConvertTo-Json -Compress
"""
    cp = r.run_read([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=60)
    hits: list[dict[str, Any]] = []
    if cp.returncode == 0 and cp.stdout.strip():
        try:
            data = json.loads(cp.stdout)
            if isinstance(data, dict):
                hits = [data]
            elif isinstance(data, list):
                hits = [x for x in data if isinstance(x, dict)]
        except Exception:
            hits = []
    for hit in hits:
        path = str(hit.get("Path", ""))
        name = str(hit.get("Name", ""))
        if path and name:
            r.run_mutate([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Remove-ItemProperty -Path '{path}' -Name '{name}' -ErrorAction SilentlyContinue"], ok_codes=(0, 1))


def vscode_extension_cleanup(r: Runner) -> None:
    if not r.args.purge_vscode_extensions:
        return
    r.info("\n== VS Code extension cleanup ==")
    code_bins = ["code", "code-insiders", "codium"]
    for bin_name in code_bins:
        if not which(bin_name):
            continue
        cp = r.run_read([bin_name, "--list-extensions"], timeout=60)
        if cp.returncode != 0:
            continue
        for ext in cp.stdout.splitlines():
            if contains_keyword(ext):
                r.run_mutate([bin_name, "--uninstall-extension", ext], ok_codes=(0, 1), timeout=120)


def final_residue_report(r: Runner) -> None:
    r.info("\n== Residue check ==")
    suspects: list[str] = []
    # Command presence.
    for cmd in list(CLI_NAMES) + ["clawhub"]:
        exe = which(cmd)
        if exe:
            suspects.append(f"command still on PATH: {cmd} -> {exe}")
    # Key paths.
    state_paths, _ = collect_state_and_config_paths(r.args)
    for p in state_paths:
        if p.exists() or p.is_symlink():
            suspects.append(f"path still exists: {p}")
    if suspects:
        for s in suspects[:200]:
            print(f"[LEFT] {s}")
        if len(suspects) > 200:
            print(f"[LEFT] ... {len(suspects)-200} more")
    else:
        print("No obvious OpenClaw/Moltbot/Clawbot residue found in checked locations.")


def write_json_report(r: Runner, args: argparse.Namespace) -> None:
    if not args.report_json:
        return
    report = {
        "version": __version__,
        "timestamp": TIMESTAMP,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "mode": "apply" if args.yes else "dry-run",
        "quarantine_root": str(r.quarantine_root) if r.quarantine_root else None,
        "removed": r.removed,
        "warnings": r.warned,
        "errors": r.errors,
    }
    p = norm_path(Path(args.report_json))
    if r.dry_run:
        print(f"[DRY-RUN] write JSON report: {p}")
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[REPORT] {p}")
    except Exception as e:
        r.err(f"failed to write JSON report {p}: {e}")


def main() -> int:
    args = parse_args()
    log_fp = setup_transcript(args.log_file)
    r = Runner(args)
    print("OpenClaw / Moltbot / Clawdbot / ClawBot full uninstaller")
    print(f"Platform: {platform.platform()}  Python: {sys.version.split()[0]}")
    print(f"Mode: {'APPLY (will delete)' if args.yes else 'DRY-RUN (no changes)'}")
    emit_privilege_hint(args)
    if args.yes and not args.quarantine:
        print("Deletion mode: permanent delete. Use --quarantine to move files aside instead.")
    if args.quarantine:
        print(f"Quarantine root: {r.quarantine_root}")

    initial_paths, config_files = collect_state_and_config_paths(args)

    # Do service shutdown before file removal, but config paths have already been collected.
    official_cli_uninstall(r)
    linux_systemd_cleanup(r)
    windows_task_cleanup(r)
    windows_service_cleanup(r)
    terminate_processes(r)
    package_manager_cleanup(r)
    nix_cleanup(r)
    docker_cleanup(r)
    vscode_extension_cleanup(r)
    remove_files(r, initial_paths, config_files)
    scan_source_repos(r)
    clean_shell_rc(r)
    clean_windows_powershell_profiles(r)
    clean_windows_user_env(r)
    clean_windows_machine_env(r)
    clean_windows_registry(r)
    final_residue_report(r)
    write_json_report(r, args)

    print("\n== Summary ==")
    print(f"Mode: {'APPLY' if args.yes else 'DRY-RUN'}")
    print(f"Warnings: {len(r.warned)}  Errors: {len(r.errors)}")
    if r.errors:
        print("Some removals failed; re-run as the installing user, or with admin/root only for system-wide services.")
    if not args.yes:
        print("Dry-run only. Re-run with --yes after reviewing the planned actions.")
    if log_fp:
        log_fp.close()
    return 1 if r.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
