import re


def strip_markdown_bold(text):
    """去掉 Markdown 粗体标记 **"""
    return re.sub(r'\*\*(.+?)\*\*', r'\1', text)
