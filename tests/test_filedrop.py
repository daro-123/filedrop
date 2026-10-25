from urllib.parse import quote
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import filedrop


class ParsePathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)

    def touch(self, name):
        path = self.cwd / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        return path

    def test_newline_records_preserve_special_names_and_order(self):
        paths = [self.touch("space name.txt"), self.touch("猫#%.txt")]
        result = filedrop.parse_paths([], b"space name.txt\n\xe7\x8c\xab#%.txt\n", null_delimited=False, cwd=self.cwd)
        self.assertEqual(result, paths)

    def test_arguments_precede_stdin_and_duplicate_spellings_collapse(self):
        first = self.touch("first")
        second = self.touch("second")
        result = filedrop.parse_paths(["first", "./first"], b"second\nfirst\n", null_delimited=False, cwd=self.cwd)
        self.assertEqual(result, [first, second])

    def test_nul_records_preserve_newlines_and_boundary_spaces(self):
        spaced = self.touch(" leading and trailing ")
        newline = self.touch("line\nbreak")
        result = filedrop.parse_paths([], b" leading and trailing \0line\nbreak\0", null_delimited=True, cwd=self.cwd)
        self.assertEqual(result, [spaced, newline])

    def test_empty_input_and_empty_records(self):
        with self.assertRaisesRegex(ValueError, "^no files supplied$"):
            filedrop.parse_paths([], None, null_delimited=False, cwd=self.cwd)
        with self.assertRaisesRegex(ValueError, "^no files supplied$"):
            filedrop.parse_paths([], b"\n\n", null_delimited=False, cwd=self.cwd)

    def test_embedded_nul_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "^path contains NUL$"):
            filedrop.parse_paths(["bad\0path"], None, null_delimited=False, cwd=self.cwd)

    def test_paths_are_lexically_absolute_without_expansion(self):
        self.touch("folder/file")
        literal_paths = ["~literal", "$HOME", "*.txt"]
        for name in literal_paths:
            self.touch(name)
        uri_path = self.touch("file:/uri")
        result = filedrop.parse_paths(
            [],
            b"folder/../folder/file\n~literal\n$HOME\n*.txt\nfile://uri\n",
            null_delimited=False,
            cwd=self.cwd,
        )
        self.assertEqual(
            result,
            [
                self.cwd / "folder/file",
                self.cwd / "~literal",
                self.cwd / "$HOME",
                self.cwd / "*.txt",
                uri_path,
            ],
        )

    def test_undecodable_filename_bytes_survive_transport(self):
        raw_name = b"undecodable-\xff"
        raw_path = os.fsencode(self.cwd) + b"/" + raw_name
        descriptor = os.open(raw_path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        result = filedrop.parse_paths(
            [], raw_name + b"\n", null_delimited=False, cwd=self.cwd
        )
        self.assertEqual(os.fsencode(result[0]), raw_path)
        filedrop.validate_paths(result)

    def test_validation_rejects_broken_symlink_and_special_file(self):
        broken = self.cwd / "broken"
        try:
            broken.symlink_to(self.cwd / "absent")
            fifo = self.cwd / "named-pipe"
            os.mkfifo(fifo)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"required filesystem object unavailable: {error}")
        for path in (broken, fifo):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "^not a regular file:"):
                    filedrop.validate_paths([path])

    def test_validation_rejects_entire_invalid_batch(self):
        valid = self.touch("valid")
        directory = self.cwd / "directory"
        directory.mkdir()
        missing = self.cwd / "missing"
        with self.assertRaisesRegex(ValueError, "^not a regular file: .+missing$"):
            filedrop.validate_paths([valid, missing])
        with self.assertRaisesRegex(ValueError, "^not a regular file: .+directory$"):
            filedrop.validate_paths([valid, directory])

    def test_symlink_to_regular_file_keeps_symlink_path(self):
        target = self.touch("target")
        link = self.cwd / "link"
        try:
            link.symlink_to(target)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        result = filedrop.parse_paths(
            [], b"link\n", null_delimited=False, cwd=self.cwd
        )
        self.assertEqual(result, [link])
        filedrop.validate_paths(result)


class SavedPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.queue_dir = self.runtime / f"filedrop-{os.getuid()}"
        self.queue = filedrop.SavedPaths(self.queue_dir)

    def touch(self, name):
        path = self.root / name
        path.touch()
        return path

    def test_add_deduplicates_in_first_seen_order_and_preserves_special_names(self):
        paths = [self.touch("first"), self.touch("line\nbreak"), self.touch("space name")]
        self.queue.add([paths[0], paths[1]])
        self.queue.add([paths[1], paths[2]])
        self.assertEqual(self.queue.load(), paths)

    def test_clear_removes_records_without_removing_source_files(self):
        source = self.touch("source")
        self.queue.add([source])
        self.queue.clear()
        self.assertEqual(self.queue.load(), [])
        self.assertTrue(source.is_file())

    def test_cli_add_rejects_invalid_batch_without_mutating_queue(self):
        valid = self.touch("valid")
        env = os.environ.copy()
        env["XDG_RUNTIME_DIR"] = str(self.runtime)
        result = subprocess.run(
            [sys.executable, str(CommandLineTests.ROOT / "filedrop.py"), "--add", str(valid), str(self.root / "missing")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.queue.load(), [])

    def test_cli_concurrent_adds_keep_every_record(self):
        paths = [self.touch(f"item-{index}") for index in range(8)]
        env = os.environ.copy()
        env["XDG_RUNTIME_DIR"] = str(self.runtime)
        processes = [
            subprocess.Popen(
                [sys.executable, str(CommandLineTests.ROOT / "filedrop.py"), "--add", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            for path in paths
        ]
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr.decode(errors="replace"))
        self.assertEqual(set(self.queue.load()), set(paths))


class SavedLoadTests(unittest.TestCase):
    def test_cli_load_merges_and_does_not_consume_saved_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir(mode=0o700)
            first, second = root / "first", root / "second"
            first.touch()
            second.touch()
            queue = filedrop.SavedPaths(runtime / f"filedrop-{os.getuid()}")
            queue.add([first])
            env = patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)})
            with env, patch.object(filedrop.sys, "stdin") as stdin, patch.object(filedrop, "run_window", return_value=0) as window:
                stdin.isatty.return_value = True
                self.assertEqual(filedrop.main(["--load", str(second)]), 0)
                self.assertEqual(filedrop.main(["--load"]), 0)
            self.assertEqual(window.call_args_list[0].args[0], [first, second])
            self.assertEqual(window.call_args_list[1].args[0], [first])
            self.assertEqual(queue.load(), [first])

    def test_clear_does_not_wait_for_stdin_eof(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir(mode=0o700)
            env = os.environ.copy()
            env["XDG_RUNTIME_DIR"] = str(runtime)
            process = subprocess.Popen(
                [sys.executable, str(CommandLineTests.ROOT / "filedrop.py"), "--clear"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            try:
                self.assertEqual(process.wait(timeout=5), 0)
            finally:
                if process.stdin:
                    process.stdin.close()


class CommandLineTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def run_script(self, *arguments, input_bytes=None, env=None):
        return subprocess.run(
            [sys.executable, str(self.ROOT / "filedrop.py"), *arguments],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )


    def test_default_invocation_does_not_access_saved_path_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.touch()
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(source / "missing")}):
                with patch.object(filedrop.sys, "stdin") as stdin, patch.object(
                    filedrop, "run_window", return_value=0
                ) as window:
                    stdin.isatty.return_value = True
                    self.assertEqual(filedrop.main([str(source)]), 0)


    def test_help_exits_without_starting_window(self):

        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn(b"--height {auto|PIXELS}", result.stdout)
        self.assertIn(b"--layout {list,grid}", result.stdout)

    def test_invalid_zoom_is_rejected_before_starting_window(self):
        for zoom in ("74", "201", "invalid"):
            with self.subTest(zoom=zoom):
                result = self.run_script("--zoom", zoom, "/etc/hosts")
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"--zoom", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)

    def test_invalid_height_is_rejected_before_starting_window(self):

        for height in ("0", "-1", "invalid"):
            with self.subTest(height=height):
                result = self.run_script("--height", height, "/etc/hosts")
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"--height", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)

    def test_run_window_rejects_invalid_height_before_loading_gtk(self):
        for height in (0, -1, True, "invalid"):
            with self.subTest(height=height):
                with self.assertRaisesRegex(ValueError, "^height must be"):
                    filedrop.run_window([], height=height)


    def test_invalid_mode_is_rejected_before_starting_window(self):
        result = self.run_script("--mode", "unknown", "/etc/hosts")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"invalid choice", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_invalid_layout_is_rejected_before_starting_window(self):
        result = self.run_script("--layout", "unknown", "/etc/hosts")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"invalid choice", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_compact_display_startup_failure_does_not_require_layer_shell(self):
        env = os.environ.copy()
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        result = self.run_script("--mode", "compact", "/etc/hosts", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"display", result.stderr.lower())
        self.assertNotIn(b"Layer Shell", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_missing_stdin_path_reports_error_without_window(self):
        result = self.run_script(input_bytes=b"/definitely/missing/filedrop-file\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"filedrop:", result.stderr)
        self.assertIn(b"/definitely/missing/filedrop-file", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_display_startup_failure_is_reported_without_traceback(self):
        env = os.environ.copy()
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        result = self.run_script("/etc/hosts", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"display", result.stderr.lower())
        self.assertNotIn(b"Traceback", result.stderr)




class DragProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi

            gi.require_version("Gio", "2.0")
            gi.require_version("Gdk", "4.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as error:
            raise unittest.SkipTest(f"PyGObject GTK dependencies unavailable: {error}")
        cls.Gio = Gio
        cls.GLib = GLib

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = [Path(self.temp.name) / "space #猫%.txt", Path(self.temp.name) / "second.txt"]
        for path in self.paths:
            path.write_bytes(b"provider fixture")

    def test_provider_exports_escaped_uri_list_and_original_locations(self):
        provider = filedrop.make_drag_provider(self.paths)
        stream = self.Gio.MemoryOutputStream.new_resizable()
        loop = self.GLib.MainLoop()
        outcome = {}

        def completed(source, result, _data=None):
            try:
                outcome["success"] = source.write_mime_type_finish(result)
            except Exception as error:
                outcome["error"] = error
            finally:
                loop.quit()

        provider.write_mime_type_async(
            "text/uri-list", stream, self.GLib.PRIORITY_DEFAULT, None, completed
        )

        def timed_out():
            outcome["timeout"] = True
            loop.quit()
            return False

        timeout_id = self.GLib.timeout_add_seconds(5, timed_out)
        loop.run()
        if not outcome.get("timeout"):
            self.GLib.source_remove(timeout_id)
        self.assertNotIn("timeout", outcome, "URI provider operation timed out")
        self.assertNotIn("error", outcome, outcome.get("error"))
        self.assertTrue(outcome.get("success"), "URI provider operation failed")
        self.assertTrue(stream.close(None))
        payload = bytes(stream.steal_as_bytes().get_data())
        expected_uris = [
            ("file://" + quote(os.fsdecode(path), safe="/")).encode("ascii")
            for path in self.paths
        ]
        expected = b"\r\n".join(expected_uris) + b"\r\n"
        self.assertEqual(payload, expected)
        recovered = [
            self.Gio.File.new_for_uri(uri.decode("ascii")).get_path()
            for uri in payload.split(b"\r\n")
            if uri
        ]
        self.assertEqual(recovered, [os.fsdecode(path) for path in self.paths])

    def test_deletion_after_validation_rejects_whole_batch(self):
        self.paths[1].unlink()
        with self.assertRaisesRegex(ValueError, "^not a regular file:"):
            filedrop.make_drag_provider(self.paths)

    def test_empty_provider_batch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "^no files selected$"):
            filedrop.make_drag_provider([])


if __name__ == "__main__":
    unittest.main()
