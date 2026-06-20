from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type

from colorama import Fore, Style

# Make ``src/`` importable when running this script directly.
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.utils import log_error, log_info, log_success, log_warning  # noqa: E402


# ---------------------------------------------------------------------------
# Console UI helpers
# ---------------------------------------------------------------------------

# Accent colours used across the launcher UI.
_C_TITLE = Fore.CYAN          # banner title
_C_ACCENT = Fore.MAGENTA      # headings / prompt
_C_LABEL = Fore.YELLOW        # inline labels / numbers
_C_DIM = Fore.WHITE           # secondary text / rules
_C_HINT = Fore.GREEN          # usage hints / keys


def _banner(title: str, subtitle: str = "") -> None:
    """Render a double-line banner box.

    The box auto-sizes to the longest line so it always looks balanced.
    """
    inner = [title]
    if subtitle:
        inner.append("")
        inner.append(subtitle)

    width = max(len(line) for line in inner) + 4

    top = "╔" + "═" * width + "╗"
    bot = "╚" + "═" * width + "╝"

    print()
    print(f"{_C_TITLE}{top}{Style.RESET_ALL}")
    for line in inner:
        pad = (width - len(line)) // 2
        centered = " " * pad + line + " " * (width - len(line) - pad)
        print(f"{_C_TITLE}║{centered}║{Style.RESET_ALL}")
    print(f"{_C_TITLE}{bot}{Style.RESET_ALL}")


def _rule(width: int = 52) -> None:
    print(_C_DIM + ("─" * width) + Style.RESET_ALL)


def _section_header(label: str) -> None:
    """A small uppercase section label with an underline rule."""
    print()
    print(f"{_C_ACCENT}{label}{Style.RESET_ALL}")
    _rule(max(len(label), 40))


def _hint_row(key: str, desc: str) -> None:
    """A two-column hint line: highlighted key + dim description."""
    print(f"    {_C_HINT}{key:<18}{Style.RESET_ALL}{_C_DIM}{desc}{Style.RESET_ALL}")


# ---------------------------------------------------------------------------
# Game discovery / loading
# ---------------------------------------------------------------------------

def scan_games() -> Dict[str, Dict[str, str]]:
    """Discover available games under ``src/games``.

    A game is any directory ``src/games/<name>/`` that contains a
    ``<name>.py`` module file. The ``template`` directory is skipped.
    """
    games_dir = _PROJECT_ROOT / "src" / "games"
    games: Dict[str, Dict[str, str]] = {}
    if not games_dir.exists():
        log_error(f"Games directory not found: {games_dir}")
        return games

    for item in sorted(games_dir.iterdir()):
        if not item.is_dir() or item.name.startswith("__") or item.name == "template":
            continue
        game_file = item / f"{item.name}.py"
        if not game_file.exists():
            continue
        games[item.name] = {
            "module_path": f"src.games.{item.name}.{item.name}",
            "display_name": item.name.upper(),
        }
    return games


def load_game_class(game_info: Dict[str, str]) -> Optional[Type]:
    """Load the game class named after the game directory (case-insensitive)."""
    try:
        module = importlib.import_module(game_info["module_path"])
    except Exception as e:
        log_error(f"Could not import {game_info['module_path']}: {e}", exc_info=True)
        return None

    target = game_info["display_name"].lower()
    for attr in dir(module):
        if attr.lower() == target:
            return getattr(module, attr)
    log_error(f"No class matching '{target}' found in {game_info['module_path']}")
    return None


def _run_cli(game_class: Type) -> None:
    game = game_class()
    game.start()


def _run_gui(game_class: Type, title: str) -> None:
    # Import lazily so the launcher works in CLI-only environments.
    from src.gui.pyside_gui import run_with_pyside
    run_with_pyside(game_class, title)


def run_game(game_class: Type, title: str, gui: bool) -> None:
    try:
        if gui:
            log_success(f"Starting {title} with PySide6 GUI...")
            _run_gui(game_class, title)
        else:
            log_success(f"Starting {title} (CLI). Press 'q' to stop.")
            _run_cli(game_class)
    except KeyboardInterrupt:
        log_info("Stopped by user")
    except Exception as e:
        log_error(f"Error running automation: {e}", exc_info=True)
    finally:
        log_info("Automation ended")


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

def list_games(games: Dict[str, Dict[str, str]]) -> None:
    """Compact one-shot game listing (used by ``--list``)."""
    _section_header("AVAILABLE GAMES")
    if not games:
        print(f"  {_C_DIM}(none){Style.RESET_ALL}")
        return
    for name, info in games.items():
        print(
            f"  {_C_LABEL}{name:<16}{Style.RESET_ALL}"
            f"{_C_DIM}→{Style.RESET_ALL} {_C_TITLE}{info['display_name']}{Style.RESET_ALL}"
        )


def _print_games_panel(names: List[str], games: Dict[str, Dict[str, str]]) -> None:
    """Render the numbered games panel for the interactive menu."""
    _section_header("GAMES")
    if not names:
        print(f"  {_C_DIM}No games detected in src/games/{Style.RESET_ALL}")
        return

    # Width of the number column so rows align.
    num_w = len(str(len(names)))

    for idx, name in enumerate(names, 1):
        display = games[name]["display_name"]
        print(
            f"  {_C_LABEL}{idx:>{num_w}}.{Style.RESET_ALL}  "
            f"{_C_TITLE}{display}{Style.RESET_ALL}"
        )


def _print_usage_legend() -> None:
    _section_header("USAGE")
    _hint_row("1", "select game by number")
    _hint_row("1g", "launch with GUI (append 'g')")
    _hint_row("0", "exit")


def interactive_menu(games: Dict[str, Dict[str, str]]) -> None:
    if not games:
        log_error("No games found in src/games. Add a game directory and try again.")
        return

    while True:
        _banner("ADB GAME AUTOMATION", "Control ADB games from your terminal")

        names = list(games.keys())
        _print_games_panel(names, games)
        _print_usage_legend()

        # Coloured prompt.
        prompt = (
            f"\n  {_C_ACCENT}❯{Style.RESET_ALL} "
            f"{_C_DIM}Select a game:{Style.RESET_ALL} "
        )
        try:
            choice = input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            log_info("Exiting...")
            return

        if choice == "":
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
            log_warning("Invalid choice. Please try again.")
            continue

        info = games[names[idx]]
        game_class = load_game_class(info)
        if game_class is None:
            log_error(f"Failed to load {info['display_name']}")
            continue
        run_game(game_class, f"{info['display_name']} Automation", gui)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Game Automation Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python launcher.py                  # Interactive menu\n"
            "  python launcher.py --list           # List games\n"
            "  python launcher.py bd2              # Run BD2 in CLI mode\n"
            "  python launcher.py bd2 --gui        # Run BD2 with GUI\n"
        ),
    )
    parser.add_argument("game", nargs="?", help="Name of the game to run")
    parser.add_argument("--gui", action="store_true", help="Run with the PySide6 GUI")
    parser.add_argument("--list", "-l", action="store_true", help="List available games")
    args = parser.parse_args()

    games = scan_games()

    if args.list:
        list_games(games)
        return 0

    if not args.game:
        # No game specified: interactive menu.
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
