# Ceph/kernel editor overlay tools

Two independent Python 3, standard-library scripts installed in `~/.local/bin`:

- `setup-ceph-kernel-workspace.py`: mount management, safe regeneration, optional `.clangd` copy.
- `compile-commands-edit.py`: a reusable, mount-independent compilation database editor.

The old symlink-based setup script is replaced; its original is backed up under
`~/.local/share/ceph-kernel-workspace/backups`. Existing repositories and old
workspace files are not migrated or deleted automatically.

## Layout and write behavior

```text
Linux source/build tree                  lower, read-only through the overlay
company repository/src                   upper, writable
company repository/.ceph-kernel-overlay-work   dedicated FUSE work directory
company repository/.ceph-kernel-overlay.lock   serializes setup/unmount operations
company repository/.ceph-kernel-overlay-owner.json   prevents shared-upper mounts
WORKSPACE/merged                         mounted editor view
WORKSPACE/.ceph-kernel-overlay.json       mount identity and regeneration settings
WORKSPACE/backups/                       previous generated files
```

Open **only the merged path** for this editing session. Matching company files
and headers take precedence over Linux files. Directories merge. No symlink
aliases or `.nvim-workspace` detection are used.

**Every write through the mount lands in company `src`.** That includes edits to
Linux-only files, new files, `compile_commands.json`, and any editor caches. A
Linux-only write copies the file into company `src`; it does not modify the
Linux lower. This script does not make the original Linux directory globally
read-only to other processes.

Do not build in the merged tree: company module Makefiles replace some kernel
Makefiles. Do not modify either backing tree behind the mounted filesystem;
unmount before company builds, checkout/reset/pull, or updating Linux. Git's
kernel `.git` may be visible inside the mount: use the real company repository
for Git inspection, and **do not run Git-changing operations in the merged tree**.
Deletion uses overlay whiteout metadata, not simply a portable Git deletion.

Only one mount managed by this tool may use a given company `src` at once. Do
not share its upper/workdir with another manually managed overlay either.
The workdir must be on the same underlying filesystem as company `src` and
must not overlap the source directories or workspace.

## Setup

Requires Linux, Python 3.9+, `fuse-overlayfs`, `fusermount3`, and access to
`/dev/fuse`. No sudo, package installation, or kernel build is performed.

First inspect the input database:

```sh
compile-commands-edit.py ~/build_part/linux/v5.14/compile_commands.json --inspect
```

Preview a mount (no directories, state, or files are written):

```sh
setup-ceph-kernel-workspace.py mount \
  ~/build_part/linux/v5.14 \
  ~/build_part/ceph-client/5.14.0 \
  ~/build_part/ceph-client-overlay/5.14 \
  --clangd-config ~/build_part/ceph-client-work/5.14/.clangd \
  --gcc-include /usr/lib/gcc/aarch64-redhat-linux/16/include \
  --dry-run
```

Remove `--dry-run` to mount and generate the database. Then open the printed
`.../merged` path, not the old workspace root or the company backing path.
The example uses a new workspace so old symlinks, databases, and workspace
instructions remain untouched. If reusing an old workspace, its `.clangd` can
still apply as an ancestor of `merged`, but old workspace-specific `AGENTS.md`
instructions may need manual updating. To copy an existing config explicitly:

```sh
setup-ceph-kernel-workspace.py mount KERNEL CLIENT NEW_WORKSPACE \
  --clangd-config /path/to/existing/.clangd
```

No machine-specific `.clangd` is invented. `--gcc-include` is optional: supply a
real compiler builtin include directory containing `stdarg.h` when the captured
commands refer to a stale GCC installation. It only repairs recognized stale
GCC builtin `-isystem` paths. The editor never launches a compiler.

By default, setup maps the common prefix of input compilation directories and
source paths to the merged mountpoint. The editor prints the detected prefix.
Inspect it first; a common ancestor is not necessarily your intended project
root, especially for databases combining separate projects or build trees.
Use an explicit original prefix when appropriate:

```sh
setup-ceph-kernel-workspace.py mount KERNEL CLIENT WORKSPACE \
  --source-prefix /old/machine/linux \
  --map /old/sdk /current/sdk
```

Additional options:

- `--database FILE`: read a different input database; default `KERNEL/compile_commands.json`.
- `--workdir DIR`: select a dedicated workdir on the upper filesystem.
- `--map OLD NEW`: additional database mappings; repeatable, longest match wins.
- `--clangd-config FILE`: copy into `merged/.clangd`, backing up an existing file.

Manage the mount:

```sh
setup-ceph-kernel-workspace.py status WORKSPACE
setup-ceph-kernel-workspace.py resume WORKSPACE --dry-run
setup-ceph-kernel-workspace.py resume WORKSPACE
setup-ceph-kernel-workspace.py refresh WORKSPACE --dry-run
setup-ceph-kernel-workspace.py refresh WORKSPACE
setup-ceph-kernel-workspace.py unmount WORKSPACE
```

After reboot or an ordinary unmount, use `resume WORKSPACE` to restore the
recorded layers and workdir. It leaves company `src/compile_commands.json` and
`.clangd` untouched: no database parsing, transformation, copying, or backups.
It requires saved workspace state and an existing regular, non-symlink database
in company `src`, but not the original input database, `.clangd` source, or GCC
include directory. An already-active matching mount is reused; foreign mounts
are still refused. `--dry-run` checks without mounting or writing anything.

Resume assumes the existing database is still appropriate; it does not check
its contents or freshness. If paths or build configuration changed, regenerate
with `refresh` after resuming, or repeat `mount` instead. If the generated
database is missing, use `mount` to regenerate it.

`refresh` requires an active matching mount and reuses saved options. Repeating
`mount` with matching layers also refreshes the database; provide any desired
non-default options again. Layer changes require a separate workspace.
Close buffers/processes using the mount before unmounting. A busy unmount fails
normally; the script never uses lazy/forced unmounts or deletes source files.

## Database editor independently

```sh
# Examine paths without writing anything.
compile-commands-edit.py INPUT.json --inspect

# Explicit remapping. No prefix substring collisions (linux != linux-old).
compile-commands-edit.py INPUT.json -o OUTPUT.json \
  --map /old/linux /new/merged \
  --map /old/sdk /new/sdk

# Infer one shared prefix, preview, then write.
compile-commands-edit.py INPUT.json --map-common-prefix /new/merged --dry-run
compile-commands-edit.py INPUT.json --map-common-prefix /new/merged -o OUTPUT.json

# Safely update a database in place (a backup is made first).
compile-commands-edit.py compile_commands.json -o compile_commands.json \
  --map /old/linux /new/merged
```

Mappings apply to compilation directories, source/output paths, and recognized
GCC/Clang path operands. They are simultaneous and component-boundary-aware,
with the longest original prefix winning. Relative path operands are interpreted
against the original compilation directory before remapping. Output paths are
not resolved through symlinks into backing repositories.

Both `arguments` and shell-quoted `command` entries are supported, including
when both fields exist. This is a compilation-command editor, not a shell
interpreter: unsupported shell constructs are rejected instead of silently
rewritten. Arbitrary `-D` macro strings are not treated as paths. Response-file
references may be mapped, but response-file contents are not edited. No missing
translation units are synthesized, and commands are not executed or checked
for successful compilation.

The entire database is validated before writing. Existing regular output files
are backed up (use `--backup-dir DIR` to relocate backups), then replaced via a
temporary file and atomic rename. Symlink and nonregular outputs are refused.
The original input is unchanged unless it is explicitly also the output.

## Failure behavior

- Invalid paths, unsafe output symlinks, conflicting mounts, nonempty mountpoints,
  unowned nonempty workdirs, or malformed input databases (during generation)
  are rejected. Resume checks the generated database's file type, not its contents.
- A foreign mount is never refreshed or unmounted.
- State is persisted before mounting, then updated with the actual mount
  ID/device, boot ID, and mount namespace. Those identifiers prevent treating
  a replacement or foreign mount as our own. A crash in the small interval
  between mounting and recording that identity requires manual verification
  and unmounting; the script deliberately refuses to guess ownership.
- If generation fails after a new mount, setup attempts to unmount that new
  view. It does not unmount an already-active view on refresh failure.
- Generated files and backups already written are retained after failures;
  cleanup is not a transaction that rolls back company edits.
- A process crash or power loss can leave a mount/state for explicit recovery.
  Use `status` and `unmount`; never recursively remove a mounted directory.

## Tests

```sh
python3 -m unittest discover \
  -s ~/.local/share/ceph-kernel-workspace/tests -v

# Adds a real mount/unmount test using disposable fixtures only.
RUN_FUSE_TESTS=1 python3 -m unittest discover \
  -s ~/.local/share/ceph-kernel-workspace/tests -v

# Optional: put disposable fixtures on a particular filesystem.
RUN_FUSE_TESTS=1 FUSE_TEST_ROOT=/path/on/virtiofs python3 -m unittest discover \
  -s ~/.local/share/ceph-kernel-workspace/tests -v
```

`WORKSPACE_TOOLS_BIN=/alternate/bin` selects alternative script versions for
these tests. Real-mount tests never use your kernel or company repository as a
layer; they create tiny disposable source trees and verify that the lower file
contents remain unchanged.
