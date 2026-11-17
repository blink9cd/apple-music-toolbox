# Build sample

A hand check of what `runner.py build` puts into the app bundle, with no signing
identity, no launchd, no Music.app and no permission prompt. `Info.plist` is the property
list an unsigned build writes; `grant.plist` is the one-shot launchd agent `install`
loads to check the app's permission.

Both files show this machine's paths as placeholders:

| Placeholder | What a real build writes there |
| --- | --- |
| `<checkout>` | The root of the git checkout that holds `runner.py` |
| `<venv>/bin/python` | The interpreter that ran the build, exactly as Python names it |
| `<home>` | The home folder of the user who ran `install` |

## The hand check

From this folder, build the bundle into a fresh folder, with no `--sign`. It needs the
Swift toolchain, and compiles into a private scratch folder inside the runner's data
folder (`data_dir` in `../layout.json`, under the home folder), never into the checkout:

```sh
out="$(mktemp -d)"
python="$(python3 -c 'import sys; print(sys.executable)')"
"$python" ../runner.py build --out "$out"
root="$(git rev-parse --show-toplevel)"
sed -e "s|$python|\&lt;venv\&gt;/bin/python|g" -e "s|$root|\&lt;checkout\&gt;|g" \
  "$out/Apple Music Toolbox Runner.app/Contents/Info.plist" | diff - Info.plist
```

The build prints `built`, then the bundle's path. The last command swaps the two machine
paths for their placeholders and compares, and `diff` prints nothing. The interpreter is
swapped first: a virtual environment inside the clone has the checkout's root in its
path, so swapping the root first would leave an interpreter line that no longer matches. What to read in
the file:

- `AMTRunnerAllowlist` holds the one interpreter and every script the app may start, as
  absolute paths. The scripts are the entries of `../allowlist.json`, each joined to the
  checkout's root.
- `NSAppleEventsUsageDescription` is the sentence macOS shows when the app first asks to
  control Music.
- The names are `Apple Music Toolbox Runner`, and the identifier is
  `local.apple-music-toolbox.runner`.

## The grant plist

`install` is the only command that writes this one, and it removes it again when the
check ends, so there is no dry run to compare. Read `grant.plist` for what it holds: the
installed app's executable, started once at load (`RunAtLoad`, with no `KeepAlive`),
running `grant_probe.py` under the allowlisted interpreter, with the probe's own
`--result` after the `--` separator.

To see a real one, read the plist in the grant folder of the runner's data folder (its
name is the grant label, `local.apple-music-toolbox.runner.grant`, with `.plist` after
it) while an install is waiting on the permission prompt.

The suites hold both files to the code on every gate run: `test_run_install` builds the
property list and `test_run_grant` the agent's, each swapping the same placeholders in.
