"""Tests for the interactive Qt decompiler app (headless via offscreen)."""
import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

try:
    from PyQt6.QtWidgets import QApplication
    import viv_decomp.qt_app as qa
    from viv_decomp.qt_viewer import GraphViewerWidget
    _HAS_QT = True
except Exception:  # pragma: no cover
    _HAS_QT = False

pytestmark = pytest.mark.skipif(not _HAS_QT, reason="PyQt6 not available")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app_raw(qapp):
    """DecompilerApp wired to the raw graph source (no binary needed)."""
    return qa.DecompilerApp(binary_path="<raw>", graph_source="raw")


class TestDecompilerApp:
    def test_construct(self, app_raw):
        assert app_raw.decomp is not None
        assert app_raw.func_list is not None

    def test_function_list_populated_raw(self, app_raw):
        # raw builder publishes synthetic addresses
        assert app_raw.func_list.count() >= 1

    def test_listing_raw_addresses(self, app_raw):
        assert 0x1000 in app_raw._function_addrs

    def test_decompile_renders_graph(self, app_raw):
        app_raw._decompile(0x1000)
        assert len(app_raw.graph_view.scene().items()) >= 1

    def test_decompile_renders_code(self, app_raw):
        app_raw._decompile(0x1000)
        code = app_raw.code_pane.toPlainText()
        assert "Function" in code or "int" in code or "{" in code

    def test_on_load_parses_hex(self, app_raw):
        app_raw.addr_edit.setText("0x2000")
        app_raw._on_load()
        assert "0x2000" in app_raw.status_label.text()

    def test_on_select_noop_for_none(self, app_raw):
        app_raw._on_select(None, None)  # must not crash

    def test_decompile_unknown_address_falls_back(self, app_raw):
        # raw builder handles any address; graph + code both populated
        app_raw._decompile(0x9999)
        assert len(app_raw.graph_view.scene().items()) >= 1


class TestLaunch:
    def test_launch_nonblocking(self, qapp):
        rc = qa.launch("<raw>", graph_source="raw", block=False)
        assert rc == 0
