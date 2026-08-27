#!/usr/bin/env python3
"""Safely offer a focused Git commit after an interactive ``chezmoi edit``."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

STATE_BASENAME = "chezmoi-edit-git.state.json"
LOCK_BASENAME = "chezmoi-edit-git.lock"
FALSE_VALUES = {"0", "false", "no", "off"}


class HelperError(RuntimeError):
    """A safety check or an invoked command failed."""


def eprint(message: str) -> None:
    print(f"chezmoi-edit-git: {message}", file=sys.stderr, flush=True)


def command_argv(env: Mapping[str, str]) -> list[str] | None:
    """Return the parent chezmoi argv when the platform exposes it losslessly."""
    proc_cmdline = Path(f"/proc/{os.getppid()}/cmdline")
    try:
        data = proc_cmdline.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    return [os.fsdecode(arg) for arg in data.rstrip(b"\0").split(b"\0")]


def _long_flag_is_true(argv: Sequence[str] | None, raw: str, flag: str) -> bool:
    if argv is not None:
        for arg in argv:
            if arg == flag:
                return True
            if arg.startswith(flag + "="):
                return arg.split("=", 1)[1].lower() not in FALSE_VALUES
        return False
    pattern = rf"(?:^|\s){re.escape(flag)}(?:=([^\s]+))?(?:\s|$)"
    match = re.search(pattern, raw)
    return bool(match and (match.group(1) or "true").lower() not in FALSE_VALUES)


def invocation_is_interactive(env: Mapping[str, str], argv: Sequence[str] | None) -> bool:
    if env.get("CHEZMOI_COMMAND") != "edit":
        return False
    raw = env.get("CHEZMOI_ARGS", "")
    if _long_flag_is_true(argv, raw, "--dry-run"):
        return False
    if _long_flag_is_true(argv, raw, "--no-tty"):
        return False
    if _long_flag_is_true(argv, raw, "--force"):
        return False
    if argv is not None:
        if "-n" in argv:
            return False
    elif re.search(r"(?:^|\s)-n(?:\s|$)", raw):
        return False
    return all(os.isatty(fd) for fd in (0, 1, 2))


def git_env(*, readonly: bool) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    env.setdefault("GIT_PAGER", "cat")
    if readonly:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def run_git(
    repo: Path,
    *args: str,
    readonly: bool = True,
    capture: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    command = ["git", "-C", os.fspath(repo), *args]
    result = subprocess.run(
        command,
        env=git_env(readonly=readonly),
        stdin=None,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise HelperError(f"{' '.join(shlex.quote(arg) for arg in command)} failed: {detail}")
    return result


def git_output(repo: Path, *args: str) -> str:
    return run_git(repo, *args).stdout.decode(errors="surrogateescape").rstrip("\n")


def optional_git_output(repo: Path, *args: str) -> str | None:
    result = run_git(repo, *args, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.decode(errors="surrogateescape").rstrip("\n")


def repository(env: Mapping[str, str]) -> tuple[Path, Path]:
    source_value = env.get("CHEZMOI_SOURCE_DIR")
    if not source_value:
        raise HelperError("CHEZMOI_SOURCE_DIR is not set")
    source = Path(source_value).expanduser().resolve()
    top = git_output(source, "rev-parse", "--show-toplevel")
    repo = Path(top).resolve()
    try:
        source.relative_to(repo)
    except ValueError as error:
        raise HelperError(f"source directory {source} is outside Git worktree {repo}") from error
    return repo, source


def git_path(repo: Path, name: str) -> Path:
    value = Path(git_output(repo, "rev-parse", "--git-path", name))
    return value if value.is_absolute() else repo / value


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
    except FileNotFoundError:
        return "missing"
    return digest.hexdigest()


def index_digest(repo: Path) -> str:
    return file_digest(git_path(repo, "index"))


def nul_paths(data: bytes) -> set[str]:
    return {os.fsdecode(item) for item in data.split(b"\0") if item}


def tracked_and_untracked_paths(repo: Path) -> set[str]:
    result = run_git(
        repo,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    )
    return nul_paths(result.stdout)


def path_fingerprint(repo: Path, relative: str) -> list[Any]:
    path = repo / relative
    try:
        info = path.lstat()
    except FileNotFoundError:
        return ["missing"]
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        target = os.fsencode(os.readlink(path))
        return ["symlink", mode, hashlib.sha256(target).hexdigest()]
    if stat.S_ISREG(info.st_mode):
        return ["file", mode, info.st_size, file_digest(path)]
    if stat.S_ISDIR(info.st_mode):
        return ["directory", mode]
    return ["other", mode, info.st_size]


def worktree_snapshot(repo: Path) -> dict[str, list[Any]]:
    return {
        path: path_fingerprint(repo, path)
        for path in sorted(tracked_and_untracked_paths(repo))
    }


def dirty_paths(repo: Path) -> set[str]:
    dirty: set[str] = set()
    for args in (
        ("diff", "--no-ext-diff", "--name-only", "-z"),
        ("diff", "--no-ext-diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        dirty.update(nul_paths(run_git(repo, *args).stdout))
    return dirty


def has_conflicts(repo: Path) -> bool:
    return bool(run_git(repo, "ls-files", "--unmerged", "-z").stdout)


def head_and_branch(repo: Path) -> tuple[str, str]:
    head = git_output(repo, "rev-parse", "--verify", "HEAD^{commit}")
    branch = optional_git_output(repo, "symbolic-ref", "-q", "HEAD")
    if not branch or not branch.startswith("refs/heads/"):
        raise HelperError("detached HEAD is not supported; source edit was not started")
    return head, branch


def process_start_time(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
    except OSError:
        return None
    return fields[21] if len(fields) > 21 else None


def process_is_same(pid: int, start_time: str | None) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    current = process_start_time(pid)
    return start_time is None or current == start_time


@contextlib.contextmanager
def state_lock(repo: Path) -> Iterator[None]:
    path = git_path(repo, LOCK_BASENAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def read_state(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise HelperError(f"cannot read session state {path}: {error}") from error
    if not isinstance(value, dict):
        raise HelperError(f"invalid session state in {path}")
    return value


def write_state(path: Path, state: Mapping[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    data = json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def state_owner_is_live(state: Mapping[str, Any]) -> bool:
    pid = state.get("parent_pid")
    start_time = state.get("parent_start_time")
    return isinstance(pid, int) and process_is_same(pid, start_time if isinstance(start_time, str) else None)


VALUE_OPTIONS = {
    "--age-recipient",
    "--age-recipient-file",
    "--cache",
    "--color",
    "--config",
    "--config-format",
    "--destination",
    "--exclude",
    "--include",
    "--mode",
    "--output",
    "--override-data",
    "--override-data-file",
    "--persistent-state",
    "--refresh-externals",
    "--source",
    "--use-builtin-age",
    "--use-builtin-git",
    "--working-tree",
}
BOOLEAN_OPTIONS = {
    "--apply",
    "--debug",
    "--dry-run",
    "--error-on-conflict",
    "--force",
    "--hardlink",
    "--init",
    "--interactive",
    "--keep-going",
    "--less-interactive",
    "--no-pager",
    "--no-tty",
    "--progress",
    "--skip-secrets",
    "--source-path",
    "--use-builtin-diff",
    "--verbose",
    "--watch",
}
SHORT_VALUE_OPTIONS = {"-c", "-D", "-i", "-o", "-R", "-S", "-W", "-x"}
SHORT_BOOLEAN_OPTIONS = {"-a", "-k", "-n", "-v"}


def edit_targets(argv: Sequence[str] | None) -> list[str] | None:
    """Extract edit operands, or None when exact argv is unavailable/no-target."""
    if argv is None:
        return None
    try:
        command_index = argv.index("edit", 1)
    except ValueError as error:
        raise HelperError("cannot identify the edit command in the parent argv") from error
    targets: list[str] = []
    index = command_index + 1
    after_separator = False
    while index < len(argv):
        argument = argv[index]
        if after_separator:
            targets.append(argument)
            index += 1
            continue
        if argument == "--":
            after_separator = True
            index += 1
            continue
        if argument.startswith("--"):
            name, separator, _ = argument.partition("=")
            if name in BOOLEAN_OPTIONS:
                index += 1
                continue
            if name in VALUE_OPTIONS:
                index += 1 if separator else 2
                if index > len(argv):
                    raise HelperError(f"missing value for {name}")
                continue
            raise HelperError(f"unsupported chezmoi edit option {name}; refusing unsafe path inference")
        if argument.startswith("-") and argument != "-":
            if argument in SHORT_BOOLEAN_OPTIONS:
                index += 1
                continue
            if argument[:2] in SHORT_VALUE_OPTIONS:
                index += 1 if len(argument) > 2 else 2
                if index > len(argv):
                    raise HelperError(f"missing value for {argument}")
                continue
            raise HelperError(f"unsupported chezmoi edit option {argument}; refusing unsafe path inference")
        targets.append(argument)
        index += 1
    return targets or None


def source_path_mode(argv: Sequence[str] | None) -> bool:
    if argv is None:
        return False
    enabled = False
    for argument in argv:
        if argument == "--source-path":
            enabled = True
        elif argument.startswith("--source-path="):
            enabled = argument.split("=", 1)[1].lower() not in FALSE_VALUES
    return enabled


def expected_source_paths(
    repo: Path,
    source: Path,
    env: Mapping[str, str],
    argv: Sequence[str] | None,
) -> set[str] | None:
    targets = edit_targets(argv)
    if targets is None:
        return None
    executable = env.get("CHEZMOI_EXECUTABLE", "chezmoi")
    config = env.get("CHEZMOI_CONFIG_FILE")
    destination = env.get("CHEZMOI_DEST_DIR")
    paths: set[str] = set()
    for target in targets:
        command = [executable]
        if config:
            command.extend(["--config", config])
        command.extend(["--source", os.fspath(source)])
        if destination:
            command.extend(["--destination", destination])
        if source_path_mode(argv):
            command.append("--source-path")
        command.extend(["source-path", "--", target])
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip()
            raise HelperError(f"cannot map edit target {target!r} to source state: {detail}")
        output = result.stdout
        if output.endswith(b"\n"):
            output = output[:-1]
        path = Path(os.fsdecode(output)).resolve()
        try:
            relative = path.relative_to(repo)
        except ValueError as error:
            raise HelperError(f"mapped source path {path} is outside Git worktree {repo}") from error
        paths.add(os.fspath(relative))
    return paths


def remote_urls(repo: Path, remote: str) -> list[str] | None:
    result = run_git(repo, "remote", "get-url", "--push", "--all", "--", remote, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.decode(errors="surrogateescape").splitlines()


def upstream_state(repo: Path, branch_ref: str) -> dict[str, Any] | None:
    branch = branch_ref.removeprefix("refs/heads/")
    remote = optional_git_output(repo, "config", "--get", f"branch.{branch}.remote")
    merge = optional_git_output(repo, "config", "--get", f"branch.{branch}.merge")
    if not remote or remote == "." or not merge or not merge.startswith("refs/heads/"):
        return None
    urls = remote_urls(repo, remote)
    if not urls:
        return None
    oid = optional_git_output(repo, "rev-parse", "--verify", "@{upstream}^{commit}")
    return {"remote": remote, "branch": merge, "expected_oid": oid, "urls": urls}


def state_paths(repo: Path) -> tuple[Path, Path]:
    return git_path(repo, STATE_BASENAME), git_path(repo, LOCK_BASENAME)


def create_pre_state(repo: Path, source: Path, env: Mapping[str, str], argv: Sequence[str] | None) -> dict[str, Any]:
    if has_conflicts(repo):
        raise HelperError("the source repository has unresolved conflicts; source edit was not started")
    head, branch = head_and_branch(repo)
    index = index_digest(repo)
    expected = expected_source_paths(repo, source, env, argv)
    dirty = dirty_paths(repo)
    if expected is not None:
        ambiguous = sorted(expected & dirty)
        if ambiguous:
            names = ", ".join(shlex.quote(path) for path in ambiguous)
            raise HelperError(f"edited path is already dirty ({names}); refusing ambiguous ownership")
    baseline = worktree_snapshot(repo)
    if worktree_snapshot(repo) != baseline:
        raise HelperError("source worktree changed while the edit session was being captured")
    current_head, current_branch = head_and_branch(repo)
    if (current_head, current_branch, index_digest(repo)) != (head, branch, index):
        raise HelperError("HEAD or index changed while the edit session was being captured")
    parent_pid = os.getppid()
    return {
        "version": 1,
        "token": secrets.token_hex(16),
        "parent_pid": parent_pid,
        "parent_start_time": process_start_time(parent_pid),
        "head": head,
        "branch": branch,
        "index": index,
        "baseline": baseline,
        "dirty": sorted(dirty),
        "expected": sorted(expected) if expected is not None else None,
        "upstream": upstream_state(repo, branch),
    }


def pre_hook(env: Mapping[str, str], argv: Sequence[str] | None) -> None:
    repo, source = repository(env)
    state = create_pre_state(repo, source, env, argv)
    state_path, _ = state_paths(repo)
    with state_lock(repo):
        existing = read_state(state_path)
        if existing is not None and state_owner_is_live(existing):
            raise HelperError("another interactive chezmoi edit session is active")
        if existing is not None:
            state_path.unlink(missing_ok=True)
        current_head, current_branch = head_and_branch(repo)
        if (
            current_head != state["head"]
            or current_branch != state["branch"]
            or index_digest(repo) != state["index"]
            or worktree_snapshot(repo) != state["baseline"]
        ):
            raise HelperError("repository changed before the edit session could be locked")
        write_state(state_path, state)


def changed_since(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> set[str]:
    return {path for path in baseline.keys() | current.keys() if baseline.get(path) != current.get(path)}


def validate_repository_state(repo: Path, state: Mapping[str, Any]) -> None:
    if has_conflicts(repo):
        raise HelperError("the source repository developed unresolved conflicts; leaving edits uncommitted")
    head, branch = head_and_branch(repo)
    if head != state.get("head"):
        raise HelperError("HEAD changed during chezmoi edit; leaving edits uncommitted")
    if branch != state.get("branch"):
        raise HelperError("the checked-out branch changed during chezmoi edit; leaving edits uncommitted")
    if index_digest(repo) != state.get("index"):
        raise HelperError("the Git index changed during chezmoi edit; leaving edits uncommitted")


def validate_changed_paths(state: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    baseline = state.get("baseline")
    if not isinstance(baseline, dict):
        raise HelperError("invalid baseline in edit session state")
    changed = changed_since(baseline, current)
    dirty = set(state.get("dirty", []))
    ambiguous = sorted(changed & dirty)
    if ambiguous:
        names = ", ".join(shlex.quote(path) for path in ambiguous)
        raise HelperError(f"pre-existing dirty path changed ({names}); leaving all edit changes uncommitted")
    expected_value = state.get("expected")
    if expected_value is not None:
        unexpected = sorted(changed - set(expected_value))
        if unexpected:
            names = ", ".join(shlex.quote(path) for path in unexpected)
            raise HelperError(f"unexpected path changed during edit ({names}); leaving all edits uncommitted")
    return sorted(changed)


def show_session(repo: Path, changed: Sequence[str]) -> None:
    print("Changed by chezmoi edit:")
    for path in changed:
        print(f"  {shlex.quote(path)}")
    previous = git_output(repo, "log", "-1", "--format=%h %s")
    print(f"Previous commit: {previous}")


def prompt_selection(repo: Path, changed: Sequence[str]) -> tuple[str, str | None]:
    prompt = "Commit (message | :s amend | :sm amend/edit message | :d diff | empty skip): "
    while True:
        try:
            response = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return "skip", None
        choice = response.strip()
        if not choice:
            return "skip", None
        if choice == ":d":
            run_git(
                repo,
                "--no-pager",
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--",
                *changed,
                capture=False,
            )
            continue
        if choice == ":s":
            return "amend", None
        if choice == ":sm":
            return "amend-edit", None
        return "commit", response


def ensure_unchanged_before_commit(
    repo: Path,
    state: Mapping[str, Any],
    selected_snapshot: Mapping[str, Any],
    selected_paths: Sequence[str],
) -> None:
    validate_repository_state(repo, state)
    current = worktree_snapshot(repo)
    if current != selected_snapshot or validate_changed_paths(state, current) != list(selected_paths):
        raise HelperError("source files changed at the commit prompt; leaving edits uncommitted")


def commit_parents(repo: Path, oid: str) -> list[str]:
    data = git_output(repo, "cat-file", "-p", oid)
    return [line.split(" ", 1)[1] for line in data.splitlines() if line.startswith("parent ")]


def make_commit(repo: Path, action: str, message: str | None, changed: Sequence[str], old_head: str) -> str:
    args = ["commit"]
    if action == "commit":
        assert message is not None
        args.extend(["--only", "-m", message])
    elif action == "amend":
        print("Amending the previous commit (history rewrite).", flush=True)
        args.extend(["--amend", "--only", "--no-edit"])
    elif action == "amend-edit":
        print("Amending the previous commit and opening its message (history rewrite).", flush=True)
        args.extend(["--amend", "--only", "--edit"])
    else:
        raise HelperError(f"invalid commit action {action}")
    args.extend(["--", *changed])
    result = run_git(repo, *args, readonly=False, capture=False, check=False)
    if result.returncode != 0:
        raise HelperError("git commit failed; local edits and existing index entries were left in place")
    new_head = git_output(repo, "rev-parse", "--verify", "HEAD^{commit}")
    expected_parents = [old_head] if action == "commit" else commit_parents(repo, old_head)
    if commit_parents(repo, new_head) != expected_parents:
        raise HelperError("commit completed but its parentage was unexpected; no rollback was attempted")
    changed_in_new_tree = nul_paths(
        run_git(repo, "diff", "--name-only", "-z", old_head, new_head, "--").stdout
    )
    if changed_in_new_tree != set(changed):
        raise HelperError("commit completed with an unexpected path set; no rollback was attempted")
    return new_head


def upstream_configuration_matches(repo: Path, branch_ref: str, expected: Mapping[str, Any]) -> bool:
    current = upstream_state(repo, branch_ref)
    if current is None:
        return False
    return (
        current.get("remote") == expected.get("remote")
        and current.get("branch") == expected.get("branch")
        and current.get("urls") == expected.get("urls")
    )


def prompt_push(
    repo: Path,
    state: Mapping[str, Any],
    new_head: str,
    amended: bool,
    committed_snapshot: Mapping[str, Any],
    committed_index: str,
) -> None:
    label = "Push REWRITE with explicit force-with-lease? [y/N] " if amended else "Push? [y/N] "
    try:
        answer = input(label).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer not in {"y", "yes"}:
        return
    head, branch = head_and_branch(repo)
    if head != new_head or branch != state.get("branch"):
        raise HelperError("HEAD or branch changed at the push prompt; local commit was kept")
    if index_digest(repo) != committed_index:
        raise HelperError("the Git index changed at the push prompt; local commit was kept")
    if worktree_snapshot(repo) != committed_snapshot:
        raise HelperError("source files changed at the push prompt; local commit was kept")
    upstream = state.get("upstream")
    if not isinstance(upstream, dict) or not upstream.get("expected_oid"):
        raise HelperError("no pinned configured upstream is available; local commit was not published")
    if not upstream_configuration_matches(repo, branch, upstream):
        raise HelperError("upstream configuration changed; local commit was not published")
    remote = upstream["remote"]
    remote_branch = upstream["branch"]
    if amended:
        lease = f"--force-with-lease={remote_branch}:{upstream['expected_oid']}"
        args = ["push", lease, "--", remote, f"HEAD:{remote_branch}"]
    else:
        args = ["push", "--", remote, f"HEAD:{remote_branch}"]
    result = run_git(repo, *args, readonly=False, capture=False, check=False)
    if result.returncode != 0:
        raise HelperError("git push failed; the local commit and edits were kept")


def load_owned_state(repo: Path) -> tuple[dict[str, Any] | None, Path]:
    state_path, _ = state_paths(repo)
    with state_lock(repo):
        state = read_state(state_path)
    if state is None:
        return None, state_path
    if state.get("parent_pid") != os.getppid() or state.get("parent_start_time") != process_start_time(os.getppid()):
        raise HelperError("edit session state belongs to a different chezmoi process")
    return state, state_path


def cleanup_state(repo: Path, state_path: Path, token: Any) -> None:
    with state_lock(repo):
        current = read_state(state_path)
        if current is not None and current.get("token") == token:
            state_path.unlink(missing_ok=True)


def post_hook(env: Mapping[str, str]) -> None:
    repo, _ = repository(env)
    state, state_path = load_owned_state(repo)
    if state is None:
        return
    try:
        validate_repository_state(repo, state)
        selected_snapshot = worktree_snapshot(repo)
        changed = validate_changed_paths(state, selected_snapshot)
        if not changed:
            return
        show_session(repo, changed)
        action, message = prompt_selection(repo, changed)
        if action == "skip":
            print("Edits left uncommitted.", flush=True)
            return
        ensure_unchanged_before_commit(repo, state, selected_snapshot, changed)
        new_head = make_commit(repo, action, message, changed, state["head"])
        committed_snapshot = worktree_snapshot(repo)
        committed_index = index_digest(repo)
        prompt_push(
            repo,
            state,
            new_head,
            action != "commit",
            committed_snapshot,
            committed_index,
        )
    finally:
        cleanup_state(repo, state_path, state.get("token"))


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"pre", "post"}:
        eprint("usage: chezmoi-edit-git.py pre|post")
        return 2
    env = os.environ
    argv = command_argv(env)
    if not invocation_is_interactive(env, argv):
        return 0
    if argv is None:
        if sys.argv[1] == "pre":
            eprint("exact chezmoi argument boundaries are unavailable; skipping the Git helper")
        return 0
    try:
        if sys.argv[1] == "pre":
            pre_hook(env, argv)
        else:
            post_hook(env)
    except HelperError as error:
        eprint(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
