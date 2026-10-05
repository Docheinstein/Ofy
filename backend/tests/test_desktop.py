import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from offliner import desktop
from offliner.config import default_data_dir, default_library_dir, default_static_dir


def test_pick_port_prefers_free_port():
    free = desktop.pick_port(0)
    assert desktop.pick_port(free) == free


def test_pick_port_falls_back_when_taken():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        taken = s.getsockname()[1]
        assert not desktop.port_is_free(taken)
        assert desktop.pick_port(taken) != taken


@pytest.fixture
def fake_backend(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "version": "x", "data_dir": str(data_dir)}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], data_dir
    srv.shutdown()


def test_running_instance_from_instance_file(fake_backend):
    port, data_dir = fake_backend
    url = f"http://127.0.0.1:{port}"
    assert desktop.running_instance(data_dir) is None
    desktop.instance_file(data_dir).write_text(json.dumps({"url": url}))
    assert desktop.running_instance(data_dir) == url


def test_running_instance_on_preferred_port(fake_backend):
    port, data_dir = fake_backend
    assert desktop.running_instance(data_dir, port) == f"http://127.0.0.1:{port}"


def test_other_data_dir_is_not_attached(fake_backend, tmp_path):
    port, _ = fake_backend
    assert desktop.running_instance(tmp_path / "other", port) is None


def test_stale_instance_file_ignored(tmp_path):
    desktop.instance_file(tmp_path).write_text(json.dumps({"url": "http://127.0.0.1:9"}))
    assert desktop.running_instance(tmp_path) is None


def test_wait_until_ready_stops_when_thread_dies():
    assert desktop.wait_until_ready("http://127.0.0.1:9", timeout=5, alive=lambda: False) is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux GTK bindings")
def test_gtk_bindings_link_only_gi(tmp_path, monkeypatch):
    site = tmp_path / "site"
    gi = site / "gi"
    gi.mkdir(parents=True)
    abi = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    (gi / "__init__.py").write_text("FAKE = True\n")
    (gi / f"_gi.{abi}-x86_64-linux-gnu.so").write_bytes(b"")
    (site / "requests").mkdir()  # must NOT become importable
    monkeypatch.setattr(desktop, "SYSTEM_SITE_DIRS", (str(site),))
    monkeypatch.setitem(sys.modules, "gi", None)  # pretend gi isn't installed in the venv
    links = tmp_path / "links"
    monkeypatch.setattr(sys, "path", list(sys.path))

    import builtins

    real_import = builtins.__import__
    state = {"linked": False}

    def fake_import(name, *a, **k):
        if name == "gi":
            if not state["linked"]:
                raise ImportError
            return type(sys)("gi")
        return real_import(name, *a, **k)

    def mark(*a, **k):
        state["linked"] = True
        return orig_symlink(*a, **k)

    orig_symlink = Path.symlink_to
    monkeypatch.setattr(Path, "symlink_to", mark)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert desktop.ensure_gtk_bindings(links) is True
    assert (links / "gi").is_symlink() and not (links / "requests").exists()
    assert str(links) in sys.path


def test_defaults_are_absolute_and_cwd_independent():
    assert default_data_dir().is_absolute() and default_data_dir().name.lower() == "offliner"
    assert default_library_dir() == Path.home() / "Music" / "Offliner"
    assert default_static_dir().parts[-2:] == ("frontend", "dist")


def test_desktop_entry():
    e = desktop.desktop_entry("/x/offliner-desktop", Path("/x/favicon.svg"))
    assert e.startswith("[Desktop Entry]\n") and "Exec=/x/offliner-desktop\n" in e and "Terminal=false" in e
