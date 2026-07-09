import sys

try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False


def strip_markdown_bold(text):
    """去掉文本中所有 Markdown 粗体标记 **（完整文本一次性处理）。"""
    if not text:
        return text
    if not isinstance(text, str):
        text = _content_to_text(text)
    return text.replace("**", "")


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
