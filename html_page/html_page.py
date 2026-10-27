#!/usr/bin/env python3
r"""Lay out a self-contained HTML report page: the frame every tool's page shares. Pure.

Why this exists
---------------
Several tools write a read-only report as one HTML file a person opens in a browser. The
page around their findings is the same for all of them: the style (light and dark),
escaped cells, a table in its scrolling wrapper, the summary table, a section, and the
whole document. Kept here once, every tool's page reads alike, and a fix to the frame
reaches all of them.

It names no tool and no check: each tool's own page module supplies its title, header,
sections and read-only line. The page holds inline CSS and nothing else: no script, and
nothing a browser would fetch (no font, image or stylesheet), so it reads the same
offline.

Every value from outside goes through `escaped`: first `shown` (a control character as a
visible ``\xNN``, a lone surrogate as its ``\uXXXX``), then HTML escaping, quotes
included, so no name can become markup. `shown` is public because a tool's plain-text
report needs the same escape for its own lines.

`ParsedPage` and `page_problems` are the check every tool's tests hold a page to: a
strict parse, each element closed in order, each id once, each link an anchor on the
page, and nothing that would fetch or run. One copy serves every tool's suite.

Entry point assumptions
-----------------------
A library with no CLI and no I/O: importers put this folder on ``sys.path`` (see
``html_page.md``) and call its functions. It imports only the standard library.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from itertools import chain, repeat

#: The summary's word for a check that did not run.
NOT_RUN = "not run"

#: The page's whole shared style. Colors are custom properties, redefined for dark mode;
#: tables scroll sideways inside their own wrapper, so the page never does. A tool adds
#: rules of its own after these, through `page`'s ``extra_css``.
CSS = """\
:root {
  color-scheme: light dark;
  --bg: #fbfaf7;
  --fg: #1d1d1f;
  --muted: #5f5f66;
  --line: #e3e1dc;
  --head: #f1efe9;
  --accent: #a8401f;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17171a;
    --fg: #ececee;
    --muted: #a0a0a8;
    --line: #2c2c31;
    --head: #212126;
    --accent: #e2876b;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
}
header, main, footer { max-width: 1100px; margin: 0 auto; padding: 0 16px; }
header { padding-top: 24px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 32px 0 4px; }
.library, .note, footer { color: var(--muted); }
.library { overflow-wrap: anywhere; margin: 0; }
.tallies {
  list-style: none; margin: 8px 0 0; padding: 0;
  display: flex; flex-wrap: wrap; gap: 4px 16px;
}
.note { margin: 0 0 10px; }
.wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td {
  text-align: left; vertical-align: top; padding: 7px 10px;
  border-bottom: 1px solid var(--line);
}
th { background: var(--head); font-weight: 600; white-space: nowrap; }
tbody tr:last-child td { border-bottom: 0; }
td.num { white-space: nowrap; font-variant-numeric: tabular-nums; }
.count {
  display: inline-block; min-width: 2em; padding: 0 8px; border-radius: 10px;
  background: var(--head); color: var(--accent); text-align: center;
}
a { color: var(--accent); }
ol, ul.differs { margin: 0; padding-left: 18px; }
footer { padding-top: 24px; padding-bottom: 48px; font-size: 14px; }
"""


# --- Text from outside -------------------------------------------------------------

#: C0 controls, DEL and C1 controls, each shown as its ``\\xNN`` escape.
_CONTROLS = {code: f"\\x{code:02x}" for code in (*range(0x20), *range(0x7F, 0xA0))}


def shown(text: str) -> str:
    r"""*text* with each control character, and each lone surrogate, as an escape.

    A linefeed in a folder name would otherwise split one row into two, and an escape
    sequence would drive the terminal. A lone surrogate (an undecodable byte in a name
    given on the command line) would make the strict UTF-8 stdout raise.
    """
    return text.translate(_CONTROLS).encode("utf-8", "backslashreplace").decode("utf-8")


# --- Cells ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """One table cell: its markup, already escaped, and whether it holds a number."""

    markup: str
    numeric: bool = False


Row = tuple[Cell, ...]


def escaped(value: object) -> str:
    """*value* as page text: control characters shown, then every markup char escaped."""
    return html.escape(shown(str(value)), quote=True)


# --- Tables --------------------------------------------------------------------------


def row_markup(row: Row, css_class: str | None = None) -> str:
    """One table row, with *css_class* on it when given.

    *css_class* is interpolated unescaped, so the caller must pass a fixed identifier
    token, never data.
    """
    cells = (
        f'<td class="num">{c.markup}</td>' if c.numeric else f"<td>{c.markup}</td>"
        for c in row
    )
    opening = "<tr>" if css_class is None else f'<tr class="{css_class}">'
    return f"{opening}{''.join(cells)}</tr>"


def table(
    columns: Sequence[str],
    rows: Sequence[Row],
    classes: Sequence[str | None] = (),
) -> list[str]:
    """A table in its own scrolling wrapper.

    *classes* gives each row its class, in order; rows past its end take none.
    """
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    row_classes = chain(classes, repeat(None))
    return [
        '<div class="wrap"><table>',
        f"<thead><tr>{head}</tr></thead>",
        "<tbody>",
        *map(row_markup, rows, row_classes),
        "</tbody>",
        "</table></div>",
    ]


# --- The summary and the sections ----------------------------------------------------


def summary_row(heading: str, count: int | None, anchor: str | None) -> Row:
    """A summary row: *heading* linked to *anchor* when given; None counts as not run.

    *anchor* is interpolated unescaped, so the caller must pass a fixed identifier
    token, never data.
    """
    shown_heading = html.escape(heading)
    if count is None:
        return (Cell(shown_heading), Cell(NOT_RUN))
    if anchor is not None:
        shown_heading = f'<a href="#{anchor}">{shown_heading}</a>'
    return (Cell(shown_heading), Cell(str(count), numeric=True))


def summary_section(rows: Sequence[Row]) -> list[str]:
    """The summary section: one row per check, each with its count."""
    return [
        '<section id="summary">',
        "<h2>Summary</h2>",
        *table(("Check", "Found"), rows),
        "</section>",
    ]


def section(
    anchor: str, heading: str, count: int, note: str, body: Sequence[str]
) -> list[str]:
    """One section: its heading and count, its one-sentence note, then *body*.

    *anchor* is interpolated unescaped, so the caller must pass a fixed identifier
    token, never data.
    """
    return [
        f'<section id="{anchor}">',
        f'<h2>{html.escape(heading)} <span class="count">{count}</span></h2>',
        f'<p class="note">{html.escape(note, quote=False)}</p>',
        *body,
        "</section>",
    ]


# --- The page ------------------------------------------------------------------------


def page(
    *,
    title: str,
    header: Sequence[str],
    main: Sequence[str],
    read_only: str,
    footer: Sequence[str] = (),
    extra_css: str = "",
) -> str:
    """The whole document.

    *title* heads the page and names it; *header* follows the title inside the page
    header, *main* is the summary and the sections, and the footer holds *read_only*,
    then each line of *footer*, each a paragraph of plain text. *extra_css* is the
    tool's own rules, after the shared ones.
    """
    shown_title = html.escape(title)
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{shown_title}</title>",
        f"<style>\n{CSS}{extra_css}</style>",
        "</head>",
        "<body>",
        "<header>",
        f"<h1>{shown_title}</h1>",
        *header,
        "</header>",
        "<main>",
        *main,
        "</main>",
        "<footer>",
        *(f"<p>{html.escape(line, quote=False)}</p>" for line in (read_only, *footer)),
        "</footer>",
        "</body>",
        "</html>",
    ]
    return "".join(f"{line}\n" for line in lines)


# --- The check -----------------------------------------------------------------------

#: The elements that take no end tag, so the parse never waits for one.
VOID_ELEMENTS = frozenset({"meta", "br", "hr", "img", "link", "input", "wbr"})
#: What would make a browser fetch or run something, as it would appear in a page,
#: matched against the page lowercased.
FETCHING = ("<script", "http", "//", "url(", "@import", "<link", " src=")


class ParsedPage(HTMLParser):
    """A page parsed whole, raising ValueError on an element closed out of order.

    ``stack`` is what stays open at the end; ``ids``, ``links`` (each ``href``),
    ``sources`` (each ``src``) and ``text`` are recorded in page order.
    """

    def __init__(self, page: str) -> None:
        """Parse *page* whole."""
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.ids: list[str] = []
        self.links: list[str] = []
        self.sources: list[str] = []
        self.text: list[str] = []
        self.feed(page)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open *tag* unless it is void; record its id, link and source."""
        named = dict(attrs)
        for key, into in (
            ("id", self.ids),
            ("href", self.links),
            ("src", self.sources),
        ):
            if named.get(key) is not None:
                into.append(str(named[key]))
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        """Close *tag*, which must be the innermost open element."""
        if not self.stack or self.stack[-1] != tag:
            raise ValueError(f"</{tag}> closes {self.stack[-1:]}")
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        """Keep the text."""
        self.text.append(data)


def page_problems(page: str) -> list[str]:
    """Each way *page* fails the check, in a fixed order; empty for a sound page."""
    try:
        parsed = ParsedPage(page)
    except ValueError as error:
        return [str(error)]
    found = [f"left open: {parsed.stack}"] if parsed.stack else []
    seen: set[str] = set()
    for anchor in parsed.ids:
        if anchor in seen:
            found.append(f"id repeated: {anchor}")
        seen.add(anchor)
    on_page = {f"#{anchor}" for anchor in seen}
    found.extend(
        f"link not on the page: {link}" for link in parsed.links if link not in on_page
    )
    found.extend(f"source: {source}" for source in parsed.sources)
    lowered = page.lower()
    found.extend(
        f"fetches or runs: {marker}" for marker in FETCHING if marker in lowered
    )
    return found
