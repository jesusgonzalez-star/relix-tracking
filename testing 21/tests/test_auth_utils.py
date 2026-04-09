import pytest

from utils.auth import has_any_role, validate_password_strength


@pytest.mark.parametrize(
    'role,allowed,expected',
    [
        ('BODEGA', ['BODEGA'], True),
        ('SUPERADMIN', ['BODEGA'], True),
        ('VISUALIZADOR', ['BODEGA'], False),
        ('ADMIN', ['SUPERADMIN'], True),
    ],
)
def test_has_any_role(role, allowed, expected):
    assert has_any_role(role, allowed) is expected


def test_validate_password_strength():
    ok, msg = validate_password_strength('abc12345')
    assert ok is True
    assert msg == ''
    ok, msg = validate_password_strength('short')
    assert ok is False


@pytest.mark.parametrize(
    'text,expected',
    [
        (None, None),
        ('', ''),
        ("a';DROP", 'aDROP'),
        ('normal', 'normal'),
    ],
)
def test_sanitize_input(text, expected):
    from utils.auth import sanitize_input

    assert sanitize_input(text) == expected
