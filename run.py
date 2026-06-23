"""
ADB Game Automation — CLI Runner

Usage::

    python run.py                        # Interactive menu
    python run.py --list                 # List available games
    python run.py cherrytale             # Run in CLI mode
    python run.py cherrytale --gui       # Run with PyWebView GUI
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Type

from colorama import Fore, Style

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from launcher import load_game_class, scan_games  # noqa: E402
from src.utils import log_error, log_info, log_success, log_warning  # noqa: E402


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

_C_TITLE  = Fore.CYAN
_C_ACCENT = Fore.MAGENTA
_C_LABEL  = Fore.YELLOW
_C_DIM    = Fore.WHITE
_C_HINT   = Fore.GREEN


def _banner(title: str, subtitle: str = "") -> None:
    inner = [title]
    if subtitle:
        inner += ["", subtitle]
    width = max(len(l) for l in inner) + 4
    top = "╔" + "═" * width + "╗"
    bot = "╚" + "═" * width + "╝"
    print()
    print(f"{_C_TITLE}{top}{Style.RESET_ALL}")
    for line in inner:
        pad = (width - len(line)) // 2
        centered = " " * pad + line + " " * (width - len(line) - pad)
        print(f"{_C_TITLE}║{centered}║{Style.RESET_ALL}")
    print(f"{_C_TITLE}{bot}{Style.RESET_ALL}")


def _rule(w: int = 52) -> None:
    print(_C_DIM + "─" * w + Style.RESET_ALL)


def _section(label: str) -> None:
    print()
    print(f"{_C_ACCENT}{label}{Style.RESET_ALL}")
    _rule(max(len(label), 40))


def _hint(key: str, desc: str) -> None:
    print(f"    {_C_HINT}{key:<16}{Style.RESET_ALL}{_C_DIM}{desc}{Style.RESET_ALL}")


# ---------------------------------------------------------------------------
# Run helpers
# ---------------------------------------------------------------------------

def _run_cli(game_class: Type) -> None:
    game = game_class()
    game.start()


def _run_gui(game_class: Type, title: str) -> None:
    from src.gui.pywebview_gui import run_with_pywebview
    run_with_pywebview(game_class, title)


def run_game(game_class: Type, title: str, gui: bool = False) -> None:
    try:
        if gui:
            log_success(f"Starting {title} with GUI...")
            _run_gui(game_class, title)
        else:
            log_success(f"Starting {title} (CLI)...")
            _run_cli(game_class)
    except KeyboardInterrupt:
        log_info("Stopped by user")
    except Exception as e:
        log_error(f"Error: {e}", exc_info=True)
    finally:
        log_info("Automation ended")


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

def list_games(games: Dict[str, Dict[str, str]]) -> None:
    _section("AVAILABLE GAMES")
    if not games:
        print(f"  {_C_DIM}(none){Style.RESET_ALL}")
        return
    for name, info in games.items():
        print(
            f"  {_C_LABEL}{name:<16}{Style.RESET_ALL}"
            f"{_C_DIM}→{Style.RESET_ALL} {_C_TITLE}{info['display_name']}{Style.RESET_ALL}"
        )


def _print_games(names: List[str], games: Dict[str, Dict[str, str]]) -> None:
    _section("GAMES")
    if not names:
        print(f"  {_C_DIM}No games found in src/games/{Style.RESET_ALL}")
        return
    w = len(str(len(names)))
    for i, name in enumerate(names, 1):
        print(
            f"  {_C_LABEL}{i:>{w}}.{Style.RESET_ALL}  "
            f"{_C_TITLE}{games[name]['display_name']}{Style.RESET_ALL}"
        )


def _print_usage() -> None:
    _section("USAGE")
    _hint("1",    "run game in CLI mode")
    _hint("1g",   "run game with GUI (append 'g')")
    _hint("0",    "exit")


def interactive_menu(games: Dict[str, Dict[str, str]]) -> None:
    if not games:
        log_error("No games found in src/games/")
        return

    names = list(games.keys())
    while True:
        _banner("ADB GAME AUTOMATION", "Control ADB games from your terminal")
        _print_games(names, games)
        _print_usage()

        prompt = (
            f"\n  {_C_ACCENT}❯{Style.RESET_ALL} "
            f"{_C_DIM}Select:{Style.RESET_ALL} "
        )
        try:
            choice = input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            log_info("Exiting...")
            return

        if not choice:
            continue
        if choice == "0":
            log_info("Exiting...")
            return

        gui = choice.lower().endswith("g")
        if gui:
            choice = choice[:-1]

        try:
            idx = int(choice) - 1
        except ValueError:
            log_warning("Please enter a valid number.")
            continue
        if not 0 <= idx < len(names):
            log_warning("Invalid choice.")
            continue

        info = games[names[idx]]
        game_class = load_game_class(info)
        if game_class is None:
            log_error(f"Failed to load {info['display_name']}")
            continue
        run_game(game_class, f"{info['display_name']} Automation", gui)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Game Automation CLI Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run.py                      # Interactive menu\n"
            "  python run.py --list               # List games\n"
            "  python run.py cherrytale           # CLI mode\n"
            "  python run.py cherrytale --gui     # PyWebView GUI\n"
        ),
    )
    parser.add_argument("game", nargs="?", help="Game name to run")
    parser.add_argument("--gui",  action="store_true", help="Launch with PyWebView GUI")
    parser.add_argument("--list", "-l", action="store_true", help="List available games")
    args = parser.parse_args()

    games = scan_games()

    if args.list:
        list_games(games)
        return 0

    if not args.game:
        interactive_menu(games)
        return 0

    name = args.game.lower()
    if name not in games:
        log_error(f"Unknown game '{args.game}'.")
        list_games(games)
        return 1

    info = games[name]
    game_class = load_game_class(info)
    if game_class is None:
        return 1
    run_game(game_class, f"{info['display_name']} Automation", args.gui)
    return 0


if __name__ == "__main__":
    sys.exit(main())
