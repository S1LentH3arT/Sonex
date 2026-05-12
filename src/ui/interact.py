import asyncio
import io
import time
from functools import lru_cache
from pathlib import Path

import requests
from PIL import Image
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.widgets import Input, Static

from src.tools.registry import ToolRegistry
from src.agent.runner import SonexRunner
from src.ui.status import UiStatus

APP_VERSION = "1.0.0"
MODEL_NAME = "sonex-mixcloud"

SAMPLE_CHAT = [
    ("user", "想听一点适合深夜写代码的电子氛围。"),
    (
        "agent",
        "可以先从低鼓点和更长尾音的合成器开始。我先给你排一个轻一点的队列，后面再慢慢加厚。",
    ),
    ("tool", "queue updated with 6 tracks"),
    (
        "agent",
        "右侧已经放进播放列表了。你也可以继续说要偏 lofi、house、shoegaze，还是更冷一点的 ambient。",
    ),
]

PLAYLIST = [
    ("01", "Night Swim", "Yaeji", "3:42"),
    ("02", "Blue Hour Transit", "Kiasmos", "4:31"),
    ("03", "Glass Receiver", "Tourist", "3:58"),
    ("04", "Afterimage", "Tycho", "5:12"),
    ("05", "Soft Signal", "The Album Leaf", "4:08"),
    ("06", "Rain on Canal Street", "Emancipator", "4:46"),
]


ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
MASCOT_IMAGE_PATH = ASSETS_DIR / "Sonex_mascot.png"
MASCOT_PIXEL_PATH = ASSETS_DIR / "mascot_pixels.txt"


def _load_mascot_pixels_from_text(path: Path) -> list[list[str | None]]:
    palette = {
        ".": None,
        "A": "#4b5161",
        "F": "#9fd9ff",
        "E": "#f4f1f3",
    }
    rows = [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("Mascot pixel file is empty")

    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("Mascot pixel file must have fixed-width rows")

    return [[palette[cell] for cell in row] for row in rows]


@lru_cache(maxsize=1)
def _cached_mascot_pixels() -> list[list[str | None]]:
    if not MASCOT_PIXEL_PATH.exists():
        raise ValueError(f"Mascot pixel file not found: {MASCOT_PIXEL_PATH}")
    return _load_mascot_pixels_from_text(MASCOT_PIXEL_PATH)


def build_mascot_art() -> Text:
    """Render the mascot from the persisted pixel text asset."""
    transparent = "#2a0918"
    try:
        pixel_rows = _cached_mascot_pixels()
    except Exception:
        pixel_rows = [
            [None, None, "#4b5161", "#4b5161", "#4b5161", None, None, None],
            [None, "#4b5161", "#f4f1f3", "#f4f1f3", "#f4f1f3", "#4b5161", None, None],
            ["#4b5161", "#f4f1f3", "#4b5161", "#f4f1f3", "#4b5161", "#f4f1f3", "#4b5161", None],
            ["#4b5161", "#f4f1f3", "#f4f1f3", "#f4f1f3", "#f4f1f3", "#f4f1f3", "#4b5161", None],
            [None, "#4b5161", "#f4f1f3", "#f4f1f3", "#f4f1f3", "#4b5161", None, None],
            [None, None, "#4b5161", None, "#4b5161", None, None, None],
        ]

    art = Text()
    for y in range(0, len(pixel_rows), 2):
        upper = pixel_rows[y]
        lower = pixel_rows[y + 1] if y + 1 < len(pixel_rows) else [None] * len(upper)
        for x in range(len(upper)):
            upper_color = upper[x] or transparent
            lower_color = lower[x] or transparent
            art.append("▀", style=f"{upper_color} on {lower_color}")
        art.append("\n")
    return art


def build_cover_art(url: str, width: int = 36) -> Text:
    # 1) 下载图片
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")

    # 2) 计算目标尺寸
    # 半块字符：上下两行合成一行，所以需要 height = width * 2 * ratio
    # ratio 用 0.55 左右更自然
    ratio = 0.55
    target_w = width
    target_h = int(width * 2 * ratio)

    # 3) 高质量缩放
    img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    pixels = img.load()

    # 4) 用半块字符渲染
    text = Text()
    for y in range(0, target_h, 2):
        for x in range(target_w):
            upper = pixels[x, y]
            lower = pixels[x, y + 1] if y + 1 < target_h else upper
            text.append("▀", style=f"#{upper[0]:02x}{upper[1]:02x}{upper[2]:02x} on "
                                   f"#{lower[0]:02x}{lower[1]:02x}{lower[2]:02x}")
        text.append("\n")
    return text


def _format_duration(ms: int) -> str:
    total_seconds = max(0, ms // 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02}"


def _format_timer(secs: int) -> str:
    minutes = secs // 60
    seconds = secs % 60
    return f"{minutes:02d}m {seconds:02}s"

def _render_bar(progress: float, width: int = 18) -> str:
    clamped = max(0.0, min(1.0, progress))
    filled = int(width * clamped)
    return "━" * filled + "━" * (width - filled)


class ChatBubble(Static):
    def __init__(self, role: str, content: str):
        super().__init__(content)
        self.classes = f"chat-bubble {role}"


class SonexApp(App):
    CSS = """Screen { color: #f5e8ee; }

    #shell { layout: vertical; height: 100%; width: 100%; padding: 1 1 0 1; }

    #content { layout: horizontal; height: 1fr; width: 100%; border: solid #6f3c55; }

    #left-pane { width: 3fr; min-width: 48; border-right: solid #6f3c55; layout: vertical; }

    #right-pane { width: 4fr; min-width: 62; layout: vertical; }

    #brand-block { layout: horizontal; height: auto; padding: 0 1 0 1; border-bottom: solid #6f3c55; }

    #mascot { width: auto; height: auto; margin: 0 1 0 0; }

    #brand-meta { width: 1fr; height: auto; content-align: left top; padding: 1 0 1 1; }

    #chat-pane { height: 1fr; padding: 0 1 0 1; }

    #chat-scroll { height: 1fr; padding: 0 1 0 1; scrollbar-size: 1 1; }

    #input-wrap { height: auto; border-top: solid #6f3c55; padding: 1 1 1 1; }

    #chat-input { height: 3; border: none; color: #f5e8ee; padding: 0 1; }

    #chat-input:focus { border: tall #b97a93; }

    #queue-pane { height: 1fr; border-bottom: solid #563043; padding: 1 2; }

    #queue-list { height: 1fr; padding-top: 1; }

    #player-pane { height: auto; min-height: 20; padding: 1 2 2 2; }

    #player-grid { layout: horizontal; height: auto; margin-top: 1; }

    #cover-wrap { width: 36; min-width: 36; padding-right: 2; }

    #track-meta { width: 1fr; padding-top: 1; }

    .section-title { color: #f3b2c6; text-style: bold; margin-bottom: 1; }

    .muted { color: #bf98a7; }

    .chat-bubble { margin-bottom: 1; padding: 1 2; width: 100%; }

    .chat-bubble.user { border-left: tall #f3b2c6; color: #fff6f8; }

    .chat-bubble.agent { border-left: tall #8fd3ff; color: #f6e9ee; }

    .chat-bubble.tool { border-left: tall #7f5d6b; color: #bf98a7; }

    .queue-row { height: auto; padding: 0 0 1 0; }

    #footer-bar { height: 1; color: #bf98a7; padding: 0 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._confirm_index = None
        self._confirm_future = None
        self.runner = SonexRunner(ui=self, tools=ToolRegistry())

        self._player_state = {
            "name": "-",
            "artist": "-",
            "album": "-",
            "duration_ms": 0,
        }
        self._start_ts = None
        self._progress_timer = None

        self._llm_start_ts = None
        self._llm_timer = None

    async def append_user_message(self, text: str) -> None:
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        await chat_scroll.mount(ChatBubble("user", text))
        chat_scroll.scroll_end(animate=False)

    async def append_agent_message(self, text: str) -> None:
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        await chat_scroll.mount(ChatBubble("agent", text))
        chat_scroll.scroll_end(animate=False)

    async def append_tool_message(self, text: str) -> None:
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        await chat_scroll.mount(ChatBubble("tool", text))
        chat_scroll.scroll_end(animate=False)
        
    async def ask_confirm(self, attached: dict) -> bool:
        self.stop_llm_timer()
        
        overlay = self.query_one("#confirm-card", VerticalScroll)
        overlay.add_class("-visible")
        self.set_input_enabled(False)
        
        text = self.query_one("#confirm-text", Static)
        tool = attached.get("tool_name")
        args = attached.get("tool_args")
        text.update(f"Sonex wanna run [b #f3b2c6]{tool}[/b #f3b2c6]-->([#bf98a7]{args}[/#bf98a7])."
                    f" Do you Confirm?")
        _confirm_future = asyncio.get_running_loop().create_future()
        result = await _confirm_future
        
        overlay.remove_class("-visible")
        
        self.set_input_enabled(True)
        self.start_llm_timer()
        return result
    
    def set_status(self, status: UiStatus) -> None:
        status_bar = self.query_one("#status-bar", Static)
        elapsed_text = _format_timer(self._llm_elapsed)
        status_bar.update(
            f"[#bf98a7]{status.message}[/#bf98a7]  [#7f5d6b]•[/#7f5d6b]  "
            f"[#d8bcc7]{elapsed_text}[/#d8bcc7]  [#7f5d6b]•[/#7f5d6b]"
            f"[#d8bcc7]{self.runner.usage_tracker} tokens[/#d8bcc7]"
        )

    def on_key(self, event: Key) -> None:
        if not (self._confirm_future and not self._confirm_future.done()):
            return
        if event.key == "up":
            self._confirm_index = max(0, self._confirm_index - 1)
            self._update_confirm_view()
            event.stop()
        elif event.key == "down":
            self._confirm_index = min(1, self._confirm_index + 1)
            self._update_confirm_view()
            event.stop()
        elif event.key == "enter":
            self._confirm_future.set_result(self._confirm_index == 0)
            event.stop()
        elif event.key == "escape":
            self._confirm_future.set_result(False)
            event.stop()

    def start_llm_timer(self) -> None:
        self._llm_start_ts = time.monotonic()
        if self._llm_timer is None:
            self._llm_timer = self.set_interval(1.0, self._tick_llm_timer)

    def stop_llm_timer(self) -> None:
        if self._llm_timer:
            self._llm_timer.pause()
        self._llm_start_ts = None

    def _tick_llm_timer(self) -> None:
        if self._llm_start_ts is None:
            return
        elasped = int(time.monotonic() - self._llm_start_ts)
        self._llm_elapsed = elasped

    def set_input_enabled(self, enabled: bool) -> None:
        input_box = self.query_one("#chat-input", Input)
        input_box.disabled = not enabled
        if enabled:
            input_box.focus()

    def render_cover_art(self, url: str = None) -> None:
        cover = build_cover_art(url, width=32)
        cover_widget = self.query_one("#cover-wrap", Static)
        cover_widget.update(cover)

    def _render_progress(self, elapsed_ms: int) -> str:
        duration_ms = max(1, self._player_state.get("duration_ms", 0))
        progress = min(1.0, elapsed_ms / duration_ms)
        bar = _render_bar(progress, width=18)
        left = _format_duration(elapsed_ms)
        right = _format_duration(duration_ms)
        return f"[#bf98a7]{left}[/#bf98a7]  [#7f5d6b]{bar}[/#7f5d6b]  [#bf98a7]{right}[/#bf98a7]"

    def _render_confirm_choices(self) -> str:
        choices = ["Yes", "No"]
        lines = []
        for i, label in enumerate(choices):
            prefix = ">" if i == self._confirm_index else " "
            style = "[b #f3b2c6]" if i == self._confirm_index else "[#bf98a7]"
            lines.append(f"{prefix} {style}{label}[/{style.strip('[')}]")
        return "\n".join(lines)

    def update_player(self, state: dict) -> None:
        self._player_state.update(state)

        info = self.query_one("#track-info", Static)
        info.update(
            f"[b #fff4f6]{state["name"]}[/b #fff4f6]\n"
            f"[#bf98a7]{state["artist"]}[/#bf98a7]\n"
            f"[#bf98a7]{state["album"]}[/#bf98a7]\n\n"
        )

    def _tick_progress(self) -> None:
        if self._start_ts is None:
            return
        elapsed_ms = int((time.monotonic() - self._start_ts) * 1000)
        duration_ms = self._player_state.get("duration_ms", 0)
        if duration_ms and elapsed_ms >= duration_ms:
            elapsed_ms = duration_ms
            if self._progress_timer:
                self._progress_timer.pause()

        progress = self.query_one("#track-progress", Static)
        progress.update(self._render_progress(elapsed_ms))

    def _update_confirm_view(self) -> None:
        confirm_choices = self.query_one("#confirm-choices", Static)
        confirm_choices.update(self._render_confirm_choices())

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            with Horizontal(id="content"):
                with Vertical(id="left-pane"):
                    with Container(id="brand-block"):
                        yield Static(self._mascot_renderable(), id="mascot")
                        yield Static(self._brand_text(), id="brand-meta")
                    with Container(id="chat-pane"):
                        yield Static("Conversation", classes="section-title")
                        with VerticalScroll(id="chat-scroll"):
                            for role, content in SAMPLE_CHAT:
                                yield ChatBubble(role, content)
                    yield Static("Snoozing...", id="status-bar")
                    with Container(id="input-wrap"):
                        yield Input(
                            placeholder="Say something to awake Sonex.",
                            id="chat-input",
                        )
                    with Container(id="confirm-card"):
                        yield Static("", id="confirm-text")
                        yield Static("", id="confirm-choices")

                with Vertical(id="right-pane"):
                    with Container(id="queue-pane"):
                        yield Static("Queue / Playlist", classes="section-title")
                        yield Static(self._queue_text(), id="queue-list")
                    with Container(id="player-pane"):
                        yield Static("Now Playing", classes="section-title")
                        with Horizontal(id="player-grid"):
                            yield Static("", id="cover-wrap")
                            with Container(id="track-meta"):
                                yield Static("", id="track-info")
                                yield Static("", id="track-progress")

    def _mascot_renderable(self) -> Text:
        return build_mascot_art()

    def _brand_text(self) -> str:
        return (
            f"[b #fff4f6]Sonex CLI[/b #fff4f6] [#bf98a7]v{APP_VERSION}[/#bf98a7]\n"
            f"[#d8bcc7]{MODEL_NAME}[/#d8bcc7] [#9d7787]•[/#9d7787] [#d8bcc7]playlist shell[/#d8bcc7]\n"
            "[#bf98a7]~/dev/sonex[/#bf98a7]\n"
            "[#9d7787]\n\nTips: Try mood, artist, or playlist keywords to steer the queue.[/#9d7787]"
        )

    def _queue_text(self) -> str:
        lines = []
        for index, title, artist, duration in PLAYLIST:
            marker = "[#f3b2c6]>>[/#f3b2c6]" if index == "01" else "[#7f5d6b]..[/#7f5d6b]"
            lines.append(
                f"{marker} [#bf98a7]{index}[/#bf98a7]  [#fff4f6]{title}[/#fff4f6]\n"
                f"    [#bf98a7]{artist}[/#bf98a7] [#7f5d6b]•[/#7f5d6b] [#bf98a7]{duration}[/#bf98a7]\n"
            )
        return "\n".join(lines)

    async def on_mount(self) -> None:
        input_box = self.query_one("#chat-input", Input)
        input_box.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        event.input.value = ""
        await self.runner.handle_user_input(text)
        event.input.focus()


if __name__ == "__main__":
    SonexApp().run()
