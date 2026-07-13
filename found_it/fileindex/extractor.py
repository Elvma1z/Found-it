from pathlib import Path
from typing import Optional

from found_it.fileindex.indexer import FileEntry


def extract_text_preview(file_path: str, max_chars: int = 500) -> str:
    try:
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext == ".pdf":
            return _extract_pdf(path, max_chars)
        elif ext in {".json", ".yaml", ".yml", ".toml", ".xml", ".csv"}:
            return _read_text_file(path, max_chars)
        elif ext in {".txt", ".md", ".rst", ".log"}:
            return _read_text_file(path, max_chars)
        elif ext in {".html", ".htm"}:
            return _extract_html(path, max_chars)
        else:
            return _read_text_file(path, max_chars)
    except Exception:
        return ""


def _read_text_file(path: Path, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:max_chars]
    except Exception:
        return ""


def _extract_pdf(path: Path, max_chars: int) -> str:
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:5]:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
                if len(text) >= max_chars:
                    break
        return text[:max_chars]
    except ImportError:
        return "[PDF - install pdfplumber to extract text]"
    except Exception:
        return ""


def _extract_html(path: Path, max_chars: int) -> str:
    try:
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
                self._skip = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in ("script", "style"):
                    self._skip = False

            def handle_data(self, data):
                if not self._skip:
                    self.text.append(data.strip())

        extractor = TextExtractor()
        html = path.read_text(encoding="utf-8", errors="replace")
        extractor.feed(html)
        return " ".join(extractor.text)[:max_chars]
    except Exception:
        return ""


def get_file_description(entry: FileEntry) -> str:
    parts = [entry.name]

    if entry.is_image:
        parts.append("image file")
    elif entry.is_code:
        parts.append(f"code file ({entry.extension})")
    elif entry.is_text:
        parts.append(f"text file ({entry.extension})")

    size_kb = entry.size_bytes / 1024
    if size_kb > 1024:
        parts.append(f"{size_kb / 1024:.1f} MB")
    else:
        parts.append(f"{size_kb:.0f} KB")

    parent = str(Path(entry.path).parent.name)
    parts.append(f"in {parent}")

    return " ".join(parts)
