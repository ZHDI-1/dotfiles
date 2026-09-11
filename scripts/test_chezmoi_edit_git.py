#!/usr/bin/env python3
"""Linux/macOS process tests and integration tests using only disposable repos."""

from __future__ import annotations

import ctypes
import errno
import importlib.util
import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import tomllib

HERE = Path(__file__).resolve().parent
HELPER = HERE / "chezmoi-edit-git.py"
CONFIG_TEMPLATE = HERE.parent / ".chezmoi.toml.tmpl"
CHEZMOI = shutil.which("chezmoi")
SPEC = importlib.util.spec_from_file_location("chezmoi_edit_git", HELPER)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def isolated_env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": os.fspath(home),
            "XDG_CONFIG_HOME": os.fspath(home / ".config"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "LC_ALL": "C",
            "VISUAL": "",
            "PYTHONUNBUFFERED": "1",
        }
    )
    if extra:
        env.update(extra)
    return env


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {command!r}\n"
            f"stdout={result.stdout.decode(errors='replace')}\n"
            f"stderr={result.stderr.decode(errors='replace')}"
        )
    return result


class PtyChild:
    def __init__(self, command: list[str], cwd: Path, env: dict[str, str]):
        pid, descriptor = pty.fork()
        if pid == 0:
            os.chdir(cwd)
            os.execve(command[0], command, env)
        self.pid = pid
        self.descriptor = descriptor
        self.output = bytearray()
        self.status: int | None = None

    def send(self, data: bytes) -> None:
        os.write(self.descriptor, data)

    def _pump(self, timeout: float = 0.1) -> None:
        if self.status is not None:
            return
        readable, _, _ = select.select([self.descriptor], [], [], timeout)
        if readable:
            try:
                data = os.read(self.descriptor, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                data = b""
            self.output.extend(data)
        pid, status = os.waitpid(self.pid, os.WNOHANG)
        if pid:
            self.status = status

    def wait_for(self, marker: bytes, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while marker not in self.output:
            if self.status is not None:
                raise AssertionError(
                    f"child exited before marker {marker!r}: {self.text}"
                )
            if time.monotonic() >= deadline:
                self.kill()
                raise AssertionError(f"timed out waiting for {marker!r}: {self.text}")
            self._pump()

    def wait_until(self, condition, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while not condition():
            if self.status is not None:
                raise AssertionError(f"child exited while waiting: {self.text}")
            if time.monotonic() >= deadline:
                self.kill()
                raise AssertionError(f"timed out waiting for child condition: {self.text}")
            self._pump()

    def finish(self, timeout: float = 15.0) -> tuple[int, str]:
        deadline = time.monotonic() + timeout
        while self.status is None:
            if time.monotonic() >= deadline:
                self.kill()
                raise AssertionError(f"child timed out: {self.text}")
            self._pump()
        while True:
            readable, _, _ = select.select([self.descriptor], [], [], 0)
            if not readable:
                break
            try:
                data = os.read(self.descriptor, 65536)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not data:
                break
            self.output.extend(data)
        os.close(self.descriptor)
        return os.waitstatus_to_exitcode(self.status), self.text

    def kill(self) -> None:
        if self.status is None:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _, self.status = os.waitpid(self.pid, 0)

    @property
    def text(self) -> str:
        return self.output.decode(errors="replace").replace("\r\n", "\n")


class ProcessInspectionTests(unittest.TestCase):
    @staticmethod
    def procargs(argv: list[bytes]) -> bytes:
        argc = len(argv).to_bytes(ctypes.sizeof(ctypes.c_int), sys.byteorder, signed=True)
        return argc + b"/opt/homebrew/bin/chezmoi\0\0\0" + b"\0".join(argv) + b"\0"

    def test_darwin_procargs_preserves_boundaries_and_ignores_environment(self) -> None:
        argv = [b"chezmoi", b"edit", b"", b"name with space", b"a'\"b", b"line\nbreak", b"\xff", b""]
        data = self.procargs(argv) + b"HOME=/Users/test\0--force\0"
        decoded = helper.parse_darwin_procargs(data)
        self.assertEqual(decoded, [os.fsdecode(arg) for arg in argv])
        self.assertEqual(helper.edit_targets(decoded), decoded[2:])
        self.assertFalse(helper._long_flag_is_true(decoded, "", "--force"))

    def test_darwin_procargs_rejects_malformed_or_truncated_data(self) -> None:
        for data in (
            b"", b"\0", self.procargs([]),
            (-1).to_bytes(ctypes.sizeof(ctypes.c_int), sys.byteorder, signed=True),
            self.procargs([b"chezmoi", b"edit"])[:-1],
            (2).to_bytes(ctypes.sizeof(ctypes.c_int), sys.byteorder) + b"unterminated",
        ):
            with self.subTest(data=data):
                self.assertIsNone(helper.parse_darwin_procargs(data))

    def test_darwin_command_argv_uses_native_sysctl(self) -> None:
        argv = [b"chezmoi", b"edit", b"/Users/test/.name with space"]
        responses = [
            (262144).to_bytes(ctypes.sizeof(ctypes.c_int), sys.byteorder),
            self.procargs(argv) + b"HOME=/Users/test\0",
        ]
        library = mock.Mock()

        def sysctl(names, count, buffer, size_pointer, new_value, new_size):
            mib = tuple(names)
            self.assertEqual(count, len(mib))
            self.assertIsNone(new_value)
            self.assertEqual(new_size, 0)
            self.assertEqual(mib, (1, 8) if len(responses) == 2 else (1, 49, 123))
            data = responses.pop(0)
            capacity = ctypes.cast(size_pointer, ctypes.POINTER(ctypes.c_size_t))
            self.assertGreaterEqual(capacity.contents.value, len(data))
            ctypes.memmove(buffer, data, len(data))
            capacity.contents.value = len(data)
            return 0

        library.sysctl.side_effect = sysctl
        with mock.patch.object(helper.sys, "platform", "darwin"), \
             mock.patch.object(helper.os, "getppid", return_value=123), \
             mock.patch.object(helper.ctypes, "CDLL", return_value=library):
            self.assertEqual(helper.command_argv({}), [os.fsdecode(arg) for arg in argv])
        self.assertEqual(library.sysctl.call_count, 2)

    def test_darwin_argument_lookup_fails_closed(self) -> None:
        argmax = (262144).to_bytes(ctypes.sizeof(ctypes.c_int), sys.byteorder)
        for responses in ([None], [b""], [b"\0" * 4], [argmax, None], [argmax, b"bad"]):
            with self.subTest(responses=responses), \
                 mock.patch.object(helper.sys, "platform", "darwin"), \
                 mock.patch.object(helper, "darwin_sysctl", side_effect=responses):
                self.assertIsNone(helper.command_argv({"CHEZMOI_ARGS": "chezmoi edit 'a b'"}))

    def test_darwin_process_identity_includes_microseconds(self) -> None:
        library = mock.Mock()

        def proc_pidinfo(pid, flavor, argument, buffer, size):
            self.assertEqual((pid, flavor, argument, size), (123, 3, 0, 136))
            info = ctypes.cast(buffer, ctypes.POINTER(helper.DarwinProcBsdInfo)).contents
            info.pbi_pid = pid
            info.pbi_start_tvsec = 1700000000
            info.pbi_start_tvusec = 42
            return size

        library.proc_pidinfo.side_effect = proc_pidinfo
        with mock.patch.object(helper.sys, "platform", "darwin"), \
             mock.patch.object(helper.ctypes, "CDLL", return_value=library), \
             mock.patch.object(helper.os, "kill"):
            self.assertEqual(helper.process_start_time(123), "1700000000.000042")
            self.assertTrue(helper.process_is_same(123, "1700000000.000042"))
            self.assertFalse(helper.process_is_same(123, "1700000000.000043"))
            library.proc_pidinfo.side_effect = None
            for result in (0, -1, 135, 136):
                # Even a full-sized response with the wrong PID is rejected.
                library.proc_pidinfo.return_value = result
                self.assertIsNone(helper.process_start_time(123))

    def test_darwin_native_api_failures_are_unavailable(self) -> None:
        library = mock.Mock()
        library.sysctl.return_value = -1
        with mock.patch.object(helper.sys, "platform", "darwin"), \
             mock.patch.object(helper.ctypes, "CDLL", return_value=library):
            self.assertIsNone(helper.command_argv({}))
        for error in (OSError("not available"), AttributeError("missing symbol")):
            with self.subTest(error=error), \
                 mock.patch.object(helper.sys, "platform", "darwin"), \
                 mock.patch.object(helper.ctypes, "CDLL", side_effect=error):
                self.assertIsNone(helper.command_argv({}))
                self.assertIsNone(helper.process_start_time(123))

    @unittest.skipUnless(sys.platform in {"linux", "darwin"}, "requires Linux or macOS")
    def test_native_parent_argv_preserves_exact_arguments(self) -> None:
        probe = (
            "import json, runpy, sys; "
            "helper = runpy.run_path(sys.argv[1]); "
            "print(json.dumps(helper['command_argv']({})))"
        )
        parent = (
            "import subprocess, sys; "
            f"subprocess.run([sys.executable, '-c', {probe!r}, sys.argv[1]], check=True)"
        )
        command = [
            sys.executable, "-c", parent, os.fspath(HELPER), "edit",
            "a b", "a'\"b", "line\nbreak", "", "--force=false", "",
        ]
        self.assertEqual(json.loads(run(command).stdout), command)

    @unittest.skipUnless(sys.platform in {"linux", "darwin"}, "requires Linux or macOS")
    def test_native_process_identity_is_available_and_stable(self) -> None:
        pid = os.getpid()
        start = helper.process_start_time(pid)
        self.assertIsNotNone(start)
        self.assertEqual(helper.process_start_time(pid), start)
        self.assertTrue(helper.process_is_same(pid, start))
        self.assertFalse(helper.process_is_same(pid, "different start time"))

    def test_missing_exact_argv_skips_hooks_instead_of_guessing(self) -> None:
        for mode in ("pre", "post"):
            with self.subTest(mode=mode), \
                 mock.patch.object(helper.sys, "argv", [os.fspath(HELPER), mode]), \
                 mock.patch.object(helper, "command_argv", return_value=None), \
                 mock.patch.object(helper, "invocation_is_interactive", return_value=True), \
                 mock.patch.object(helper, "pre_hook") as pre, \
                 mock.patch.object(helper, "post_hook") as post, \
                 mock.patch.object(helper, "eprint"):
                self.assertEqual(helper.main(), 0)
                pre.assert_not_called()
                post.assert_not_called()


class Sandbox:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chezmoi-edit-git-test-")
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "source"
        self.home = self.root / "home"
        self.remote = self.root / "origin.git"
        self.repo.mkdir()
        self.home.mkdir()
        self.env = isolated_env(self.home)
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        files = {
            "dot_alpha": "alpha 0\n",
            "dot_beta": "beta 0\n",
            "dot_gamma": "gamma 0\n",
            "dot_template.tmpl": "template 0\n",
            "dot_name with space": "space 0\n",
        }
        for relative, content in files.items():
            (self.repo / relative).write_text(content)
        self.git("add", "--", *files)
        self.git("commit", "-q", "-m", "base commit")
        run(
            ["git", "init", "-q", "--bare", "--initial-branch=main", os.fspath(self.remote)],
            env=self.env,
        )
        self.git("remote", "add", "origin", os.fspath(self.remote))
        self.git("push", "-q", "-u", "origin", "main")
        self._write_editors()
        self.config = self.root / "chezmoi.toml"
        self.config.write_text(
            f"""sourceDir = {json.dumps(os.fspath(self.repo))}
[git]
    autoAdd = false
    autoCommit = false
    autoPush = false
[hooks.edit.pre]
    command = "python3"
    args = [{json.dumps(os.fspath(HELPER))}, "pre"]
[hooks.edit.post]
    command = "python3"
    args = [{json.dumps(os.fspath(HELPER))}, "post"]
"""
        )
        for source_name, destination_name in {
            "dot_alpha": ".alpha",
            "dot_beta": ".beta",
            "dot_gamma": ".gamma",
            "dot_template.tmpl": ".template",
            "dot_name with space": ".name with space",
        }.items():
            (self.home / destination_name).write_text((self.repo / source_name).read_text())

    def close(self) -> None:
        self.temporary.cleanup()

    def _write_editors(self) -> None:
        self.source_editor = self.root / "source-editor.py"
        self.source_editor.write_text(
            """#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import time

mode = os.environ.get("SOURCE_EDITOR_MODE", "append")
if mode == "fail":
    raise SystemExit(7)
if mode == "block":
    Path(os.environ["EDITOR_READY"]).write_text("ready")
    release = Path(os.environ["EDITOR_RELEASE"])
    while not release.exists():
        time.sleep(0.02)
if mode != "noop":
    addition = os.environ.get("SOURCE_EDITOR_APPEND", "edited\\n")
    for argument in os.sys.argv[1:]:
        with open(argument, "a") as file:
            file.write(addition)
action = os.environ.get("SOURCE_EDITOR_GIT_ACTION")
repo = os.environ.get("TEST_SOURCE_REPO")
env = os.environ.copy()
if action == "head":
    subprocess.run(["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", "racing head"], env=env, check=True)
elif action == "index":
    Path(repo, "dot_beta").write_text("racing index\\n")
    subprocess.run(["git", "-C", repo, "add", "--", "dot_beta"], env=env, check=True)
"""
        )
        self.message_editor = self.root / "message-editor.py"
        self.message_editor.write_text(
            """#!/usr/bin/env python3
import os
from pathlib import Path
import sys
Path(sys.argv[1]).write_text(os.environ["EDITED_COMMIT_MESSAGE"] + "\\n")
"""
        )
        self.source_editor.chmod(0o755)
        self.message_editor.chmod(0o755)

    def git(self, *args: str, input: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return run(
            ["git", "-C", os.fspath(self.repo), *args],
            env=self.env,
            input=input,
            check=check,
        )

    def git_text(self, *args: str) -> str:
        return self.git(*args).stdout.decode(errors="surrogateescape").rstrip("\n")

    def command(self, *edit_args: str) -> list[str]:
        return [
            os.fspath(CHEZMOI),
            "--config",
            os.fspath(self.config),
            "--source",
            os.fspath(self.repo),
            "--destination",
            os.fspath(self.home),
            *edit_args,
        ]

    def child(self, *edit_args: str, extra_env: dict[str, str] | None = None) -> PtyChild:
        env = self.env.copy()
        env.update(
            {
                "EDITOR": os.fspath(self.source_editor),
                "GIT_EDITOR": os.fspath(self.message_editor),
                "TEST_SOURCE_REPO": os.fspath(self.repo),
            }
        )
        if extra_env:
            env.update(extra_env)
        return PtyChild(self.command(*edit_args), self.home, env)

    def interactive(
        self,
        *edit_args: str,
        input: bytes = b"",
        extra_env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        child = self.child(*edit_args, extra_env=extra_env)
        if input:
            child.send(input)
        return child.finish()

    def head(self) -> str:
        return self.git_text("rev-parse", "HEAD")

    def state_path(self) -> Path:
        return self.repo / ".git" / "chezmoi-edit-git.state.json"


class ChezmoiEditGitTests(unittest.TestCase):
    def setUp(self) -> None:
        if CHEZMOI is None:
            self.skipTest("chezmoi is required on PATH")
        self.box = Sandbox()

    def tearDown(self) -> None:
        self.box.close()

    def test_new_commit_limits_paths_and_preserves_unrelated_changes(self) -> None:
        (self.box.repo / "dot_beta").write_text("beta staged\n")
        self.box.git("add", "--", "dot_beta")
        staged_entry = self.box.git_text("ls-files", "--stage", "--", "dot_beta")
        (self.box.repo / "dot_gamma").write_text("gamma unstaged\n")

        rc, output = self.box.interactive(
            "edit",
            os.fspath(self.box.home / ".template"),
            os.fspath(self.box.home / ".name with space"),
            input=b"focused source edit\n\n",
        )

        self.assertEqual(rc, 0, output)
        self.assertEqual(self.box.git_text("log", "-1", "--format=%s"), "focused source edit")
        committed = set(
            self.box.git_text("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
        )
        self.assertEqual(committed, {"dot_template.tmpl", "dot_name with space"})
        self.assertEqual(self.box.git_text("ls-files", "--stage", "--", "dot_beta"), staged_entry)
        self.assertEqual(self.box.git_text("diff", "--cached", "--name-only"), "dot_beta")
        self.assertEqual(self.box.git_text("diff", "--name-only"), "dot_gamma")
        self.assertIn("Changed by chezmoi edit:", output)
        self.assertIn("dot_template.tmpl", output)
        self.assertIn("'dot_name with space'", output)
        self.assertIn("Previous commit:", output)
        self.assertFalse(self.box.state_path().exists())

    def test_amend_keep_message(self) -> None:
        original = self.box.head()
        (self.box.repo / "dot_beta").write_text("beta staged\n")
        self.box.git("add", "--", "dot_beta")
        staged_entry = self.box.git_text("ls-files", "--stage", "--", "dot_beta")
        (self.box.repo / "dot_gamma").write_text("gamma unstaged\n")
        rc, output = self.box.interactive(
            "edit", os.fspath(self.box.home / ".alpha"), input=b":s\n\n"
        )
        self.assertEqual(rc, 0, output)
        self.assertNotEqual(self.box.head(), original)
        self.assertEqual(self.box.git_text("rev-list", "--count", "HEAD"), "1")
        self.assertEqual(self.box.git_text("log", "-1", "--format=%s"), "base commit")
        self.assertEqual(self.box.git_text("ls-files", "--stage", "--", "dot_beta"), staged_entry)
        self.assertEqual(self.box.git_text("diff", "--cached", "--name-only"), "dot_beta")
        self.assertEqual(self.box.git_text("diff", "--name-only"), "dot_gamma")
        self.assertIn("history rewrite", output)
        self.assertIn("Push REWRITE with explicit force-with-lease?", output)

    def test_amend_and_edit_message(self) -> None:
        rc, output = self.box.interactive(
            "edit",
            os.fspath(self.box.home / ".alpha"),
            input=b":sm\n\n",
            extra_env={"EDITED_COMMIT_MESSAGE": "reworded base"},
        )
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.box.git_text("rev-list", "--count", "HEAD"), "1")
        self.assertEqual(self.box.git_text("log", "-1", "--format=%s"), "reworded base")

    def test_diff_then_skip_and_noop_do_not_commit(self) -> None:
        original = self.box.head()
        index_before = (self.box.repo / ".git" / "index").read_bytes()
        rc, output = self.box.interactive(
            "edit", os.fspath(self.box.home / ".alpha"), input=b":d\n\n"
        )
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.box.head(), original)
        self.assertEqual((self.box.repo / ".git" / "index").read_bytes(), index_before)
        self.assertIn("diff --git a/dot_alpha b/dot_alpha", output)
        self.assertIn("edited", output)
        self.assertIn("Edits left uncommitted.", output)
        self.assertEqual(self.box.git_text("diff", "--name-only"), "dot_alpha")

        self.box.git("checkout", "-q", "--", "dot_alpha")
        rc, output = self.box.interactive(
            "edit",
            os.fspath(self.box.home / ".alpha"),
            extra_env={"SOURCE_EDITOR_MODE": "noop"},
        )
        self.assertEqual(rc, 0, output)
        self.assertNotIn("Commit (message", output)
        self.assertEqual(self.box.head(), original)

    def test_predirty_edited_path_is_refused_before_editor(self) -> None:
        original = self.box.head()
        (self.box.repo / "dot_alpha").write_text("already dirty\n")
        rc, output = self.box.interactive("edit", os.fspath(self.box.home / ".alpha"))
        self.assertNotEqual(rc, 0)
        self.assertIn("already dirty", (self.box.repo / "dot_alpha").read_text())
        self.assertNotIn("edited", (self.box.repo / "dot_alpha").read_text())
        self.assertIn("refusing ambiguous ownership", output)
        self.assertEqual(self.box.head(), original)

    def test_template_source_path_and_apply_remain_independent(self) -> None:
        original = self.box.head()
        rc, output = self.box.interactive(
            "edit",
            os.fspath(self.box.home / ".template"),
            "--apply",
            input=b"\n",
        )
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.box.head(), original)
        self.assertIn("edited", (self.box.repo / "dot_template.tmpl").read_text())
        self.assertIn("edited", (self.box.home / ".template").read_text())

    def test_dry_run_and_headless_runs_never_enter_git_flow(self) -> None:
        original = self.box.head()
        index_before = (self.box.repo / ".git" / "index").read_bytes()
        rc, output = self.box.interactive(
            "--dry-run", "edit", os.fspath(self.box.home / ".alpha")
        )
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.box.head(), original)
        self.assertEqual((self.box.repo / ".git" / "index").read_bytes(), index_before)
        self.assertFalse(self.box.state_path().exists())
        self.assertNotIn("Commit (message", output)
        self.assertIn("edited", (self.box.repo / "dot_alpha").read_text())

        self.box.git("checkout", "-q", "--", "dot_alpha")
        index_before_headless = (self.box.repo / ".git" / "index").read_bytes()
        result = run(
            self.box.command("edit", os.fspath(self.box.home / ".alpha")),
            cwd=self.box.home,
            env=self.box.env
            | {
                "EDITOR": os.fspath(self.box.source_editor),
                "TEST_SOURCE_REPO": os.fspath(self.box.repo),
            },
            input=b"must not become a message\n",
            check=False,
        )
        combined = (result.stdout + result.stderr).decode(errors="replace")
        self.assertEqual(result.returncode, 0, combined)
        self.assertEqual(self.box.head(), original)
        self.assertEqual(
            (self.box.repo / ".git" / "index").read_bytes(), index_before_headless
        )
        self.assertFalse(self.box.state_path().exists())
        self.assertNotIn("Commit (message", combined)

    def test_stale_explicit_lease_rejects_after_tracking_ref_refresh(self) -> None:
        competitor = self.box.root / "competitor"
        run(["git", "clone", "-q", os.fspath(self.box.remote), os.fspath(competitor)], env=self.box.env)
        competitor_env = isolated_env(self.box.home)
        run(["git", "-C", os.fspath(competitor), "config", "user.name", "Competitor"], env=competitor_env)
        run(["git", "-C", os.fspath(competitor), "config", "user.email", "other@example.invalid"], env=competitor_env)
        (competitor / "dot_beta").write_text("remote advance\n")
        run(["git", "-C", os.fspath(competitor), "add", "dot_beta"], env=competitor_env)
        run(["git", "-C", os.fspath(competitor), "commit", "-q", "-m", "remote advance"], env=competitor_env)
        competitor_head = run(
            ["git", "-C", os.fspath(competitor), "rev-parse", "HEAD"], env=competitor_env
        ).stdout.decode().strip()

        child = self.box.child("edit", os.fspath(self.box.home / ".alpha"))
        child.send(b":s\n")
        child.wait_for(b"Push REWRITE with explicit force-with-lease? [y/N]")
        run(["git", "-C", os.fspath(competitor), "push", "-q", "origin", "main"], env=competitor_env)
        self.box.git("fetch", "-q", "origin")
        child.send(b"y\n")
        rc, output = child.finish()

        self.assertNotEqual(rc, 0, output)
        remote_head = run(
            ["git", "--git-dir", os.fspath(self.box.remote), "rev-parse", "refs/heads/main"],
            env=self.box.env,
        ).stdout.decode().strip()
        self.assertEqual(remote_head, competitor_head)
        self.assertEqual(self.box.git_text("rev-parse", "refs/remotes/origin/main"), competitor_head)
        self.assertNotEqual(self.box.head(), competitor_head)
        self.assertIn("stale info", output.lower())
        self.assertIn("local commit and edits were kept", output)

    def test_successful_new_and_amend_pushes_update_configured_upstream(self) -> None:
        rc, output = self.box.interactive(
            "edit", os.fspath(self.box.home / ".alpha"), input=b"published change\ny\n"
        )
        self.assertEqual(rc, 0, output)
        remote_head = run(
            ["git", "--git-dir", os.fspath(self.box.remote), "rev-parse", "refs/heads/main"],
            env=self.box.env,
        ).stdout.decode().strip()
        self.assertEqual(remote_head, self.box.head())

        rc, output = self.box.interactive(
            "edit", os.fspath(self.box.home / ".beta"), input=b":s\ny\n"
        )
        self.assertEqual(rc, 0, output)
        remote_head = run(
            ["git", "--git-dir", os.fspath(self.box.remote), "rev-parse", "refs/heads/main"],
            env=self.box.env,
        ).stdout.decode().strip()
        self.assertEqual(remote_head, self.box.head())
        self.assertIn("Push REWRITE with explicit force-with-lease?", output)

    def test_failed_editor_state_is_stale_and_cleaned_by_next_edit(self) -> None:
        original = self.box.head()
        rc, output = self.box.interactive(
            "edit",
            os.fspath(self.box.home / ".alpha"),
            extra_env={"SOURCE_EDITOR_MODE": "fail"},
        )
        self.assertNotEqual(rc, 0, output)
        self.assertTrue(self.box.state_path().exists())
        self.assertEqual(self.box.head(), original)

        rc, output = self.box.interactive(
            "edit",
            os.fspath(self.box.home / ".alpha"),
            extra_env={"SOURCE_EDITOR_MODE": "noop"},
        )
        self.assertEqual(rc, 0, output)
        self.assertFalse(self.box.state_path().exists())
        self.assertNotIn("Commit (message", output)

    def test_push_failure_keeps_new_local_commit(self) -> None:
        missing = self.box.root / "missing-remote.git"
        self.box.git("remote", "set-url", "--push", "origin", os.fspath(missing))
        original = self.box.head()
        rc, output = self.box.interactive(
            "edit",
            os.fspath(self.box.home / ".alpha"),
            input=b"local survives\ny\n",
        )
        self.assertNotEqual(rc, 0, output)
        self.assertNotEqual(self.box.head(), original)
        self.assertEqual(self.box.git_text("log", "-1", "--format=%s"), "local survives")
        self.assertEqual(self.box.git_text("status", "--short", "--", "dot_alpha"), "")
        self.assertIn("git push failed", output)

    def test_unknown_upstream_never_guesses(self) -> None:
        self.box.git("config", "--unset-all", "branch.main.remote")
        self.box.git("config", "--unset-all", "branch.main.merge")
        original = self.box.head()
        rc, output = self.box.interactive(
            "edit", os.fspath(self.box.home / ".alpha"), input=b"local only\ny\n"
        )
        self.assertNotEqual(rc, 0, output)
        self.assertNotEqual(self.box.head(), original)
        self.assertIn("no pinned configured upstream", output)

    def test_head_and_index_changes_during_edit_are_refused(self) -> None:
        with self.subTest("HEAD"):
            original = self.box.head()
            rc, output = self.box.interactive(
                "edit",
                os.fspath(self.box.home / ".alpha"),
                extra_env={"SOURCE_EDITOR_GIT_ACTION": "head"},
            )
            self.assertNotEqual(rc, 0, output)
            self.assertNotEqual(self.box.head(), original)
            self.assertEqual(self.box.git_text("log", "-1", "--format=%s"), "racing head")
            self.assertIn("HEAD changed during chezmoi edit", output)
            self.assertIn("edited", (self.box.repo / "dot_alpha").read_text())

        self.box.close()
        self.box = Sandbox()
        with self.subTest("index"):
            original = self.box.head()
            rc, output = self.box.interactive(
                "edit",
                os.fspath(self.box.home / ".alpha"),
                extra_env={"SOURCE_EDITOR_GIT_ACTION": "index"},
            )
            self.assertNotEqual(rc, 0, output)
            self.assertEqual(self.box.head(), original)
            self.assertEqual(self.box.git_text("diff", "--cached", "--name-only"), "dot_beta")
            self.assertIn("Git index changed during chezmoi edit", output)
            self.assertIn("edited", (self.box.repo / "dot_alpha").read_text())

    def test_concurrent_edit_session_is_refused(self) -> None:
        ready = self.box.root / "editor.ready"
        release = self.box.root / "editor.release"
        first = self.box.child(
            "edit",
            os.fspath(self.box.home / ".alpha"),
            extra_env={
                "SOURCE_EDITOR_MODE": "block",
                "EDITOR_READY": os.fspath(ready),
                "EDITOR_RELEASE": os.fspath(release),
            },
        )
        first.wait_until(ready.exists)

        rc2, output2 = self.box.interactive("edit", os.fspath(self.box.home / ".beta"))
        self.assertNotEqual(rc2, 0, output2)
        self.assertIn("another interactive chezmoi edit session is active", output2)

        release.write_text("go")
        first.send(b"\n")
        rc1, output1 = first.finish()
        self.assertEqual(rc1, 0, output1)
        self.assertIn("Edits left uncommitted", output1)

    def test_detached_head_and_conflicts_are_guarded(self) -> None:
        self.box.git("checkout", "-q", "--detach")
        rc, output = self.box.interactive("edit", os.fspath(self.box.home / ".alpha"))
        self.assertNotEqual(rc, 0)
        self.assertIn("detached HEAD", output)
        self.assertEqual((self.box.repo / "dot_alpha").read_text(), "alpha 0\n")

        self.box.close()
        self.box = Sandbox()
        base = self.box.git_text("rev-parse", "HEAD:dot_alpha")
        other = self.box.git("hash-object", "-w", "--stdin", input=b"other\n").stdout.decode().strip()
        entries = (
            f"100644 {base} 1\tdot_alpha\n"
            f"100644 {base} 2\tdot_alpha\n"
            f"100644 {other} 3\tdot_alpha\n"
        ).encode()
        self.box.git("update-index", "--index-info", input=entries)
        rc, output = self.box.interactive("edit", os.fspath(self.box.home / ".alpha"))
        self.assertNotEqual(rc, 0)
        self.assertIn("unresolved conflicts", output)

    def test_repository_template_renders_native_hooks_and_git_automation_off(self) -> None:
        empty_config = self.box.root / "empty-config.toml"
        empty_config.write_text("")
        rendered = run(
            [
                os.fspath(CHEZMOI),
                "--config",
                os.fspath(empty_config),
                "--source",
                os.fspath(self.box.repo),
                "--destination",
                os.fspath(self.box.home),
                "execute-template",
            ],
            cwd=self.box.home,
            env=self.box.env,
            # The [data] prompts are init-only; this test renders the hook section.
            input=CONFIG_TEMPLATE.read_bytes().split(b"\n[data]", 1)[0],
        ).stdout
        config = tomllib.loads(rendered.decode())
        self.assertEqual(
            config["git"], {"autoAdd": False, "autoCommit": False, "autoPush": False}
        )
        expected_helper = os.fspath(self.box.repo / "scripts" / "chezmoi-edit-git.py")
        self.assertEqual(config["hooks"]["edit"]["pre"]["args"], [expected_helper, "pre"])
        self.assertEqual(config["hooks"]["edit"]["post"]["args"], [expected_helper, "post"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
