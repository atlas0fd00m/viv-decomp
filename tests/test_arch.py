"""Tests for arch/selector.py — ArchSelector & arch detection."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from dec_engine.dec_impl.arch.selector import (
    ArchSelector,
    arch_name_for_workspace,
    symbolik_context_for_arch,
)


class _FakeVw:
    def __init__(self, arch):
        self._arch = arch

    def getMeta(self, key):
        if key == "Architecture":
            return self._arch
        return None


class TestSymbolikContextForArch:
    @pytest.mark.skipif(
        not pytest.importorskip("vivisect", reason=None) is not None,
        reason="vivisect not installed",
    )
    def test_amd64_class_present(self):
        ctx = symbolik_context_for_arch("amd64")
        assert ctx is not None

    def test_amd64_alias(self):
        ctx = symbolik_context_for_arch("x86-64")
        assert ctx == symbolik_context_for_arch("amd64")

    def test_i386_alias(self):
        ctx = symbolik_context_for_arch("x86")
        assert ctx == symbolik_context_for_arch("i386")

    def test_unknown_arch_none(self):
        assert symbolik_context_for_arch("bogus_arch") is None

    def test_empty_arch_none(self):
        assert symbolik_context_for_arch("") is None
        assert symbolik_context_for_arch(None) is None

    def test_unsupported_arch_aliases_recognized(self):
        # arm/mips/ppc are recognized but have no bundled Vivisect context
        assert symbolik_context_for_arch("arm") is None
        assert symbolik_context_for_arch("mips") is None
        assert symbolik_context_for_arch("ppc") is None

    def test_arm64_alias(self):
        assert symbolik_context_for_arch("aarch64") == symbolik_context_for_arch("arm64")

    def test_powerpc_alias(self):
        assert symbolik_context_for_arch("powerpc") == symbolik_context_for_arch("ppc")


class TestArchNameForWorkspace:
    def test_detects_amd64(self):
        vw = _FakeVw("amd64")
        assert arch_name_for_workspace(vw) == "amd64"

    def test_detects_i386(self):
        vw = _FakeVw("i386")
        assert arch_name_for_workspace(vw) == "i386"

    def test_none_vw(self):
        assert arch_name_for_workspace(None) is None

    def test_no_meta(self):
        class NoMeta:
            def getMeta(self, key):
                return None
        assert arch_name_for_workspace(NoMeta()) is None

    def test_exception_returns_none(self):
        class BrokenVw:
            def getMeta(self, key):
                raise RuntimeError("boom")
        assert arch_name_for_workspace(BrokenVw()) is None


class TestArchSelector:
    def test_default_amd64(self):
        sel = ArchSelector()
        assert sel.DEFAULT_ARCH == "amd64"

    def test_override_i386(self):
        sel = ArchSelector(arch="i386")
        assert sel._requested == "i386"

    def test_context_from_override(self):
        sel = ArchSelector(arch="amd64")
        ctx = sel.context_class()
        assert ctx is not None

    def test_context_detects_from_vw(self):
        sel = ArchSelector()  # no override
        ctx = sel.context_class(_FakeVw("i386"))
        # i386 context should resolve
        assert ctx is not None

    def test_instantiate_unknown_arch_uses_amyd64(self):
        sel = ArchSelector(arch="bogus")
        # falls back to default amd64 context
        inst = sel.instantiate(None)
        assert inst is not None
        assert type(inst).__name__ == "Amd64SymbolikAnalysisContext"

    def test_unknown_arch_falls_back_to_default(self):
        sel = ArchSelector(arch="nope")
        ctx = sel.context_class()
        assert ctx == symbolik_context_for_arch("amd64")
