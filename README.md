# Filedrop

Filedrop opens a compact popup titled “Drag to share” for a finite batch of existing local files. Each file appears as a draggable row or responsive grid tile; each item drags only its own file. The source files remain unchanged; drag actions offer COPY only. Receiving applications choose whether to accept a drop. The app does not export unsaved editor buffers.

`--mode compact` (default) uses a decorated normal GTK window that users can move using their desktop's window controls. Niri may tile normal windows unless its configuration floats Filedrop. Compact mode does not load or require GTK4 Layer Shell and can use any display backend supported by GTK. `--mode shell` uses GTK4 Layer Shell and appears centered on the compositor-selected output. Layer Shell anchors surfaces to output edges or center; it cannot place a surface beside the pointer.

Use `--no-decorate` to hide native window decorations and the app header in compact mode; file rows or tiles remain draggable, and `V`, zoom, and Escape shortcuts remain available. Headerless compact windows use matching 12-pixel top and bottom content margins. `--decorate` explicitly enables native decorations and keeps the app header. This option has no effect on `--mode shell`, which keeps its app header.

The file area uses one flat, theme-aware background in both layouts, including themes that paint a separate titlebar band.

## Requirements

- Python 3.10 or newer.
- GTK 4.8 or newer and PyGObject.
- For shell mode, GTK4 Layer Shell with its GObject introspection typelib and a Wayland compositor with layer-shell support. Niri supports this protocol.

`nix develop` provides a pinned, isolated runtime with Python, PyGObject, GTK4, and GTK4 Layer Shell. It does not install packages or change system configuration.

Launch compact mode by default, or select shell mode explicitly:

```sh
python3 filedrop.py "/path/to/a file.txt"
python3 filedrop.py --mode shell "/path/to/a file.txt"
python3 filedrop.py --layout grid "/path/to/a file.txt"
python3 filedrop.py --no-decorate "/path/to/a file.txt"
python3 filedrop.py --decorate "/path/to/a file.txt"
```

Alternatively, install GTK4 and PyGObject from your distribution; install GTK4 Layer Shell only when using shell mode. Filedrop does not install native libraries through pip.

Enter the project runtime with Nix flakes:

```sh
nix develop
python3 filedrop.py "/path/to/a file.txt"
python3 filedrop.py --mode shell "/path/to/a file.txt"
```


## Install and run

Install Filedrop into a private virtual environment and add its launcher to `~/.local/bin`:

```sh
mise run install
filedrop "/path/to/a file.txt" "/path/to/another.txt"
```

The install uses `~/.local/share/filedrop` by default. Add `~/.local/bin` to `PATH` to run `filedrop` by name. Re-run `mise run install` to update the installed app from the current source. `mise install` installs tools declared by mise; it does not install Filedrop.

Set `FILEDROP_INSTALL_PREFIX` and `FILEDROP_BIN_DIR` to override the environment and launcher locations. The install requires Python 3.10+, `venv`, pip, setuptools 61+, and wheel already available to that Python; it uses no package index and installs no native libraries. `--system-site-packages` keeps host PyGObject available to the app.

Or run without installation:

```sh
python3 filedrop.py "/path/to/a file.txt"
python3 -m filedrop "/path/to/a file.txt"
```

Quote direct arguments when names contain shell whitespace or metacharacters. Put `--` before any filename beginning with `-`, for example `filedrop -- -draft.txt`.

Filedrop reads stdin only when stdin is not a terminal. It reads finite input through EOF before opening the window; it does not monitor a live stream. Positional arguments come first, followed by stdin records. Newline delimits records by default, and `--null` / `-0` selects NUL delimiters. Empty records are ignored. Other spaces, quotes, and backslashes are literal filename characters, not shell syntax. Use NUL delimiters for filenames containing newlines. Relative paths resolve against the launch working directory. `~`, variables, globs, and `file://` values are not expanded. Duplicate absolute spellings collapse while retaining their first position.

Examples:

```sh
filedrop "./a file.txt" './猫#%.txt'
printf '%s\n' "./a file.txt" './another.txt' | filedrop
find . -type f -print0 | filedrop --null
```

## Save files for later

`--add` saves file paths for later use without opening the window. Repeat calls append paths; duplicates keep their first position. The saved queue stores absolute path names, not file contents. Files must exist when added and again when loaded.

`--load` opens saved files plus any direct arguments or stdin paths. Saved paths come first. Loading does not consume the queue, so repeat loads show same saved files. `--clear` removes saved path records only; it never removes source files and does not read stdin. It accepts no positional files.

```sh
filedrop --add "/path/to/a file.txt"
printf '%s\n' "/path/to/another.txt" | filedrop --add
filedrop --load
filedrop --load "/path/to/one-time-file.txt"
filedrop --clear
```

The queue lives under `$XDG_RUNTIME_DIR/filedrop-UID` when `XDG_RUNTIME_DIR` is set, or `${TMPDIR:-/tmp}/filedrop-UID` otherwise. Filedrop requires a private, current-user-owned queue directory and uses mode `0700`; queue and lock files use mode `0600`. Runtime directories may be cleared on logout or reboot. Temporary-directory queues may survive longer, but system cleanup can remove them at any time. The queue contains paths that reveal file names; it does not copy file data or provide durable storage.

All supplied paths must name existing regular files (a symlink to a regular file is accepted). One invalid path rejects the entire batch. Each item drags only its own file and highlights on hover; its theme-aware background covers the full draggable item. File items use a `grab` cursor in both list and grid layouts. List rows show a file icon, name, and trailing drag grip. Grid tiles show a file-type icon above an ellipsized name without a visible drag grip; tiles remain draggable, and tooltips contain the full path. Use the header view toggle or press `V` to switch layouts while open; the same files and current zoom remain. Press `c`/`C` to clear saved path records and remove current items from the window; the window shows “No files”. This never deletes source files. If clearing the saved queue fails, current items remain and the error appears in the status label. During a drag, current-item removal waits until the transfer ends. Press `?` to show the theme-aware, centered Key/Action shortcut card with 12px internal padding; zoom keys display `+ / =` and `-`, while keypad bindings still work. It does not move file content. Press `q`/`Q` or Escape to close; during a drag, dismissal waits until the transfer ends. `--layout {list,grid}` selects the initial layout; list is default. Use − and + header buttons, or press `-` and `+` (keypad subtract/add also work), to scale text and icons from 75% to 200% in 25% steps. Unshifted `=` also increases zoom. `--zoom PERCENT` sets initial text and icon size from 75% to 200%; default is 100%. For example, `filedrop --zoom 150` starts at 150%, including with `--load` or `--no-decorate`. Zoom is not persisted; popup height and heading stay unchanged in fixed-height mode. Control, Alt, Super, and Meta modified shortcuts do not activate. Selection controls and file counts are absent.

`--height PIXELS` sets fixed window height; the default is 420 pixels. `--height auto` sizes the window to its GTK-measured natural content after startup, layout changes, zoom changes, clearing files, and showing or hiding the shortcut overlay. Larger file batches grow the window; the visible shortcut overlay also contributes its full height, and hiding it restores the content-fit height. Auto mode removes the fixed 180-pixel content minimum and measures wrapped grid rows at the available inner width. Auto height caps at 90% of the window's monitor height, or the first display monitor when GTK cannot identify one; longer content scrolls. GTK minimum sizes may constrain this cap. This works in compact and shell modes and keeps the 460-pixel window width.


## Launch saved editor files

Save the current file first. These examples pass argument arrays, so shell quoting is unnecessary. Close or disconnect editor subprocess stdin: otherwise the process can wait forever for EOF before opening its window. Require `filedrop` on `PATH`.

Vim with job support:

```vim
:let g:filedrop_job = job_start(['filedrop', expand('%:p')], {'in_io': 'null'})
```

Emacs, evaluated with `M-:`:

```elisp
(let ((p (make-process :name "filedrop" :buffer "*filedrop*"
                       :command (list "filedrop" (buffer-file-name))
                       :connection-type 'pipe :noquery t)))
  (process-send-eof p))
```

## Verification

Run behavior tests from the project root inside `nix develop`:

```sh
python3 -m unittest discover -s tests -v
mise run test
```

Build wheel and source distribution through the installed setuptools PEP 517 backend:

```sh
python3 -c 'import setuptools.build_meta as backend; backend.build_sdist("dist"); backend.build_wheel("dist")'
mise run build
```

The Nix shell supplies native GTK runtime libraries and typelibs. Building distributions with system Python requires `setuptools` and `wheel` there.

The suite covers path parsing, validation, saved-path queue behavior and concurrency, CLI boundaries, individual-file drag selection, and asynchronous URI-provider serialization. Run it from the project root inside `nix develop`:

```sh
nix develop --command python3 -m unittest discover -s tests -v
```

For desktop verification, create existing fixture files with distinct contents and use a Wayland compositor with layer-shell support:

```sh
printf '%s\n' "$fixture/first file.txt" "$fixture/猫#%.txt" "$fixture/third.txt" | python3 filedrop.py --mode shell --layout grid
printf '%s\n' "$fixture/first file.txt" "$fixture/猫#%.txt" "$fixture/third.txt" | python3 filedrop.py --mode compact --layout grid
```

List is the default; select initial grid independently with `--layout grid`. Press `v` or `V` to toggle layout, `+`/`=`/keypad-add to increase zoom, and `-`/keypad-subtract to decrease zoom. Verify same files remain and zoom stays bounded from 75% to 200%; modified shortcuts must not activate. Verify each row or tile drags only its own file. Empty status text stays hidden. Header buttons request 32×32 minimum sizes. Grid tiles wrap, scroll vertically, and avoid horizontal overflow at 200% zoom. GTK smoke verified direct list and saved grid `--load --no-decorate` launches at `--zoom 150`; measured fixture icon/grip sizes were 30px/24px and Pango label scale was 1.5. Header buttons changed zoom to 175%, restored 150%, and remained bounded at 75% and 200%.

Height smoke verified content-fit and shrinking after clear in compact, undecorated, grid, and shell modes; fixed 520-pixel height stayed fixed through layout changes, zoom changes, and clearing. Undecorated auto-height smoke at 150% zoom measured equal 19-pixel gaps above and below a grid tile in a 111-pixel window, and equal 15-pixel gaps around a list row in a 68-pixel window. Grid gaps also stayed equal at 75% and 200% zoom. Six grid tiles at 200% zoom fit their two measured rows without scrolling. Long list and grid content scrolled in an 864-pixel window on the tested monitor.

Shortcut-overlay desktop smoke verified that an undecorated auto-height grid window grew from 92 to 174 pixels when `?` showed all shortcut rows, then shrank to 92 pixels when hidden. List mode grew from 58 to 174 pixels and shrank back. A 12-row list measured 454 pixels; a 40-tile grid reached the 864-pixel monitor cap. An explicit 420-pixel height stayed unchanged while toggling shortcuts.
