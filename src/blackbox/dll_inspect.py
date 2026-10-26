"""Static checks on a user-model DLL before PSS/E loads it.

A small PE (Portable Executable) reader, standard library only: the machine
type (PSS/E 35 and later are 64-bit), the exported symbol names (does the DLL
provide the model the .dyr asks for?), and the DLLs it imports (can Windows
find each one?). This catches the common "model not found" and "module could
not be found" failures with a specific message, before any PSS/E run.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

MACHINES = {0x8664: "x64", 0x14C: "x86", 0xAA64: "ARM64"}
# Always present on Windows; not worth reporting as found or missing.
SYSTEM_DLLS = {"kernel32.dll", "user32.dll", "advapi32.dll", "ntdll.dll", "gdi32.dll", "shell32.dll",
               "ole32.dll", "oleaut32.dll", "ws2_32.dll", "msvcrt.dll", "imagehlp.dll", "dbghelp.dll", "psapi.dll"}


@dataclass
class DllReport:
    path: str
    sha256: str = ""
    machine: str | None = None
    exports: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    missing_imports: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def exports_model(self, model: str) -> bool:
        return model.upper() in {_bare(e) for e in self.exports}

    def to_dict(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "machine": self.machine, "exports": self.exports,
                "imports": self.imports, "missing_imports": self.missing_imports, "problems": self.problems,
                "notes": self.notes}


def _bare(symbol: str) -> str:
    """PERCBL, _PERCBL, PERCBL_, perc_bl@16 -> comparable upper-case name."""
    name = symbol.split("@")[0].strip("_").upper()
    return name


class _Pe:
    def __init__(self, data: bytes):
        self.data = data
        if data[:2] != b"MZ":
            raise ValueError("not a Windows DLL (no MZ header)")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not a Windows DLL (no PE header)")
        self.machine, nsections = struct.unpack_from("<HH", data, pe + 4)
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        magic = struct.unpack_from("<H", data, opt)[0]
        dd = opt + (112 if magic == 0x20B else 96)
        self.export_rva = struct.unpack_from("<I", data, dd)[0]
        self.import_rva = struct.unpack_from("<I", data, dd + 8)[0]
        self.sections = []
        sec = opt + opt_size
        for i in range(nsections):
            off = sec + 40 * i
            vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, off + 8)
            self.sections.append((vaddr, max(vsize, rsize), raddr))

    def offset(self, rva: int) -> int:
        for vaddr, size, raddr in self.sections:
            if vaddr <= rva < vaddr + size:
                return rva - vaddr + raddr
        raise ValueError(f"address {rva:#x} is outside every section")

    def cstr(self, rva: int) -> str:
        off = self.offset(rva)
        end = self.data.index(b"\0", off)
        return self.data[off:end].decode("ascii", "replace")

    def exports(self) -> list[str]:
        if not self.export_rva:
            return []
        off = self.offset(self.export_rva)
        n_names = struct.unpack_from("<I", self.data, off + 24)[0]
        names_rva = struct.unpack_from("<I", self.data, off + 32)[0]
        names_off = self.offset(names_rva) if n_names else 0
        return [self.cstr(struct.unpack_from("<I", self.data, names_off + 4 * i)[0]) for i in range(n_names)]

    def imports(self) -> list[str]:
        if not self.import_rva:
            return []
        off = self.offset(self.import_rva)
        names = []
        while True:
            name_rva = struct.unpack_from("<I", self.data, off + 12)[0]
            if name_rva == 0:
                break
            names.append(self.cstr(name_rva))
            off += 20
        return names


def _search_dirs(dll_path: Path, psse_root: str | None) -> list[Path]:
    dirs = [dll_path.parent]
    if psse_root:
        dirs += [Path(psse_root) / "PSSBIN", Path(psse_root) / "PSSLIB"]
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    dirs += [Path(windir) / "System32", Path(windir)]
    dirs += [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    return dirs


def _findable(name: str, dirs: list[Path]) -> bool:
    lower = name.lower()
    if lower in SYSTEM_DLLS or lower.startswith(("api-ms-win-", "ext-ms-")):
        return True
    return any((d / name).is_file() for d in dirs)


def inspect_dll(path: str, *, psse_root: str | None = None, models: tuple[str, ...] = ()) -> DllReport:
    report = DllReport(path)
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        report.problems.append(f"cannot read {path}: {exc.strerror or exc}")
        return report
    report.sha256 = hashlib.sha256(data).hexdigest()
    try:
        pe = _Pe(data)
        report.machine = MACHINES.get(pe.machine, f"{pe.machine:#x}")
        report.exports = pe.exports()
        report.imports = pe.imports()
    except (ValueError, struct.error) as exc:
        report.problems.append(f"{p.name}: {exc}")
        return report
    if report.machine != "x64":
        report.problems.append(f"{p.name} is built for {report.machine}; PSS/E 35 and later load only x64 DLLs")
    dirs = _search_dirs(p, psse_root)
    report.missing_imports = [n for n in report.imports if not _findable(n, dirs)]
    for name in report.missing_imports:
        report.problems.append(f"{p.name} needs {name}, which is not next to the DLL, in PSS/E's PSSBIN, or on PATH")
    for model in models:
        if report.exports and not report.exports_model(model):
            report.notes.append(f"{p.name} does not export a symbol named {model}; if PSS/E cannot find the model, "
                                "this DLL is not the one that provides it")
    return report
