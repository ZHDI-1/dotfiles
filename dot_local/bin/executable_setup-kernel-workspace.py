#!/usr/bin/env python3
"""Mount a kernel editing view: Linux (RO lower) + bind-mounted module sources.

    WORKSPACE/merged           OverlayFS: lower KERNEL, upper WORKSPACE/upper
    WORKSPACE/merged/<target>  bind mounts from the module repository's src/

Layouts: ceph binds each directory company src owns (fs/ceph, net/ceph, ...)
at the same kernel path, and single files where it shares a directory with
Linux (drivers/block/rbd.c); kfuse binds kfuse-driver's flat src/ at fs/fuse.
Running this as setup-ceph-kernel-workspace.py or
setup-kfuse-kernel-workspace.py picks the layout for mount.

Edits under a bind go straight to the module repository, and that repository
may change while mounted. Every other write through merged/ (the generated
compile_commands.json, clangd's .cache, notes in Linux files) lands in the
workspace-private upper, never in either repository. Do not change the Linux
tree while mounted. This does not make the original Linux path read-only to
other processes.

No builds, source substitutions, or Neovim-specific workspace detection happen
here. Database transformations are delegated to compile-commands-edit.py.
Only mount/umount are elevated with sudo, never database or state writes.
"""

import argparse
import contextlib
import fcntl
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

STATE_NAME = ".kernel-workspace.json"
STATE_VERSION = 3
BACKEND = "overlay-bind"
EDITOR = Path(__file__).resolve().with_name("compile-commands-edit.py")
IDENTITY_KEYS = (
    "layout", "kernel", "repo", "source", "workspace", "merged", "upper", "workdir"
)
# A bind is ours by where it came from and where it sits. Its option fields
# describe the source filesystem, which may be remounted independently of us.
BIND_IDENTITY = (
    "id", "device", "root", "boot_id", "namespace", "target", "type", "source"
)
# Outputs of an in-tree module build are never bound over Linux's own files.
ARTIFACTS = (
    "*.o", "*.o.d", "*.ko", "*.mod", "*.mod.c", ".*.cmd", "*.a",
    "modules.order", "Module.symvers",
)
# Tool output the old overlay layout left at the root of company src.
SOURCE_SKIP = (".cache", ".git", "compile_commands.json", ".clangd")
# Company src replaces these Linux directories outright: a file it dropped must
# not show through from Linux as if it were still part of the company build.
CEPH_OWNED = ("fs/ceph", "net/ceph", "include/linux/ceph", "include/linux/crush")
DEFAULT_LAYOUT = {
    "setup-ceph-kernel-workspace.py": "ceph",
    "setup-kfuse-kernel-workspace.py": "kfuse",
}.get(Path(sys.argv[0]).name)


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


def is_artifact(name):
    return any(fnmatch.fnmatch(name, pattern) for pattern in ARTIFACTS)


def bind(source, target, kind):
    return {"source": str(source), "target": target, "kind": kind}


def ceph_binds(kernel, source):
    for name in ("fs/ceph", "net/ceph", "include/linux/ceph"):
        require_directory(source / name)
    binds = []

    def walk(relative):
        for entry in sorted(os.scandir(source / relative), key=lambda e: e.name):
            if not relative.parts and entry.name in SOURCE_SKIP:
                continue
            target = (relative / entry.name).as_posix()
            lower = kernel / target
            if entry.is_symlink() or lower.is_symlink():
                raise SetupError(f"refusing symlink on a bind path: {target}")
            if entry.is_dir():
                # Bind whole directories Linux lacks or company src owns; inside
                # shared ones (drivers/block) only company files replace Linux's.
                if target in CEPH_OWNED or not os.path.lexists(lower):
                    binds.append(bind(entry.path, target, "dir"))
                elif lower.is_dir():
                    walk(relative / entry.name)
                else:
                    raise SetupError(f"company directory replaces a Linux file: {target}")
            elif entry.is_file():
                if is_artifact(entry.name):
                    continue
                if os.path.lexists(lower) and not lower.is_file():
                    raise SetupError(f"company file replaces a Linux directory: {target}")
                binds.append(bind(entry.path, target, "file"))
            else:
                raise SetupError(f"unsupported file type in company src: {entry.path}")

    walk(Path())
    return binds


def kfuse_binds(kernel, source):
    # kfuse-driver's src/ is a flat copy of fs/fuse that is built out of tree.
    require_file(source / "fuse_i.h")
    require_directory(kernel / "fs/fuse")
    return [bind(source, "fs/fuse", "dir")]


LAYOUTS = {"ceph": ceph_binds, "kfuse": kfuse_binds}


def layout_binds(plan):
    return LAYOUTS[plan["layout"]](Path(plan["kernel"]), Path(plan["source"]))


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
                    "mount_options": left[5],
                    "type": right[0],
                    "source": unescape(right[1]),
                    "super_options": unescape(right[2]),
                }
            )
    return records


def mount_at(path, records=None):
    records = mount_records() if records is None else records
    # Last entry is the visible mount when mounts have been stacked.
    return next((r for r in reversed(records) if r["target"] == str(path)), None)


def require_current(plan):
    if plan.get("version") != STATE_VERSION or plan.get("backend") != BACKEND:
        raise SetupError("unsupported workspace backend/state")


def is_overlay(record, plan):
    if not record or record["type"] != "overlay" or record.get("root") != "/":
        return False
    options = dict(
        item.split("=", 1)
        for item in record.get("super_options", "").split(",")
        if "=" in item
    )
    return record["target"] == plan["merged"] and all(
        options.get(option) == plan[key]
        for option, key in (
            ("lowerdir", "kernel"), ("upperdir", "upper"), ("workdir", "workdir")
        )
    )


def is_bind_ours(record, saved):
    return bool(record and saved) and all(
        record.get(key) == saved.get(key) for key in BIND_IDENTITY
    )


def view_mounts(state, records=None):
    """Split the mounts at and below merged/ into ours (per saved state) and foreign."""
    records = mount_records() if records is None else records
    merged = Path(state["merged"])
    saved = state.get("mounted") or {}
    foreign = []
    # Filesystem type/layers alone are not ownership: also retain the actual
    # mount ID/device, boot and namespace to reject replacement mounts.
    overlay = mount_at(merged, records)
    if overlay and not (is_overlay(overlay, state) and overlay == saved.get("overlay")):
        foreign.append(overlay["target"])
        overlay = None
    binds = {}
    for record in records:
        target = Path(record["target"])
        if merged not in target.parents:
            continue
        relative = target.relative_to(merged).as_posix()
        if is_bind_ours(record, saved.get("binds", {}).get(relative)):
            binds[relative] = record
        else:
            foreign.append(record["target"])
    return overlay, binds, foreign


def require_writable(record):
    # OverlayFS may return mount success but fall back to a read-only superblock
    # when its workdir cannot be created. The per-mount flags can still say rw.
    if any(
        "rw" not in record.get(key, "").split(",")
        for key in ("mount_options", "super_options")
    ):
        raise SetupError(
            "native OverlayFS mounted read-only; check kernel diagnostics and "
            "upper/workdir filesystem compatibility (including virtiofs permissions). "
            "Keep the workspace on a supported local filesystem"
        )


def persist(plan):
    contents = (json.dumps(plan, indent=2) + "\n").encode()
    atomic_write(state_path(Path(plan["workspace"])), contents)


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
    if not isinstance(plan, dict):
        raise SetupError(f"unsupported setup state: {path}")
    require_current(plan)
    if plan.get("layout") not in LAYOUTS:
        raise SetupError(f"unknown layout in {path}")
    for key in IDENTITY_KEYS[1:] + ("database",):
        if not isinstance(plan.get(key), str) or not Path(plan[key]).is_absolute():
            raise SetupError(f"invalid {key} in {path}")
    if not isinstance(plan.get("binds"), list) or not all(
        isinstance(item, dict) and {"source", "target", "kind"} <= item.keys()
        for item in plan["binds"]
    ):
        raise SetupError(f"invalid binds in {path}")
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


def privileged_command(command):
    if os.geteuid() == 0:
        return command
    if not shutil.which("sudo"):
        raise SetupError("sudo is required for native mount/umount operations")
    # sudo may prompt on the terminal; its own passwd_timeout bounds that wait.
    return ["sudo", "--", *command]


def run_privileged(command):
    try:
        # No timeout here: it would also cut off someone typing the password.
        run(privileged_command(command), timeout=None)
    except SetupError as exc:
        raise SetupError(
            f"{exc}; native OverlayFS and bind mounts need mount privileges and a "
            "compatible upper/workdir filesystem. Run as your normal user; only "
            "mount/umount are sudo'd (do not sudo the whole script)"
        ) from exc


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
    print(f"Layout:                               {plan['layout']}")
    print(f"Linux lower (unchanged through mount): {plan['kernel']}")
    print(f"Module sources (bind mounts):         {plan['source']}")
    print(f"Merged editor path:                   {plan['merged']}")
    print(f"Private upper (all other writes):     {plan['upper']}")
    print(f"Overlay work directory:               {plan['workdir']}")
    print(f"Input database:                       {plan['database']}")
    print(
        "Source prefix:                        "
        + (plan.get("source_prefix") or "auto (reported by editor)")
    )
    print(f"Bind mounts ({len(plan['binds'])}):")
    for item in plan["binds"]:
        print(f"  {item['kind']:<4} {item['target']}  <- {item['source']}")


def report_hidden(plan):
    # A directory bind hides every Linux entry the module repository lacks.
    for item in plan["binds"]:
        lower = Path(plan["kernel"]) / item["target"]
        if item["kind"] != "dir" or not lower.is_dir():
            continue
        present = set(os.listdir(item["source"]))
        hidden = sorted(
            name for name in os.listdir(lower)
            if name not in present and not is_artifact(name)
        )
        if hidden:
            print(f"note: merged/{item['target']} hides Linux-only: {', '.join(hidden)}")


def warn_uncovered(plan):
    # A bound C file Linux never compiled has no flags; clangd would only guess.
    prefix = plan.get("source_prefix") or plan["kernel"]
    with open(plan["database"], encoding="utf-8") as handle:
        entries = json.load(handle)
    compiled = {
        os.path.normpath(os.path.join(entry.get("directory", ""), entry["file"]))
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("file"), str)
    }
    if not any(path.startswith(prefix + os.sep) for path in compiled):
        return  # Database not laid out under the kernel path; the editor reports it.
    missing = []
    for item in plan["binds"]:
        if not os.path.lexists(Path(plan["kernel"]) / item["target"]):
            continue  # Not a Linux path (company mount/ helpers are user space).
        if item["kind"] == "file":
            names = [item["target"]]
        else:
            names = [
                f"{item['target']}/{(Path(d) / f).relative_to(item['source']).as_posix()}"
                for d, _, files in os.walk(item["source"])
                for f in files
            ]
        missing += [
            name for name in names
            if name.endswith(".c") and not is_artifact(Path(name).name)
            and os.path.join(prefix, name) not in compiled
        ]
    if missing:
        print(
            f"warning: no compile command for {len(missing)} bound C file(s): "
            + ", ".join(sorted(missing)[:8]),
            file=sys.stderr,
        )


def validate_binds(plan):
    kernel, upper = Path(plan["kernel"]), Path(plan["upper"])
    if not plan["binds"]:
        raise SetupError("layout produced no bind mounts")
    targets = [PurePosixPath(item["target"]) for item in plan["binds"]]
    for item, target in zip(plan["binds"], targets):
        source = Path(item["source"])
        if target.is_absolute() or ".." in target.parts or not target.parts:
            raise SetupError(f"invalid bind target: {target}")
        if any(other != target and target in other.parents for other in targets):
            raise SetupError(f"nested bind targets below {target}")
        is_kind = Path.is_dir if item["kind"] == "dir" else Path.is_file
        if source.is_symlink() or not is_kind(source):
            raise SetupError(f"bind source missing or not a real {item['kind']}: {source}")
        if overlaps(source, Path(plan["workspace"])):
            raise SetupError(f"bind source overlaps the workspace: {source}")
        # mount(8) follows symlinks, so a link on the path could aim a bind
        # outside merged/. Check both layers; the view is checked again live.
        for layer in (kernel, upper):
            for parent in reversed(target.parents[:-1]):
                path = layer / parent
                if path.is_symlink() or (os.path.lexists(path) and not path.is_dir()):
                    raise SetupError(f"bind path is not a real directory: {path}")
        lower, placeholder = kernel / target, upper / target
        if os.path.lexists(lower):
            if lower.is_symlink() or not is_kind(lower):
                raise SetupError(f"Linux has a different file type at {lower}")
            if os.path.lexists(placeholder):
                # Written through merged/ while the bind was absent; never hide it.
                raise SetupError(f"private upper shadows a bind target: {placeholder}")
        elif os.path.lexists(placeholder) and (
            placeholder.is_symlink()
            or not is_kind(placeholder)
            or (item["kind"] == "dir" and any(placeholder.iterdir()))
            or (item["kind"] == "file" and placeholder.stat().st_size)
        ):
            raise SetupError(f"private upper has content at a bind target: {placeholder}")


def validate(plan, previous=None, *, resume=False):
    require_current(plan)
    if previous:
        require_current(previous)
    kernel, repo, source, workspace, merged, upper, workdir = (
        Path(plan[k]) for k in IDENTITY_KEYS[1:]
    )
    for path in (kernel, repo, source):
        require_directory(path)
    for name in ("Makefile", "Kconfig"):
        require_file(kernel / name)
    require_directory(kernel / "include/linux")
    if source != repo / "src" or source.is_symlink():
        raise SetupError(
            "module sources must be a real src directory directly below the repository"
        )
    if not resume:
        require_file(Path(plan["database"]))
        if plan.get("clangd_config"):
            require_file(Path(plan["clangd_config"]))
        if plan.get("gcc_include"):
            require_file(Path(plan["gcc_include"]) / "stdarg.h")
    if overlaps(kernel, repo):
        raise SetupError("kernel and module repositories must not overlap")
    if any(overlaps(workspace, root) for root in (kernel, repo)):
        raise SetupError("workspace must be separate from both source repositories")
    for path in (merged, upper, workdir):
        if path.is_symlink():
            raise SetupError(f"refusing symlink: {path}")
    for path in (kernel, upper, workdir, merged):
        if any(char in str(path) for char in ",:\\\n\r"):
            raise SetupError(f"unsupported overlay option delimiter in path: {path}")
    if nearest_existing(upper).stat().st_dev != nearest_existing(workdir).stat().st_dev:
        raise SetupError("upper and workdir must be on the same filesystem")
    if previous and any(previous[key] != plan[key] for key in IDENTITY_KEYS):
        raise SetupError(
            "this workspace records a different layout or layers; use a new workspace directory"
        )
    validate_binds(plan)
    state = previous or plan
    overlay, binds, foreign = view_mounts(state)
    if foreign:
        raise SetupError("refusing unrecognized mount(s): " + ", ".join(foreign))
    current = bool(overlay) and set(binds) == {i["target"] for i in state["binds"]}
    if (overlay or binds) and not current:
        raise SetupError("view is partially mounted; run umount, then mount or resume")
    if current:
        require_writable(overlay)
    else:
        if merged.exists() and (not merged.is_dir() or any(merged.iterdir())):
            raise SetupError(f"mountpoint must be empty: {merged}")
        for path in (upper, workdir):
            if path.exists() and not path.is_dir():
                raise SetupError(f"not a directory: {path}")
            # Without saved state, existing layer contents were not made here.
            if not previous and path.exists() and any(path.iterdir()):
                raise SetupError(f"refusing nonempty, unowned {path}")
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
            raise SetupError(f"input and generated output are the same file: {input_path}")
    if not shutil.which("mount") or not shutil.which("umount"):
        raise SetupError("mount and umount (util-linux) must be installed")
    if os.geteuid() != 0 and not shutil.which("sudo"):
        raise SetupError("sudo is required for native mount/umount operations")
    return current


def adopt_mounted(plan, previous, current):
    if not current:
        plan["mounted"] = {"overlay": None, "binds": {}}
        return
    # Keep describing what is mounted; a changed module tree applies on remount.
    if plan["binds"] != previous["binds"]:
        print(
            "warning: module tree changed since mount; run remount to update the binds",
            file=sys.stderr,
        )
    plan["binds"], plan["mounted"] = previous["binds"], previous["mounted"]


@contextlib.contextmanager
def setup_lock(plan):
    # The private upper belongs to one workspace, so that is all we serialize.
    # Binding the same repository into several workspaces is safe.
    lock = Path(plan["workspace"]) / ".kernel-workspace.lock"
    if lock.is_symlink():
        raise SetupError(f"refusing symlink lock: {lock}")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError(
                "another setup/unmount operation is using this workspace"
            ) from None
        yield
    finally:
        os.close(fd)


def prepare_upper(plan):
    kernel, upper = Path(plan["kernel"]), Path(plan["upper"])
    # A bind target Linux lacks (company mount/) needs a mountpoint in the view.
    for item in plan["binds"]:
        if os.path.lexists(kernel / item["target"]):
            continue
        placeholder = upper / item["target"]
        placeholder.parent.mkdir(parents=True, exist_ok=True)
        if item["kind"] == "dir":
            placeholder.mkdir(exist_ok=True)
        else:
            placeholder.touch(exist_ok=True)
    # Git stops at a bind's filesystem boundary, but from any Linux path in
    # merged/ it would find Linux's .git, so a status, gitsigns or commit there
    # would act on the kernel repository. A whiteout (unprivileged since Linux
    # 5.8) hides it in the view only.
    whiteout = upper / ".git"
    if os.path.lexists(kernel / ".git") and not os.path.lexists(whiteout):
        try:
            os.mknod(whiteout, stat.S_IFCHR, os.makedev(0, 0))
        except OSError as exc:
            print(f"warning: cannot hide Linux's .git in merged/: {exc}", file=sys.stderr)


def require_mountpoint(merged, item):
    # Same symlink concern as validate_binds, now on the live overlay view.
    path = merged
    for part in PurePosixPath(item["target"]).parts:
        path = path / part
        if path.is_symlink():
            raise SetupError(f"refusing symlink on a bind path: {path}")
    if not (path.is_dir() if item["kind"] == "dir" else path.is_file()):
        raise SetupError(f"bind mountpoint missing or the wrong type: {path}")


def mount_view(plan):
    merged = Path(plan["merged"])
    mounted = plan["mounted"]
    options = (
        f"lowerdir={plan['kernel']},upperdir={plan['upper']},"
        f"workdir={plan['workdir']},nosuid,nodev"
    )
    try:
        run_privileged(
            ["mount", "-t", "overlay", "overlay", "-o", options, "--", plan["merged"]]
        )
    finally:
        # We verified an empty, unmounted target before this call. Capture even
        # a mount made by a command that subsequently errors, so the exception
        # path can clean it up. The same applies to each bind below.
        record = mount_at(merged)
        if is_overlay(record, plan):
            mounted["overlay"] = record
            persist(plan)
    if not mounted["overlay"] or mount_at(merged) != mounted["overlay"]:
        raise SetupError("mount returned without the expected native overlay layers")
    require_writable(mounted["overlay"])
    for item in plan["binds"]:
        target = merged / item["target"]
        require_mountpoint(merged, item)
        try:
            run_privileged(["mount", "--bind", "--", item["source"], str(target)])
        finally:
            record = mount_at(target)
            with contextlib.suppress(OSError):
                if record and os.path.samefile(target, item["source"]):
                    mounted["binds"][item["target"]] = record
                    persist(plan)
        if item["target"] not in mounted["binds"]:
            raise SetupError(f"bind mount did not appear at {target}")


def unmount(plan):
    require_current(plan)
    overlay, binds, foreign = view_mounts(plan)
    if foreign:
        raise SetupError(
            "refusing to unmount mounts not owned by this workspace: " + ", ".join(foreign)
        )
    if not overlay and not binds:
        print("Already unmounted; edits, the private upper, and the database are retained.")
        return
    mounted = plan["mounted"]
    # Deepest first: every bind must go before the overlay it sits on.
    for target in sorted(binds, key=lambda t: t.count("/"), reverse=True):
        run_privileged(["umount", "--", binds[target]["target"]])
        mounted["binds"].pop(target)
        persist(plan)
    if overlay:
        run_privileged(["umount", "--", plan["merged"]])
        mounted["overlay"] = None
        persist(plan)
    merged = Path(plan["merged"])
    if any(
        r["target"] == str(merged) or merged in Path(r["target"]).parents
        for r in mount_records()
    ):
        raise SetupError("mounts are still present after umount")
    print("Unmounted. Edits, the private upper, and the database are retained; nothing was deleted.")


def remount(plan):
    # Directory binds show repository changes live, but a file bind keeps the
    # inode it was made from (git replaces files on checkout) and OverlayFS
    # caches Linux lookups. A fresh mount picks up both, plus new module files.
    # Check that resume can succeed before dropping the current view.
    validate(dict(plan, binds=layout_binds(plan)), plan, resume=True)
    with setup_lock(plan):
        unmount(plan)
    # setup() takes the lock itself and revalidates, so a racing operation fails.
    setup(plan, resume=True)


def find_workspace(start):
    for path in (start, *start.parents):
        if os.path.lexists(state_path(path)):
            return path
    raise SetupError(f"no workspace state at or above {start}; pass WORKSPACE")


def shell_in_source(plan):
    merged = Path(plan["merged"])
    cwd = Path.cwd()
    if cwd == merged or merged in cwd.parents:
        print(
            "note: the calling shell stays in merged/, so umount/remount are busy "
            "until you exit this shell (Ctrl-D)",
            file=sys.stderr,
        )
    shell = os.environ.get("SHELL") or "/bin/sh"
    # Like chezmoi cd: a child cannot move the caller's directory, so become a
    # shell in the module sources instead; exiting it returns to the caller.
    os.chdir(plan["source"])
    os.execvp(shell, [shell])


def setup(plan, dry_run=False, refresh=False, *, resume=False):
    workspace = Path(plan["workspace"])
    plan["binds"] = layout_binds(plan)
    previous = load_state(workspace, required=resume)
    current = validate(plan, previous, resume=resume)
    adopt_mounted(plan, previous, current)
    describe(plan)
    report_hidden(plan)
    if not resume:
        # Validate the entire database before mounting or writing state.
        run(editor_command(plan, dry_run=True))
        warn_uncovered(plan)
    if refresh and not current:
        raise SetupError("workspace is not mounted; use mount first")
    if dry_run:
        print("Dry run: no mount, directories, database, or state were changed.")
        return
    workspace.mkdir(parents=True, exist_ok=True)
    with setup_lock(plan):
        previous = load_state(workspace, required=resume)
        current = validate(plan, previous, resume=resume)
        adopt_mounted(plan, previous, current)
        for key in ("merged", "upper", "workdir"):
            Path(plan[key]).mkdir(exist_ok=True)
        persist(plan)
        try:
            if not current:
                prepare_upper(plan)
                mount_view(plan)
            if not resume:
                run(editor_command(plan, dry_run=False))
                if plan.get("clangd_config"):
                    atomic_write(
                        Path(plan["merged"]) / ".clangd",
                        Path(plan["clangd_config"]).read_bytes(),
                        workspace / "backups",
                    )
        except BaseException:
            if not current:
                print("Setup failed; unmounting the newly created view.", file=sys.stderr)
                try:
                    unmount(plan)
                except (SetupError, OSError, subprocess.TimeoutExpired) as exc:
                    print(f"cleanup failed: {exc}; use the umount command", file=sys.stderr)
            raise
    print("\nReady: nvim " + shlex.quote(plan["merged"]))
    if resume:
        print("Reused the private upper's compile_commands.json and .clangd unchanged.")
    else:
        print(
            "The database is in the private upper; backups are in workspace/backups."
        )
    print(
        "Edits under the binds go straight to the module repository; other writes "
        "through merged/ stay in the private upper. Do not build in merged/."
    )
    if any(item["kind"] == "file" for item in plan["binds"]):
        print(
            "Single-file binds keep the file they were mounted from: remount after "
            "git replaces one of them, or after the Linux tree changes."
        )
    else:
        print("Remount after the Linux tree changes.")


def make_plan(args):
    kernel, repo, workspace = (
        absolute(v) for v in (args.kernel, args.repo, args.workspace)
    )
    return {
        "version": STATE_VERSION,
        "backend": BACKEND,
        "layout": args.layout,
        "kernel": str(kernel),
        "repo": str(repo),
        "source": str(repo / "src"),
        "workspace": str(workspace),
        "merged": str(workspace / "merged"),
        "upper": str(workspace / "upper"),
        "workdir": str(workspace / "work"),
        "binds": [],
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


def print_status(plan):
    describe(plan)
    overlay, binds, foreign = view_mounts(plan)
    expected = {item["target"] for item in plan["binds"]}
    if foreign:
        status = "FOREIGN MOUNT: " + ", ".join(foreign)
    elif overlay and set(binds) == expected:
        status = "mounted"
    elif overlay or binds:
        status = (
            f"PARTIAL ({'overlay, ' if overlay else 'no overlay, '}"
            f"{len(binds)}/{len(expected)} binds); run umount"
        )
    else:
        status = "unmounted"
    print("Status: " + status)
    return 0 if status in ("mounted", "unmounted") else 1


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
        "repo",
        help="module repository (company Ceph client or kfuse-driver worktree); "
        "its src directory is bind-mounted into the view",
    )
    mount.add_argument(
        "workspace", help="separate directory; the editor view is WORKSPACE/merged"
    )
    mount.add_argument(
        "--layout",
        choices=sorted(LAYOUTS),
        default=DEFAULT_LAYOUT,
        required=DEFAULT_LAYOUT is None,
        help="where src/ goes in the view (default from the command name: "
        f"{DEFAULT_LAYOUT or 'none'})",
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
        (
            "remount",
            "umount then resume, so replaced bound files and Linux changes show up",
        ),
        ("umount", "unmount without deleting edits or state"),
        ("status", "show recorded layers, binds, and current mount identity"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("workspace")
        if name in ("resume", "refresh"):
            command.add_argument("--dry-run", action="store_true")
    cd = commands.add_parser(
        "cd",
        help="start $SHELL in the module repository's src; exit it (Ctrl-D) to return",
    )
    cd.add_argument(
        "workspace",
        nargs="?",
        help="default: the workspace at or above the current directory",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "mount":
            setup(make_plan(args), args.dry_run)
        else:
            if args.workspace is None:
                workspace = find_workspace(Path.cwd())
            else:
                workspace = absolute(args.workspace)
            plan = load_state(workspace)
            if args.command == "cd":
                shell_in_source(plan)
            elif args.command == "resume":
                setup(plan, args.dry_run, resume=True)
            elif args.command == "refresh":
                setup(plan, args.dry_run, refresh=True)
            elif args.command == "remount":
                remount(plan)
            elif args.command == "umount":
                with setup_lock(plan):
                    unmount(plan)
            else:
                return print_status(plan)
        return 0
    except (SetupError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
