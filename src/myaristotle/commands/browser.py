from pathlib import Path
import shutil
import subprocess
import sys

from ..browser import find_chrome_profile_for_account
from ..config import load_config
from .common import RichHelpFormatter, console, err_console, resolve_target_project


def register(subparsers):
    p = subparsers.add_parser(
        "open_pwd_in_browser",
        help="Open Aristotle project URL in Google Chrome with the matching account profile",
        formatter_class=RichHelpFormatter,
    )
    p.add_argument("target", nargs="?", default=None, help="Target project spec, ID, or directory")
    p.add_argument("--config", "-c", type=Path, default=None, help="Path to config.yaml")
    p.set_defaults(func=handle)


def handle(args):
    cfg, _ = load_config(args.config)
    resolved = resolve_target_project(cfg, args.target)

    if not resolved:
        err_console.print(f"[red]Error: Could not find configured project for '{args.target or Path.cwd().name}'[/red]")
        sys.exit(1)

    target_spec, p_cfg = resolved
    url = f"https://aristotle.harmonic.fun/projects/{p_cfg.id}"
    profile_dir = find_chrome_profile_for_account(p_cfg.account)

    chrome_bin = shutil.which("google-chrome-stable") or shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome_bin:
        err_console.print("[red]Error: google-chrome-stable executable not found in PATH.[/red]")
        sys.exit(1)

    cmd = [chrome_bin]
    if profile_dir:
        cmd.append(f"--profile-directory={profile_dir}")
    cmd.append(url)

    prof_desc = f"profile: [cyan]{profile_dir}[/cyan]" if profile_dir else "[yellow]no matching profile found[/yellow]"
    console.print(
        f"[bold green]🌐 Opening Aristotle project[/bold green] [cyan]{p_cfg.id}[/cyan] "
        f"([dim]{target_spec}[/dim]) in Google Chrome\n"
        f"   [dim]Account:[/dim] [bold]{p_cfg.account}[/bold] ({prof_desc})\n"
        f"   [dim]URL:[/dim] [link={url}]{url}[/link]"
    )

    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
