"""Optimize Gradle build outputs, never upstream wheels or application sources.

Run after Chaquopy creates requirements archives and before it hashes assets.
Unstripped libraries and an audit report stay outside the APK for diagnostics.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from zipfile import ZipFile

try:
    from scripts.android_apk_size import elf_sections
except ModuleNotFoundError:
    from android_apk_size import elf_sections


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def runtime_layout(data):
    """Compare loadable sections and segment mappings, including RELRO.

    Removing debug sections may move segments within the file. Their virtual
    addresses, sizes, flags and alignment must stay identical.
    """
    sections = {n: s for n, s in elf_sections(data).items() if s["flags"] & 2}
    endian = "<" if data[5] == 1 else ">"
    offset = struct.unpack_from(endian + "Q", data, 32)[0]
    size, count = struct.unpack_from(endian + "HH", data, 54)
    segments = []
    for index in range(count):
        kind, flags, file_offset, virtual, physical, filesz, memsz, alignment = struct.unpack_from(
            endian + "IIQQQQQQ", data, offset + index * size)
        if kind == 1 and alignment > 1 and file_offset % alignment != virtual % alignment:
            raise ValueError("Misaligned ELF load segment")
        segments.append((kind, flags, virtual, physical, filesz, memsz, alignment))
    return sections, segments


def optimize_requirements(root, output, strip_tool):
    archives = sorted(root.rglob("requirements-*.imy"))
    if not archives:
        raise ValueError(f"No Chaquopy requirements archives in {root}")
    executable = shutil.which(str(strip_tool))
    if not executable:
        raise ValueError("LLVM strip is required: set ANIMAN_LLVM_STRIP to llvm-strip (or the NDK tool)")
    tool_version = subprocess.check_output([executable, "--version"], text=True).strip()
    if "llvm" not in tool_version.lower():
        raise ValueError("Use LLVM strip, not the host-only GNU strip")
    output.mkdir(parents=True, exist_ok=True)
    report = {"tool": tool_version, "flag": "--strip-unneeded", "libraries": [],
              "archives": [], "runtime_tested": False}
    with tempfile.TemporaryDirectory(prefix="animan-strip-", dir=output) as temp:
        workspace = Path(temp)
        pending = []
        for index, archive in enumerate(archives):
            replacement = workspace / f"{index}.imy"
            with ZipFile(archive) as original, ZipFile(replacement, "w") as optimized:
                optimized.comment = original.comment
                for entry in original.infolist():
                    data = original.read(entry)
                    if entry.filename.endswith(".so") and data.startswith(b"\x7fELF"):
                        sections = elf_sections(data)
                        if any(n.startswith((".debug", ".zdebug")) or n in (".symtab", ".strtab")
                               for n in sections):
                            before = sha256(data)
                            source = workspace / "input.so"
                            target = workspace / "output.so"
                            source.write_bytes(data)
                            subprocess.run([executable, "--strip-unneeded", str(source),
                                            "-o", str(target)], check=True)
                            stripped = target.read_bytes()
                            if runtime_layout(data) != runtime_layout(stripped):
                                raise ValueError(f"LLVM changed runtime ELF layout: {entry.filename}")
                            if len(stripped) >= len(data):
                                raise ValueError(f"LLVM did not reduce {entry.filename}")
                            # Content-addressed originals cannot collide across packages/ABIs.
                            symbols = output / "symbols" / (before + ".so")
                            symbols.parent.mkdir(exist_ok=True)
                            symbols.write_bytes(data)
                            report["libraries"].append({
                                "archive": archive.name, "name": entry.filename,
                                "original_sha256": before, "optimized_sha256": sha256(stripped),
                                "original_bytes": len(data), "optimized_bytes": len(stripped),
                                "allocated_sections_and_segment_mappings_unchanged": True,
                                "original_file": str(symbols.relative_to(output)),
                            })
                            data = stripped
                    # Preserve names, permissions, compression, dates and all license metadata.
                    optimized.writestr(entry, data)
            report["archives"].append({
                "name": archive.name, "before_bytes": archive.stat().st_size,
                "after_bytes": replacement.stat().st_size,
                "sha256": sha256(replacement.read_bytes()),
            })
            pending.append((replacement, archive))
        # Validate every library before publishing any replacement.
        for replacement, archive in pending:
            # Atomic even when the report directory lives on another filesystem.
            staging = archive.with_suffix(".imy.tmp")
            try:
                shutil.copyfile(replacement, staging)
                os.replace(staging, archive)
            finally:
                staging.unlink(missing_ok=True)
    (output / "native-optimization.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def deduplicate_sources(root):
    """Only remove public copies whose URLs run.py serves from animelab/static."""
    static = root / "animelab/static"
    frontend = root / "frontend/dist"
    candidates = list((frontend / "img").rglob("*")) + [frontend / "manifest.json"]
    removed = []
    for item in sorted(candidates):
        if not item.is_file():
            continue
        canonical = static / item.relative_to(frontend)
        if canonical.is_file() and item.read_bytes() == canonical.read_bytes():
            removed.append(str(item.relative_to(root)))
            item.unlink()
    return removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    native = commands.add_parser("requirements")
    native.add_argument("root", type=Path)
    native.add_argument("--output", type=Path, required=True)
    native.add_argument("--llvm-strip", default=os.environ.get("ANIMAN_LLVM_STRIP", "llvm-strip"))
    source = commands.add_parser("sources")
    source.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.command == "requirements":
        result = optimize_requirements(args.root, args.output, args.llvm_strip)
        print(f"Optimized {len(result['libraries'])} libraries; originals retained in {args.output}")
    else:
        print(f"Removed {len(deduplicate_sources(args.root))} duplicate public assets")
