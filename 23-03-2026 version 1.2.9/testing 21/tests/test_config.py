"""Tests para config.py — validación de parámetros y ofuscación."""

from config import (
    obfuscate_password_in_uri,
    _validate_driver_18_params,
)


class TestObfuscatePasswordInUri:
    def test_obfuscates_password(self):
        uri = 'mssql+pyodbc://user:secret123@server/db?driver=ODBC'
        result = obfuscate_password_in_uri(uri)
        assert 'secret123' not in result
        assert '***' in result
        assert 'user:***@server' in result

    def test_no_password_unchanged(self):
        uri = 'mssql+pyodbc://@server/db?driver=ODBC'
        result = obfuscate_password_in_uri(uri)
        assert result == uri

    def test_empty_string(self):
        assert obfuscate_password_in_uri('') == ''

    def test_none(self):
        assert obfuscate_password_in_uri(None) is None


class TestValidateDriver18Params:
    def test_valid_values(self):
        enc, tsc = _validate_driver_18_params('yes', 'no')
        assert enc == 'yes'
        assert tsc == 'no'

    def test_defaults_on_empty(self):
        enc, tsc = _validate_driver_18_params('', '')
        assert enc == 'no'
        assert tsc == 'yes'

    def test_defaults_on_none(self):
        enc, tsc = _validate_driver_18_params(None, None)
        assert enc == 'no'
        assert tsc == 'yes'

    def test_invalid_encrypt_falls_back(self):
        enc, tsc = _validate_driver_18_params('invalid', 'yes')
        assert enc == 'no'

    def test_invalid_trust_falls_back(self):
        enc, tsc = _validate_driver_18_params('yes', 'invalid')
        assert tsc == 'yes'

    def test_case_insensitive(self):
        enc, tsc = _validate_driver_18_params('YES', 'NO')
        assert enc == 'yes'
        assert tsc == 'no'

    def test_optional_mandatory(self):
        enc, _ = _validate_driver_18_params('optional', 'yes')
        assert enc == 'optional'
        enc, _ = _validate_driver_18_params('mandatory', 'yes')
        assert enc == 'mandatory'
