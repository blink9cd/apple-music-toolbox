# html_page.py

The frame of a self-contained HTML report page, shared by every tool that writes one: the
style, the escaped cells, the tables, the summary, the sections and the document around
them. Each tool supplies only its own wording.

## Why it exists

Several tools write a read-only report as a single HTML file that a person opens in a
browser. The page around their findings is the same for all of them, so it lives here once:
the pages read alike, and a fix to the frame reaches every one of them. A tool's own page
module names its title, its header, its sections with their one-sentence notes, and its
read-only line; this library names no tool and no check.

The page is one HTML5 document with inline CSS and nothing else: no script, and nothing a
browser would fetch (no font, image or stylesheet), so it reads the same offline and from a
`file://` path. Colors are custom properties redefined for dark mode, and each table scrolls
sideways inside its own wrapper, so on a phone the page itself never does.

## The escape: `shown`, then `escaped`

Every value from outside the tool (a file or folder name, a tag, a reason quoted from a
child process) is text the tool did not write. `escaped(value)` turns it into page text in
two steps:

1. `shown` spells each C0 control, DEL and C1 control as a visible `\xNN` (lowercase hex, a
   tab as `\x09`, never `\t`), and then each lone surrogate, an undecodable byte in a name,
   as its backslash escape. Every other character, accents, CJK and the direction marks
   included, comes back unchanged.
2. `html.escape` with `quote=True` escapes `<`, `>`, `&` and both quotes, so no name can
   become markup or leave an attribute.

`shown` is public because a tool's plain-text report needs the same escape for its own
lines: a linefeed in a folder name would split one row into two, an escape sequence would
drive the terminal, and a lone surrogate would make a strict UTF-8 stdout raise. One copy
serves both forms, so the text report and the page always show a name the same way.

It is deliberately narrower than `stdio_utf8.spell_unsafe`, which also spells the
direction marks and the line and paragraph separators. This escape keeps those characters
as they are, so a report built on one cannot switch to the other without changing its output.

## Usage

Importers put this folder on `sys.path`, the same way they reach any other shared library,
and call the functions:

```python
import html_page
from html_page import Cell

rows = [(Cell(html_page.escaped(name)), Cell(str(size), numeric=True))]
page = html_page.page(
    title="A report",
    header=["<p>What was read, and when.</p>"],
    main=[
        *html_page.summary_section([html_page.summary_row("Found", 1, "found")]),
        *html_page.section(
            "found", "Found", 1, "One sentence.", html_page.table(("Name", "Size"), rows)
        ),
    ],
    read_only="Nothing was changed.",
)
```

## Public surface

| Name | Meaning |
| --- | --- |
| `shown(text)` | *text* with each control character and lone surrogate as its escape. |
| `escaped(value)` | `str(value)` through `shown`, then HTML-escaped, quotes included. |
| `Cell` | One table cell: its markup, already escaped, and whether it holds a number (`numeric`, which keeps it on one line in tabular figures). |
| `Row` | A tuple of `Cell`. |
| `row_markup(row, css_class)` | One `<tr>`, with *css_class* on it when given. |
| `table(columns, rows, classes)` | A table in its scrolling wrapper; *classes* gives each row its class, in order. |
| `summary_row(heading, count, anchor)` | A summary row: the heading linked to *anchor* when given; a `None` count reads `not run`. |
| `summary_section(rows)` | The summary section: one row per check, with its count. |
| `section(anchor, heading, count, note, body)` | One section: its heading and count, its note, then *body*. |
| `page(...)` | The whole document, keyword-only: `title`, `header`, `main`, `read_only`, `footer`, `extra_css`. |
| `CSS` | The shared style; a tool adds its own rules after it through `extra_css`. |
| `NOT_RUN` | The summary's word for a check that did not run. |
| `ParsedPage(page)` | A strict parse of *page*: `ValueError` on an element closed out of order; `stack` (left open), `ids`, `links`, `sources` and `text`, in page order. |
| `page_problems(page)` | Each way *page* fails the check below, as a line of text; empty for a sound page. |
| `VOID_ELEMENTS` | The elements that take no end tag, so the parse never waits for one. |
| `FETCHING` | What would make a browser fetch or run something, as it would appear in a page. |

Every function returns markup lines (or the whole page) and does no I/O: writing the file,
atomically and outside any repository, is the calling tool's job.

## The check every page is held to

`page_problems` is what each tool's tests assert of a page it writes, so the parse and
the rules live here once rather than in each suite. A sound page has:

- every element closed, and in order (a misclosed one is reported as the parse's error);
- every `id` once;
- every link an anchor to an `id` on the page;
- no `src` attribute, and none of `FETCHING` anywhere in the page, case ignored.

A suite asserts the list is empty, so a failure names each problem, and reads the page's
text or ids from `ParsedPage` when it checks content. Both are pure and use only the
standard library's `html.parser`; nothing a page builder calls depends on them.

## Notes

- **Fixed tokens are interpolated unescaped.** An `anchor` or a `css_class` lands in an
  attribute as given, so a caller passes a fixed identifier, never data. Headings, notes,
  column names, the title and the footer lines are escaped here; a `Cell`'s markup is
  escaped by the caller, through `escaped`, because a cell may hold markup of its own (a
  link, a list).
- **Byte-for-byte stability is a contract.** Tools pin their whole page by length and
  digest, so any change to the markup or the style here is a change to every such page,
  and those pins must be re-derived on purpose.
- It imports only the standard library, and ships no `samples/`: it has no CLI, and each
  tool that writes a page ships the sample that shows one.

## Testing it

`test_html_page.py` beside this file pins each piece's markup, checks that a whole page
passes `page_problems`, and pins each problem the check names. Run it directly with Python.
