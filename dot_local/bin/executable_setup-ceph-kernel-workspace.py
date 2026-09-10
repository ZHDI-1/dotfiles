#!/usr/bin/env python3
"""Mount a Ceph editing view: Linux (RO lower) + company src (RW upper).

No builds, source substitutions, or Neovim-specific workspace detection happen
here. Database transformations are delegated to compile-commands-edit.py.
All writes THROUGH merged/ (including non-Ceph edits) go to company src.
Do not change either backing tree while mounted. This does not make the
original Linux path read-only to other processes.
"""

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

STATE_NAME = ".ceph-kernel-overlay.json"
EDITOR = Path(__file__).resolve().with_name("compile-commands-edit.py")
IDENTITY_KEYS = ("kernel", "client", "upper", "workspace", "merged", "workdir")


class SetupError(Exception):
    pass


def absolute(value):
    return Path(value).expanduser().resolve()


def overlaps(a, b):
    return a == b or a in b.parents or b in a.parents


def require_directory(path):
    if not path.is_dir():
        raise SetupError(f"directory not found: {path}")


def require_file(path):
    if not path.is_file():
        raise SetupError(f"file not found: {path}")


def nearest_existing(path):
    while not path.exists():
        path = path.parent
    return path


def mount_records():
    """Read mount identities without guessing from whether a directory is empty."""

    def unescape(text):
        return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), text)

    records = []
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    namespace = os.readlink("/proc/self/ns/mnt")
    with open("/proc/self/mountinfo", encoding="utf-8") as handle:
        for line in handle:
            before, separator, after = line.partition(" - ")
            if not separator:
                continue
            left, right = before.split(), after.split()
            records.append(
                {
                    "id": left[0],
                    "device": left[2],
                    "root": unescape(left[3]),
                    "boot_id": boot_id,
                    "namespace": namespace,
                    "target": unescape(left[4]),
                    "type": right[0],
                    "source": unescape(right[1]),
                }
            )
    return records


def mount_at(path, records=None):
    records = mount_records() if records is None else records
    # Last entry is the visible mount when mounts have been stacked.
    return next((r for r in reversed(records) if r["target"] == str(path)), None)


def is_overlay(record):
    return bool(record and record["type"] in ("fuse.fuse-overlayfs", "fuse-overlayfs"))


def is_ours(record, plan):
    # fuse-overlayfs 1.16 ignores fsname=. Use the actual mount ID/device,
    # boot and namespace, not a guessed name or just the filesystem type.
    return is_overlay(record) and record == plan.get("mounted")


def owner_path(plan):
    return Path(plan["client"]) / ".ceph-kernel-overlay-owner.json"


def load_owner(plan):
    path = owner_path(plan)
    if path.is_symlink():
        raise SetupError(f"refusing symlink ownership file: {path}")
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        owner = json.load(handle)
    if (
        not isinstance(owner, dict)
        or owner.get("version") != 1
        or owner.get("upper") != plan["upper"]
        or not isinstance(owner.get("merged"), str)
        or not Path(owner["merged"]).is_absolute()
    ):
        raise SetupError(f"invalid overlay ownership file: {path}")
    return owner


def persist(plan):
    contents = (json.dumps(plan, indent=2) + "\n").encode()
    atomic_write(state_path(Path(plan["workspace"])), contents)
    atomic_write(owner_path(plan), contents)


def state_path(workspace):
    return workspace / STATE_NAME


def load_state(workspace, required=True):
    path = state_path(workspace)
    if path.is_symlink():
        raise SetupError(f"refusing symlink state file: {path}")
    if not path.exists():
        if required:
            raise SetupError(f"no setup state at {path}; use the mount command first")
        return None
    with path.open(encoding="utf-8") as handle:
        plan = json.load(handle)
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise SetupError(f"unsupported setup state: {path}")
    for key in IDENTITY_KEYS + ("database",):
        if not isinstance(plan.get(key), str) or not Path(plan[key]).is_absolute():
            raise SetupError(f"invalid {key} in {path}")
    if plan["workspace"] != str(workspace) or plan["merged"] != str(
        workspace / "merged"
    ):
        raise SetupError(f"state belongs to a different workspace: {path}")
    return plan


def atomic_write(path, contents, backup_dir=None):
    if path.is_symlink():
        raise SetupError(f"refusing to overwrite symlink: {path}")
    if path.exists() and not path.is_file():
        raise SetupError(f"refusing to overwrite non-file: {path}")
    if path.exists() and path.read_bytes() == contents:
        return
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    if path.exists() and backup_dir:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = backup_dir / f"{path.name}.bak.{stamp}"
        with backup.open("xb") as handle:
            handle.write(path.read_bytes())
        print(f"backup: {backup}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(contents)
            os.fchmod(handle.fileno(), mode)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(command, timeout=120):
    print("+ " + shlex.join(map(str, command)), flush=True)
    result = subprocess.run(list(map(str, command)), check=False, timeout=timeout)
    if result.returncode:
        raise SetupError(
            f"command exited with status {result.returncode}: {command[0]}"
        )


def editor_command(plan, dry_run):
    require_file(EDITOR)
    command = [
        sys.executable,
        str(EDITOR),
        plan["database"],
        "--output",
        str(Path(plan["merged"]) / "compile_commands.json"),
        "--backup-dir",
        str(Path(plan["workspace"]) / "backups"),
    ]
    if plan.get("source_prefix"):
        command += ["--map", plan["source_prefix"], plan["merged"]]
    else:
        command += ["--map-common-prefix", plan["merged"]]
    for old, new in plan.get("maps", []):
        command += ["--map", old, new]
    if plan.get("gcc_include"):
        command += ["--gcc-include", plan["gcc_include"]]
    if dry_run:
        command.append("--dry-run")
    return command


def describe(plan):
    print(f"Linux lower (unchanged through mount): {plan['kernel']}")
    print(f"Company upper (ALL overlay writes):   {plan['upper']}")
    print(f"Merged editor path:                   {plan['merged']}")
    print(f"Overlay work directory:               {plan['workdir']}")
    print(f"Input database:                       {plan['database']}")
    print(
        "Source prefix:                        "
        + (plan.get("source_prefix") or "auto (reported by editor)")
    )


def validate(plan, previous=None, *, resume=False):
    kernel, client, upper, workspace, merged, workdir = (
        Path(plan[k]) for k in IDENTITY_KEYS
    )
    for path in (kernel, client, upper):
        require_directory(path)
    for name in ("Makefile", "Kconfig"):
        require_file(kernel / name)
    require_directory(kernel / "include/linux")
    for name in ("fs/ceph", "net/ceph", "include/linux/ceph"):
        require_directory(upper / name)
    if upper != client / "src" or upper.is_symlink():
        raise SetupError(
            "company src must be a real directory directly below the client repository"
        )
    if not resume:
        require_file(Path(plan["database"]))
        if plan.get("clangd_config"):
            require_file(Path(plan["clangd_config"]))
        if plan.get("gcc_include"):
            require_file(Path(plan["gcc_include"]) / "stdarg.h")
    if overlaps(kernel, client):
        raise SetupError("kernel and company repositories must not overlap")
    if any(overlaps(workspace, root) for root in (kernel, client)):
        raise SetupError("workspace must be separate from both source repositories")
    if any(overlaps(workdir, root) for root in (kernel, upper, workspace)):
        raise SetupError("workdir must not overlap lower, upper, or workspace")
    if merged.is_symlink() or workdir.is_symlink():
        raise SetupError("merged and workdir must not be symlinks")
    for path in (kernel, upper, workdir, merged):
        if any(char in str(path) for char in ",:\\\n\r"):
            raise SetupError(f"unsupported overlay option delimiter in path: {path}")
    if nearest_existing(workdir).stat().st_dev != upper.stat().st_dev:
        raise SetupError("workdir and company src must be on the same filesystem")
    if previous and any(previous[key] != plan[key] for key in IDENTITY_KEYS):
        raise SetupError(
            "this workspace records different overlay layers; use a new workspace directory"
        )
    records = mount_records()
    current = mount_at(merged, records)
    if current and (not previous or not is_ours(current, previous)):
        raise SetupError(f"refusing to use an unrecognized existing mount at {merged}")
    owner = load_owner(plan)
    if (
        owner
        and owner["merged"] != str(merged)
        and mount_at(Path(owner["merged"]), records)
    ):
        raise SetupError(
            f"company src already mounted/reserved by this tool at {owner['merged']}"
        )
    for record in records:
        target = Path(record["target"])
        if target != merged and merged in target.parents:
            raise SetupError(f"refusing workspace with nested mount: {target}")
    if not current:
        if merged.exists() and (not merged.is_dir() or any(merged.iterdir())):
            raise SetupError(f"mountpoint must be empty: {merged}")
        if workdir.exists() and not workdir.is_dir():
            raise SetupError(f"workdir is not a directory: {workdir}")
        owned_workdir = previous or (
            owner
            and all(
                owner.get(key) == plan[key] for key in ("kernel", "upper", "workdir")
            )
        )
        if not owned_workdir and workdir.exists() and any(workdir.iterdir()):
            raise SetupError(f"refusing nonempty, unowned workdir: {workdir}")
    # Refuse output symlinks even before mounting. Do not follow one into Linux.
    for name in ("compile_commands.json", ".clangd"):
        if name == ".clangd" and not plan.get("clangd_config"):
            continue
        destination = upper / name
        visible = destination if os.path.lexists(destination) else kernel / name
        if visible.is_symlink() or (visible.exists() and not visible.is_file()):
            raise SetupError(f"unsafe overlay output: {visible}")
        if resume:
            # Reuse the generated upper file, never the unmapped lower database.
            # Only check its type: resuming must not read/transform the full JSON.
            if name == "compile_commands.json" and not destination.is_file():
                raise SetupError(
                    f"no generated database at {destination}; use mount to regenerate it"
                )
            continue
        input_path = Path(
            plan["database"]
            if name == "compile_commands.json"
            else plan["clangd_config"]
        )
        if destination.exists() and os.path.samefile(destination, input_path):
            raise SetupError(
                f"input and company output are the same file: {input_path}"
            )
    if not shutil.which("fuse-overlayfs") or not shutil.which("fusermount3"):
        raise SetupError("fuse-overlayfs and fusermount3 must be installed")
    return current


@contextlib.contextmanager
def setup_lock(plan):
    # Outside src, and stable across workspaces: serialize our upper-layer users.
    lock = Path(plan["client"]) / ".ceph-kernel-overlay.lock"
    if lock.is_symlink():
        raise SetupError(f"refusing symlink lock: {lock}")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError(
                "another setup/unmount operation is using this company repository"
            ) from None
        yield
    finally:
        os.close(fd)


def unmount(plan):
    record = mount_at(Path(plan["merged"]))
    if not record:
        print("Already unmounted; company edits and generated files are retained.")
        return
    if not is_ours(record, plan):
        raise SetupError("refusing to unmount a filesystem not owned by this setup")
    run(["fusermount3", "-u", plan["merged"]], timeout=30)
    if mount_at(Path(plan["merged"])):
        raise SetupError("mount is still present after fusermount3")
    print(
        "Unmounted. Company edits and generated files are retained; nothing was deleted."
    )


def setup(plan, dry_run=False, refresh=False, *, resume=False):
    workspace = Path(plan["workspace"])
    previous = load_state(workspace, required=resume)
    current = validate(plan, previous, resume=resume)
    describe(plan)
    if not resume:
        # Validate the entire database before mounting or writing state.
        run(editor_command(plan, dry_run=True))
    if refresh and not current:
        raise SetupError("workspace is not mounted; use mount first")
    if dry_run:
        print("Dry run: no mount, directories, database, or state were changed.")
        return
    with setup_lock(plan):
        previous = load_state(workspace, required=resume)
        current = validate(plan, previous, resume=resume)
        workspace.mkdir(parents=True, exist_ok=True)
        Path(plan["merged"]).mkdir(exist_ok=True)
        Path(plan["workdir"]).mkdir(parents=True, exist_ok=True)
        if current:
            plan["mounted"] = current
        else:
            plan.pop("mounted", None)
        persist(plan)
        try:
            if not current:
                options = (
                    f"lowerdir={plan['kernel']},upperdir={plan['upper']},"
                    f"workdir={plan['workdir']}"
                )
                try:
                    run(["fuse-overlayfs", "-o", options, plan["merged"]], timeout=30)
                finally:
                    # We verified an empty, unmounted target before this call.
                    # Capture even a mount made by a command that subsequently
                    # errors/times out, so the exception path can clean it up.
                    record = mount_at(Path(plan["merged"]))
                    if is_overlay(record):
                        plan["mounted"] = record
                        persist(plan)
                if not is_ours(mount_at(Path(plan["merged"])), plan):
                    raise SetupError(
                        "fuse-overlayfs returned without the expected mount"
                    )
            if not resume:
                run(editor_command(plan, dry_run=False))
                if plan.get("clangd_config"):
                    atomic_write(
                        Path(plan["merged"]) / ".clangd",
                        Path(plan["clangd_config"]).read_bytes(),
                        workspace / "backups",
                    )
        except BaseException:
            if not current and is_ours(mount_at(Path(plan["merged"])), plan):
                print(
                    "Setup failed; unmounting the newly created view.", file=sys.stderr
                )
                try:
                    unmount(plan)
                except (SetupError, OSError, subprocess.TimeoutExpired) as exc:
                    print(
                        f"cleanup failed: {exc}; use the unmount command",
                        file=sys.stderr,
                    )
            raise
    print("\nReady: nvim " + shlex.quote(plan["merged"]))
    if resume:
        print(
            "Reused company src/compile_commands.json; database and .clangd left unchanged."
        )
    else:
        print(
            "The output database is company src/compile_commands.json; backups are in workspace/backups."
        )
    print(
        "Edit through merged/, do not build there, and unmount before changing backing trees."
    )
    print(
        "Do not run Git-changing commands in merged/: Linux's .git may be visible there."
    )


def make_plan(args):
    kernel, client, workspace = (
        absolute(v) for v in (args.kernel, args.client, args.workspace)
    )
    # Leave leaf resolution to validation, so symlink workdirs cannot slip through.
    workdir = (
        Path(os.path.abspath(os.path.expanduser(args.workdir)))
        if args.workdir
        else client / ".ceph-kernel-overlay-work"
    )
    workdir = workdir.parent.resolve() / workdir.name
    return {
        "version": 1,
        "kernel": str(kernel),
        "client": str(client),
        "upper": str(client / "src"),
        "workspace": str(workspace),
        "merged": str(workspace / "merged"),
        "workdir": str(workdir),
        "database": str(
            absolute(args.database)
            if args.database
            else kernel / "compile_commands.json"
        ),
        # Source prefix may no longer exist. Do NOT realpath it.
        "source_prefix": args.source_prefix,
        "maps": args.map,
        "gcc_include": str(absolute(args.gcc_include)) if args.gcc_include else None,
        "clangd_config": str(absolute(args.clangd_config))
        if args.clangd_config
        else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    mount = commands.add_parser(
        "mount", help="mount (or refresh an existing matching mount)"
    )
    mount.add_argument("kernel", help="configured Linux source/build tree (lower)")
    mount.add_argument(
        "client",
        help="company repository; its src directory becomes the writable upper",
    )
    mount.add_argument(
        "workspace", help="separate directory; the editor view is WORKSPACE/merged"
    )
    mount.add_argument(
        "--workdir",
        help="dedicated overlay scratch directory; defaults beside client/src",
    )
    mount.add_argument(
        "--database", help="input database; defaults to KERNEL/compile_commands.json"
    )
    mount.add_argument(
        "--source-prefix",
        help="original kernel prefix recorded in the database; default: infer common prefix",
    )
    mount.add_argument(
        "--map",
        nargs=2,
        action="append",
        default=[],
        metavar=("OLD", "NEW"),
        help="additional database prefix mapping (repeatable)",
    )
    mount.add_argument(
        "--gcc-include",
        help="replace stale GCC builtin -isystem paths with this directory (must contain stdarg.h)",
    )
    mount.add_argument(
        "--clangd-config",
        help="optionally copy an existing .clangd into the merged root (backs up any previous file)",
    )
    mount.add_argument("--dry-run", action="store_true")
    for name, help_text in (
        ("resume", "restore a saved mount without regenerating the database or .clangd"),
        ("refresh", "regenerate the database for an existing mount"),
        ("unmount", "unmount without deleting edits or state"),
        ("status", "show recorded layers and current mount identity"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("workspace")
        if name in ("resume", "refresh"):
            command.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "mount":
            setup(make_plan(args), args.dry_run)
        else:
            plan = load_state(absolute(args.workspace))
            if args.command == "resume":
                setup(plan, args.dry_run, resume=True)
            elif args.command == "refresh":
                setup(plan, args.dry_run, refresh=True)
            elif args.command == "unmount":
                with setup_lock(plan):
                    unmount(plan)
            else:
                describe(plan)
                record = mount_at(Path(plan["merged"]))
                print(
                    "Status: "
                    + (
                        "mounted"
                        if is_ours(record, plan)
                        else "FOREIGN MOUNT"
                        if record
                        else "unmounted"
                    )
                )
                if record and not is_ours(record, plan):
                    return 1
        return 0
    except (SetupError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
