import re
import sys

try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False


def strip_markdown_bold(text):
    """去掉 Markdown 粗体标记 **"""
    return re.sub(r'\*\*(.+?)\*\*', r'\1', text)