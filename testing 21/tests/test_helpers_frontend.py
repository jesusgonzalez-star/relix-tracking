from routes.frontend_routes import (
    _normalize_patente,
    _is_valid_patente,
    _parse_evidencia_urls_field,
    _sanitize_next_url,
    _extract_evidence_filename,
)


def test_normalize_patente():
    # 6 caracteres alfanuméricos sin guion: inserta guion tras los 4 primeros.
    assert _normalize_patente(' ab 12 cd ') == 'AB12-CD'
    assert _normalize_patente('') == ''


def test_is_valid_patente():
    assert _is_valid_patente('AB1234') is True
    assert _is_valid_patente('12345') is False
    assert _is_valid_patente('') is False
    assert _is_valid_patente('AB--12') is False


def test_parse_evidencia_urls_field():
    assert _parse_evidencia_urls_field('') == []
    assert _parse_evidencia_urls_field('http://a/img.jpg') == ['http://a/img.jpg']
    raw = '["http://one", "http://two"]'
    assert _parse_evidencia_urls_field(raw) == ['http://one', 'http://two']


def test_sanitize_next_url_strips_next_query():
    u = _sanitize_next_url('/dashboard?next=/evil')
    assert 'next=' not in (u or '').lower()


def test_extract_evidence_filename():
    assert _extract_evidence_filename('/foo/evidencias/bar.png') == 'bar.png'
    assert _extract_evidence_filename('') is None
