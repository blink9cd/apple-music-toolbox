# library_audit.py

Find where a library folder's audio files and Music.app disagree: a file Music.app has no
track for, a track whose file is gone, an album with holes in its track numbers, an album
split in two by a difference in how its files spell it, an album whose files and tracks
differ in count; and the causes of a track that will not sync to an iPhone that this Mac
can see: an iCloud placeholder, a file it cannot read, Music.app's size out of step with
the file's, an unchecked track, and, under `--decode`, a file that does not decode.
**Read-only**: it never writes to Music.app, never adds a track, and never changes a file.
macOS only.

## Why it exists

A refresh of a run's changed tracks once found one file Music.app held no track for. Its
album folder held only the album's first and last tracks and two cover images, and nothing
else: a partial import or a half-finished copy. Nothing reported it until a tool happened to
name that file. This tool looks for that class of mistake across the whole library at once,
between the files and Music.app, and lists what it finds for a person to act on.

It adds nothing to Music.app by design. A file Music.app lacks may be exactly the half-copied
album above, and importing it automatically would turn a visible mistake into a broken album
in the library. `tag_refresh --missing-list` is the matching choice there: it lists such
files instead of adding them.

## Prerequisites

- **macOS**, where Music.app and `osascript` exist. Anywhere else a run exits `2` with one
  line before it reads anything.
- **Music.app already running.** The tool asks `application "Music" is running`, which
  answers without launching it, before it says anything else to Music; when Music is not
  running it exits `2`. The tool never launches Music itself, but if Music quits mid-run,
  the next call's `tell` block relaunches it.
- **The automation permission** for the terminal that runs it, to control Music (System
  Settings > Privacy & Security > Automation). The first run asks for it.
- **Optional: the project's `refresh_tags` extra** (`pip install ".[refresh_tags]"` from the
  project root), for mutagen, which the track-number check needs. Without it that check and
  the unreadable-tags list are skipped, the report says `tag checks skipped: mutagen not
  installed`, and every other check still runs.

## Usage

```text
library_audit.py --library <folder> [--format text|json|html] [--report <file>] [--decode]
```

| Option | Default | Description |
| --- | --- | --- |
| `--library` | required | The library folder to walk. There is no default: a tool that guessed it from Music.app would audit whatever Music.app already agrees with. |
| `--format` | `text` | The report's form: `text`, grouped by check; `json`, the same content as one object; or `html`, one page of tables, which needs `--report` (all below). Never inferred: `--report audit.html` alone writes text. |
| `--report` | none | Write the report to this file instead of stdout, replaced whole. Refused, exit `2` before any work, when its folder does not exist or lies inside a git working tree. Required by `--format html`. |
| `--decode` | off | Also decode every matched, local, readable file in full with `afconvert` (below). Slow: hours on a library of about 21,000 files, so it is never the default. |

## What it compares

**The files.** Every audio file under `--library` (`.mp3`, `.m4a`, `.m4p`, `.aac`, `.aif`,
`.aiff`, and `.wav`, any case: what Music.app imports, so not `.flac`, which it does not), hidden files and hidden folders skipped, symbolic
links to folders not followed. A folder it cannot read, and a file it cannot stat, are
listed under `unreadable files and folders`, never skipped in silence.

**The tracks.** Every track Music.app holds, of every class, listed 1000 at a time through
one read-only call a batch (below), each with its persistent ID, file location, cloud
status, album, artist (the album artist, or the track's artist when that is empty), disc
number, track number, compilation flag, class, enabled flag (the checkbox) and size. Shared tracks (a cloud track with no file
in this library) and any other class are listed too, not only file tracks: only a file
track has a location, so every other track is listed with none and placed by the same rule
as a file track whose location is missing.

**The match.** A track belongs to a file when the path Music.app gives for it stats to the
same device and inode as the walked file, never by comparing the path text: Music.app gives
the resolved path (an iCloud Drive library's real location, say), which is rarely the one the
library folder was named by. Each track then lands in exactly one place:

| The track | Where it lands |
| --- | --- |
| its file is one of the walked files | matched to that file |
| no location, or its file is gone, and its cloud status is `purchased`, `matched`, `uploaded`, or `subscription` | counted as "cloud-only", not listed: a copy exists in the cloud |
| no location, or its file is gone, and any other cloud status | listed as a track whose file is gone |
| its file exists outside `--library` | counted as "outside --library", not listed |

A track whose file sits under `--library` but in a hidden folder, or with a suffix the walk
does not collect, is counted as outside too: the walk never saw that file.

**What a live run confirmed, and what it could not.** The four cloud statuses are named as
Music.app's scripting dictionary names them (`CLOUD_COPY_STATUSES` in `src/audit_walk.py`),
and a track's class as the dictionary names it (`file track`, `shared track`). A read-only
live run on a library of about 20,000 tracks confirmed that a class coerces to that text
(`file track`) and that a status coerces to a word (`unknown`). That library used neither
iCloud Music Library nor Sync Library, so every track read `unknown` and none of the four
cloud-copy words was seen. Until one is, a track whose status reads some other way would be
listed as gone rather than counted as cloud-only, which is the safe direction.

## The checks

**What an album is:** an album group is the album artist (the artist when that
is empty), the album and the disc. A file's come from its tags; a Music.app track's from the
listing's same three fields. Both sides are compared the same way: tab, linefeed, and
carriage return turned into spaces (as the listing script does), Unicode composed (NFC),
surrounding spaces stripped, and case folded, so `Invented Album` and `INVENTED ALBUM` (with a trailing space) are
one album; Music.app's disc `0` (none) is disc 1, as a file's absent disc tag is. An album
filed across several folders is therefore one album, and a lone single beside another album
in one folder is its own. A file whose tags cannot be read falls back to its folder as its
group, and so does every file when mutagen is absent; the report marks such a group
`(by folder)`. A file whose tags read but name no album still groups by its (empty) names,
as Music.app, which read the same tags, will too. A file or track flagged as a compilation
(ID3 `TCMP` reading `1`, MP4 `cpil` set, Music.app's `compilation`) groups under one shared
artist key instead of any artist name, as Music.app files a compilation, so a compilation
whose tracks name many artists and no album artist is one album; the report shows its
artist as `(compilation)`. Two different compilations that share a title and a disc
therefore merge into one group, which can only hide a gap, never invent one. An album on
which only some files carry the compilation flag splits into two groups, the flagged and
the unflagged, as Music.app splits it.

**An iCloud placeholder's tags are never read from the file**, because opening it makes
iCloud download it. A placeholder matched to a Music.app track takes its tags from that
track's listing row instead: the album, the artist as the row gives it (the album artist,
else the artist), the disc, the track number, and the compilation flag, with no track count.
The row holds what Music.app last read from the file, so the placeholder groups and is
gap-checked as its file would be while the two agree. A file retagged outside Music.app
since then (by another tagger) still groups by Music.app's older names, which can show as
an album split by spelling or a gap the files do not have; `tag_refresh` makes Music.app
reread it. A row's track number `0` is no track number, since Music.app reports a blank
number as `0`, so a placeholder's pregap track (below) reads as unnumbered. A row's number past four digits is no number too, as in a file's tag (check 3): a track number reads as none and a disc number as disc 1. A placeholder with no track falls back to its folder as its group, like a
file whose tags cannot be read, but it is not listed under unreadable tags, since its tags
were never tried. In the count check a matched placeholder and its track are one item in
one group, as any matched file and its track are, so it never makes the counts differ on
its own; an unmatched one is a file with no track, and makes its folder group's counts
differ as any such file does.

1. **Files with no Music.app track**: walked files no track matched.
2. **Music.app tracks whose file is gone**: as in the table above.
3. **Track-number gaps**, per album group: the numbers from 1 to the highest track-count tag
   (or, with none, to the highest track number) that no file carries. A disc holding a
   track numbered `0`, a pregap ("hidden track one") track, runs from 0 instead and ends one
   below its track-count tag, because MusicBrainz numbers such a disc 0 to total - 1 and
   Picard writes it that way (`0/14` to `13/14`). Fewer files than the
   track-count tag always leaves such a number, so one check covers both. Track and disc
   numbers are read from ID3 (`TRCK`, `TPOS`) and MP4 (`trkn`, `disk`) tags, the names from
   ID3 `TPE2`, `TPE1`, `TALB` and MP4 `aART`, `©ART`, `©alb`, the compilation flag from
   ID3 `TCMP` and MP4 `cpil`; an absent disc number is
   disc 1. A number past four digits is read as no number. A group that is one spelling of a
   split album (the next check) is not listed here.
4. **Albums split by spelling**: one album whose files spell its artist or its title two
   ways, so that it makes two groups (or more), each with holes the other fills. A
   typographic hyphen against an ASCII one, `&` against `and`, and curly against straight
   quotes all print alike or nearly, and Music.app keeps each spelling its own album, so
   the gap check alone would report each half as an album missing the other's tracks. Two
   gap groups are taken as one album when all of these hold:

   - both are grouped by tags (a group by folder has no names to compare) and on one disc;
   - no track number is in both;
   - each holds a number the other's gap lacks: a group with no gap is a whole album,
     never half of one;
   - their artists are one name, or their albums are, compared loosely: case and
     compatibility forms folded (NFKC), every dash and hyphen lookalike read as a hyphen,
     curly quotes and primes as straight ones, every `&` as the word `and` (so `A&B`
     matches `A and B`), quotes dropped, other punctuation read as a space, and spacing
     collapsed. A name that folds to nothing (empty, or punctuation alone) is no name and
     matches nothing, so two albums with no title never pair on that. A compilation's
     artist is its fixed compilation key, which is no name either: two compilations pair
     only when their albums match, and a compilation never pairs with an artist merely
     named `(compilation)`;
   - their track-count tags agree: when both carry one and the two differ, they are two
     albums. A count tag on one side only refuses nothing.

   The loose comparison is for this pairing only: the groups themselves stay as the
   strict comparison above makes them, as Music.app keeps them. Pairs join into one
   finding, so an album split three ways is one finding, but never by chaining: a group
   joins only when its names and count tag match every group already joined, so of
   `P / X`, `P / Y`, and `R / Y` the outer two never meet. A joined album never holds one
   number twice. The pair holding the most tracks together joins first (then report
   order), and a group that would then repeat a number, or fail to match a member, is
   left out of the join and keeps its own gap.

   Three misses and two risks remain. Two contiguous halves with no count tag (tracks 1
   to 5 and 6 to 10) are not joined: neither has a gap the other fills, so each reads as
   a whole album. Halves whose artist and album both differ under the loose comparison
   are not joined either, and nor are halves whose count tags disagree (one half
   mis-tagged). A pair of different albums by one artist, with equal count tags and
   track numbers that fill each other's gaps, is still joined, since the artist alone
   matching is enough (the album may differ in a way the loose comparison does not fold,
   a space inside a word, say). Likewise, two different artists' albums sharing a title
   ("Greatest Hits", "Live") are joined under the same conditions, since the album alone
   matching is enough.
   Each split is one finding (exit `1`), listed with each spelling as tagged and the
   tracks it holds, then a note naming each character two spellings differ in, by code
   point and Unicode name, since the difference is often invisible. The numbers the joined
   album still lacks, counted as the gap check counts them, are shown there, once, and
   the halves leave the gap check. Nothing here retags a file: which spelling is right is
   left to whoever keeps the library. The fix is one spelling for both halves in your
   tagger, then `tag_refresh` so Music.app rereads them: for example, MusicBrainz Picard's Options > Metadata > Convert Unicode punctuation
   characters to ASCII. The report names no tagger, since the setting is that tool's own.
5. **Files with no track number**: tags read (or, for an iCloud placeholder, its track's
   listing row), but holding no usable track number. An ID3 track number of `0` is a
   pregap track, not a missing number; an MP4 `0` is a missing number, because iTunes
   stores a blank number beside a set total as `(0, total)`. Each is a
   finding (exit `1`), listed apart from unreadable tags, since its album is known; it is
   left out of the gap check and still counted in the next.
6. **Files and Music.app tracks differ**, per album group: the group's audio files against
   its Music.app tracks that expect a local file, which is every matched track and every
   gone one. Cloud-only tracks are left out: they hold no file, so counting them would make
   every album with one differ. Tracks outside `--library` are left out too, since the walk
   never saw their files. A matched track and its file are one item, so the track counts
   toward its file's group (by tags, or by folder when the file's tags could not be read),
   whatever album Music.app lists for it: a file retagged since it was imported makes no
   difference. A file with no track, a file two tracks point at (a duplicate in Music.app)
   and a gone track all make the counts differ.

   **A gone track** has no file, so it is placed by its location and Music.app's fields.
   When its location's folder is a walked folder whose every file is grouped by folder, it
   counts toward that folder group; that folder is found by device and inode, or by the
   path text (separators and dots collapsed, composed) when it cannot be stat. Otherwise a
   gone track with no location, or one whose location lies inside `--library`, counts
   toward its listed album, artist, and disc. One whose location lies outside `--library` is
   left out, as the tracks outside are: inside means its folder, or a folder above it,
   stats to the library folder's device and inode, or failing that its path text lies
   under the library folder's. A gone track left out here is still listed under check 2.

   **Without mutagen** the groups are folders: a folder's files against the tracks matched
   to them plus the gone tracks whose location's folder is that folder, found as above. A
   gone track with no location, or whose folder holds no walked file, is not counted here;
   it is still listed under check 2.
7. **Unreadable tags**: files mutagen cannot open or parse, or that hold no tag at all; they
   are grouped by folder. An iCloud placeholder is never among them: its tags are never
   read from the file (see *What an album is*).

## The sync checks: what this Mac can see of a track that will not sync

A track that stops reaching an iPhone by a Finder sync can be stopped on either side. These
checks list the causes visible on this Mac. They see the Mac only. Music.app's
scripting dictionary has no iPhone source, so no call can see the phone's copy: a track the
phone lists but cannot play, the fault that prompted these checks, is invisible here, and a
clean report does not clear the phone. The text report closes its sync sections with one
line saying so.

None of the cheap checks opens a file: they use the one `stat` the walk already takes, the
listing, and one `os.access` question per file. A file that is an iCloud placeholder is never
opened by them, because opening one makes iCloud download it, and nor is it by the tag
checks above, which take a placeholder's tags from its Music.app track instead.

1. **iCloud placeholders**: a walked file whose `st_flags` carries `SF_DATALESS`
   (`0x40000000`; Python names it from 3.13, and the tool falls back to the value on an
   older one). Its audio is not on this Mac, so a Finder sync cannot copy it. A finding.
2. **Files that cannot be read**: a walked file, not a placeholder, that `os.access` says
   this user may not read. It is listed under `unreadable files and folders`, reason `read
   access refused`, since that section already means a file the tool could not get at. A
   finding.
3. **Music.app's size out of step with the file**: a matched track whose listed size is
   known and not 0 but differs from its file's `st_size`, listed with both numbers. Music.app's
   record is stale; `tag_refresh` makes it read the file again. A track listing no size (0) is
   not judged. A size the listing gives as anything but plain digits is "unknown": never a
   mismatch, and counted in the summary's `sizes unknown`. A finding.
4. **Unchecked tracks**: every listed track whose `enabled` is false, wherever it was placed.
   Such a track is skipped only when the phone syncs "only checked songs", but anything listed
   here is a finding, as in every other section.
5. **Files that do not decode**, under `--decode` only: each matched file that is local
   (not a placeholder) and readable is decoded in full with
   `/usr/bin/afconvert -f WAVE -d LEI16 <file> <copy>.wav`, the copy written into a private
   temporary folder the tool makes (readable by this user only) and removes, never beside
   the audio, and each copy deleted as soon as its decode ends. Each call runs through
   `bounded_run` with a 120 s bound (`DECODE_TIMEOUT_S` in `src/audit_sync.py`: a 7-minute
   320 kbps track decoded in well under 5 s). A non-zero exit, or the bound passing, is a
   finding with `afconvert`'s last line (stderr first, then stdout, else its exit code).
   Placeholders and files that cannot be read are skipped and counted, never decoded. One
   progress line goes to stderr per 500 files. An `afconvert` that cannot be started at all
   ends the run with exit `2` and no report. A pass is not proof: `afconvert` tolerates
   some damage, so a file that decodes may still fail elsewhere.

```text
iCloud placeholders: 1
  /path/to/Library/The Placeholder Band/Invented Album/03 Third.mp3
  note: a placeholder's audio is not on this Mac, so a Finder sync cannot copy it
Music.app size differs from the file: 1
  /path/to/Library/The Placeholder Band/Invented Album/01 First.mp3: Music.app 4096, file 8
  note: Music.app's record is stale; tag_refresh makes it reread the file
unchecked tracks: 1
  The Placeholder Band / Invented Album, disc 1 track 12: /path/to/Library/The Placeholder Band/Invented Album/12 Last.mp3
  note: an unchecked track is skipped only when the phone syncs only checked songs
files that do not decode: 1
  /path/to/Library/The Placeholder Band/Invented Album/05 Fifth.mp3: Error: invented reason
  note: afconvert tolerates some damage, so a file that decodes is not proven sound
decode skipped: 1 (iCloud placeholders and files that cannot be read)
the sync checks see this Mac only: Music.app cannot see an iPhone, so a track the phone lists but cannot play is not found here
```

A section's note shows only when it lists something. Without `--decode` the decode's two
lines give way to one `decode check not run (--decode)` line.

## The report

The report goes to stdout, or to `--report`; one progress line per batch
(`tracks 1-1000 of N`) and every refusal go to stderr. Nothing is printed until the whole
audit is done.

Text, one section per check with its count, each item indented, then the summary:

```text
library: /path/to/Library
files with no Music.app track: 1
  /path/to/Library/The Placeholder Band/Invented Album/04 Bonus.mp3
Music.app tracks whose file is gone: 1
  The Placeholder Band / Invented Album, disc 1 track 2 [local only]: /path/to/Library/The Placeholder Band/Invented Album/02 Second.mp3
track-number gaps: 1
  The Placeholder Band / Invented Album, disc 1: missing 2-11 (files 2, track-count tag 12)
albums split by spelling: 1
  The Split-Level Duo / Second Invented Album, disc 1: 2 spellings, still missing 6
    1. The Split-Level Duo / Second Invented Album: tracks 2, 4
    2. The Split‐Level Duo / Second Invented Album: tracks 1, 3, 5
    1 and 2 differ in the artist: U+002D HYPHEN-MINUS vs U+2010 HYPHEN
files with no track number: 1
  /path/to/Library/The Placeholder Band/Invented Album/Hidden Track.mp3
files and Music.app tracks differ: 2
  The Placeholder Band / Invented Album, disc 1: files 3, Music.app tracks 4
  /path/to/Library/The Placeholder Band/Invented Album (by folder): files 1, Music.app tracks 0
unreadable tags: 1
  /path/to/Library/The Placeholder Band/Invented Album/04 Bonus.mp3
unreadable files and folders: 0
iCloud placeholders: 0
Music.app size differs from the file: 0
unchecked tracks: 0
decode check not run (--decode)
the sync checks see this Mac only: Music.app cannot see an iPhone, so a track the phone lists but cannot play is not found here
summary: findings 8; audio files 9, Music.app tracks 9; cloud-only 0, outside --library 0, unparsed rows 0, sizes unknown 0
```

Here the album's tag group holds three files (tracks 1 and 12, and the unnumbered hidden
track) against four Music.app tracks (those three, and the gone track 2), while the bonus
file, whose tags cannot be read, is judged by its folder. The duo's five files spell its
name two ways, which print alike: each spelling is numbered, a `differ` line names the
characters each pair of spellings differs in (artist, album, or both), and the header ends
with the numbers the joined album still lacks, when it lacks any. A difference is cut short
after three changes, and a change after three characters a side, each saying how many more
there are. A gone track with no
location at all reads `: no location`. Without mutagen the `track-number gaps`, `albums split by
spelling`, `files with no track number` and `unreadable tags` sections give way to one `tag checks skipped:
mutagen not installed` line. Names are printed with each control character as a visible
`\xNN` escape, so no name can split a line or drive the terminal.

`--format json` prints one object holding the same content, ASCII only (every other
character escaped):

| Key | Value |
| --- | --- |
| `schema` | `4`; raised whenever a key changes meaning or goes (2: gaps and counts per album group, and `no_track_number`; 3: `split_albums`, whose halves leave `track_gaps`; 4: the sync checks' keys, and `unreadable_paths` also holding refused files) |
| `library` | the library folder, absolute |
| `audio_files`, `music_tracks` | the files walked, and the tracks Music.app counted: every class, shared tracks included, so in a library with none it is the file-track count |
| `findings` | how many findings: every listed item, plus each unparsed row |
| `no_track` | the paths of the files with no track |
| `file_gone` | one object a gone track: `persistent_id`, `cloud_status`, `artist`, `album`, `disc`, `track`, `location` (empty for none) |
| `track_gaps` | one object a gap: `artist`, `album`, `disc`, `missing` (a list of numbers), `files`, `track_count` (null for none); null when the tag checks were skipped |
| `split_albums` | one object an album split by spelling: `disc`; `spellings`, one object each in report order: `artist` (`(compilation)` for a compilation), `album` (each as tagged, first spelling seen) and `tracks` (a list of numbers); `still_missing`, the numbers the joined album lacks (a list, empty for none); `differs`, one object each pair of spellings, every pair differing in one name at least: `between` (the pair's two indexes into `spellings`, from 0), `artist` and `album` (each the note naming the differing characters, null where that name is spelled alike). Null when the tag checks were skipped |
| `no_track_number` | the paths of the files whose tags hold no track number; null when the tag checks were skipped |
| `count_differs` | one object a group: `grouped_by` (`tags` or `folder`), `artist` (`(compilation)` for a compilation), `album`, `disc` (each null for a folder group), `folder` (null for a tag group), `files`, `tracks` |
| `unreadable_tags` | the paths whose tags could not be read; null when the tag checks were skipped |
| `unreadable_paths` | one object each: `path`, `reason`; a file the access check refuses reads `read access refused` |
| `unparsed_rows` | listing lines in no row's shape |
| `cloud_only`, `outside_library` | the two tallies |
| `icloud_placeholders` | the paths of the walked files that are iCloud placeholders |
| `size_differs` | one object a matched track whose size is out of step: `path`, `persistent_id`, `music_size`, `file_size` |
| `unchecked` | one object an unchecked track: `persistent_id`, `artist`, `album`, `disc`, `track`, `location` (empty for none) |
| `sizes_unknown` | how many matched tracks listed a size that was not an exact integer; a tally, not a finding |
| `decode_failed` | one object a file that did not decode: `path`, `reason`; null when `--decode` was not given |
| `decode_skipped` | how many matched files the decode skipped, placeholders and files that cannot be read; null when `--decode` was not given |

**The report is the library's own data.** It holds album, artist, and file names, so it never
belongs in a repository: `--report` refuses any path inside a git working tree, judged by a
`.git` entry in the target's folder or any folder above it, symbolic links resolved. The file
is written to a temporary file beside it and renamed over it, so a reader never sees half a
report, and it is created readable by the user who ran the tool only.

### The HTML report

`--format html` writes the same report as one page of tables, for reading in a browser. It
goes to a file only, so it needs `--report`: without one the run exits `2` with one line on
stderr, before Music.app is asked anything. The format is never inferred from the report's
name: `--report audit.html` with the default format writes text.

The page is rendered from the very object the JSON format serializes, so the two never
disagree. It is one self-contained HTML5 document: inline CSS, no script, and nothing a
browser would fetch (no font, image, or stylesheet), in light and dark. It holds:

- a header: the library folder and the tallies (audio files, Music.app tracks, findings,
  cloud-only, outside the library, sizes unknown, and decode skipped when `--decode` ran);
- a summary table of every check in report order with its count; a check that found
  something links to its section, and a check that did not run (the tag checks without
  mutagen, the decode without `--decode`) reads `not run`;
- one section per check that found something: its heading and count, one sentence on what
  the finding means and the usual fix, then a table (the unparsed rows, a bare count, have
  no table). Paths are shown relative to the library folder when under it, else absolute;
- a footer: that nothing was changed, and that the sync checks see this Mac only.

Every name is escaped, and shown with each control character as a visible `\xNN`, as in the
text report. Tables scroll sideways inside their own frame, so on a phone the page itself
does not. The frame (the style, the tables, the summary, and the escape) is the shared
`html_page` library in `html_page/` at the project root (`html_page.md` there), found
at one fixed place on `sys.path`; `phone_audit`'s page is laid out in it too.

## The listing call, and why a failed call ends the run

The tracks come from `music_calls.list_tracks`, and their count from
`music_calls.count_tracks`, in `../tag_refresh/src/`: this tool shares tag_refresh's
Music.app calls rather than keeping its own, so both use the same two bounds (30 s per Apple
event inside the script, 35 s on the whole call) and the same failure types;
`../tag_refresh/tag_refresh.md`, "Bounds, and why a timeout ends the run", says why those
numbers. The listing reads each property for a whole range of tracks in one Apple event, so
a batch costs eleven events however many tracks it holds, plus one for the locations. When a
range holds a track that is not a file track, which has no location, the locations are read
one file track at a time instead, and every other track is given none.

**Why plain track ranges.** A read-only live run on a library of about 20,000 tracks
measured the choice. Over `file tracks i thru j of library playlist 1`, Music.app filters
the library up to index `j` on every Apple event, so each property read over 250 tracks near
the end of the library cost about 5 s, and a batch's reads outlived the 35 s bound. The same
reads over `tracks i thru j` took roughly 1 s per 250 tracks and 2.4 s per 2000. Reading
each property for the whole library at once is no way round it: `location of every file
track` failed with error -1741. So the listing indexes plain tracks, the count it is checked
against counts plain tracks too, and the batch is 1000 tracks, far inside the bound.

**The row format.** A row is eleven tab-separated fields ended by a linefeed: persistent ID,
cloud status, disc number, track number, path (empty for a track with no file, and for every
track that is not a file track), album, artist, compilation flag (`true` or `false`), the
track's class (`file track`, `shared track`, `URL track`), the enabled flag (`true` or
`false`) and the size in bytes; a new field goes at the end, so the fields before it keep
their places. A missing disc or track number reads as 0, a missing name as empty, a missing
size as 0. AppleScript integers stop at 536,870,911: a larger size arrives as a real,
which AppleScript writes in exponent form (`6.0E+8`), not an exact integer. The script
therefore writes each size as millions and the rest, each an exact integer, the rest padded
to six digits, so every size is plain decimal digits; the parser takes up to fifteen digits
as exact and reads anything else as an unknown size, counted, never a mismatch. The
rows are built after the script's `tell` block, so no step of building them is sent to
Music.app, and joined once rather than appended one by one. Album and artist names have each
tab, linefeed, and carriage return turned into a space inside the script, so no name can
split a row; a row whose path holds one is counted as an unparsed row, a finding, since that
track could not be placed.

**A failed, timed-out, or refused call ends the run with exit `2` and no report.** A partial
listing would report every unlisted track's file as having no track, which is worse than no
report. So each listing is confirmed, not trusted: the script compares the lengths of the
property lists it read and errors when they differ (one track's path would otherwise
be paired with another's ID); each batch must answer one row, parsed or not, per index it
asked for; and the track count is asked again after the last batch. Any of those
failing ends the run the same way; a changed count says the library changed during the
audit (an import, say, shifts every index after it), so run it again once nothing is
importing.

**What the re-count cannot catch.** It compares two totals, so a change that nets to zero
between batches, one track added and another removed, leaves the count unchanged while the
indices after the change shift: a track could then be listed twice, or not at all, and the
report would carry the false findings that follow (a file with no track, or a duplicate).
Run the audit while nothing is importing or deleting; a finding that looks wrong is worth one
re-run before acting on it.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Nothing found. Cloud-only and outside-the-library tracks are tallies, not findings. |
| `1` | Findings: anything listed in a section, the sync sections included, or an unparsed listing row. |
| `2` | Could not start or run: not macOS, Music.app not running or the probe unanswered, `--library` not a readable folder, bad options (`--format html` without `--report` among them), a `--report` inside a git working tree or in a folder that does not exist (asked at start and again just before the write), a Music.app call that failed or timed out, a listing that did not account for its range, a library that changed during the audit, an `afconvert` that could not be started (`--decode`), or a report that could not be written. |
| `130` | Ctrl-C: before the report, nothing is printed or written; while it is delivered, a `--report` file is left as it was and printed text may stop part way. |

## Tests

`test_library_audit.py` runs every suite in `tests/`. None reaches Music.app, the real
library, the network, or anything outside a temporary directory: every call goes through a
fake runner that plays `osascript` from an invented library and records each argument list,
so a suite asserts that the `is running` probe came first and that nothing but the three
reading scripts was ever sent. The access check and the decoder are fakes too: no test
reaches `afconvert`, and a run without `--decode` fails if the decoder is called at all. An
iCloud placeholder cannot be made in a test, so its `stat` flag is invented, and the tag
reader those suites hand in fails the test if it is ever asked for a placeholder's tags.

One suite does reach Music.app, and only when asked: `tests/test_audit_live.py` makes the
count and then one listing of at most the first 50 tracks, through the same two scripts and
`real_run` a run uses, after an `is running` probe that never launches Music. Both scripts
only read. It checks shape alone: the count is a non-negative integer, every row has the
listing's field count and parses through `audit_rows`, and the rows number the range asked
for. A failure names row positions and counts of bad rows, and a failed call only its error
number, so no name or count from the library is printed. It skips unless
`LIBRARY_AUDIT_LIVE` is `1`, under `APPLE_MUSIC_TOOLBOX_OFFLINE`, off macOS, and when
Music.app is not running:

```bash
LIBRARY_AUDIT_LIVE=1 python library_audit/test_library_audit.py
```

## The hand check

`samples/README.md` runs the tool over a small invented library folder against a fake
`osascript`, so it never reaches the real Music.app and prints the same report everywhere.
To audit your own library, run it with `--library` naming the folder Music.app's files live
in, and keep the report out of any repository: stdout, or a `--report` outside one.
