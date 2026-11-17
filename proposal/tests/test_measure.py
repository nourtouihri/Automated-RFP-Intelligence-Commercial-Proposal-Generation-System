import os

import pytest

from proposal import measure


@pytest.fixture
def font_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(measure, "FONT_DIRS", [str(tmp_path)])
    measure.font_file.cache_clear()
    measure._font.cache_clear()
    yield tmp_path
    measure.font_file.cache_clear()
    measure._font.cache_clear()


def test_font_file_finds_the_named_font_in_the_font_dirs(font_dir):
    (font_dir / "user").mkdir()
    (font_dir / "user" / "Montserrat-Bold.ttf").write_bytes(b"")
    assert measure.font_file("Montserrat", True) == str(font_dir / "user" / "Montserrat-Bold.ttf")


def test_measuring_without_any_font_file_fails_instead_of_returning_zero(font_dir):
    with pytest.raises(measure.FontNotFound):
        measure.line_count("a deck that would never overflow", "Inter", False, 16, 100)


def test_windows_font_folders_include_the_per_user_one():
    env = {"WINDIR": "W", "LOCALAPPDATA": "L"}
    assert measure.font_dirs("win32", env) == [os.path.join("W", "Fonts"),
                                              os.path.join("L", "Microsoft", "Windows", "Fonts")]
    assert measure.font_dirs("win32", {"WINDIR": "W"}) == [os.path.join("W", "Fonts")]
    assert measure.font_dirs("linux", env) == ["/usr/share/fonts"]


def test_one_unbroken_word_is_cut_by_characters_to_fit():
    text, size = measure.fit_text("x" * 400, "Inter", False, 15, 300, 20, truncate=True)
    assert text.endswith("…") and 1 < len(text) < 400
    assert measure.fits(text, "Inter", False, size, 300, 20)
