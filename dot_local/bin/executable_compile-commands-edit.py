#!/usr/bin/env python3
"""Safely edit a Linux GCC/Clang JSON compilation database.

The editor performs lexical (not realpath) POSIX path mapping.  It supports the
usual compile_commands.json ``arguments`` and simple shell-quoted ``command``
forms, common GCC/Clang path options, response-file references, dependency
paths passed with ``-Wp``, and GCC prefix-map options.  Response-file contents
are deliberately not read or changed.

This is not a general shell rewriter.  A ``command`` containing active shell
operators, redirections, glob/brace/tilde expansion, parameter or command
expansion is rejected.  Quoted literal macro values are supported.  No
compiler or shell process is executed.
"""

from __future__ import annotations

import argparse
import copy
import datetime as _datetime
import json
import os
import re
import shlex
import shutil
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


class EditError(Exception):
    """An input or safety error suitable for showing to a CLI user."""


def _require_path_text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise EditError("{} must be a non-empty string".format(description))
    if "\0" in value:
        raise EditError("{} contains a NUL byte".format(description))
    return value


def lexical_absolute(path: str, base: str) -> str:
    """Return an absolute, lexical POSIX path without resolving symlinks."""
    _require_path_text(path, "path")
    if os.path.isabs(path):
        result = os.path.normpath(path)
    else:
        result = os.path.normpath(os.path.join(base, path))
    # POSIX normpath intentionally preserves exactly two leading slashes, but
    # that implementation-defined namespace is outside this Linux tool's
    # scope.  Collapse it so component-prefix comparisons have one spelling.
    if result.startswith("//"):
        result = "/" + result.lstrip("/")
    if not os.path.isabs(result):  # Defensive: callers always pass abs bases.
        result = os.path.normpath(os.path.join(os.getcwd(), result))
    return result


def path_is_within(path: str, prefix: str) -> bool:
    if prefix == "/":
        return path.startswith("/")
    return path == prefix or path.startswith(prefix + os.sep)


@dataclass(frozen=True)
class PathMap:
    source: str
    destination: str
    origin: str


class PathMapper:
    """Apply the longest matching component-bounded map exactly once."""

    def __init__(self, mappings: Iterable[PathMap]):
        by_source: Dict[str, PathMap] = {}
        for mapping in mappings:
            previous = by_source.get(mapping.source)
            if previous is not None:
                if previous.destination != mapping.destination:
                    raise EditError(
                        "conflicting mappings for {!r}: {!r} ({}) and {!r} ({})".format(
                            mapping.source,
                            previous.destination,
                            previous.origin,
                            mapping.destination,
                            mapping.origin,
                        )
                    )
                continue
            by_source[mapping.source] = mapping
        self.mappings = sorted(
            by_source.values(),
            key=lambda item: (len(item.source.split(os.sep)), len(item.source)),
            reverse=True,
        )

    def apply(self, path: str) -> str:
        path = lexical_absolute(path, "/")
        for mapping in self.mappings:
            if not path_is_within(path, mapping.source):
                continue
            if mapping.source == "/":
                suffix = path.lstrip("/")
            else:
                suffix = path[len(mapping.source) :].lstrip("/")
            if not suffix:
                return mapping.destination
            return lexical_absolute(suffix, mapping.destination)
        return path


@dataclass
class SourceEntry:
    index: int
    directory: str
    file: str
    output: Optional[str]
    command_argv: Optional[List[str]]


@dataclass
class RewriteStats:
    entries: int = 0
    argument_entries: int = 0
    command_entries: int = 0
    both_entries: int = 0
    entries_changed: int = 0
    directory_fields_changed: int = 0
    file_fields_changed: int = 0
    output_fields_changed: int = 0
    argument_tokens_changed: int = 0
    command_tokens_changed: int = 0
    gcc_includes_replaced: int = 0


# Options whose following argv element is a filesystem path.  Joined spelling
# is handled separately for options for which GCC/Clang conventionally allows
# it.  The list is intentionally bounded rather than guessing about every
# option value.
SEPARATE_PATH_OPTIONS = frozenset(
    {
        "-I",
        "-isystem",
        "-isystem-after",
        "-iquote",
        "-idirafter",
        "-include",
        "-include-pch",
        "-imacros",
        "-isysroot",
        "--sysroot",
        "-o",
        "-MF",
        "-MJ",
        "-B",
        "-L",
        "-F",
        "-iframework",
        "-iframeworkwithsysroot",
        "--gcc-toolchain",
        "-gcc-toolchain",
        "-resource-dir",
        "-working-directory",
        "-dependency-file",
        "-serialize-diagnostics",
        "-fmodule-map-file",
        "-fmodules-cache-path",
        "-ivfsoverlay",
        "--config",
        "-fprofile-list",
        "-fprofile-remapping-file",
    }
)

# Check longest names first so, for example, -isystem is not confused with a
# shorter spelling.  The option prefix is retained byte-for-byte.
JOINED_PATH_OPTIONS = (
    "-iframeworkwithsysroot",
    "-isystem-after",
    "-idirafter",
    "-isystem",
    "-iquote",
    "-isysroot",
    "-imacros",
    "-include",
    "-MF",
    "-MJ",
    "-I",
    "-o",
    "-B",
    "-L",
    "-F",
)

# Long path options are accepted as --option=PATH (or -option=PATH) in
# addition to their separate spelling.  Requiring '=' avoids interpreting an
# unrelated option that merely shares a prefix.
EQUALS_PATH_OPTIONS = tuple(
    sorted(
        {
            "--sysroot",
            "--gcc-toolchain",
            "-gcc-toolchain",
            "-resource-dir",
            "-working-directory",
            "-dependency-file",
            "-serialize-diagnostics",
            "-fmodule-map-file",
            "-fmodules-cache-path",
            "-ivfsoverlay",
            "--config",
            "-fprofile-list",
            "-fprofile-remapping-file",
            "-include-pch",
        },
        key=len,
        reverse=True,
    )
)

# Their values are deliberately not treated as paths.  This chiefly prevents
# a separate -D value containing a mapped-looking string from being changed.
NON_PATH_OPTIONS_WITH_VALUE = frozenset(
    {
        "-D",
        "-U",
        "-A",
        "-x",
        "-std",
        "-target",
        "--target",
        "-arch",
        "-mllvm",
        "-Xclang",
        "-Xassembler",
        "-Xlinker",
    }
)

PREFIX_MAP_OPTIONS = (
    "-fdebug-prefix-map=",
    "-ffile-prefix-map=",
    "-fmacro-prefix-map=",
    "-fprofile-prefix-map=",
)

WP_SEPARATE_PATH_OPTIONS = frozenset(
    {"-MD", "-MMD", "-MF", "-MJ", "-dependency-file", "-I", "-isystem"}
)
WP_JOINED_PATH_OPTIONS = ("-MMD", "-MF", "-MJ", "-MD", "-I", "-isystem")


def validate_simple_command(command: str, entry_index: int) -> List[str]:
    """Reject active shell syntax, then parse a simple command with shlex."""
    if not command:
        raise EditError("entry {} 'command' must not be empty".format(entry_index))
    if "\0" in command:
        raise EditError("entry {} 'command' contains a NUL byte".format(entry_index))

    quote: Optional[str] = None
    escaped = False
    at_word_start = True
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            if char == "\n":
                raise EditError(
                    "entry {} command uses a shell line continuation".format(
                        entry_index
                    )
                )
            escaped = False
            at_word_start = False
            index += 1
            continue

        if quote == "'":
            if char == "'":
                quote = None
            index += 1
            continue

        if quote == '"':
            if char == '"':
                quote = None
            elif char == "\\":
                escaped = True
            elif char in "$`":
                raise EditError(
                    "entry {} command uses shell expansion inside double quotes".format(
                        entry_index
                    )
                )
            elif char == "\n":
                raise EditError(
                    "entry {} command contains an unsupported newline".format(
                        entry_index
                    )
                )
            index += 1
            continue

        if char == "\\":
            escaped = True
        elif char in "'\"":
            quote = char
            at_word_start = False
        elif char.isspace():
            if char == "\n":
                raise EditError(
                    "entry {} command contains an unsupported newline".format(
                        entry_index
                    )
                )
            at_word_start = True
        elif char in ";|&<>()":
            raise EditError(
                "entry {} command uses unsupported shell operator {!r}".format(
                    entry_index, char
                )
            )
        elif char in "$`":
            raise EditError(
                "entry {} command uses unsupported shell expansion".format(entry_index)
            )
        elif char in "*?[{}":
            raise EditError(
                "entry {} command uses unsupported unquoted shell expansion syntax {!r}".format(
                    entry_index, char
                )
            )
        elif char == "~" and at_word_start:
            raise EditError(
                "entry {} command uses unsupported tilde expansion".format(entry_index)
            )
        elif char == "#" and at_word_start:
            raise EditError(
                "entry {} command uses an unsupported shell comment".format(entry_index)
            )
        else:
            at_word_start = False
        index += 1

    if escaped:
        raise EditError("entry {} command ends with a backslash".format(entry_index))
    if quote is not None:
        raise EditError(
            "entry {} command has an unterminated quote".format(entry_index)
        )

    try:
        argv = shlex.split(command, comments=False, posix=True)
    except ValueError as exc:
        raise EditError(
            "entry {} command cannot be parsed safely: {}".format(entry_index, exc)
        ) from exc
    if not argv:
        raise EditError("entry {} 'command' has no arguments".format(entry_index))
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
        raise EditError(
            "entry {} command starts with a shell assignment; use 'env NAME=value compiler ...' instead".format(
                entry_index
            )
        )
    if any("\0" in token for token in argv):
        raise EditError("entry {} command contains a NUL argument".format(entry_index))
    return argv


def _reject_duplicate_keys(pairs: Sequence[Tuple[str, object]]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EditError("JSON object contains duplicate key {!r}".format(key))
        result[key] = value
    return result


def load_database(input_path: str) -> object:
    try:
        with open(input_path, "r", encoding="utf-8") as handle:
            return json.load(
                handle,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    EditError("JSON contains non-standard constant {}".format(value))
                ),
            )
    except EditError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EditError("cannot read {}: {}".format(input_path, exc)) from exc


def validate_database(database: object, database_parent: str) -> List[SourceEntry]:
    if not isinstance(database, list):
        raise EditError("compilation database must be a JSON array")

    sources: List[SourceEntry] = []
    for index, entry in enumerate(database):
        label = "entry {}".format(index)
        if not isinstance(entry, dict):
            raise EditError("{} must be a JSON object".format(label))

        if "directory" not in entry:
            raise EditError("{} is missing 'directory'".format(label))
        if "file" not in entry:
            raise EditError("{} is missing 'file'".format(label))
        raw_directory = _require_path_text(entry["directory"], label + " 'directory'")
        raw_file = _require_path_text(entry["file"], label + " 'file'")
        directory = lexical_absolute(raw_directory, database_parent)
        source_file = lexical_absolute(raw_file, directory)

        output: Optional[str] = None
        if "output" in entry:
            raw_output = _require_path_text(entry["output"], label + " 'output'")
            output = lexical_absolute(raw_output, directory)

        has_arguments = "arguments" in entry
        has_command = "command" in entry
        if not has_arguments and not has_command:
            raise EditError(
                "{} must contain 'arguments', 'command', or both".format(label)
            )

        if has_arguments:
            arguments = entry["arguments"]
            if not isinstance(arguments, list) or not arguments:
                raise EditError(
                    "{} 'arguments' must be a non-empty JSON array".format(label)
                )
            for argument_index, token in enumerate(arguments):
                if not isinstance(token, str):
                    raise EditError(
                        "{} 'arguments'[{}] must be a string".format(
                            label, argument_index
                        )
                    )
                if "\0" in token:
                    raise EditError(
                        "{} 'arguments'[{}] contains a NUL byte".format(
                            label, argument_index
                        )
                    )

        command_argv: Optional[List[str]] = None
        if has_command:
            command = entry["command"]
            if not isinstance(command, str):
                raise EditError("{} 'command' must be a string".format(label))
            command_argv = validate_simple_command(command, index)

        sources.append(SourceEntry(index, directory, source_file, output, command_argv))

    return sources


def common_entry_prefix(sources: Sequence[SourceEntry]) -> Optional[str]:
    if not sources:
        return None
    paths: List[str] = []
    for source in sources:
        paths.append(source.directory)
        paths.append(source.file)
    try:
        return lexical_absolute(os.path.commonpath(paths), "/")
    except ValueError as exc:
        raise EditError(
            "cannot derive one lexical common prefix: {}".format(exc)
        ) from exc


class ArgvRewriter:
    def __init__(
        self,
        mapper: PathMapper,
        original_directory: str,
        new_directory: str,
        original_file: str,
        original_output: Optional[str],
        gcc_include: Optional[str],
    ):
        self.mapper = mapper
        self.original_directory = original_directory
        self.new_directory = new_directory
        self.original_file = original_file
        self.original_output = original_output
        self.gcc_include = gcc_include
        self.changed = 0
        self.gcc_replaced = 0

    def _rewrite_path(self, value: str, *, force_relative: bool = True) -> str:
        if not value or "\0" in value:
            return value
        original_absolute = lexical_absolute(value, self.original_directory)
        mapped_absolute = self.mapper.apply(original_absolute)
        if os.path.isabs(value):
            return mapped_absolute
        if not force_relative:
            return value
        # Keep the original relative spelling when it already names the mapped
        # object from the mapped working directory.  This avoids gratuitously
        # turning -I./include into -Iinclude.
        if lexical_absolute(value, self.new_directory) == mapped_absolute:
            return value
        return os.path.relpath(mapped_absolute, self.new_directory)

    def _looks_like_stale_gcc_include(self, value: str) -> bool:
        if not value:
            return False
        candidate = value[1:] if value.startswith("=") else value
        absolute = lexical_absolute(candidate, self.original_directory)
        parts = tuple(part for part in absolute.split(os.sep) if part)
        if (
            os.path.basename(absolute) != "include"
            or "gcc" not in parts
            or "lib" not in parts
        ):
            return False
        return not os.path.isfile(os.path.join(absolute, "stdarg.h"))

    def _rewrite_isystem_path(self, value: str) -> str:
        if self.gcc_include is not None and self._looks_like_stale_gcc_include(value):
            self.gcc_replaced += 1
            if value.startswith("="):
                return "=" + self.gcc_include
            return self.gcc_include
        return self._rewrite_path(value)

    def _rewrite_prefix_map(self, token: str) -> str:
        for option in PREFIX_MAP_OPTIONS:
            if not token.startswith(option):
                continue
            payload = token[len(option) :]
            if "=" not in payload:
                return token
            left, virtual_right = payload.split("=", 1)
            if not left:
                return token
            rewritten_left = self._rewrite_path(left)
            return option + rewritten_left + "=" + virtual_right
        return token

    def _rewrite_wp(self, token: str) -> str:
        if not token.startswith("-Wp,"):
            return token
        components = token.split(",")
        index = 1
        while index < len(components):
            component = components[index]
            if component in WP_SEPARATE_PATH_OPTIONS and index + 1 < len(components):
                value_index = index + 1
                old_value = components[value_index]
                if component == "-isystem":
                    components[value_index] = self._rewrite_isystem_path(old_value)
                else:
                    components[value_index] = self._rewrite_path(old_value)
                index += 2
                continue
            handled = False
            for option in WP_JOINED_PATH_OPTIONS:
                if component.startswith(option) and len(component) > len(option):
                    old_value = component[len(option) :]
                    if option == "-isystem":
                        new_value = self._rewrite_isystem_path(old_value)
                    else:
                        new_value = self._rewrite_path(old_value)
                    components[index] = option + new_value
                    handled = True
                    break
            index += 1
            if handled:
                continue
        return ",".join(components)

    def _rewrite_bare(self, token: str) -> str:
        if not token or token == "-":
            return token
        if os.path.isabs(token):
            return self._rewrite_path(token)

        absolute = lexical_absolute(token, self.original_directory)
        if absolute == self.original_file or (
            self.original_output is not None and absolute == self.original_output
        ):
            return self._rewrite_path(token)

        # Relative positional names containing a slash are file-like in the
        # supported compiler command shape.  Plain names are left alone so a
        # PATH-resolved compiler or an unrelated option value cannot become a
        # filesystem-relative path after a directory-only mapping.
        if "/" in token or token.startswith("."):
            return self._rewrite_path(token)
        return token

    def rewrite(self, argv: Sequence[str]) -> Tuple[List[str], int, int]:
        result = list(argv)
        index = 0
        end_options = False
        while index < len(result):
            token = result[index]
            new_token = token

            if end_options:
                new_token = self._rewrite_bare(token)
            elif token == "--":
                end_options = True
            elif any(token.startswith(option) for option in PREFIX_MAP_OPTIONS):
                new_token = self._rewrite_prefix_map(token)
            elif token.startswith("-Wp,"):
                new_token = self._rewrite_wp(token)
            elif token.startswith("@") and len(token) > 1:
                new_token = "@" + self._rewrite_path(token[1:])
            elif token in SEPARATE_PATH_OPTIONS:
                if index + 1 >= len(result):
                    raise EditError("path option {!r} has no argument".format(token))
                old_value = result[index + 1]
                if token == "-isystem":
                    new_value = self._rewrite_isystem_path(old_value)
                else:
                    new_value = self._rewrite_path(old_value)
                if new_value != old_value:
                    result[index + 1] = new_value
                    self.changed += 1
                index += 2
                continue
            else:
                equals_match = None
                for option in EQUALS_PATH_OPTIONS:
                    prefix = option + "="
                    if token.startswith(prefix):
                        equals_match = prefix
                        break
                if equals_match is not None:
                    value = token[len(equals_match) :]
                    if value:
                        new_token = equals_match + self._rewrite_path(value)
                else:
                    joined_match = None
                    for option in JOINED_PATH_OPTIONS:
                        if token.startswith(option) and len(token) > len(option):
                            joined_match = option
                            break
                    if joined_match is not None:
                        value = token[len(joined_match) :]
                        if joined_match == "-isystem":
                            new_value = self._rewrite_isystem_path(value)
                        else:
                            new_value = self._rewrite_path(value)
                        new_token = joined_match + new_value
                    elif token in NON_PATH_OPTIONS_WITH_VALUE:
                        # Do not inspect or rewrite this unrelated value.
                        index += 2 if index + 1 < len(result) else 1
                        continue
                    elif token.startswith("-"):
                        pass
                    else:
                        new_token = self._rewrite_bare(token)

            if new_token != token:
                result[index] = new_token
                self.changed += 1
            index += 1

        return result, self.changed, self.gcc_replaced


def rewrite_database(
    database: List[object],
    sources: Sequence[SourceEntry],
    mapper: PathMapper,
    gcc_include: Optional[str],
) -> Tuple[List[object], RewriteStats]:
    result = copy.deepcopy(database)
    stats = RewriteStats(entries=len(sources))

    for source in sources:
        old_entry = database[source.index]
        entry = result[source.index]
        assert isinstance(old_entry, dict) and isinstance(entry, dict)

        has_arguments = "arguments" in old_entry
        has_command = "command" in old_entry
        stats.argument_entries += int(has_arguments)
        stats.command_entries += int(has_command)
        stats.both_entries += int(has_arguments and has_command)

        new_directory = mapper.apply(source.directory)
        new_file = mapper.apply(source.file)
        new_output = mapper.apply(source.output) if source.output is not None else None

        if entry["directory"] != new_directory:
            entry["directory"] = new_directory
            stats.directory_fields_changed += 1
        if entry["file"] != new_file:
            entry["file"] = new_file
            stats.file_fields_changed += 1
        if source.output is not None and entry["output"] != new_output:
            entry["output"] = new_output
            stats.output_fields_changed += 1

        if has_arguments:
            arguments = old_entry["arguments"]
            assert isinstance(arguments, list)
            rewriter = ArgvRewriter(
                mapper,
                source.directory,
                new_directory,
                source.file,
                source.output,
                gcc_include,
            )
            rewritten, changed, gcc_replaced = rewriter.rewrite(arguments)
            if changed:
                entry["arguments"] = rewritten
            stats.argument_tokens_changed += changed
            stats.gcc_includes_replaced += gcc_replaced

        if has_command:
            assert source.command_argv is not None
            rewriter = ArgvRewriter(
                mapper,
                source.directory,
                new_directory,
                source.file,
                source.output,
                gcc_include,
            )
            rewritten, changed, gcc_replaced = rewriter.rewrite(source.command_argv)
            if changed:
                entry["command"] = shlex.join(rewritten)
            stats.command_tokens_changed += changed
            stats.gcc_includes_replaced += gcc_replaced

        if entry != old_entry:
            stats.entries_changed += 1

    return result, stats


def inspect_existing_output(path: str) -> Optional[os.stat_result]:
    if not os.path.lexists(path):
        return None
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise EditError("cannot inspect output {}: {}".format(path, exc)) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise EditError("refusing symlink output {}".format(path))
    if not stat.S_ISREG(metadata.st_mode):
        raise EditError("refusing non-regular output {}".format(path))
    return metadata


def validate_output_location(path: str) -> Optional[os.stat_result]:
    metadata = inspect_existing_output(path)
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise EditError("output parent is not an existing directory: {}".format(parent))
    return metadata


def make_backup(output: str, backup_dir: Optional[str]) -> str:
    target_directory = backup_dir or os.path.dirname(output)
    try:
        os.makedirs(target_directory, mode=0o700, exist_ok=True)
    except OSError as exc:
        raise EditError(
            "cannot create backup directory {}: {}".format(target_directory, exc)
        ) from exc
    if not os.path.isdir(target_directory):
        raise EditError(
            "backup location is not a directory: {}".format(target_directory)
        )

    timestamp = _datetime.datetime.now(_datetime.timezone.utc).strftime(
        "%Y%m%d-%H%M%S.%fZ"
    )
    source_mode = stat.S_IMODE(os.stat(output).st_mode)
    for _attempt in range(10):
        unique = uuid.uuid4().hex[:12]
        backup = os.path.join(
            target_directory,
            "{}.bak.{}.{}".format(os.path.basename(output), timestamp, unique),
        )
        try:
            descriptor = os.open(
                backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, source_mode or 0o600
            )
        except FileExistsError:
            continue
        except OSError as exc:
            raise EditError("cannot create backup {}: {}".format(backup, exc)) from exc

        try:
            with (
                open(output, "rb") as source_handle,
                os.fdopen(descriptor, "wb") as backup_handle,
            ):
                shutil.copyfileobj(source_handle, backup_handle)
                backup_handle.flush()
                os.fsync(backup_handle.fileno())
            try:
                shutil.copystat(output, backup, follow_symlinks=False)
            except OSError:
                # The bytes are the safety property; metadata preservation is
                # best effort on filesystems that reject timestamp changes.
                pass
            return backup
        except Exception as exc:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(backup)
            except OSError:
                pass
            if isinstance(exc, EditError):
                raise
            raise EditError("cannot back up {}: {}".format(output, exc)) from exc

    raise EditError("could not allocate a unique backup name for {}".format(output))


def atomic_write(
    output: str,
    payload: bytes,
    initial_metadata: Optional[os.stat_result],
) -> None:
    parent = os.path.dirname(output)
    prefix = ".{}.".format(os.path.basename(output))
    descriptor = -1
    temporary: Optional[str] = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=prefix, suffix=".tmp", dir=parent
        )
        mode = (
            stat.S_IMODE(initial_metadata.st_mode)
            if initial_metadata is not None
            else 0o644
        )
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        current = inspect_existing_output(output)
        if initial_metadata is None:
            if current is not None:
                raise EditError("output appeared while editing; refusing to replace it")
        elif current is None or (
            current.st_dev != initial_metadata.st_dev
            or current.st_ino != initial_metadata.st_ino
        ):
            raise EditError("output changed while editing; refusing to replace it")

        os.replace(temporary, output)
        temporary = None
    except EditError:
        raise
    except OSError as exc:
        raise EditError("cannot atomically write {}: {}".format(output, exc)) from exc
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def report(
    input_path: str,
    common_prefix: Optional[str],
    mapper: PathMapper,
    stats: RewriteStats,
    mode: str,
    output: Optional[str],
    backup: Optional[str],
) -> None:
    print("input: {}".format(input_path))
    if common_prefix is None:
        print("detected common prefix: <none; empty database>")
    elif common_prefix == "/":
        print("detected common prefix: / (unsafe for automatic mapping)")
    else:
        print("detected common prefix: {}".format(common_prefix))
    print("entries: {}".format(stats.entries))
    print("arguments entries: {}".format(stats.argument_entries))
    print("command entries: {}".format(stats.command_entries))
    print("entries with both forms: {}".format(stats.both_entries))
    print("active mappings: {}".format(len(mapper.mappings)))
    for mapping in mapper.mappings:
        print(
            "  map {} -> {} ({})".format(
                mapping.source, mapping.destination, mapping.origin
            )
        )
    print("entries changed: {}".format(stats.entries_changed))
    print("argument path tokens changed: {}".format(stats.argument_tokens_changed))
    print("command path tokens changed: {}".format(stats.command_tokens_changed))
    print("stale GCC includes replaced: {}".format(stats.gcc_includes_replaced))
    print("mode: {}".format(mode))
    if output is not None:
        print("output: {}".format(output))
    if backup is not None:
        print("backup: {}".format(backup))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Lexically map paths in a Linux GCC/Clang compilation database. "
            "Simple shlex-compatible command lines are supported; active shell "
            "syntax is rejected and response-file contents are not edited."
        ),
        epilog=(
            "Map destinations are not required to exist. Relative entry "
            "directories use INPUT's parent; relative entry file/output and "
            "compiler path operands use each entry's original directory."
        ),
    )
    parser.add_argument("input", metavar="INPUT", help="input compile_commands JSON")
    parser.add_argument("-o", "--output", metavar="PATH", help="atomic output path")
    parser.add_argument(
        "--map",
        dest="maps",
        action="append",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=[],
        help="component-bounded lexical path mapping (repeatable)",
    )
    parser.add_argument(
        "--map-common-prefix",
        metavar="NEW",
        help="map the detected common entry/source prefix to NEW",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="validate and print detected prefix/counts without writing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate, transform, and report without writing",
    )
    parser.add_argument(
        "--backup-dir",
        metavar="DIR",
        help="put backups of an existing output in DIR (default: beside output)",
    )
    parser.add_argument(
        "--gcc-include",
        metavar="DIR",
        help=(
            "replace stale .../lib/.../gcc/.../include -isystem paths with DIR; "
            "DIR/stdarg.h must exist"
        ),
    )
    return parser


def run(options: argparse.Namespace) -> int:
    cwd = lexical_absolute(os.getcwd(), "/")
    input_path = lexical_absolute(options.input, cwd)
    if not os.path.isfile(input_path):
        raise EditError("input is not a regular readable file: {}".format(input_path))
    database_parent = os.path.dirname(input_path)

    database = load_database(input_path)
    sources = validate_database(database, database_parent)
    common_prefix = common_entry_prefix(sources)

    mappings: List[PathMap] = []
    for map_index, pair in enumerate(options.maps, start=1):
        old, new = pair
        source = lexical_absolute(_require_path_text(old, "--map OLD"), cwd)
        destination = lexical_absolute(_require_path_text(new, "--map NEW"), cwd)
        mappings.append(PathMap(source, destination, "--map #{}".format(map_index)))

    if options.map_common_prefix is not None:
        if common_prefix is None:
            raise EditError("cannot automatically map the prefix of an empty database")
        if common_prefix == "/":
            raise EditError("refusing unsafe automatic mapping from root '/'")
        destination = lexical_absolute(
            _require_path_text(options.map_common_prefix, "--map-common-prefix NEW"),
            cwd,
        )
        mappings.append(PathMap(common_prefix, destination, "--map-common-prefix"))

    mapper = PathMapper(mappings)

    gcc_include: Optional[str] = None
    if options.gcc_include is not None:
        gcc_include = lexical_absolute(
            _require_path_text(options.gcc_include, "--gcc-include DIR"), cwd
        )
        if not os.path.isdir(gcc_include) or not os.path.isfile(
            os.path.join(gcc_include, "stdarg.h")
        ):
            raise EditError(
                "--gcc-include is unusable; expected regular file {}".format(
                    os.path.join(gcc_include, "stdarg.h")
                )
            )

    assert isinstance(database, list)
    rewritten, stats = rewrite_database(database, sources, mapper, gcc_include)

    no_write = options.inspect or options.dry_run
    output: Optional[str] = None
    initial_metadata: Optional[os.stat_result] = None
    if options.output is not None:
        output = lexical_absolute(options.output, cwd)
        # A dry run still rejects an already-present unsafe target, but it does
        # not require a not-yet-created parent directory.
        if no_write:
            initial_metadata = inspect_existing_output(output)
        else:
            initial_metadata = validate_output_location(output)
    elif not no_write:
        raise EditError("-o/--output is required unless --inspect or --dry-run is used")

    backup_dir: Optional[str] = None
    if options.backup_dir is not None:
        backup_dir = lexical_absolute(options.backup_dir, cwd)

    if no_write:
        mode_parts = []
        if options.inspect:
            mode_parts.append("inspect")
        if options.dry_run:
            mode_parts.append("dry-run")
        report(
            input_path,
            common_prefix,
            mapper,
            stats,
            "+".join(mode_parts),
            output,
            None,
        )
        return 0

    try:
        serialized = (
            json.dumps(
                rewritten, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise EditError(
            "cannot serialize transformed database: {}".format(exc)
        ) from exc

    backup: Optional[str] = None
    if initial_metadata is not None:
        backup = make_backup(output, backup_dir)
    atomic_write(output, serialized, initial_metadata)
    report(input_path, common_prefix, mapper, stats, "write", output, backup)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)
    try:
        return run(options)
    except EditError as exc:
        parser.exit(2, "{}: error: {}\n".format(parser.prog, exc))
    return 2


if __name__ == "__main__":
    sys.exit(main())
