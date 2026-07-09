import os
import sys
import time
import unicodedata

try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

if sys.platform == "win32":
    import msvcrt


def get_terminal_width(default=80):
    """获取当前控制台列宽；失败时回退 default。"""
    try:
        return max(1, os.get_terminal_size().columns)
    except OSError:
        return default


def terminal_rule(char="─"):
    """与当前控制台等宽的分隔线（每次调用实时取宽度）。"""
    # 留 1 列余量，避免写满最后一列时终端自动折行导致多出空行
    return char * max(1, get_terminal_width() - 1)


def char_display_width(ch: str) -> int:
    if not ch:
        return 0
    if ch == "\t":
        return 4
    ea = unicodedata.east_asian_width(ch)
    return 2 if ea in ("W", "F") else 1


def display_width(s: str) -> int:
    return sum(char_display_width(ch) for ch in s)


def strip_markdown_bold(text):
    """去掉文本中所有 Markdown 粗体标记 **（完整文本一次性处理）。"""
    if not text:
        return text
    if not isinstance(text, str):
        text = _content_to_text(text)
    return text.replace("**", "")


def _usable_width(default=80):
    """
    可用于绘制一行的显示列数。
    比真实列宽少 1，防止写满最后一列时终端自动换行，
    导致「逻辑 1 行 = 视觉 2 行」，重绘时擦不干净、线越叠越多。
    """
    return max(1, get_terminal_width(default) - 1)


def print_user_block(content, *, leading_newline=False):
    """
    用与终端等宽的上下两条线包住用户消息（历史回放等只读展示）。
    宽度在打印当下按终端尺寸计算。
    """
    width = _usable_width()
    rule = "─" * width
    if leading_newline:
        print()
    print(rule)
    text = strip_markdown_bold(content) if content else ""
    body = f"You: {text}"
    for line in _wrap_by_display_width(body, width):
        print(line)
    print(rule)


def _truncate_to_width(text: str, width: int) -> str:
    if width < 1:
        width = 1
    out = []
    w = 0
    for ch in text:
        cw = char_display_width(ch)
        if w + cw > width:
            break
        out.append(ch)
        w += cw
    return "".join(out)


def _wrap_paragraph(paragraph: str, width: int) -> list:
    """将不含 \\n 的一段按显示宽度折行。"""
    if width < 1:
        width = 1
    if not paragraph:
        return [""]
    lines = []
    current = []
    current_w = 0
    for ch in paragraph:
        cw = char_display_width(ch)
        if cw > width:
            if current:
                lines.append("".join(current))
                current = []
                current_w = 0
            lines.append(ch)
            continue
        if current_w + cw > width and current:
            lines.append("".join(current))
            current = [ch]
            current_w = cw
        else:
            current.append(ch)
            current_w += cw
    lines.append("".join(current))
    return lines if lines else [""]


def _wrap_by_display_width(text: str, width: int) -> list:
    """按显示宽度折行；硬换行 \\n 先分段，保证每行 display_width <= width。"""
    if width < 1:
        width = 1
    lines = []
    # split 保留空段，使连续换行变成空行
    parts = text.split("\n")
    for part in parts:
        lines.extend(_wrap_paragraph(part, width))
    return lines if lines else [""]


def _visual_rows_of_line(line: str, term_width: int) -> int:
    """一行文本在终端宽度 term_width 下会占几行（缩放 reflow 用）。"""
    if term_width < 1:
        term_width = 1
    dw = display_width(line)
    if dw <= 0:
        return 1
    return (dw + term_width - 1) // term_width


def _visual_height(lines: list, term_width: int) -> int:
    return sum(_visual_rows_of_line(line, term_width) for line in lines)


def _index_to_row_col(text: str, char_index: int, width: int):
    """
    将正文中的字符下标映射到折行后的 (row, display_col)。
    支持硬换行 \\n。display_col 为 0-based 显示列。
    """
    if width < 1:
        width = 1
    row = 0
    col = 0
    i = 0
    n = min(char_index, len(text))
    while i < n:
        ch = text[i]
        if ch == "\n":
            row += 1
            col = 0
            i += 1
            continue
        cw = char_display_width(ch)
        if col + cw > width and col > 0:
            row += 1
            col = 0
        col += cw
        i += 1
    if col >= width:
        row += 1
        col = 0
    return row, col


def _shift_pressed() -> bool:
    """检测 Shift 是否按下（用于区分 Enter / Shift+Enter）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        # VK_SHIFT=0x10；高位表示当前按下
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
    except Exception:
        return False


def _move_buffer_vertically(buffer: list, cur: int, direction: int) -> int:
    """
    在硬换行构成的逻辑行之间上下移动光标。
    direction: -1 上行，+1 下行。尽量保持列位置。
    """
    if not buffer or direction == 0:
        return cur
    # 各逻辑行 [start, end) 不含行尾 \\n
    starts = [0]
    for i, ch in enumerate(buffer):
        if ch == "\n":
            starts.append(i + 1)
    line_idx = 0
    for i, st in enumerate(starts):
        if st <= cur:
            line_idx = i
    col = cur - starts[line_idx]
    new_idx = line_idx + direction
    if new_idx < 0 or new_idx >= len(starts):
        return cur
    new_start = starts[new_idx]
    if new_idx + 1 < len(starts):
        new_end = starts[new_idx + 1] - 1  # 指向 \\n
    else:
        new_end = len(buffer)
    return min(new_start + col, new_end)


def read_framed_input(prompt="You: ", initial="", *, leading_newline=True):
    """
    Claude Code 风格框线输入：
      ────────────────────────  ← 一开始就画上，宽度随终端实时变化
      You: 在这里输入|
      ────────────────────────

    Enter 提交；Shift+Enter 换行。
    Windows 下用按键循环实现实时重绘；其它平台退化为先画框再 input。
    返回用户输入字符串（不含首尾 strip，由调用方决定）。
    """
    if sys.platform != "win32":
        return _read_framed_input_fallback(prompt, initial, leading_newline=leading_newline)
    return _read_framed_input_win(prompt, initial, leading_newline=leading_newline)


def _read_framed_input_fallback(prompt, initial, *, leading_newline):
    if leading_newline:
        print()
    width = _usable_width()
    print("─" * width)
    try:
        if initial:
            typed = input(f"{prompt}{initial}")
            text = typed if typed else initial
        else:
            text = input(prompt)
    except EOFError:
        print("─" * _usable_width())
        raise
    print("─" * _usable_width())
    return text


def _read_framed_input_win(prompt, initial, *, leading_newline):
    buffer = list(initial or "")
    cur = len(buffer)  # 光标：字符下标 0..len(buffer)
    # 上一帧的逻辑行（每行保证不触发终端自动折行）
    prev_lines = []
    # 上一帧光标所在逻辑行（0=顶线）；None=尚未绘制
    cursor_frame_row = None
    last_term_width = get_terminal_width()

    if leading_newline:
        sys.stdout.write("\n")
        sys.stdout.flush()

    def body_text():
        return prompt + "".join(buffer)

    def build_lines(usable):
        rule = "─" * usable
        content_lines = _wrap_by_display_width(body_text(), usable)
        return [rule, *content_lines, rule]

    def emit_row(text, usable, *, last=False):
        """写一行并清掉行尾残留；非末行再换行。保证不因写满列宽多出空行。"""
        fitted = _truncate_to_width(text, usable)
        sys.stdout.write("\r\033[2K")
        sys.stdout.write(fitted)
        if not last:
            sys.stdout.write("\n")

    def wipe_old_frame(term_width):
        """
        移到旧帧顶部，并清除从该处到屏幕底部的一切。
        缩放后终端会 reflow：上移量必须按「旧逻辑行在新宽度下的可视行数」算，
        否则旧分割线擦不掉，每次重绘再叠一层。
        """
        if not prev_lines:
            return

        # 假定编辑时光标在 cursor 逻辑行 reflow 后的最后一节
        if cursor_frame_row is not None and 0 <= cursor_frame_row < len(prev_lines):
            up = _visual_height(prev_lines[:cursor_frame_row], term_width)
            up += max(0, _visual_rows_of_line(prev_lines[cursor_frame_row], term_width) - 1)
        else:
            # 假定在底线行末
            up = max(0, _visual_height(prev_lines, term_width) - 1)

        if up > 0:
            sys.stdout.write(f"\033[{up}A")
        # 清掉本行及下方全部残留（含缩放堆出来的旧线）
        sys.stdout.write("\r\033[2K\033[J")

    def draw(*, editing=True):
        nonlocal prev_lines, cursor_frame_row, last_term_width

        term_width = get_terminal_width()
        usable = max(1, term_width - 1)
        lines = build_lines(usable)
        height = len(lines)

        if prev_lines:
            wipe_old_frame(term_width)

        for i, line in enumerate(lines):
            emit_row(line, usable, last=(i == height - 1))

        prev_lines = list(lines)
        last_term_width = term_width

        if not editing:
            sys.stdout.write("\n")
            sys.stdout.flush()
            prev_lines = []
            cursor_frame_row = None
            return

        # 光标放到内容区（逻辑行 1..height-2）
        body = body_text()
        char_index = len(prompt) + cur
        row_in_content, col = _index_to_row_col(body, char_index, usable)
        target_row = 1 + row_in_content
        target_row = max(1, min(target_row, height - 2))

        # 当前在底线（height-1）
        delta = (height - 1) - target_row
        if delta > 0:
            sys.stdout.write(f"\033[{delta}A")
        elif delta < 0:
            sys.stdout.write(f"\033[{-delta}B")
        sys.stdout.write(f"\r\033[{col + 1}G")
        sys.stdout.flush()
        cursor_frame_row = target_row

    draw(editing=True)

    while True:
        # 空闲轮询终端宽度；变化时整框擦除再画，避免堆线
        if not msvcrt.kbhit():
            tw = get_terminal_width()
            if tw != last_term_width:
                # 等尺寸稍稳再画，减少最大化动画中途连刷
                time.sleep(0.05)
                if get_terminal_width() == tw:
                    draw(editing=True)
            else:
                time.sleep(0.03)
            continue

        ch = msvcrt.getwch()

        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            if code == "K":  # Left
                if cur > 0:
                    cur -= 1
            elif code == "M":  # Right
                if cur < len(buffer):
                    cur += 1
            elif code == "H":  # Up — 按硬换行在行间移动
                cur = _move_buffer_vertically(buffer, cur, -1)
            elif code == "P":  # Down
                cur = _move_buffer_vertically(buffer, cur, 1)
            elif code == "G":  # Home — 移到当前逻辑行首
                line_start = cur
                while line_start > 0 and buffer[line_start - 1] != "\n":
                    line_start -= 1
                cur = line_start
            elif code == "O":  # End — 移到当前逻辑行尾（\\n 前）
                line_end = cur
                while line_end < len(buffer) and buffer[line_end] != "\n":
                    line_end += 1
                cur = line_end
            elif code == "S":  # Delete
                if cur < len(buffer):
                    buffer.pop(cur)
            draw(editing=True)
            continue

        if ch in ("\r", "\n"):
            # Shift+Enter：插入换行；普通 Enter：提交
            if _shift_pressed():
                buffer.insert(cur, "\n")
                cur += 1
                draw(editing=True)
                continue
            draw(editing=False)
            return "".join(buffer)

        if ch == "\x03":
            draw(editing=False)
            raise KeyboardInterrupt

        if ch == "\x08":  # Backspace
            if cur > 0:
                buffer.pop(cur - 1)
                cur -= 1
            draw(editing=True)
            continue

        if ch == "\x1b":  # Esc 清空
            buffer.clear()
            cur = 0
            draw(editing=True)
            continue

        # 可打印字符（含中文）；\\n 只通过 Shift+Enter 插入
        if ch >= " " or ord(ch) > 127:
            buffer.insert(cur, ch)
            cur += 1
            draw(editing=True)


def _content_to_text(content):
    """将 langchain chunk/message content 规范为 str。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" or "text" in block:
                    parts.append(block.get("text") or "")
            else:
                text = getattr(block, "text", None)
                if text:
                    parts.append(text)
        return "".join(parts)
    return str(content)


class StreamingBoldStripper:
    """
    流式去除 ** 标记。

    只在 chunk 末尾残留单个 * 时暂存，等待下一块判断是否构成 **；
    绝不会把完整的 ** 拆成两个字面量 * 输出（旧实现的 bug）。
    """

    def __init__(self):
        self._hold_star = False

    def feed(self, content) -> str:
        text = _content_to_text(content)
        if self._hold_star:
            text = "*" + text
            self._hold_star = False
        if not text:
            return ""

        out = []
        i = 0
        n = len(text)
        while i < n:
            if text[i] == "*" and i + 1 < n and text[i + 1] == "*":
                i += 2
            elif text[i] == "*" and i + 1 == n:
                # 末尾单个 *：可能是跨 chunk 的 ** 前半，先挂起
                self._hold_star = True
                i += 1
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    def flush(self) -> str:
        """流结束时输出未能配对的字面量 *。"""
        if self._hold_star:
            self._hold_star = False
            return "*"
        return ""
