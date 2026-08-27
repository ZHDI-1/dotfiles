#!/usr/bin/env python3
"""CLI-level tests for compile-commands-edit.py.

All temporary files are created below this checkout so the suite does not
write elsewhere on the workstation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).absolute().parent
TOOL_NAME = "compile-commands-edit.py"
_configured_bin = os.environ.get("WORKSPACE_TOOLS_BIN")
if _configured_bin:
    TOOL = Path(_configured_bin).expanduser() / TOOL_NAME
elif (ROOT / TOOL_NAME).is_file():
    TOOL = ROOT / TOOL_NAME
else:
    TOOL = Path.home() / ".local" / "bin" / TOOL_NAME


class CompileCommandsEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix=".test-compile-commands-edit-", dir=str(ROOT)
        )
        self.work = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def write_database(self, entries, name="input.json") -> Path:
        path = self.work / name
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path

    def invoke(self, *arguments: object) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(TOOL)] + [str(item) for item in arguments]
        return subprocess.run(
            command,
            cwd=str(self.work),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def read_json(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def assert_success(self, completed: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(
            completed.returncode,
            0,
            "stdout:\n{}\nstderr:\n{}".format(completed.stdout, completed.stderr),
        )

    def test_explicit_maps_are_bounded_longest_and_non_cascading(self) -> None:
        old = self.work / "old"
        ordinary = self.work / "ordinary"
        special = self.work / "special"
        cascade = self.work / "must-not-cascade"
        output = self.work / "output.json"
        database = self.write_database(
            [
                {
                    "directory": str(old / "build"),
                    "file": str(old / "src" / "one.c"),
                    "arguments": [
                        "cc",
                        str(old / "src" / "one.c"),
                        str(old / "src2" / "not-matched.c"),
                        str(old / "other" / "two.c"),
                    ],
                    "unknown": {"keep": [1, True, None]},
                }
            ]
        )

        completed = self.invoke(
            database,
            "-o",
            output,
            "--map",
            old,
            ordinary,
            "--map",
            old / "src",
            special,
            "--map",
            ordinary,
            cascade,
        )
        self.assert_success(completed)
        edited = self.read_json(output)
        self.assertEqual(len(edited), 1)
        entry = edited[0]
        self.assertEqual(entry["directory"], str(ordinary / "build"))
        self.assertEqual(entry["file"], str(special / "one.c"))
        self.assertEqual(entry["arguments"][1], str(special / "one.c"))
        self.assertEqual(
            entry["arguments"][2], str(ordinary / "src2" / "not-matched.c")
        )
        self.assertEqual(entry["arguments"][3], str(ordinary / "other" / "two.c"))
        self.assertNotIn(str(cascade), json.dumps(edited))
        self.assertEqual(entry["unknown"], {"keep": [1, True, None]})
        self.assertEqual(self.read_json(database)[0]["directory"], str(old / "build"))

    def test_leading_shell_assignment_is_not_silently_requoted(self) -> None:
        database = self.write_database(
            [
                {
                    "directory": "/old",
                    "file": "a.c",
                    "command": "FLAGS='has spaces' gcc /old/a.c",
                }
            ]
        )
        output = self.work / "output.json"
        result = self.invoke(database, "--map", "/old", "/new", "-o", output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("shell assignment", result.stderr)
        self.assertFalse(output.exists())

    def test_conflicting_duplicate_sources_are_rejected_without_output(self) -> None:
        old = self.work / "old"
        database = self.write_database(
            [{"directory": str(old), "file": "a.c", "arguments": ["cc", "a.c"]}]
        )
        output = self.work / "output.json"
        completed = self.invoke(
            database,
            "-o",
            output,
            "--map",
            old,
            self.work / "new-a",
            "--map",
            old / ".",
            self.work / "new-b",
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("conflicting mappings", completed.stderr)
        self.assertFalse(output.exists())

    def test_path_flags_wp_response_prefix_map_and_macro_literals(self) -> None:
        old = self.work / "old"
        new = self.work / "new"
        directory = old / "build"
        source = old / "src" / "main.c"
        argv = [
            "cc",
            "-I" + str(old / "include"),
            "-isystem",
            str(old / "system"),
            "-iquote" + str(old / "quote"),
            "-idirafter",
            str(old / "after"),
            "-include",
            str(old / "config.h"),
            "-imacros" + str(old / "macros.h"),
            "-isysroot",
            str(old / "sdk"),
            "--sysroot=" + str(old / "sdk2"),
            "-o" + str(old / "out" / "main.o"),
            "-MF",
            str(old / "deps" / "main.d"),
            "@" + str(old / "response files" / "main.rsp"),
            "-Wp,-MMD," + str(old / "deps" / "wp.d"),
            "-ffile-prefix-map=" + str(old / "src") + "=/virtual/old/src",
            "-DROOT=" + str(old / "src"),
            "-D",
            str(old / "src" / "literal-not-a-path"),
            "-plugin-value=" + str(old / "unrelated"),
            str(source),
        ]
        database = self.write_database(
            [
                {
                    "directory": str(directory),
                    "file": str(source),
                    "output": str(old / "out" / "main.o"),
                    "arguments": argv,
                }
            ]
        )
        output = self.work / "output.json"
        completed = self.invoke(database, "-o", output, "--map", old, new)
        self.assert_success(completed)
        changed = self.read_json(output)[0]["arguments"]

        self.assertIn("-I" + str(new / "include"), changed)
        self.assertEqual(changed[changed.index("-isystem") + 1], str(new / "system"))
        self.assertIn("-iquote" + str(new / "quote"), changed)
        self.assertEqual(changed[changed.index("-idirafter") + 1], str(new / "after"))
        self.assertEqual(changed[changed.index("-include") + 1], str(new / "config.h"))
        self.assertIn("-imacros" + str(new / "macros.h"), changed)
        self.assertEqual(changed[changed.index("-isysroot") + 1], str(new / "sdk"))
        self.assertIn("--sysroot=" + str(new / "sdk2"), changed)
        self.assertIn("-o" + str(new / "out" / "main.o"), changed)
        self.assertEqual(
            changed[changed.index("-MF") + 1], str(new / "deps" / "main.d")
        )
        self.assertIn("@" + str(new / "response files" / "main.rsp"), changed)
        self.assertIn("-Wp,-MMD," + str(new / "deps" / "wp.d"), changed)
        self.assertIn(
            "-ffile-prefix-map=" + str(new / "src") + "=/virtual/old/src", changed
        )
        self.assertIn("-DROOT=" + str(old / "src"), changed)
        define_index = changed.index("-D")
        self.assertEqual(
            changed[define_index + 1], str(old / "src" / "literal-not-a-path")
        )
        self.assertIn("-plugin-value=" + str(old / "unrelated"), changed)
        self.assertEqual(changed[-1], str(new / "src" / "main.c"))

    def test_both_forms_are_rewritten_and_quotes_remain_semantically_equal(
        self,
    ) -> None:
        old = self.work / "old root"
        new = self.work / "new root"
        source = old / "source dir" / "a file.c"
        object_file = old / "object dir" / "a file.o"
        macro = '-DKBUILD_MODFILE="init/mounts"'
        command_argv = [
            "cc",
            "-I" + str(old / "include dir"),
            macro,
            "-c",
            str(source),
            "-o",
            str(object_file),
        ]
        command = " ".join(shlex.quote(token) for token in command_argv)
        arguments = ["clang", "-I", str(old / "other include"), str(source)]
        database = self.write_database(
            [
                {
                    "directory": str(old / "build"),
                    "file": str(source),
                    "arguments": arguments,
                    "command": command,
                }
            ]
        )
        output = self.work / "output.json"
        completed = self.invoke(database, "-o", output, "--map", old, new)
        self.assert_success(completed)
        entry = self.read_json(output)[0]

        rewritten_command = shlex.split(entry["command"], posix=True)
        self.assertEqual(rewritten_command[2], macro)
        self.assertEqual(rewritten_command[1], "-I" + str(new / "include dir"))
        self.assertEqual(rewritten_command[4], str(new / "source dir" / "a file.c"))
        self.assertEqual(rewritten_command[6], str(new / "object dir" / "a file.o"))
        self.assertEqual(entry["arguments"][2], str(new / "other include"))
        self.assertEqual(entry["arguments"][3], str(new / "source dir" / "a file.c"))
        self.assertIn("entries with both forms: 1", completed.stdout)

    def test_command_bytes_stay_unchanged_when_relative_argv_semantics_do(self) -> None:
        old = self.work / "old"
        new = self.work / "new"
        raw_command = (
            "cc  -I'./include dir' "
            "-DKBUILD_MODFILE='\"init/mounts\"' -c './src/a file.c'"
        )
        database = self.write_database(
            [
                {
                    "directory": str(old),
                    "file": "src/a file.c",
                    "command": raw_command,
                }
            ]
        )
        output = self.work / "output.json"
        completed = self.invoke(database, "-o", output, "--map", old, new)
        self.assert_success(completed)
        entry = self.read_json(output)[0]
        self.assertEqual(entry["command"], raw_command)
        self.assertEqual(entry["directory"], str(new))
        self.assertEqual(entry["file"], str(new / "src" / "a file.c"))

    def test_relative_out_of_tree_operands_follow_separate_mappings(self) -> None:
        old = self.work / "old"
        merged = self.work / "merged"
        original_directory = old / "build"
        database = self.write_database(
            [
                {
                    "directory": str(original_directory),
                    "file": "../source/unit.c",
                    "output": "objects/unit.o",
                    "arguments": [
                        "cc",
                        "-I../source/include",
                        "@../source/options.rsp",
                        "-o",
                        "objects/unit.o",
                        "../source/unit.c",
                    ],
                }
            ]
        )
        output = self.work / "output.json"
        completed = self.invoke(
            database,
            "-o",
            output,
            "--map",
            old / "build",
            merged / "build-tree",
            "--map",
            old / "source",
            merged / "external" / "source",
        )
        self.assert_success(completed)
        entry = self.read_json(output)[0]
        self.assertEqual(entry["directory"], str(merged / "build-tree"))
        self.assertEqual(entry["file"], str(merged / "external" / "source" / "unit.c"))
        self.assertEqual(
            entry["output"], str(merged / "build-tree" / "objects" / "unit.o")
        )
        self.assertIn("-I../external/source/include", entry["arguments"])
        self.assertIn("@../external/source/options.rsp", entry["arguments"])
        self.assertEqual(entry["arguments"][-1], "../external/source/unit.c")
        self.assertEqual(
            entry["arguments"][entry["arguments"].index("-o") + 1], "objects/unit.o"
        )

    def test_malformed_later_entry_does_not_write_or_backup(self) -> None:
        old = self.work / "old"
        database = self.write_database(
            [
                {"directory": str(old), "file": "ok.c", "arguments": ["cc", "ok.c"]},
                {"directory": str(old), "file": "bad.c", "arguments": ["cc", 7]},
            ]
        )
        output = self.work / "output.json"
        sentinel = b"existing output must survive\n"
        output.write_bytes(sentinel)
        completed = self.invoke(database, "-o", output, "--map", old, self.work / "new")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("arguments", completed.stderr)
        self.assertEqual(output.read_bytes(), sentinel)
        self.assertEqual(list(self.work.glob("output.json.bak.*")), [])
        self.assertEqual(list(self.work.glob(".output.json.*.tmp")), [])

    def test_existing_output_gets_unique_backup_beside_it(self) -> None:
        directory = self.work / "tree"
        database = self.write_database(
            [{"directory": str(directory), "file": "a.c", "arguments": ["cc", "a.c"]}]
        )
        output = self.work / "compile_commands.json"
        old_bytes = b"previous output\n"
        output.write_bytes(old_bytes)
        completed = self.invoke(database, "-o", output)
        self.assert_success(completed)
        backups = list(self.work.glob("compile_commands.json.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old_bytes)
        self.assertRegex(backups[0].name, r"\.bak\.\d{8}-\d{6}\.\d{6}Z\.[0-9a-f]{12}$")
        self.assertEqual(self.read_json(output)[0]["file"], str(directory / "a.c"))
        self.assertEqual(list(self.work.glob(".compile_commands.json.*.tmp")), [])

    def test_backup_dir_is_used_for_same_file_overwrite(self) -> None:
        database = self.write_database(
            [
                {
                    "directory": "relative-build",
                    "file": "a.c",
                    "arguments": ["cc", "a.c"],
                }
            ],
            name="compile_commands.json",
        )
        original = database.read_bytes()
        backups = self.work / "backups"
        completed = self.invoke(database, "-o", database, "--backup-dir", backups)
        self.assert_success(completed)
        backup_files = list(backups.glob("compile_commands.json.bak.*"))
        self.assertEqual(len(backup_files), 1)
        self.assertEqual(backup_files[0].read_bytes(), original)
        self.assertNotEqual(database.read_bytes(), original)
        self.assertEqual(
            self.read_json(database)[0]["directory"], str(self.work / "relative-build")
        )

    def test_symlink_and_non_regular_outputs_are_refused(self) -> None:
        database = self.write_database(
            [{"directory": str(self.work), "file": "a.c", "arguments": ["cc", "a.c"]}]
        )
        target = self.work / "target.json"
        target.write_text("do not touch", encoding="utf-8")
        link = self.work / "link.json"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("symlinks unavailable: {}".format(exc))
        linked = self.invoke(database, "-o", link)
        self.assertNotEqual(linked.returncode, 0)
        self.assertIn("symlink", linked.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "do not touch")

        directory_output = self.work / "directory-output"
        directory_output.mkdir()
        non_regular = self.invoke(database, "-o", directory_output)
        self.assertNotEqual(non_regular.returncode, 0)
        self.assertIn("non-regular", non_regular.stderr)

    def test_dry_run_never_changes_output_or_creates_backup_directory(self) -> None:
        old = self.work / "old"
        database = self.write_database(
            [{"directory": str(old), "file": "a.c", "arguments": ["cc", "a.c"]}]
        )
        original_input = database.read_bytes()
        output = self.work / "output.json"
        output.write_bytes(b"sentinel")
        backup_dir = self.work / "not-created"
        completed = self.invoke(
            database,
            "--dry-run",
            "-o",
            output,
            "--backup-dir",
            backup_dir,
            "--map",
            old,
            self.work / "new-does-not-exist",
        )
        self.assert_success(completed)
        self.assertEqual(database.read_bytes(), original_input)
        self.assertEqual(output.read_bytes(), b"sentinel")
        self.assertFalse(backup_dir.exists())
        self.assertIn("mode: dry-run", completed.stdout)

    def test_inspect_needs_no_output_and_reports_prefix_and_counts(self) -> None:
        root = self.work / "source-root"
        database = self.write_database(
            [
                {
                    "directory": str(root / "build"),
                    "file": "../src/a.c",
                    "arguments": ["cc", "../src/a.c"],
                },
                {
                    "directory": str(root / "build"),
                    "file": "../src/b.c",
                    "command": "cc ../src/b.c",
                },
            ]
        )
        completed = self.invoke(database, "--inspect")
        self.assert_success(completed)
        self.assertIn("detected common prefix: {}".format(root), completed.stdout)
        self.assertIn("entries: 2", completed.stdout)
        self.assertIn("arguments entries: 1", completed.stdout)
        self.assertIn("command entries: 1", completed.stdout)
        self.assertEqual(set(self.work.iterdir()), {database})

    def test_common_prefix_mapping_single_source_and_root_rejection(self) -> None:
        old = self.work / "one-root"
        merged = self.work / "merged"
        single = self.write_database(
            [
                {
                    "directory": str(old / "build"),
                    "file": str(old / "source" / "only.c"),
                    "arguments": ["cc", str(old / "source" / "only.c")],
                }
            ],
            name="single.json",
        )
        output = self.work / "single-output.json"
        completed = self.invoke(single, "-o", output, "--map-common-prefix", merged)
        self.assert_success(completed)
        entry = self.read_json(output)[0]
        self.assertEqual(entry["directory"], str(merged / "build"))
        self.assertEqual(entry["file"], str(merged / "source" / "only.c"))

        multiple = self.write_database(
            [
                {
                    "directory": "/alpha-root/build",
                    "file": "/alpha-root/a.c",
                    "arguments": ["cc", "/alpha-root/a.c"],
                },
                {
                    "directory": "/beta-root/build",
                    "file": "/beta-root/b.c",
                    "arguments": ["cc", "/beta-root/b.c"],
                },
            ],
            name="multiple.json",
        )
        refused_output = self.work / "multiple-output.json"
        refused = self.invoke(
            multiple,
            "-o",
            refused_output,
            "--map-common-prefix",
            merged,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("root '/'", refused.stderr)
        self.assertFalse(refused_output.exists())

        inspected = self.invoke(multiple, "--inspect")
        self.assert_success(inspected)
        self.assertIn("unsafe for automatic mapping", inspected.stdout)

    def test_optional_gcc_include_replaces_only_stale_builtin_paths(self) -> None:
        replacement = self.work / "host gcc" / "include"
        replacement.mkdir(parents=True)
        (replacement / "stdarg.h").write_text("/* usable */\n", encoding="utf-8")

        valid = self.work / "valid" / "lib" / "gcc" / "triple" / "1" / "include"
        valid.mkdir(parents=True)
        (valid / "stdarg.h").write_text("/* old but valid */\n", encoding="utf-8")
        stale = self.work / "missing" / "lib" / "gcc" / "triple" / "9" / "include"
        unrelated = self.work / "missing" / "includes"
        source = self.work / "src" / "a.c"
        command_argv = [
            "gcc",
            "-isystem",
            str(stale),
            "-isystem" + str(valid),
            "-isystem",
            str(unrelated),
            str(source),
        ]
        database = self.write_database(
            [
                {
                    "directory": str(self.work),
                    "file": str(source),
                    "arguments": command_argv,
                    "command": " ".join(shlex.quote(item) for item in command_argv),
                }
            ]
        )
        output = self.work / "output.json"
        completed = self.invoke(database, "-o", output, "--gcc-include", replacement)
        self.assert_success(completed)
        entry = self.read_json(output)[0]
        arguments = entry["arguments"]
        self.assertEqual(arguments[arguments.index("-isystem") + 1], str(replacement))
        self.assertIn("-isystem" + str(valid), arguments)
        unrelated_index = len(arguments) - 3
        self.assertEqual(arguments[unrelated_index], "-isystem")
        self.assertEqual(arguments[unrelated_index + 1], str(unrelated))
        self.assertEqual(shlex.split(entry["command"]).count(str(replacement)), 1)
        self.assertIn("stale GCC includes replaced: 2", completed.stdout)

        invalid_output = self.work / "invalid-output.json"
        invalid = self.invoke(
            database,
            "-o",
            invalid_output,
            "--gcc-include",
            self.work / "no-stdarg",
        )
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("stdarg.h", invalid.stderr)
        self.assertFalse(invalid_output.exists())

    def test_active_shell_syntax_is_rejected_without_execution(self) -> None:
        marker = self.work / "must-not-exist"
        database = self.write_database(
            [
                {
                    "directory": str(self.work),
                    "file": "a.c",
                    "command": "cc a.c && touch {}".format(shlex.quote(str(marker))),
                }
            ]
        )
        completed = self.invoke(database, "--dry-run")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("shell operator", completed.stderr)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
