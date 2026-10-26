"""Interactive tester for GenAI review description prompts.

Reuses Frigate's GenAI provider plugins and prompt builders so results match
what Frigate produces at runtime, without needing a running Frigate instance.

Setup:
    1. Enable `review.genai.debug_save_thumbnails: True` in Frigate so debug
       output is saved under clips/genai-requests/<review_id>/.
    2. Copy one or more of those folders (numbered frame images plus
       prompt.txt) into testing-scripts/genai-review-examples/.
    3. Activate the project's virtual environment and run from the repo root:
       python testing-scripts/genai_review_tester.py

The script presents a menu to edit provider settings (provider, base URL,
optional API key, model) or run an example. Examples are selected with the
up/down arrow keys and launched with Enter. A writing style preset can be
applied on top of the saved prompt to compare tone between runs, and after a
response the model can be asked follow-up questions about the same frames.

Provider settings are stored in
testing-scripts/genai-review-examples/.settings.json (gitignored).
"""

import importlib
import json
import logging
import os
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    import msvcrt
else:  # pragma: no cover - the Windows build never reaches this branch
    import termios
    import tty

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from gannet.config.camera.genai import GenAIConfig, GenAIProviderEnum  # noqa: E402
from gannet.genai.prompts import (  # noqa: E402
    REVIEW_RESPONSE_STYLES,
    build_review_description_response_format,
)

EXAMPLES_DIR = Path(__file__).resolve().parent / "genai-review-examples"
SETTINGS_FILE = EXAMPLES_DIR / ".settings.json"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Providers are imported individually so a missing SDK for an unused provider
# does not break the script. Keys match GenAIProviderEnum values, values are
# the module names under gannet.genai.plugins.
PROVIDER_MODULES = {
    GenAIProviderEnum.openai: "openai",
    GenAIProviderEnum.azure_openai: "azure-openai",
    GenAIProviderEnum.gemini: "gemini",
    GenAIProviderEnum.ollama: "ollama",
    GenAIProviderEnum.llamacpp: "llama_cpp",
}


@dataclass
class TesterSettings:
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 120
    runtime_options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "TesterSettings":
        if SETTINGS_FILE.is_file():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                return cls(
                    **{k: v for k, v in data.items() if k in cls.__annotations__}
                )
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Ignoring invalid settings file: {e}")
        return cls()

    def save(self) -> None:
        EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def describe(self) -> str:
        if not self.provider:
            return "not configured"
        key = "set" if self.api_key else "none"
        return (
            f"provider={self.provider} base_url={self.base_url or '(default)'} "
            f"model={self.model or '(none)'} api_key={key}"
        )


#: the keys the menu understands, normalized across platforms
KEY_UP = "up"
KEY_DOWN = "down"
KEY_ENTER = "enter"
KEY_ESCAPE = "escape"
KEY_CANCEL = "cancel"

#: the scan codes the Windows console reports for the arrow keys
WINDOWS_SCAN_CODES = {"H": KEY_UP, "P": KEY_DOWN}


def _read_key_posix() -> str:
    """Read one key press from a POSIX terminal in cbreak mode."""
    char = sys.stdin.read(1)

    if char == "\x1b":
        sequence = sys.stdin.read(1)
        if sequence != "[":
            return KEY_ESCAPE
        arrow = sys.stdin.read(1)
        return {"A": KEY_UP, "B": KEY_DOWN}.get(arrow, "")

    if char in ("\r", "\n"):
        return KEY_ENTER

    if char == "\x03":
        return KEY_CANCEL

    return char


def _read_key_windows() -> str:
    """Read one key press from the Windows console.

    The console reports a function or arrow key as a two character sequence:
    a prefix of ``\\x00`` or ``\\xe0`` followed by the scan code.
    """
    char = msvcrt.getwch()

    if char in ("\x00", "\xe0"):
        return WINDOWS_SCAN_CODES.get(msvcrt.getwch(), "")

    if char == "\x03":
        return KEY_CANCEL

    if char in ("\r", "\n"):
        return KEY_ENTER

    if char == "\x1b":
        return KEY_ESCAPE

    return char


@contextmanager
def _raw_key_input():
    """Read single key presses without the terminal echoing them.

    POSIX puts the terminal in cbreak mode, Windows uses the console's own
    key reader, which never echoes.
    """
    if IS_WINDOWS:
        yield _read_key_windows
        return

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield _read_key_posix
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)


@contextmanager
def _ansi_console() -> Iterator[bool]:
    """Enable ANSI cursor control while drawing, restoring the mode afterward.

    Windows 10 and 11 support escape sequences, but the console only processes
    them when virtual terminal processing is enabled. The mode belongs to the
    console rather than this process, so the original value must be restored
    when the menu exits.
    """
    if not IS_WINDOWS:
        yield True
        return

    import ctypes
    from ctypes import wintypes

    enable_virtual_terminal_processing = 0x0004
    std_output_handle = ctypes.c_uint32(-11).value

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_std_handle = kernel32.GetStdHandle
        get_std_handle.argtypes = [wintypes.DWORD]
        get_std_handle.restype = wintypes.HANDLE

        get_console_mode = kernel32.GetConsoleMode
        get_console_mode.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_console_mode.restype = wintypes.BOOL

        set_console_mode = kernel32.SetConsoleMode
        set_console_mode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        set_console_mode.restype = wintypes.BOOL

        handle = get_std_handle(std_output_handle)
        mode = wintypes.DWORD()
        can_enable = get_console_mode(handle, ctypes.byref(mode))
        original_mode = mode.value
        can_enable = can_enable and set_console_mode(
            handle, original_mode | enable_virtual_terminal_processing
        )
    except (AttributeError, OSError):  # pragma: no cover - Windows only
        yield False
        return

    if not can_enable:
        yield False
        return

    try:
        yield True
    finally:
        set_console_mode(handle, original_mode)


def select_option(
    title: str, options: list[str], descriptions: list[str] | None = None
) -> int | None:
    """Render an arrow-key menu and return the selected index, or None.

    Up/down (or j/k) moves, Enter selects, q or Esc cancels. Falls back to a
    numbered prompt when stdin is not a TTY.
    """
    print(f"\n{title}")

    if not sys.stdin.isatty():
        for i, option in enumerate(options):
            print(f"  {i + 1}. {option}")
        choice = input("Selection (blank to cancel): ").strip()
        if not choice:
            return None
        try:
            index = int(choice) - 1
        except ValueError:
            return None
        return index if 0 <= index < len(options) else None

    selected = 0

    def render(first: bool, *, in_place: bool) -> None:
        if not first:
            if in_place:
                # Move the cursor back up and redraw in place
                sys.stdout.write(f"\x1b[{len(options)}A")
            else:
                # the console cannot move the cursor, so the menu is printed
                # again and the previous copy scrolls out of the way
                print()
        for i, option in enumerate(options):
            marker = "❯" if i == selected else " "
            line = f"  {marker} {option}"
            if descriptions and descriptions[i]:
                line += f"  ({descriptions[i]})"
            if in_place:
                sys.stdout.write(f"\x1b[2K{line}\n")
            else:
                sys.stdout.write(f"{line}\n")
        sys.stdout.flush()

    with _ansi_console() as in_place:
        render(True, in_place=in_place)

        with _raw_key_input() as read_key:
            while True:
                key = read_key()

                if key == KEY_UP or key == "k":
                    selected = (selected - 1) % len(options)
                elif key == KEY_DOWN or key == "j":
                    selected = (selected + 1) % len(options)
                elif key == KEY_ENTER:
                    return selected
                elif key in (KEY_ESCAPE, KEY_CANCEL, "q"):
                    return None
                else:
                    continue

                render(False, in_place=in_place)


def prompt_text(label: str, current: str, secret: bool = False) -> str:
    """Prompt for a text value, keeping the current value on empty input."""
    shown = ("***" if current else "") if secret else current
    value = input(f"{label} [{shown}]: ").strip()
    if not value:
        return current
    if value == "-":
        return ""
    return value


def edit_settings(settings: TesterSettings) -> None:
    providers = [p.value for p in GenAIProviderEnum]
    index = select_option("Select a provider:", providers)
    if index is None:
        return

    settings.provider = providers[index]
    print("Enter a value, press Enter to keep the current value, or '-' to clear.")
    settings.base_url = prompt_text("Base URL", settings.base_url)
    settings.api_key = prompt_text("API key (optional)", settings.api_key, secret=True)
    settings.model = prompt_text("Model", settings.model)
    settings.save()
    print(f"Saved settings: {settings.describe()}")


def build_client(settings: TesterSettings) -> Any | None:
    """Instantiate the Frigate provider client for the saved settings."""
    from gannet.genai import PROVIDERS

    try:
        provider = GenAIProviderEnum(settings.provider)
    except ValueError:
        print("No valid provider configured. Edit settings first.")
        return None

    module = PROVIDER_MODULES[provider]
    try:
        importlib.import_module(f"gannet.genai.plugins.{module}")
    except ImportError as e:
        print(f"Failed to import provider plugin '{module}': {e}")
        return None

    config = GenAIConfig(
        provider=provider,
        base_url=settings.base_url or None,
        api_key=settings.api_key or None,
        model=settings.model,
        runtime_options=settings.runtime_options,
    )
    client = PROVIDERS[provider](config, timeout=settings.timeout, validate_model=False)
    if client.provider is None:
        print("Provider failed to initialize. Check the base URL and API key.")
        return None
    return client


def list_examples() -> list[Path]:
    if not EXAMPLES_DIR.is_dir():
        return []
    return sorted(
        entry
        for entry in EXAMPLES_DIR.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )


def load_frames(example: Path) -> list[bytes]:
    """Load the example's frames as JPEG bytes in frame order.

    Frames are saved by Frigate as <index>.jpg or <index>.webp. Non-JPEG
    images are re-encoded to JPEG to match what Frigate sends to providers.
    """
    import cv2

    def frame_order(path: Path) -> tuple[int, str]:
        try:
            return (int(path.stem), path.name)
        except ValueError:
            return (1 << 30, path.name)

    frames: list[bytes] = []
    files = sorted(
        (f for f in example.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS),
        key=frame_order,
    )
    for file in files:
        if file.suffix.lower() in (".jpg", ".jpeg"):
            frames.append(file.read_bytes())
            continue

        image = cv2.imread(str(file))
        if image is None:
            print(f"  Skipping unreadable image {file.name}")
            continue
        ok, jpg = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
        if ok:
            frames.append(jpg.tobytes())
    return frames


def apply_style(prompt: str, style: str) -> str:
    """Apply a style preset to a saved prompt.

    Presets replace the per-field response guidance lines, matching what
    Frigate builds at runtime. Handles both the current guidance format
    ("- `scene`: ...") and the 0.17 format ("- `scene` (string): ...").
    """
    overrides = REVIEW_RESPONSE_STYLES.get(style, {})
    for field_name, guidance in overrides.items():
        pattern = rf"^- `{field_name}`(?: \(string\))?: .*$"
        prompt, count = re.subn(
            pattern,
            lambda _: f"- `{field_name}`: {guidance}",
            prompt,
            count=1,
            flags=re.M,
        )
        if count == 0:
            print(f"  Warning: no `{field_name}` guidance found in saved prompt")
    return prompt


def pretty_print_response(response: str) -> None:
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        print(response)
        return
    print(json.dumps(parsed, indent=2, ensure_ascii=False))


def followup_loop(client: Any, base_prompt: str, frames: list[bytes]) -> None:
    """Let the user ask the model follow-up questions about the same frames."""
    transcript = base_prompt
    print("\nAsk follow-up questions about this sequence (blank line to finish).")
    while True:
        try:
            question = input("follow-up> ").strip()
        except EOFError:
            return
        if not question:
            return

        prompt = (
            f"{transcript}\n\n---\n"
            "Answer the follow-up question below about the same sequence of "
            "frames. Respond in plain text, not JSON.\n"
            f"Question: {question}"
        )
        start = time.monotonic()
        answer = client._send(prompt, frames)
        elapsed = time.monotonic() - start
        if answer is None:
            print("No response from provider (see logs above).")
            continue
        print(f"\n{answer}\n({elapsed:.1f}s)")
        transcript = f"{prompt}\n\nYour answer:\n{answer}"


def run_example(settings: TesterSettings) -> None:
    examples = list_examples()
    if not examples:
        print(
            f"No examples found. Copy debug output folders from "
            f"clips/genai-requests/ into {EXAMPLES_DIR}/"
        )
        return

    index = select_option(
        "Select an example (arrow keys, Enter to launch):",
        [e.name for e in examples],
    )
    if index is None:
        return
    example = examples[index]

    styles = ["default"] + list(REVIEW_RESPONSE_STYLES)
    style_index = select_option("Select a response style:", styles)
    if style_index is None:
        return
    style = styles[style_index]

    prompt_file = example / "prompt.txt"
    if not prompt_file.is_file():
        print(f"{example.name} has no prompt.txt, cannot run")
        return
    prompt = apply_style(prompt_file.read_text(encoding="utf-8"), style)

    frames = load_frames(example)
    if not frames:
        print(f"{example.name} contains no frame images, cannot run")
        return

    client = build_client(settings)
    if client is None:
        return

    # Keep the other_concerns field in the schema only when the saved prompt
    # asked for it; the schema builder only checks truthiness of the list.
    concerns = ["_"] if "other_concerns" in prompt else []
    response_format = build_review_description_response_format(concerns)

    print(
        f"\nSending {len(frames)} frames to {settings.provider} "
        f"(model={settings.model or '(none)'}, style={style})..."
    )
    start = time.monotonic()
    response = client._send(prompt, frames, response_format)
    elapsed = time.monotonic() - start

    if response is None:
        print("No response from provider (see logs above).")
        return

    print(f"\nResponse ({elapsed:.1f}s):\n")
    pretty_print_response(response)
    followup_loop(client, f"{prompt}\n\nYour analysis:\n{response}", frames)


def main() -> None:
    os.chdir(REPO_ROOT)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    settings = TesterSettings.load()

    print("Frigate GenAI review prompt tester")
    while True:
        choice = select_option(
            f"Menu (settings: {settings.describe()}):",
            ["Run a review example", "Edit provider settings", "Quit"],
        )
        if choice == 0:
            if not settings.provider:
                print("Configure provider settings first.")
                edit_settings(settings)
                if not settings.provider:
                    continue
            run_example(settings)
        elif choice == 1:
            edit_settings(settings)
        else:
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
