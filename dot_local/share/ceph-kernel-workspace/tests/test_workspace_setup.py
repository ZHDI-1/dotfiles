#!/usr/bin/env python3
"""Unit tests; optional isolated real mounts with RUN_OVERLAY_TESTS=1.

WORKSPACE_TOOLS_BIN selects the scripts under test. OVERLAY_TEST_ROOT can place
throwaway fixtures on a particular filesystem. Native mounts need sudo access.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BIN = Path(os.environ.get("WORKSPACE_TOOLS_BIN", Path.home() / ".local/bin"))
SCRIPT = BIN / "setup-ceph-kernel-workspace.py"
spec = importlib.util.spec_from_file_location("workspace_setup", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def write(path, content=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def fixture(base):
    kernel, client, workspace = (
        base / name for name in ("linux", "company", "workspace")
    )
    for name in (
        "Makefile",
        "Kconfig",
        "kernel/core.c",
        "fs/ceph/inode.c",
        "include/linux/ceph/example.h",
    ):
        write(kernel / name, "kernel\n")
    for name in (
        "fs/ceph/inode.c",
        "net/ceph/messenger.c",
        "include/linux/ceph/example.h",
    ):
        write(client / "src" / name, "company\n")
    database = [
        {
            "directory": "/old/linux",
            "file": "/old/linux/kernel/core.c",
            "arguments": ["gcc", "-I./include", "-c", "kernel/core.c"],
        },
        {
            "directory": "/old/linux",
            "file": "/old/linux/fs/ceph/inode.c",
            "arguments": ["gcc", "-I/old/linux/include", "-c", "fs/ceph/inode.c"],
        },
    ]
    write(kernel / "compile_commands.json", json.dumps(database))
    return {
        "version": setup.STATE_VERSION,
        "backend": setup.BACKEND,
        "kernel": str(kernel),
        "client": str(client),
        "upper": str(client / "src"),
        "workspace": str(workspace),
        "merged": str(workspace / "merged"),
        "workdir": str(client / ".ceph-kernel-overlay-native-work"),
        "database": str(kernel / "compile_commands.json"),
        "source_prefix": None,
        "maps": [],
        "gcc_include": None,
        "clangd_config": None,
    }


def native_record(plan):
    return {
        "target": plan["merged"],
        "type": "overlay",
        "source": "overlay",
        "mount_options": "rw,nosuid,nodev",
        "id": "91",
        "device": "0:45",
        "root": "/",
        "boot_id": "boot-a",
        "namespace": "mnt:[100]",
        "super_options": (
            f"rw,lowerdir={plan['kernel']},upperdir={plan['upper']},"
            f"workdir={plan['workdir']}"
        ),
    }


def legacy_plan(plan):
    old = dict(plan, version=1)
    old.pop("backend", None)
    return old


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="overlay-setup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.plan = fixture(self.base)
        self.output = io.StringIO()

    def validate(self, previous=None, records=None):
        with (
            mock.patch.object(setup, "mount_records", return_value=records or []),
            mock.patch.object(setup.shutil, "which", return_value="/tool"),
        ):
            return setup.validate(self.plan, previous)

    def test_good_plan(self):
        self.assertIsNone(self.validate())

    def test_workspace_must_be_separate(self):
        self.plan["workspace"] = self.plan["kernel"] + "/workspace"
        self.plan["merged"] = self.plan["workspace"] + "/merged"
        with self.assertRaisesRegex(setup.SetupError, "separate"):
            self.validate()

    def test_nonempty_mountpoint_refused(self):
        write(Path(self.plan["merged"]) / "important", "keep")
        with self.assertRaisesRegex(setup.SetupError, "empty"):
            self.validate()

    def test_existing_mountpoint_symlink_refused(self):
        workspace = Path(self.plan["workspace"])
        workspace.mkdir()
        (workspace / "merged").symlink_to(self.plan["kernel"])
        with self.assertRaisesRegex(setup.SetupError, "symlinks"):
            self.validate()

    def test_upper_symlink_refused(self):
        upper = Path(self.plan["upper"])
        moved = upper.with_name("original-src")
        upper.rename(moved)
        upper.symlink_to(moved)
        with self.assertRaisesRegex(setup.SetupError, "real directory"):
            self.validate()

    def test_workdir_overlap_refused(self):
        self.plan["workdir"] = self.plan["upper"] + "/work"
        with self.assertRaisesRegex(setup.SetupError, "overlap"):
            self.validate()

    def test_unowned_nonempty_workdir_refused(self):
        write(Path(self.plan["workdir"]) / "precious", "keep")
        with self.assertRaisesRegex(setup.SetupError, "unowned"):
            self.validate()
        self.assertIsNone(self.validate(previous=self.plan))

    def test_different_layer_identity_refused(self):
        previous = dict(self.plan, kernel="/other/kernel")
        with self.assertRaisesRegex(setup.SetupError, "different overlay"):
            self.validate(previous)

    def test_unsafe_output_symlink_refused(self):
        target = Path(self.plan["upper"]) / "compile_commands.json"
        target.symlink_to(self.plan["database"])
        with self.assertRaisesRegex(setup.SetupError, "unsafe overlay output"):
            self.validate()

    def test_nonregular_output_refused(self):
        (Path(self.plan["upper"]) / "compile_commands.json").mkdir()
        with self.assertRaisesRegex(setup.SetupError, "unsafe overlay output"):
            self.validate()

    def test_input_cannot_be_upper_output(self):
        target = write(Path(self.plan["upper"]) / "compile_commands.json", "[]")
        self.plan["database"] = str(target)
        with self.assertRaisesRegex(setup.SetupError, "same file"):
            self.validate()

    def test_mount_identity(self):
        own = native_record(self.plan)
        self.plan["mounted"] = own
        self.assertEqual(self.validate(self.plan, [own]), own)
        with self.assertRaisesRegex(setup.SetupError, "unrecognized"):
            self.validate(None, [own])
        for field, value in (
            ("source", "foreign"),
            ("id", "92"),
            ("boot_id", "boot-b"),
            ("namespace", "mnt:[200]"),
            ("type", "fuse.fuse-overlayfs"),
            ("super_options", "rw,lowerdir=/foreign,upperdir=/other,workdir=/work"),
        ):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(setup.SetupError, "unrecognized"),
            ):
                self.validate(self.plan, [dict(own, **{field: value})])

    def test_same_upper_cannot_be_mounted_twice(self):
        other = dict(native_record(self.plan), target="/elsewhere")
        owner = dict(self.plan, merged="/elsewhere")
        write(setup.owner_path(self.plan), json.dumps(owner))
        with self.assertRaisesRegex(setup.SetupError, "already mounted"):
            self.validate(self.plan, [other])

    def test_nested_mount_refused(self):
        nested = {
            "target": self.plan["merged"] + "/nested",
            "type": "tmpfs",
            "source": "tmpfs",
        }
        with self.assertRaisesRegex(setup.SetupError, "nested mount"):
            self.validate(self.plan, [nested])

    def test_native_plan_uses_new_state_and_workdir(self):
        with mock.patch.object(setup, "setup") as mount:
            self.assertEqual(
                setup.main([
                    "mount", self.plan["kernel"], self.plan["client"],
                    self.plan["workspace"], "--dry-run",
                ]),
                0,
            )
        plan = mount.call_args.args[0]
        self.assertEqual(plan["version"], setup.STATE_VERSION)
        self.assertEqual(plan["backend"], "kernel-overlayfs")
        self.assertEqual(plan["workdir"], self.plan["workdir"])
        self.assertTrue(mount.call_args.args[1])

    def test_privilege_boundary(self):
        command = ["mount", "-t", "overlay"]
        with mock.patch.object(setup.os, "geteuid", return_value=0):
            self.assertEqual(setup.privileged_command(command), command)
        with (
            mock.patch.object(setup.os, "geteuid", return_value=501),
            mock.patch.object(setup.shutil, "which", return_value="/usr/bin/sudo"),
        ):
            self.assertEqual(
                setup.privileged_command(command), ["sudo", "-n", "--", *command]
            )
        with (
            mock.patch.object(setup.os, "geteuid", return_value=501),
            mock.patch.object(setup.shutil, "which", return_value=None),
            self.assertRaisesRegex(setup.SetupError, "sudo is required"),
        ):
            setup.privileged_command(command)

    def test_fuse_tools_no_longer_required(self):
        tools = {"mount": "/bin/mount", "umount": "/bin/umount", "sudo": "/bin/sudo"}
        with (
            mock.patch.object(setup, "mount_records", return_value=[]),
            mock.patch.object(setup.shutil, "which", side_effect=tools.get),
        ):
            self.assertIsNone(setup.validate(self.plan))

    def test_legacy_workspace_commands_leave_state_and_mount_untouched(self):
        old = legacy_plan(self.plan)
        old["mounted"] = dict(native_record(old), type="fuse.fuse-overlayfs")
        workspace = Path(old["workspace"])
        workspace.mkdir()
        setup.persist(old)
        state = setup.state_path(workspace).read_bytes()
        owner = setup.owner_path(old).read_bytes()
        for command in ("mount", "resume", "refresh", "unmount"):
            with (
                self.subTest(command=command),
                mock.patch.object(setup, "mount_records", return_value=[old["mounted"]]),
                mock.patch.object(setup, "run") as run,
                contextlib.redirect_stdout(self.output),
                contextlib.redirect_stderr(self.output),
            ):
                args = [command, str(workspace)]
                if command == "mount":
                    args = [command, old["kernel"], old["client"], str(workspace)]
                self.assertEqual(setup.main(args), 1)
                run.assert_not_called()
                self.assertIn("legacy FUSE", self.output.getvalue())
                self.assertEqual(setup.state_path(workspace).read_bytes(), state)
                self.assertEqual(setup.owner_path(old).read_bytes(), owner)
                self.assertFalse(Path(old["workdir"]).exists())
                self.assertFalse(
                    (Path(old["client"]) / ".ceph-kernel-overlay.lock").exists()
                )

    def test_legacy_upper_owner_refused_even_when_unmounted(self):
        owner = legacy_plan(dict(self.plan, merged="/old/workspace/merged"))
        write(setup.owner_path(self.plan), json.dumps(owner))
        with self.assertRaisesRegex(setup.SetupError, "legacy FUSE"):
            self.validate()

    def test_unknown_backend_refused(self):
        self.plan["backend"] = "another-overlay"
        with self.assertRaisesRegex(setup.SetupError, "unsupported overlay"):
            self.validate()

    def test_fuse_mount_never_adopted_or_unmounted(self):
        record = dict(native_record(self.plan), type="fuse.fuse-overlayfs")
        self.plan["mounted"] = record
        with self.assertRaisesRegex(setup.SetupError, "unrecognized"):
            self.validate(self.plan, [record])
        with (
            mock.patch.object(setup, "mount_at", return_value=record),
            mock.patch.object(setup, "run") as run,
            self.assertRaisesRegex(setup.SetupError, "not owned"),
        ):
            setup.unmount(self.plan)
        run.assert_not_called()

    def test_dry_run_does_not_create_directories(self):
        with (
            mock.patch.object(setup, "mount_records", return_value=[]),
            mock.patch.object(setup.shutil, "which", return_value="/tool"),
            mock.patch.object(setup, "run") as run,
            mock.patch.object(setup, "EDITOR", Path(self.plan["database"])),
            contextlib.redirect_stdout(self.output),
        ):
            setup.setup(self.plan, dry_run=True)
        self.assertFalse(Path(self.plan["workspace"]).exists())
        self.assertFalse(Path(self.plan["workdir"]).exists())
        self.assertIn("--dry-run", run.call_args.args[0])
        self.assertEqual(run.call_count, 1)

    def test_editor_command_options(self):
        self.plan.update(
            source_prefix="/old",
            maps=[["/sdk", "/new-sdk"]],
            gcc_include="/gcc/include",
        )
        with mock.patch.object(setup, "EDITOR", Path(self.plan["database"])):
            command = setup.editor_command(self.plan, True)
        self.assertNotIn("--map-common-prefix", command)
        self.assertEqual(command.count("--map"), 2)
        self.assertIn("--gcc-include", command)
        self.assertIn("--dry-run", command)

    def test_preflight_failure_never_mounts(self):
        with (
            mock.patch.object(setup, "validate", return_value=None),
            mock.patch.object(setup, "EDITOR", Path(self.plan["database"])),
            mock.patch.object(
                setup, "run", side_effect=setup.SetupError("bad database")
            ),
            contextlib.redirect_stdout(self.output),
        ):
            with self.assertRaisesRegex(setup.SetupError, "bad database"):
                setup.setup(self.plan)
        self.assertFalse(Path(self.plan["workspace"]).exists())
        self.assertFalse(Path(self.plan["workdir"]).exists())

    def test_generation_failure_unmounts_only_new_mount(self):
        record = native_record(self.plan)
        for current in (None, record):
            with (
                self.subTest(existing=bool(current)),
                mock.patch.object(setup, "validate", return_value=current),
                mock.patch.object(setup, "mount_at", return_value=record),
                mock.patch.object(setup, "EDITOR", Path(self.plan["database"])),
                mock.patch.object(setup, "unmount") as unmount,
                contextlib.redirect_stdout(self.output),
                contextlib.redirect_stderr(self.output),
            ):

                def execute(command, **kwargs):
                    if command[0] == sys.executable and "--dry-run" not in command:
                        raise setup.SetupError("output error")

                with mock.patch.object(setup, "run", side_effect=execute):
                    with self.assertRaisesRegex(setup.SetupError, "output error"):
                        setup.setup(self.plan)
                self.assertEqual(unmount.call_count, 0 if current else 1)
                self.assertTrue(setup.state_path(Path(self.plan["workspace"])).exists())

    def test_unexpected_overlay_layers_never_adopted_on_mount_failure(self):
        record = dict(native_record(self.plan), super_options="rw,lowerdir=/foreign")
        with (
            mock.patch.object(setup, "validate", return_value=None),
            mock.patch.object(setup, "mount_at", return_value=record),
            mock.patch.object(setup, "EDITOR", Path(self.plan["database"])),
            mock.patch.object(setup, "run"),
            mock.patch.object(setup, "unmount") as unmount,
            contextlib.redirect_stdout(self.output),
            self.assertRaisesRegex(setup.SetupError, "expected native overlay layers"),
        ):
            setup.setup(self.plan)
        unmount.assert_not_called()
        self.assertNotIn("mounted", setup.load_state(Path(self.plan["workspace"])))

    def test_busy_unmount_fails_without_force_or_lazy_flags(self):
        record = native_record(self.plan)
        self.plan["mounted"] = record
        with (
            mock.patch.object(setup, "mount_at", return_value=record),
            mock.patch.object(setup.os, "geteuid", return_value=0),
            mock.patch.object(setup, "run", side_effect=setup.SetupError("busy")) as run,
            self.assertRaisesRegex(setup.SetupError, "busy"),
        ):
            setup.unmount(self.plan)
        run.assert_called_once_with(["umount", "--", self.plan["merged"]], timeout=30)
        self.assertEqual(self.plan["mounted"], record)

    def test_foreign_mount_never_unmounted(self):
        record = {"target": self.plan["merged"], "source": "foreign", "type": "tmpfs"}
        with (
            mock.patch.object(setup, "mount_at", return_value=record),
            mock.patch.object(setup, "run") as run,
        ):
            with self.assertRaisesRegex(setup.SetupError, "not owned"):
                setup.unmount(self.plan)
            run.assert_not_called()

    def test_unmount_idempotent(self):
        with (
            mock.patch.object(setup, "mount_at", return_value=None),
            mock.patch.object(setup, "run") as run,
            contextlib.redirect_stdout(self.output),
        ):
            setup.unmount(self.plan)
            run.assert_not_called()

    def test_atomic_write_backup(self):
        target = write(self.base / "settings", "before")
        backup = self.base / "backups"
        setup.atomic_write(target, b"after", backup)
        self.assertEqual(target.read_bytes(), b"after")
        self.assertEqual(next(backup.iterdir()).read_bytes(), b"before")
        setup.atomic_write(target, b"after", backup)
        self.assertEqual(len(list(backup.iterdir())), 1)

    def test_atomic_write_refuses_symlink(self):
        original = write(self.base / "original", "before")
        target = self.base / "link"
        target.symlink_to(original)
        with self.assertRaisesRegex(setup.SetupError, "symlink"):
            setup.atomic_write(target, b"after")
        self.assertEqual(original.read_text(), "before")

    def test_state_roundtrip_and_relocation_refusal(self):
        workspace = Path(self.plan["workspace"])
        workspace.mkdir()
        path = setup.state_path(workspace)
        setup.atomic_write(path, json.dumps(self.plan).encode())
        self.assertEqual(setup.load_state(workspace), self.plan)
        bad = dict(self.plan, merged="/other/merged")
        path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(setup.SetupError, "different workspace"):
            setup.load_state(workspace)

    def test_mountinfo_escape_parsing(self):
        content = (
            "91 1 0:45 / /tmp/a\\040b rw - overlay overlay "
            "rw,lowerdir=/tmp/l\\040b,upperdir=/tmp/u,workdir=/tmp/w\n"
        )
        with mock.patch("builtins.open", mock.mock_open(read_data=content)):
            record = setup.mount_records()[0]
        self.assertEqual(record["target"], "/tmp/a b")
        self.assertEqual(record["source"], "overlay")
        self.assertIn("lowerdir=/tmp/l b", record["super_options"])


class ResumeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="overlay-resume-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.plan = fixture(self.base)
        self.workspace = Path(self.plan["workspace"])
        self.workspace.mkdir()
        self.database = write(
            Path(self.plan["upper"]) / "compile_commands.json", "[]\n"
        )
        self.clangd = write(
            Path(self.plan["upper"]) / ".clangd", "# keep editor config\n"
        )
        self.plan["clangd_config"] = str(
            write(self.base / "input.clangd", "# original\n")
        )
        self.plan["gcc_include"] = str(self.base / "gcc/include")
        write(Path(self.plan["gcc_include"]) / "stdarg.h")
        write(Path(self.plan["workdir"]) / "scratch", "retained")
        self.record = dict(
            native_record(self.plan), boot_id="new-boot", namespace="mnt:[200]"
        )
        self.plan["mounted"] = dict(
            self.record, boot_id="old-boot", namespace="mnt:[100]"
        )
        setup.persist(self.plan)
        self.before = self.generated_snapshot()
        self.records = []
        self.output = io.StringIO()
        patches = (
            mock.patch.object(setup, "mount_records", return_value=self.records),
            mock.patch.object(setup.shutil, "which", return_value="/tool"),
            mock.patch.object(setup.os, "geteuid", return_value=501),
            mock.patch.object(
                setup, "editor_command", side_effect=AssertionError("editor called")
            ),
            mock.patch.object(setup, "run", side_effect=self.execute),
        )
        for patch in patches:
            self.addCleanup(patch.stop)
            result = patch.start()
        self.run = result

    def execute(self, command, **kwargs):
        self.assertEqual(command[:3], ["sudo", "-n", "--"])
        if command[3] == "mount":
            self.records.append(self.record)
        elif command[3] == "umount":
            self.records.clear()
        else:
            self.fail(f"unexpected command during resume: {command}")

    def generated_snapshot(self):
        return {
            path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
            for path in (self.database, self.clangd)
        }

    def resume(self, *options):
        with (
            contextlib.redirect_stdout(self.output),
            contextlib.redirect_stderr(self.output),
        ):
            return setup.main(["resume", str(self.workspace), *options])

    def test_resume_after_reboot_preserves_files_and_records_new_identity(self):
        self.assertEqual(self.resume(), 0, self.output.getvalue())
        self.run.assert_called_once_with(
            [
                "sudo", "-n", "--", "mount", "-t", "overlay", "overlay", "-o",
                (
                    f"lowerdir={self.plan['kernel']},upperdir={self.plan['upper']},"
                    f"workdir={self.plan['workdir']},nosuid,nodev"
                ),
                "--", self.plan["merged"],
            ],
            timeout=30,
        )
        saved = setup.load_state(self.workspace)
        self.assertEqual(saved["mounted"], self.record)
        self.assertEqual(setup.load_owner(saved), saved)
        self.assertEqual(self.generated_snapshot(), self.before)
        self.assertFalse((self.workspace / "backups").exists())
        self.assertEqual(
            (Path(self.plan["workdir"]) / "scratch").read_text(), "retained"
        )
        with contextlib.redirect_stdout(self.output):
            self.assertEqual(setup.main(["unmount", str(self.workspace)]), 0)
        self.assertEqual(self.records, [])

    def test_resume_does_not_need_original_generation_inputs(self):
        Path(self.plan["database"]).unlink()
        Path(self.plan["clangd_config"]).unlink()
        (Path(self.plan["gcc_include"]) / "stdarg.h").unlink()
        with mock.patch.object(setup, "EDITOR", self.base / "missing-editor.py"):
            self.assertEqual(self.resume(), 0, self.output.getvalue())
        self.assertEqual(self.generated_snapshot(), self.before)

    def test_resume_already_mounted_does_not_remount(self):
        self.records.append(self.record)
        self.plan["mounted"] = self.record
        setup.persist(self.plan)
        self.assertEqual(self.resume(), 0, self.output.getvalue())
        self.run.assert_not_called()
        self.assertEqual(self.generated_snapshot(), self.before)

    def test_resume_dry_run_does_not_write_or_mount(self):
        state = setup.state_path(self.workspace).read_bytes()
        owner = setup.owner_path(self.plan).read_bytes()
        self.assertEqual(self.resume("--dry-run"), 0, self.output.getvalue())
        self.run.assert_not_called()
        self.assertEqual(setup.state_path(self.workspace).read_bytes(), state)
        self.assertEqual(setup.owner_path(self.plan).read_bytes(), owner)
        self.assertFalse(Path(self.plan["merged"]).exists())
        self.assertFalse(
            (Path(self.plan["client"]) / ".ceph-kernel-overlay.lock").exists()
        )
        self.assertEqual(self.generated_snapshot(), self.before)

    def test_resume_requires_saved_state(self):
        setup.state_path(self.workspace).unlink()
        self.assertEqual(self.resume(), 1)
        self.assertIn("use the mount command first", self.output.getvalue())
        self.run.assert_not_called()

    def test_resume_requires_generated_upper_database(self):
        self.database.unlink()  # The lower's input database is not a substitute.
        self.assertEqual(self.resume(), 1)
        self.assertIn("use mount to regenerate", self.output.getvalue())
        self.run.assert_not_called()

    def test_resume_refuses_unsafe_generated_database(self):
        self.database.unlink()
        for kind in ("symlink", "directory"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    self.database.symlink_to(self.plan["database"])
                else:
                    self.database.mkdir()
                self.assertEqual(self.resume(), 1)
                self.assertIn("unsafe overlay output", self.output.getvalue())
                self.run.assert_not_called()
                if kind == "symlink":
                    self.database.unlink()
                else:
                    self.database.rmdir()

    def test_resume_refuses_foreign_mount_even_with_reused_mount_id(self):
        self.records.append(self.record)  # Same ID, but saved state is from old boot.
        self.assertEqual(self.resume(), 1)
        self.assertIn("unrecognized existing mount", self.output.getvalue())
        self.run.assert_not_called()

    def test_resume_refuses_nonempty_mountpoint(self):
        write(Path(self.plan["merged"]) / "important", "keep")
        self.assertEqual(self.resume(), 1)
        self.assertIn("mountpoint must be empty", self.output.getvalue())
        self.run.assert_not_called()

    def test_readonly_mount_success_is_cleaned_up_without_generation(self):
        self.record["super_options"] = self.record["super_options"].replace("rw,", "ro,", 1)
        self.assertEqual(self.resume(), 1)
        self.assertIn("native OverlayFS mounted read-only", self.output.getvalue())
        self.assertEqual(self.records, [])
        self.assertEqual(self.run.call_count, 2)  # mount, then normal owned cleanup
        self.assertEqual(self.generated_snapshot(), self.before)

    def test_existing_readonly_mount_refused_without_unmounting(self):
        self.record["mount_options"] = "ro,nosuid,nodev"
        self.plan["mounted"] = self.record
        setup.persist(self.plan)
        self.records.append(self.record)
        state = setup.state_path(self.workspace).read_bytes()
        self.assertEqual(self.resume(), 1)
        self.assertIn("mounted read-only", self.output.getvalue())
        self.run.assert_not_called()
        self.assertEqual(self.records, [self.record])
        self.assertEqual(setup.state_path(self.workspace).read_bytes(), state)
        self.assertEqual(self.generated_snapshot(), self.before)

    def test_mount_denied_before_attachment_preserves_files(self):
        self.run.side_effect = setup.SetupError("permission denied")
        self.assertEqual(self.resume(), 1)
        self.assertIn("sudo -v", self.output.getvalue())
        self.assertEqual(self.records, [])
        self.assertEqual(self.run.call_count, 1)
        self.assertEqual(self.generated_snapshot(), self.before)
        self.assertNotIn("mounted", setup.load_state(self.workspace))

    def test_failed_resume_cleans_up_new_mount(self):
        def fail_after_mount(command, **kwargs):
            self.execute(command, **kwargs)
            if command[3] == "mount":
                raise setup.SetupError("mount failed after attaching")

        self.run.side_effect = fail_after_mount
        self.assertEqual(self.resume(), 1)
        self.assertIn("mount failed after attaching", self.output.getvalue())
        self.assertEqual(self.records, [])
        self.assertEqual(self.run.call_count, 2)
        self.assertEqual(self.generated_snapshot(), self.before)


@unittest.skipUnless(
    os.environ.get("RUN_OVERLAY_TESTS") == "1",
    "set RUN_OVERLAY_TESTS=1 for isolated real native OverlayFS tests",
)
class RealOverlayTests(unittest.TestCase):
    def test_mount_edit_refresh_unmount(self):
        root = os.environ.get("OVERLAY_TEST_ROOT")
        temporary = tempfile.TemporaryDirectory(
            prefix="ceph-overlay-live-test-", dir=root
        )
        base = Path(temporary.name).resolve()
        plan = fixture(base)
        workspace = Path(plan["workspace"])
        merged = Path(plan["merged"])
        upper = Path(plan["upper"])
        kernel = Path(plan["kernel"])
        before = {
            str(p.relative_to(kernel)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in kernel.rglob("*")
            if p.is_file()
        }
        command = [
            sys.executable,
            str(SCRIPT),
            "mount",
            plan["kernel"],
            plan["client"],
            plan["workspace"],
        ]
        try:
            subprocess.run(command + ["--dry-run"], check=True, timeout=120)
            self.assertFalse(workspace.exists())
            subprocess.run(command, check=True, timeout=120)
            self.assertTrue(os.path.ismount(merged))
            saved = setup.load_state(workspace)
            self.assertTrue(setup.is_ours(setup.mount_at(merged), saved))
            self.assertEqual(setup.mount_at(merged)["type"], "overlay")
            self.assertEqual((upper / "compile_commands.json").stat().st_uid, os.getuid())
            self.assertEqual(setup.state_path(workspace).stat().st_uid, os.getuid())
            self.assertEqual((merged / "fs/ceph/inode.c").read_text(), "company\n")
            self.assertEqual((merged / "kernel/core.c").read_text(), "kernel\n")
            write(merged / "fs/ceph/inode.c", "company edited\n")
            self.assertEqual(
                (upper / "fs/ceph/inode.c").read_text(), "company edited\n"
            )
            write(merged / "kernel/core.c", "kernel edited in upper\n")
            self.assertEqual((kernel / "kernel/core.c").read_text(), "kernel\n")
            self.assertEqual(
                (upper / "kernel/core.c").read_text(), "kernel edited in upper\n"
            )
            write(merged / "new-file", "new\n")
            self.assertTrue((upper / "new-file").is_file())
            self.assertEqual((upper / "kernel/core.c").stat().st_uid, os.getuid())
            # Native whiteouts must hide a lower file without changing the lower.
            (merged / "Kconfig").unlink()
            self.assertFalse((merged / "Kconfig").exists())
            self.assertEqual((kernel / "Kconfig").read_text(), "kernel\n")
            database = json.loads((merged / "compile_commands.json").read_text())
            self.assertTrue((upper / "compile_commands.json").is_file())
            self.assertTrue(all(e["directory"] == str(merged) for e in database))
            self.assertTrue(
                all(e["file"].startswith(str(merged) + "/") for e in database)
            )
            subprocess.run(
                [sys.executable, str(SCRIPT), "refresh", str(workspace)],
                check=True,
                timeout=120,
            )
            subprocess.run(
                [sys.executable, str(SCRIPT), "status", str(workspace)],
                check=True,
                timeout=30,
            )
            # Refuse a second editor view sharing the same company upper.
            result = subprocess.run(
                command[:-1] + [str(base / "second-workspace"), "--dry-run"],
                timeout=120,
            )
            self.assertNotEqual(result.returncode, 0)
            subprocess.run(
                [sys.executable, str(SCRIPT), "unmount", str(workspace)],
                check=True,
                timeout=30,
            )
            self.assertFalse(os.path.ismount(merged))
            # Resume reuses state/workdir and leaves generated files untouched.
            database_bytes = (upper / "compile_commands.json").read_bytes()
            database_stat = (upper / "compile_commands.json").stat()
            clangd = write(upper / ".clangd", "# retained across resume\n")
            clangd_stat = clangd.stat()
            backups = sorted((workspace / "backups").iterdir())
            for _ in range(2):  # Also idempotent while already mounted.
                subprocess.run(
                    [sys.executable, str(SCRIPT), "resume", str(workspace)],
                    check=True,
                    timeout=30,
                )
                self.assertTrue(os.path.ismount(merged))
                self.assertEqual(
                    (merged / "compile_commands.json").read_bytes(), database_bytes
                )
                resumed_stat = (upper / "compile_commands.json").stat()
                self.assertEqual(resumed_stat.st_mtime_ns, database_stat.st_mtime_ns)
                self.assertEqual(resumed_stat.st_ino, database_stat.st_ino)
                self.assertEqual(
                    (merged / ".clangd").read_text(), "# retained across resume\n"
                )
                self.assertEqual(clangd.stat().st_mtime_ns, clangd_stat.st_mtime_ns)
                self.assertEqual(sorted((workspace / "backups").iterdir()), backups)
            subprocess.run(
                [sys.executable, str(SCRIPT), "unmount", str(workspace)],
                check=True,
                timeout=30,
            )
            after = {
                str(p.relative_to(kernel)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in kernel.rglob("*")
                if p.is_file()
            }
            self.assertEqual(before, after)
        finally:
            if os.path.ismount(merged):
                try:
                    subprocess.run(
                        setup.privileged_command(["umount", "--", str(merged)]),
                        check=False, timeout=30,
                    )
                except subprocess.TimeoutExpired:
                    pass
            if not os.path.ismount(merged):
                # Kernel-private scratch children can be root-owned/mode 000.
                # Remove ONLY this disposable fixture's workdir, after unmount.
                try:
                    subprocess.run(
                        setup.privileged_command(["rm", "-rf", "--", plan["workdir"]]),
                        check=True, timeout=30,
                    )
                    temporary.cleanup()
                except BaseException:
                    temporary._finalizer.detach()
                    raise
            else:
                # Never recursively delete through a mount if cleanup fails.
                temporary._finalizer.detach()
                raise RuntimeError(
                    f"test mount remains at {merged}; manual unmount required"
                )


if __name__ == "__main__":
    unittest.main()
