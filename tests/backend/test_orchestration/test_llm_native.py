"""Tests for app.llm.native: wheel-tier selection, NVIDIA library-dir
registration, and the install-state probe the setup scripts consult.

Everything runs against injected hooks — no llama_cpp, no NVIDIA packages,
no platform monkeypatching.
"""

import pytest

from app.llm import native


@pytest.fixture(autouse=True)
def reset_library_dir_cache():
    native._library_dirs_added = None
    yield
    native._library_dirs_added = None


# -- pick_wheel_tier ----------------------------------------------------------


@pytest.mark.parametrize(
    ("banner", "tier"),
    [
        ("| NVIDIA-SMI 580.88   Driver Version: 580.88   CUDA Version: 13.0 |", "cu130"),
        ("CUDA Version: 13.1", "cu130"),
        # The tester machine: driver 566.36 supports at most CUDA 12.7.
        ("| NVIDIA-SMI 566.36   Driver Version: 566.36   CUDA Version: 12.7 |", "cu124"),
        ("CUDA Version: 12.4", "cu124"),
        ("CUDA Version: 12.3", "cpu-old-driver"),
        ("CUDA Version: 11.8", "cpu-old-driver"),
        ("", "cpu"),
        ("nvidia-smi: command produced no version banner", "cpu"),
        ("CUDA Version: N/A", "cpu"),
    ],
)
def test_pick_wheel_tier(banner, tier):
    assert native.pick_wheel_tier(banner) == tier


def test_pick_wheel_tier_multiline_banner():
    banner = (
        "+-----------------------------------------------------------+\n"
        "| NVIDIA-SMI 566.36    Driver Version: 566.36               |\n"
        "|                      CUDA Version: 12.7                   |\n"
        "+-----------------------------------------------------------+\n"
    )
    assert native.pick_wheel_tier(banner) == "cu124"


# -- add_nvidia_library_dirs --------------------------------------------------


def test_no_nvidia_packages_is_a_noop(tmp_path):
    registered = []
    added = native.add_nvidia_library_dirs(
        search_paths=[str(tmp_path)], platform="win32", register=registered.append
    )
    assert added == []
    assert registered == []


def test_windows_registers_bin_dirs_including_nested_layout(tmp_path):
    # cu12 layout: nvidia/<component>/bin
    flat = tmp_path / "nvidia" / "cuda_runtime" / "bin"
    flat.mkdir(parents=True)
    # hypothetical cu13 layout: one extra nesting level
    nested = tmp_path / "nvidia" / "cu13" / "cublas" / "bin"
    nested.mkdir(parents=True)

    registered = []
    added = native.add_nvidia_library_dirs(
        search_paths=[str(tmp_path)], platform="win32", register=registered.append
    )
    assert sorted(added) == sorted([str(flat), str(nested)])
    assert sorted(registered) == sorted(added)


def test_linux_preloads_cuda_libs_in_dependency_order(tmp_path):
    lib_dir = tmp_path / "nvidia" / "cuda_runtime" / "lib"
    lib_dir.mkdir(parents=True)
    for name in ("libcudart.so.12", "libcublas.so.12", "libcublasLt.so.12"):
        (lib_dir / name).touch()

    loaded = []
    native.add_nvidia_library_dirs(
        search_paths=[str(tmp_path)], platform="linux", preload=loaded.append
    )
    names = [path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for path in loaded]
    # cublas links cublasLt links cudart: preload order must match.
    assert names == ["libcudart.so.12", "libcublasLt.so.12", "libcublas.so.12"]


def test_register_failures_are_nonfatal(tmp_path):
    (tmp_path / "nvidia" / "broken" / "bin").mkdir(parents=True)
    (tmp_path / "nvidia" / "good" / "bin").mkdir(parents=True)

    def register(path):
        if "broken" in path:
            raise OSError("bad dir")

    added = native.add_nvidia_library_dirs(
        search_paths=[str(tmp_path)], platform="win32", register=register
    )
    assert [p for p in added if "good" in p] == added
    assert len(added) == 1


def test_idempotent_second_call_returns_cache_without_registering(tmp_path):
    (tmp_path / "nvidia" / "cuda_runtime" / "bin").mkdir(parents=True)
    registered = []
    first = native.add_nvidia_library_dirs(
        search_paths=[str(tmp_path)], platform="win32", register=registered.append
    )
    second = native.add_nvidia_library_dirs(
        search_paths=[str(tmp_path)], platform="win32", register=registered.append
    )
    assert second == first
    assert len(registered) == 1


# -- probe_install_state ------------------------------------------------------


class _FakeLlamaCpp:
    def __init__(self, supports_gpu):
        self._supports_gpu = supports_gpu

    def llama_supports_gpu_offload(self):
        if isinstance(self._supports_gpu, BaseException):
            raise self._supports_gpu
        return self._supports_gpu


def test_probe_missing_when_not_installed():
    assert (
        native.probe_install_state(find_spec=lambda name: None) == "missing"
    )


@pytest.mark.parametrize("error", [ImportError("no module"), OSError("DLL load failed")])
def test_probe_broken_when_import_fails(error):
    """A CUDA wheel whose runtime/driver is missing dies at import time —
    the state the setup scripts repair with a reinstall."""

    def importer():
        raise error

    state = native.probe_install_state(
        find_spec=lambda name: object(), importer=importer
    )
    assert state == "broken"


def test_probe_gpu_when_offload_supported():
    state = native.probe_install_state(
        find_spec=lambda name: object(),
        importer=lambda: _FakeLlamaCpp(True),
    )
    assert state == "gpu"


def test_probe_cpu_when_offload_unsupported_or_probe_errors():
    assert (
        native.probe_install_state(
            find_spec=lambda name: object(),
            importer=lambda: _FakeLlamaCpp(False),
        )
        == "cpu"
    )
    # An ABI surprise in the capability call is not "broken": the build
    # imported fine, so treat it as CPU rather than triggering a reinstall.
    assert (
        native.probe_install_state(
            find_spec=lambda name: object(),
            importer=lambda: _FakeLlamaCpp(RuntimeError("abi")),
        )
        == "cpu"
    )
