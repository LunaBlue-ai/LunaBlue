"""Native-library plumbing for llama-cpp-python (stdlib-only).

Two audiences share this module:

- The setup scripts (``scripts/setup.ps1`` / ``setup.sh``) call
  :func:`pick_wheel_tier` and :func:`probe_install_state` via ``python -c`` to
  decide which prebuilt wheel index to install from and whether the installed
  build already matches the machine. Keeping that logic here (instead of
  duplicating it in PowerShell 5.1 and POSIX sh) makes it testable and
  immune to shell quoting/parsing quirks.
- :mod:`app.llm.runtime` calls :func:`import_llama` /
  :func:`add_nvidia_library_dirs` so a CUDA wheel can resolve the runtime
  libraries shipped by the ``nvidia-*`` pip packages — no system CUDA
  toolkit install required.

Wheel tiers: the prebuilt CUDA wheels on the abetlen index are built per
CUDA major/minor series, and a wheel only initializes when the NVIDIA
driver supports that CUDA version. ``nvidia-smi``'s banner reports the
driver's *maximum* supported CUDA version, which is what
:func:`pick_wheel_tier` keys off. cu121 is not a tier: its Windows wheels
stopped at an old release.
"""

import ctypes
import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

_CUDA_VERSION_RE = re.compile(r"CUDA Version:\s*(\d+)\.(\d+)")

# Linux load order matters: cublas links against cublasLt, both against
# cudart, and dlopen resolves the SONAMEs from already-loaded libraries.
_LINUX_PRELOAD_STEMS = ("libcudart.so", "libcublasLt.so", "libcublas.so")


def pick_wheel_tier(smi_output: str) -> str:
    """Map ``nvidia-smi`` banner output to a llama-cpp-python wheel tier.

    Returns ``"cu130"`` (driver supports CUDA >= 13.0), ``"cu124"``
    (>= 12.4), ``"cpu-old-driver"`` (an NVIDIA driver answered but is too
    old for any current prebuilt CUDA wheel), or ``"cpu"`` (no parseable
    CUDA version — treat as no usable NVIDIA GPU).
    """
    match = _CUDA_VERSION_RE.search(smi_output)
    if not match:
        return "cpu"
    major, minor = int(match.group(1)), int(match.group(2))
    if major >= 13:
        return "cu130"
    if (major, minor) >= (12, 4):
        return "cu124"
    return "cpu-old-driver"


def _nvidia_component_dirs(
    subdir: str, search_paths: Iterable[str]
) -> list[Path]:
    """``<site-packages>/nvidia/**/<subdir>`` dirs, up to two levels deep.

    The cu12 packages use ``nvidia/<component>/<subdir>``; scan one extra
    nesting level so a differently laid-out cu13 series is found too.
    """
    found: list[Path] = []
    for entry in search_paths:
        root = Path(entry) / "nvidia"
        try:
            children = sorted(p for p in root.iterdir() if p.is_dir())
        except OSError:
            continue
        for child in children:
            if (child / subdir).is_dir():
                found.append(child / subdir)
                continue
            try:
                grandchildren = sorted(
                    p for p in child.iterdir() if p.is_dir()
                )
            except OSError:
                continue
            for grand in grandchildren:
                if (grand / subdir).is_dir():
                    found.append(grand / subdir)
    return found


_library_dirs_added: list[str] | None = None


def add_nvidia_library_dirs(
    *,
    search_paths: Iterable[str] | None = None,
    platform: str | None = None,
    register: Callable[[str], Any] | None = None,
    preload: Callable[[str], Any] | None = None,
) -> list[str]:
    """Make pip-installed NVIDIA CUDA runtime libraries loadable.

    Windows: registers each ``nvidia/**/bin`` dir via
    ``os.add_dll_directory`` so the CUDA wheel's DLL dependencies
    (``cudart64_*.dll``, ``cublas64_*.dll``) resolve. Elsewhere: preloads
    ``libcudart``/``libcublasLt``/``libcublas`` from ``nvidia/**/lib`` with
    ``RTLD_GLOBAL`` (``LD_LIBRARY_PATH`` changes after process start are
    ignored by the dynamic loader). No-op when the packages are absent —
    a CPU build never needs any of this, so every failure is non-fatal.

    Idempotent: the first call's result is cached and returned as-is on
    subsequent calls. The keyword arguments exist as test injection points.
    """
    global _library_dirs_added
    if _library_dirs_added is not None:
        return _library_dirs_added
    if search_paths is None:
        search_paths = list(sys.path)
    if platform is None:
        platform = sys.platform
    added: list[str] = []
    if platform == "win32":
        if register is None:
            register = os.add_dll_directory
        for directory in _nvidia_component_dirs("bin", search_paths):
            try:
                register(str(directory))
            except OSError:
                continue
            added.append(str(directory))
    else:
        if preload is None:
            def preload(path: str) -> None:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
        lib_dirs = _nvidia_component_dirs("lib", search_paths)
        for stem in _LINUX_PRELOAD_STEMS:
            loaded = False
            for directory in lib_dirs:
                for lib in sorted(directory.glob(stem + ".*")):
                    try:
                        preload(str(lib))
                    except OSError:
                        continue
                    added.append(str(lib))
                    loaded = True
                    break
                if loaded:
                    break
    _library_dirs_added = added
    return added


def probe_install_state(
    *,
    find_spec: Callable[[str], Any] | None = None,
    importer: Callable[[], Any] | None = None,
) -> str:
    """Classify the installed llama-cpp-python build for the setup scripts.

    Returns ``"missing"`` (not installed), ``"broken"`` (installed but the
    import fails — typically a CUDA wheel whose runtime/driver is absent or
    too old), ``"gpu"`` (imports and reports GPU offload support), or
    ``"cpu"`` (imports, CPU-only build).

    Must run in a fresh interpreter each time the scripts consult it: a
    reinstalled wheel cannot be re-imported into a process that already
    loaded the previous one.
    """
    if find_spec is None:
        find_spec = importlib.util.find_spec
    try:
        if find_spec("llama_cpp") is None:
            return "missing"
    except (ImportError, ValueError):
        return "missing"
    add_nvidia_library_dirs()
    if importer is None:
        def importer() -> Any:
            import llama_cpp

            return llama_cpp
    try:
        llama_cpp = importer()
    except (ImportError, OSError):
        return "broken"
    try:
        supported = bool(llama_cpp.llama_supports_gpu_offload())
    except Exception:
        return "cpu"
    return "gpu" if supported else "cpu"


def import_llama() -> Any:
    """Import and return ``llama_cpp`` with NVIDIA library dirs registered.

    Raises whatever the import raises (``ImportError``/``OSError``) —
    :mod:`app.llm.runtime` translates that into an actionable startup error.
    """
    add_nvidia_library_dirs()
    import llama_cpp

    return llama_cpp
