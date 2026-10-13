"""Interactive Qt application for the decompiler.

Loads a binary through ``VivisectDecompiler``, lists functions, and on
selection decompiles the function and renders its CFG + C code in the Qt
viewer (``qt_viewer``). Works headless via ``QT_QPA_PLATFORM=offscreen``.

Function listing uses the graph builder's workspace when available, else a
small set of synthetic addresses for the raw builder (test path).
"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger("viv-decomp.qt")

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QListWidget, QListWidgetItem,
        QSplitter, QPlainTextEdit, QLabel, QLineEdit, QPushButton,
        QHBoxLayout, QVBoxLayout, QWidget,
    )
    from PyQt6.QtCore import Qt
    _HAS_QT = True
except ImportError:  # pragma: no cover
    _HAS_QT = False
    QApplication = QMainWindow = QListWidget = QListWidgetItem = QSplitter = \
        QPlainTextEdit = QLabel = QLineEdit = QPushButton = QHBoxLayout = \
        QVBoxLayout = QWidget = type("_Fallback", (), {})

from viv_decomp.decompiler import VivisectDecompiler
from viv_decomp.qt_viewer import GraphViewerWidget


class DecompilerApp(QMainWindow):
    """Interactive decompiler: function list -> graph + code panes."""

    def __init__(self, binary_path: str, graph_source: str = "vivisect",
                 arch: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.binary_path = binary_path
        self.graph_source = graph_source
        self.arch = arch

        self.decomp = VivisectDecompiler(
            binary_path=binary_path,
            graph_source=graph_source,
            arch=arch,
        )

        self.setWindowTitle(f"viv-decomp — {binary_path}")
        self.setMinimumSize(1100, 700)
        self._build_ui()

        self._function_addrs: List[int] = []
        self._refresh_functions()

    # ── UI construction ──

    def _build_ui(self):
        root = QWidget(self)

        # Address entry + load button (top bar)
        top = QHBoxLayout()
        self.addr_edit = QLineEdit(root)
        self.addr_edit.setPlaceholderText("0x1000")
        self.load_btn = QPushButton("Decompile", root)
        self.load_btn.clicked.connect(self._on_load)
        top.addWidget(QLabel("Function addr:"))
        top.addWidget(self.addr_edit)
        top.addWidget(self.load_btn)

        # Body: function list | (graph + code)
        body = QSplitter(self)
        self.func_list = QListWidget(body)
        self.func_list.currentItemChanged.connect(self._on_select)
        self.func_list.setMaximumWidth(240)

        right = QSplitter(self)  # vertical: graph, code
        self.graph_view = GraphViewerWidget(parent=right)
        self.code_pane = QPlainTextEdit(right)
        self.code_pane.setReadOnly(True)
        right.addWidget(self.graph_view)
        right.addWidget(self.code_pane)
        right.setOrientation(Qt.Orientation.Vertical)

        body.addWidget(self.func_list)
        body.addWidget(right)

        layout = QVBoxLayout(root)
        layout.addLayout(top)
        layout.addWidget(body)

        # Header label for current status
        self.status_label = QLabel("", self)
        layout.addWidget(self.status_label)

        self.setCentralWidget(root)

    # ── Function enumeration ──

    def _list_function_addrs(self) -> List[int]:
        """Return function entry addresses from the builder's workspace."""
        builder = self.decomp.graph_builder
        vw = getattr(builder, "vw", None)
        if vw is not None:
            try:
                return sorted(vw.getFunctions())
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not list functions: %s", exc)
        # Synthetic fallback for the raw graph source (test path)
        if self.graph_source in ("raw", "ghidra"):
            return [0x1000, 0x2000, 0x3000]
        return []

    def _refresh_functions(self):
        self.func_list.clear()
        self._function_addrs = self._list_function_addrs()
        for addr in self._function_addrs:
            item = QListWidgetItem(f"0x{addr:x}")
            item.setData(Qt.ItemDataRole.UserRole, addr)
            self.func_list.addItem(item)
        self.status_label.setText(f"{len(self._function_addrs)} functions")

    # ── Event handlers ──

    def _on_select(self, current, _prev):
        if current is None:
            return
        addr = current.data(Qt.ItemDataRole.UserRole)
        self._decompile(addr)

    def _on_load(self):
        text = self.addr_edit.text().strip()
        if not text:
            return
        addr = int(text, 16) if text.lower().startswith("0x") else int(text, 16)
        self._decompile(addr)

    def _decompile(self, funcva: int):
        """Decompile a function, render graph + code."""
        try:
            graph = self.decomp.graph_builder.get_graph(funcva)
            self.graph_view.set_graph(graph)
            code = self.decomp.decompile_address(funcva).text
            self.code_pane.setPlainText(code)
            self.status_label.setText(f"0x{funcva:x} — {len(graph.blocks)} blocks")
        except Exception as exc:  # pragma: no cover
            self.status_label.setText(f"Failed 0x{funcva:x}: {type(exc).__name__}: {exc}")
            self.code_pane.setPlainText(f"// Error: {type(exc).__name__}: {exc}")


def launch(binary_path: str, graph_source: str = "vivisect",
           arch: Optional[str] = None, block: bool = True) -> int:
    """Launch the interactive decompiler Qt app."""
    app = QApplication.instance() or QApplication([])
    window = DecompilerApp(binary_path, graph_source=graph_source, arch=arch)
    window.show()
    if block:
        return app.exec()
    window.repaint()
    return 0
