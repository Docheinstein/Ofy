import pytest

from ofy.download.paths import (
    DEFAULT_TEMPLATE,
    TemplateError,
    render_template,
    sanitize_component,
    validate_template,
)

VALUES = {
    "albumartist": "Radiohead", "artist": "Radiohead", "album": "OK Computer", "title": "Airbag",
    "year": "1997", "disc": 1, "disctotal": 1, "track": 1, "tracktotal": 12, "ext": "mp3",
}


def test_default_template():
    assert str(render_template(DEFAULT_TEMPLATE, VALUES)) == "Radiohead/OK Computer/1-01 - Airbag.mp3"


def test_multi_disc():
    p = render_template(DEFAULT_TEMPLATE, {**VALUES, "disc": 2, "disctotal": 2, "track": 7})
    assert p.name == "2-07 - Airbag.mp3"


def test_values_cannot_create_directories():
    p = render_template(DEFAULT_TEMPLATE, {**VALUES, "albumartist": "AC/DC", "title": "../../etc/passwd"})
    assert p.parts[0] == "AC_DC"
    assert ".." not in p.parts
    assert len(p.parts) == 3


@pytest.mark.parametrize("raw,expected", [
    ('What?: "Yes" <No> | * \\', "What__ _Yes_ _No_ _ _ _"),
    ("Trailing dots...", "Trailing dots"),
    ("  spaces  ", "spaces"),
    (".hidden", "hidden"),
    ("CON", "CON_"),
    ("nul.txt", "nul.txt_"),
    ("", "_"),
    ("tab\there", "tab_here"),
])
def test_sanitize_component(raw, expected):
    assert sanitize_component(raw) == expected


def test_max_length_preserves_extension():
    name = "x" * 400 + ".mp3"
    out = sanitize_component(name)
    assert len(out.encode()) <= 180
    assert out.endswith(".mp3")


def test_max_length_multibyte():
    out = sanitize_component("é" * 300)
    assert len(out.encode()) <= 180
    out.encode("utf-8")  # still valid


def test_unicode_kept():
    assert sanitize_component("Sigur Rós – Ágætis byrjun") == "Sigur Rós – Ágætis byrjun"


def test_validate_template():
    validate_template(DEFAULT_TEMPLATE)
    with pytest.raises(TemplateError):
        validate_template("{albumartist}/{nope}.{ext}")
    with pytest.raises(TemplateError):
        validate_template("{albumartist}/{title}")
    with pytest.raises(TemplateError):
        validate_template("/abs/{title}.{ext}")


def test_numeric_format_on_string_value():
    p = render_template("{track:02} {title}.{ext}", {**VALUES, "track": "3"})
    assert str(p) == "03 Airbag.mp3"


def test_album_folder_has_no_year():
    p = render_template(DEFAULT_TEMPLATE, {**VALUES, "albumartist": "Pink Floyd", "album": "Meddle", "year": "1971"})
    assert p.parts[:2] == ("Pink Floyd", "Meddle")


def test_old_default_template_is_upgraded():
    from ofy.config import Settings
    from ofy.download.paths import LEGACY_DEFAULT_TEMPLATES

    for old in LEGACY_DEFAULT_TEMPLATES:
        assert Settings(path_template=old).path_template == DEFAULT_TEMPLATE
    custom = "{artist}/{year} {album}/{title}.{ext}"
    assert Settings(path_template=custom).path_template == custom
