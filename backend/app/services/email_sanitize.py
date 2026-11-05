"""Strip quoted reply history / signatures before safety scan and LLM."""

from __future__ import annotations

import re

# Gmail / Outlook / Apple Mail common quote markers
_QUOTE_START_RE = re.compile(
    r"(?:^|\n)"
    r"(?:"
    r"On .{0,200} wrote:\s*"
    r"|-{2,} ?Original Message ?-{2,}"
    r"|From:\s.+\nSent:\s"
    r"|_{5,}"
    r"|Begin forwarded message:"
    r")",
    re.IGNORECASE,
)

_SIGNATURE_RE = re.compile(
    r"(?:^|\n)-- \n.*\Z",
    re.DOTALL,
)


def strip_quoted_reply(body: str) -> str:
    """Remove quoted history and trailing signature so reminder text cannot re-trigger policy."""
    if not body:
        return ""
    m = _QUOTE_START_RE.search(body)
    if m:
        body = body[: m.start()]
    body = _SIGNATURE_RE.sub("", body)
    lines: list[str] = []
    for line in body.splitlines():
        if line.startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()
