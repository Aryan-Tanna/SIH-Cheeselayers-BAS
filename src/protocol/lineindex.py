"""Line-number lookups for validator error messages.

json.load() throws source position away, and this project's protocol
files are hand-authored, conventionally-formatted JSON (roughly one key
per line) rather than machine-generated. Rather than pull in a full
JSON-with-source-positions parser, this does a second, regex-based scan
of the raw text for the handful of key patterns the validator needs a
line number for. It is a heuristic, not a JSON AST: on adversarially
reformatted JSON (everything on one line, keys reordered oddly) it can
point at the wrong line. That trade-off is worth it for a validator
whose whole job is being loud at authors, not for parsing untrusted
input from strangers.
"""

from __future__ import annotations

import re


class LineIndex:
    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self._id_lines: dict[str, int] = {}
        for i, line in enumerate(self.lines, start=1):
            for m in re.finditer(r'"id"\s*:\s*"([^"]+)"', line):
                self._id_lines.setdefault(m.group(1), i)

    def line_for_id(self, id_value: str) -> int | None:
        return self._id_lines.get(id_value)

    def line_for_object_key(self, key_name: str, after_line: int = 0) -> int | None:
        """First line at/after `after_line` (1-indexed, 0 = start) that
        opens `"key_name": {`."""
        pattern = re.compile(rf'"{re.escape(key_name)}"\s*:\s*\{{')
        for i, line in enumerate(self.lines, start=1):
            if i < after_line:
                continue
            if pattern.search(line):
                return i
        return None

    def line_for_key_value(
        self, key_name: str, value: str | None = None, after_line: int = 0, before_line: int | None = None
    ) -> int | None:
        if value is not None:
            pattern = re.compile(rf'"{re.escape(key_name)}"\s*:\s*"{re.escape(value)}"')
        else:
            pattern = re.compile(rf'"{re.escape(key_name)}"\s*:')
        for i, line in enumerate(self.lines, start=1):
            if i < after_line:
                continue
            if before_line is not None and i > before_line:
                break
            if pattern.search(line):
                return i
        return None
