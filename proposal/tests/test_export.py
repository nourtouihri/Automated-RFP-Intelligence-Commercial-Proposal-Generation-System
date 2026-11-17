import subprocess

import pytest

from proposal import export


def test_soffice_path_prefers_the_configured_executable(tmp_path, monkeypatch):
    exe = tmp_path / "soffice.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("SOFFICE_PATH", str(exe))
    assert export.soffice_path() == str(exe)


def test_a_wrong_soffice_path_is_reported_not_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("SOFFICE_PATH", str(tmp_path / "missing.exe"))
    with pytest.raises(FileNotFoundError, match="SOFFICE_PATH"):
        export.soffice_path()


def fake_soffice(monkeypatch, tmp_path, writes_pdf=True):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        seen["stale_pdf_existed"] = (tmp_path / "d.pdf").exists()
        if writes_pdf:
            (tmp_path / "d.pdf").write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(export.subprocess, "run", run)
    monkeypatch.setattr(export, "soffice_path", lambda: "soffice")
    (tmp_path / "d.pptx").write_bytes(b"")
    return seen


def test_to_pdf_runs_soffice_headless_with_a_private_profile_and_returns_the_pdf(tmp_path, monkeypatch):
    seen = fake_soffice(monkeypatch, tmp_path)
    (tmp_path / "d.pdf").write_bytes(b"stale")
    pdf = export.to_pdf(tmp_path / "d.pptx")
    assert pdf == tmp_path / "d.pdf" and pdf.read_bytes() == b"%PDF"
    assert seen["stale_pdf_existed"] is False
    assert "--headless" in seen["cmd"] and "pdf" in seen["cmd"]
    assert any(a.startswith("-env:UserInstallation=file:") and "proposal-soffice-profile" in a
               for a in seen["cmd"])
    assert seen["kw"]["check"] is True and seen["kw"]["timeout"] == 180


def test_to_pdf_says_so_when_soffice_wrote_nothing(tmp_path, monkeypatch):
    fake_soffice(monkeypatch, tmp_path, writes_pdf=False)
    with pytest.raises(RuntimeError, match="without writing"):
        export.to_pdf(tmp_path / "d.pptx")
