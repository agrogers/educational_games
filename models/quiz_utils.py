"""
Shared constants, regex patterns, and helper functions used by quiz models.
"""
import re
import unicodedata

# Extensible patterns for question and answer line detection.
# Add new compiled regexes to support additional quiz text formats.
_QUESTION_PATTERNS = [
    # "1. What is..." or "1) What is..."
    re.compile(r'^(\d+)[\.)\:]\s+(?P<text>.+)$'),
    # "Question 1: What is..." or "Question 1. What is..."
    re.compile(r'^Question\s+\d+[:\.\)]\s*(?P<text>.+)$', re.IGNORECASE),
]

_ANSWER_PATTERNS = [
    # "A) text", "A. text", "A: text"
    re.compile(r'^(?P<letter>[A-Za-z])[\)\.:]\s+(?P<text>.+)$'),
]

# Prefixes to strip from parsed text.
_QUESTION_PREFIX_RE = re.compile(
    r'^(?:Question\s+\d+[:\.\)]\s*|\d+[:\.\)]\s+)', re.IGNORECASE
)
_ANSWER_PREFIX_RE = re.compile(
    r'^[A-Za-z][\)\.:]\s+'
)

# Plain Markdown detection patterns (used in _extract_lines_from_html).
# _MD_BOLD_ITALIC_RE: ***text*** — whole-line bold+italic wrap
# _MD_ITALIC_RE:      *text*    — whole-line italic wrap (empty *  * is rejected)
_MD_BOLD_ITALIC_RE = re.compile(r'^\*{3}(.+)\*{3}\s*$')
_MD_ITALIC_RE = re.compile(r'^\*([^*]+)\*\s*$')


def _normalize_text(text):
    """
    Normalise Unicode characters that are common in text copied from AI tools
    (ChatGPT, NotebookLM, etc.) or word-processors.

    Converts: smart quotes, non-breaking spaces, soft hyphens, zero-width chars,
    en/em dashes, Unicode ellipsis, and leading bullet points.
    """
    text = unicodedata.normalize('NFC', text)
    # Smart / curly quotes → straight quotes
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    # Non-breaking and other special spaces → regular space
    text = re.sub(r'[\u00a0\u202f\u2007\u2009\u3000]', ' ', text)
    # Soft hyphen (invisible, causes regex matching issues)
    text = text.replace('\u00ad', '')
    # Zero-width characters
    text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
    # En dash / em dash / horizontal bar → hyphen
    text = re.sub(r'[\u2013\u2014\u2015]', '-', text)
    # Unicode ellipsis → three dots
    text = text.replace('\u2026', '...')
    # Leading bullet points (common in ChatGPT / NotebookLM lists)
    text = re.sub(r'^[\u2022\u2023\u25e6\u2043\u2219\u00b7]\s*', '', text.strip())
    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()
