"""Select local files and drag them into desktop applications."""

from __future__ import annotations

import argparse
import fcntl
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Sequence


def parse_paths(
    arguments: Sequence[str],
    piped: bytes | None,
    *,
    null_delimited: bool,
    cwd: Path,
) -> list[Path]:
    paths = list(arguments)
    if piped is not None:
        separator = b"\0" if null_delimited else b"\n"
        paths.extend(os.fsdecode(item) for item in piped.split(separator) if item)

    result: list[Path] = []
    seen: set[Path] = set()
    for value in paths:
        if "\0" in value:
            raise ValueError("path contains NUL")
        path = Path(os.path.abspath(os.path.join(os.fspath(cwd), value)))
        if path not in seen:
            seen.add(path)
            result.append(path)
    if not result:
        raise ValueError("no files supplied")
    return result


def validate_paths(paths: Sequence[Path]) -> None:
    if not paths:
        raise ValueError("no files supplied")
    for path in paths:
        if "\0" in os.fspath(path):
            raise ValueError("path contains NUL")
        try:
            if not path.is_file():
                raise ValueError(f"not a regular file: {path}")
        except OSError as error:
            raise ValueError(f"not a regular file: {path}") from error


def _queue_directory() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime or tempfile.gettempdir())
    if not base.is_dir():
        raise OSError(f"runtime directory is not a directory: {base}")
    if runtime:
        info = base.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OSError(f"runtime directory must be private and owned by current user: {base}")
    directory = base / f"filedrop-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.stat()
    if not directory.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError(f"saved-path directory must be private and owned by current user: {directory}")
    return directory


class SavedPaths:
    """Private, process-safe queue of filesystem-encoded absolute paths."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory if directory is not None else _queue_directory()
        self.path = self.directory / "paths"
        self.lock_path = self.directory / "paths.lock"

    def _locked(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.stat()
        if not self.directory.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OSError(f"saved-path directory must be private and owned by current user: {self.directory}")
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.lock_path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise OSError(f"saved-path lock must be private and owned by current user: {self.lock_path}")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _read(self) -> list[Path]:
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return []
        return [Path(os.path.abspath(os.fsdecode(record))) for record in data.split(b"\0") if record]

    def add(self, paths: Sequence[Path]) -> None:
        descriptor = self._locked()
        try:
            existing = self._read()
            ordered = list(existing)
            seen = set(existing)
            for path in paths:
                if path not in seen:
                    ordered.append(path)
                    seen.add(path)
            data = b"\0".join(os.fsencode(path) for path in ordered)
            temporary_descriptor, temporary_name = tempfile.mkstemp(prefix=".paths-", dir=self.directory)
            try:
                with os.fdopen(temporary_descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, self.path)
            except BaseException:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise
        finally:
            os.close(descriptor)

    def load(self) -> list[Path]:
        descriptor = self._locked()
        try:
            return self._read()
        finally:
            os.close(descriptor)

    def clear(self) -> None:
        descriptor = self._locked()
        try:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        finally:
            os.close(descriptor)


def _display(value: str) -> str:
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")




def make_drag_provider(paths: Sequence[Path]):
    if not paths:
        raise ValueError("no files selected")
    validate_paths(paths)
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gio", "2.0")
    from gi.repository import Gdk, Gio, GLib

    files = [Gio.File.new_for_path(os.fsencode(path)) for path in paths]
    file_list = Gdk.FileList.new_from_array(files)
    typed = Gdk.ContentProvider.new_for_value(file_list)
    uris = "".join(file.get_uri() + "\r\n" for file in files).encode("utf-8")
    uri_provider = Gdk.ContentProvider.new_for_bytes("text/uri-list", GLib.Bytes.new(uris))
    return Gdk.ContentProvider.new_union([typed, uri_provider])


def _parse_height(value: str) -> int | str:
    if value == "auto":
        return value
    try:
        height = int(value)
    except ValueError as error:
        raise ValueError("height must be 'auto' or a positive pixel count") from error
    if height <= 0:
        raise ValueError("height must be 'auto' or a positive pixel count")
    return height



def run_window(
    paths: Sequence[Path],
    mode: str = "compact",
    layout: str = "list",
    decorate: bool = True,
    zoom: int = 100,
    height: int | str = 420,
) -> int:
    if not 75 <= zoom <= 200:
        raise ValueError("zoom must be between 75 and 200")
    if isinstance(height, str):
        height = _parse_height(height)
    elif (
        not isinstance(height, int)
        or isinstance(height, bool)
        or height <= 0
    ):
        raise ValueError("height must be 'auto' or a positive pixel count")


    try:
        if mode == "shell":
            from ctypes import CDLL

            # Layer Shell must load before GI to interpose Wayland client symbols.
            CDLL("libgtk4-layer-shell.so")
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        gi.require_version("Gio", "2.0")
        if mode == "shell":
            gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gdk, Gio, GLib, Gtk, Pango
        if mode == "shell":
            from gi.repository import Gtk4LayerShell
    except (ImportError, OSError, ValueError) as error:
        dependencies = "GTK 4 and PyGObject"
        if mode == "shell":
            dependencies += ", and GTK4 Layer Shell"
        raise RuntimeError(
            f"GTK dependencies unavailable; install {dependencies}: {error}"
        ) from error

    if Gtk.get_major_version() < 4 or (
        Gtk.get_major_version() == 4 and Gtk.get_minor_version() < 8
    ):
        raise RuntimeError("GTK 4.8 or newer is required")
    initialized = Gtk.init_check()
    if isinstance(initialized, tuple):
        initialized = initialized[0]
    if not initialized or Gdk.Display.get_default() is None:
        raise RuntimeError("could not connect to a graphical display")
    if mode == "shell" and not Gtk4LayerShell.is_supported():
        raise RuntimeError("a Wayland compositor with layer-shell support is required")

    class FiledropApplication(Gtk.Application):
        def __init__(self) -> None:
            super().__init__(application_id="org.filedrop.App", flags=Gio.ApplicationFlags.NON_UNIQUE)
            self.window = None

        def do_activate(self) -> None:
            if self.window is not None:
                self.window.present()
                return
            window = Gtk.ApplicationWindow(application=self)
            self.window = window
            self.layout = layout
            window.set_resizable(False)

            if mode == "shell":
                window.set_decorated(False)
                Gtk4LayerShell.init_for_window(window)
                Gtk4LayerShell.set_namespace(window, "filedrop")
                Gtk4LayerShell.set_layer(window, Gtk4LayerShell.Layer.OVERLAY)
                Gtk4LayerShell.set_keyboard_mode(
                    window, Gtk4LayerShell.KeyboardMode.ON_DEMAND
                )

            overlay = Gtk.Overlay()
            overlay.add_css_class("filedrop-content")
            window.set_child(overlay)
            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            root.set_margin_top(12 if mode == "compact" and not decorate else 0)
            root.set_margin_bottom(12)
            root.set_margin_start(12)
            root.set_margin_end(12)
            overlay.set_child(root)
            style = Gtk.CssProvider()
            style.load_from_data(
                b".filedrop-content { background: @theme_bg_color; border-radius: inherit; }"
                b".file-row { border-radius: 6px; padding: 4px 8px; }"
                b".file-row:hover { background-color: alpha(@theme_fg_color, 0.08); }"
                b".filedrop-header .filedrop-header-button { min-width: 32px; min-height: 32px; padding: 0; }"
b".filedrop-shortcuts { margin: 0; padding: 12px; }"
            )
            display = Gdk.Display.get_default()
            Gtk.StyleContext.add_provider_for_display(
                display,
                style,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            window._filedrop_style = style


            heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            heading.add_css_class("filedrop-header")
            heading.set_size_request(-1, 48)
            heading.set_margin_bottom(4)
            root.append(heading)
            title = Gtk.Label(label="Drag to share")
            title.set_xalign(0)
            title.set_hexpand(True)
            title.add_css_class("title-4")
            title.set_valign(Gtk.Align.CENTER)
            heading.append(title)

            layout_button = Gtk.Button()
            layout_button.add_css_class("flat")
            layout_button.add_css_class("filedrop-header-button")
            layout_button.set_size_request(32, 32)
            layout_button.set_valign(Gtk.Align.CENTER)
            heading.append(layout_button)

            current_zoom = zoom

            decrease = Gtk.Button(label="−")
            decrease.set_tooltip_text("Decrease text and icon size (−)")
            decrease.update_property(
                [Gtk.AccessibleProperty.LABEL],
                ["Decrease text and icon size"],
            )
            decrease.add_css_class("flat")
            decrease.add_css_class("filedrop-header-button")
            decrease.set_size_request(32, 32)
            decrease.set_valign(Gtk.Align.CENTER)
            heading.append(decrease)
            increase = Gtk.Button(label="+")
            increase.set_tooltip_text("Increase text and icon size (+)")
            increase.update_property(
                [Gtk.AccessibleProperty.LABEL],
                ["Increase text and icon size"],
            )
            increase.add_css_class("flat")
            increase.add_css_class("filedrop-header-button")
            increase.set_size_request(32, 32)
            increase.set_valign(Gtk.Align.CENTER)
            heading.append(increase)
            heading.set_visible(mode != "compact" or decorate)

            status = Gtk.Label()
            status.set_xalign(0)
            status.set_wrap(True)
            status.set_visible(False)
            root.append(status)

            shortcuts = Gtk.Grid()
            shortcuts.set_column_spacing(18)
            shortcuts.set_row_spacing(4)
            shortcuts.set_visible(False)
            shortcuts.set_halign(Gtk.Align.CENTER)
            shortcuts.set_valign(Gtk.Align.CENTER)
            shortcuts.add_css_class("card")
            shortcuts.add_css_class("filedrop-shortcuts")
            for column, label in enumerate(("Key", "Action")):
                heading_label = Gtk.Label(label=label)
                heading_label.set_xalign(0)
                heading_label.add_css_class("heading")
                shortcuts.attach(heading_label, column, 0, 1, 1)
            shortcut_rows = (
                ("v / V", "Switch layout"),
                ("+ / =", "Increase zoom"),
                ("-", "Decrease zoom"),
                ("c / C", "Clear saved files"),
                ("?", "Show shortcuts"),
                ("Esc / q / Q", "Close window"),
            )
            for row, (key_label, action) in enumerate(shortcut_rows, start=1):
                key_cell = Gtk.Label(label=key_label)
                key_cell.set_xalign(0)
                action_cell = Gtk.Label(label=action)
                action_cell.set_xalign(0)
                shortcuts.attach(key_cell, 0, row, 1, 1)
                shortcuts.attach(action_cell, 1, row, 1, 1)
            overlay.add_overlay(shortcuts)
            overlay.set_measure_overlay(shortcuts, height == "auto")

            def toggle_shortcuts():
                shortcuts.set_visible(not shortcuts.get_visible())
                schedule_auto_height()

            scroller = Gtk.ScrolledWindow()
            scroller.set_vexpand(True)
            scroller.set_min_content_height(-1 if height == "auto" else 180)
            scroller.set_propagate_natural_height(height == "auto")
            if height == "auto":
                # Preserve height-for-width measurement for wrapped grid rows.
                scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            root.append(scroller)


            list_items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            grid_items = Gtk.FlowBox()
            grid_items.set_selection_mode(Gtk.SelectionMode.NONE)
            grid_items.set_homogeneous(True)
            grid_items.set_row_spacing(8)
            grid_items.set_column_spacing(8)
            grid_items.set_min_children_per_line(1)
            grid_items.set_max_children_per_line(100)
            entries = []
            retained: list[object] = []
            drag_active = False
            dismiss_after_drag = False
            clear_after_drag = False

            empty_state = Gtk.Label(label="No files")
            empty_state.set_hexpand(True)
            empty_state.set_vexpand(True)
            empty_state.set_halign(Gtk.Align.CENTER)
            empty_state.set_valign(Gtk.Align.CENTER)
            empty_state.set_visible(False)
            root.append(empty_state)


            def adjust_auto_height():
                if height != "auto":
                    return GLib.SOURCE_REMOVE
                scroller.set_max_content_height(-1)
                _minimum, natural, _minimum_baseline, _natural_baseline = window.measure(
                    Gtk.Orientation.VERTICAL, 460
                )
                _minimum, scroller_natural, _minimum_baseline, _natural_baseline = (
                    scroller.measure(
                        Gtk.Orientation.VERTICAL,
                        460 - root.get_margin_start() - root.get_margin_end(),
                    )
                )
                display = Gdk.Display.get_default()
                surface = window.get_surface()
                monitor = (
                    display.get_monitor_at_surface(surface)
                    if surface is not None
                    and hasattr(display, "get_monitor_at_surface")
                    else None
                )
                if monitor is None:
                    monitors = display.get_monitors()
                    monitor = monitors.get_item(0) if monitors.get_n_items() else None
                max_height = (
                    round(monitor.get_geometry().height * 0.9)
                    if monitor is not None
                    else 720
                )
                fixed_height = natural - scroller_natural
                if natural > max_height:
                    scroller.set_max_content_height(
                        max(1, max_height - fixed_height)
                    )
                else:
                    scroller.set_max_content_height(-1)
                window.set_default_size(460, -1)
                return GLib.SOURCE_REMOVE

            auto_height_pending = False

            def schedule_auto_height():
                nonlocal auto_height_pending
                if height == "auto" and not auto_height_pending:
                    auto_height_pending = True

                    def run_adjustment():
                        nonlocal auto_height_pending
                        auto_height_pending = False
                        return adjust_auto_height()

                    GLib.idle_add(run_adjustment)


            def clear_current_items():
                for entry in entries:
                    item = entry["item"]
                    old_parent = item.get_parent()
                    if old_parent is list_items:
                        list_items.remove(item)
                    elif old_parent is not None:
                        old_parent.set_child(None)
                        grid_items.remove(old_parent)
                entries.clear()
                retained.clear()
                scroller.set_visible(False)
                empty_state.set_visible(True)
                schedule_auto_height()


            def update_zoom():
                factor = current_zoom / 100
                decrease.set_sensitive(current_zoom > 75)
                increase.set_sensitive(current_zoom < 200)
                for entry in entries:
                    entry["icon"].set_pixel_size(round(20 * factor))
                    entry["grip"].set_pixel_size(round(16 * factor))
                    attributes = Pango.AttrList.new()
                    attributes.insert(Pango.attr_scale_new(factor))
                    entry["label"].set_attributes(attributes)
                schedule_auto_height()

            def change_zoom(step):
                nonlocal current_zoom
                current_zoom = min(200, max(75, current_zoom + step))
                update_zoom()


            def apply_layout():
                grid = self.layout == "grid"
                for entry in entries:
                    item = entry["item"]
                    old_parent = item.get_parent()
                    if old_parent is list_items:
                        list_items.remove(item)
                    elif old_parent is not None:
                        old_parent.set_child(None)
                        grid_items.remove(old_parent)
                    item.set_orientation(
                        Gtk.Orientation.VERTICAL if grid else Gtk.Orientation.HORIZONTAL
                    )
                    item.set_valign(Gtk.Align.START if grid else Gtk.Align.CENTER)
                    item.set_hexpand(True)
                    entry["label"].set_xalign(0.5 if grid else 0)
                    entry["label"].set_justify(
                        Gtk.Justification.CENTER if grid else Gtk.Justification.LEFT
                    )
                    entry["grip"].set_visible(not grid)
                    entry["grip"].set_child_visible(not grid)
                    if grid:
                        grid_items.append(item)
                    else:
                        list_items.append(item)
                scroller.set_child(grid_items if grid else list_items)
                scroller.set_visible(bool(entries))
                empty_state.set_visible(not entries)
                icon_name = "view-list-symbolic" if grid else "view-grid-symbolic"
                tooltip = "Show list view (V)" if grid else "Show grid view (V)"
                layout_button.set_child(Gtk.Image.new_from_icon_name(icon_name))
                layout_button.set_tooltip_text(tooltip)
                layout_button.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
                schedule_auto_height()


            def toggle_layout(_button):
                self.layout = "list" if self.layout == "grid" else "grid"
                apply_layout()

            layout_button.connect("clicked", toggle_layout)


            decrease.connect("clicked", lambda _button: change_zoom(-25))
            increase.connect("clicked", lambda _button: change_zoom(25))
            for path in paths:
                item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                item.set_cursor_from_name("grab")
                item.add_css_class("file-row")
                item.set_margin_top(3)
                item.set_margin_bottom(3)
                item.set_margin_start(4)
                item.set_margin_end(4)
                item.set_tooltip_text(_display(str(path)))
                item.set_accessible_role(Gtk.AccessibleRole.GROUP)

                content_type, _uncertain = Gio.content_type_guess(
                    filename=_display(path.name), data=None
                )
                icon = Gtk.Image.new_from_gicon(
                    Gio.content_type_get_icon(content_type)
                )
                item.append(icon)
                label = Gtk.Label(label=_display(path.name))
                label.set_ellipsize(Pango.EllipsizeMode.END)
                label.set_hexpand(True)
                item.append(label)
                grip = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
                grip.set_pixel_size(16)
                grip.set_tooltip_text("Drag file")
                grip.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
                item.append(grip)
                entries.append({"item": item, "icon": icon, "label": label, "grip": grip})

                source = Gtk.DragSource()
                source.set_actions(Gdk.DragAction.COPY)

                def prepare(_source, _x, _y, path=path):
                    snapshot = [path]
                    try:
                        provider = make_drag_provider(snapshot)
                    except (ValueError, OSError) as error:
                        status.set_text(_display(str(error)))
                        status.set_visible(True)
                        return None
                    status.set_text("")
                    status.set_visible(False)
                    retained[:] = [snapshot, provider]
                    return provider

                def drag_begin(_source, _drag):
                    nonlocal drag_active
                    drag_active = True

                def drag_end(_source, _drag, _delete_data):
                    nonlocal drag_active, dismiss_after_drag, clear_after_drag
                    drag_active = False
                    retained.clear()
                    if clear_after_drag:
                        clear_after_drag = False
                        clear_current_items()
                    if dismiss_after_drag:
                        dismiss_after_drag = False
                        GLib.idle_add(lambda: (window.close(), False)[1])

                source.connect("prepare", prepare)
                source.connect("drag-begin", drag_begin)
                source.connect("drag-end", drag_end)
                item.add_controller(source)

            apply_layout()
            update_zoom()
            schedule_auto_height()

            def close_requested(_window):
                nonlocal dismiss_after_drag
                if drag_active:
                    dismiss_after_drag = True
                    return True
                return False

            window.connect("close-request", close_requested)

            keys = Gtk.EventControllerKey()
            keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

            def key_pressed(_controller, keyval, _keycode, state):
                nonlocal dismiss_after_drag, clear_after_drag
                if keyval == Gdk.KEY_Escape:
                    if drag_active:
                        dismiss_after_drag = True
                        return False
                    window.close()
                    return True
                if state & (Gdk.ModifierType.CONTROL_MASK |
                            Gdk.ModifierType.ALT_MASK |
                            Gdk.ModifierType.SUPER_MASK |
                            Gdk.ModifierType.META_MASK):
                    return False
                if keyval in (Gdk.KEY_q, Gdk.KEY_Q):
                    if drag_active:
                        dismiss_after_drag = True
                        return False
                    window.close()
                    return True
                if keyval in (Gdk.KEY_v, Gdk.KEY_V):
                    toggle_layout(None)
                    return True
                if keyval in (Gdk.KEY_c, Gdk.KEY_C):
                    try:
                        SavedPaths().clear()
                    except (OSError, ValueError) as error:
                        status.set_text(_display(str(error)))
                    else:
                        status.set_text("Saved file list cleared")
                        if drag_active:
                            clear_after_drag = True
                        else:
                            clear_current_items()
                    status.set_visible(True)
                    return True
                if keyval == Gdk.KEY_question:
                    toggle_shortcuts()
                    return True
                if keyval in (Gdk.KEY_plus, Gdk.KEY_KP_Add, Gdk.KEY_equal):
                    change_zoom(25)
                    return True
                if keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                    change_zoom(-25)
                    return True
                return False

            keys.connect("key-pressed", key_pressed)
            window.add_controller(keys)
            if height != "auto":
                window.set_default_size(460, height)
            adjust_auto_height()
            window.present()

    application = FiledropApplication()
    return application.run([sys.argv[0]])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="filedrop",
        description="Select local files for desktop drag-and-drop.",
    )

    parser.add_argument(
        "--height",
        type=_parse_height,
        default=420,
        metavar="{auto|PIXELS}",
        help="window height in pixels or auto-fit content (default: 420)",
    )
    parser.add_argument("--layout", choices=("list", "grid"), default="list", help="file layout (default: list)")
    parser.add_argument("--zoom", type=int, default=100, metavar="PERCENT", help="initial text and icon size in percent (75-200; default: 100)")
    parser.add_argument("--mode", choices=("shell", "compact"), default="compact", help="popup window mode (default: compact)")
    parser.add_argument(
        "--decorate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="show native window decorations in compact mode (default)",
    )
    parser.add_argument("-0", "--null", action="store_true", dest="null_delimited", help="read NUL-separated paths from stdin")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--add", action="store_true", help="save supplied files for a later --load")
    operation.add_argument("--load", action="store_true", help="open saved files and any supplied files")
    operation.add_argument("--clear", action="store_true", help="clear saved file paths")
    parser.add_argument("files", nargs="*", help="existing file paths")
    try:
        args = parser.parse_args(argv)
        if not 75 <= args.zoom <= 200:
            parser.error("--zoom must be between 75 and 200")

        if args.clear:
            if args.files:
                parser.error("--clear does not accept file paths")
            SavedPaths().clear()
            return 0
        cwd = Path.cwd()
        piped = None
        if not sys.stdin.isatty():
            piped = sys.stdin.buffer.read()
        if args.load and not args.files and not piped:
            supplied = []
        else:
            supplied = parse_paths(args.files, piped, null_delimited=args.null_delimited, cwd=cwd)
            validate_paths(supplied)
        if args.add:
            SavedPaths().add(supplied)
            return 0
        if args.load:
            saved = SavedPaths().load()
            paths = parse_paths(
                [os.fspath(path) for path in saved] + [os.fspath(path) for path in supplied],
                None,
                null_delimited=args.null_delimited,
                cwd=cwd,
            )
            validate_paths(paths)
        else:
            paths = supplied
        return run_window(
            paths,
            mode=args.mode,
            layout=args.layout,
            decorate=args.decorate,
            zoom=args.zoom,
            height=args.height,
        )
    except ValueError as error:
        print(f"filedrop: {error}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as error:
        print(f"filedrop: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
