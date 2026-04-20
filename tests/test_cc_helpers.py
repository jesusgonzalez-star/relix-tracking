"""Tests para utils/cc_helpers.py — normalización de CC."""

from utils.cc_helpers import normalize_cc_assignments, build_softland_cc_match_clause


class TestNormalizeCcAssignments:
    def test_csv_input(self):
        result = normalize_cc_assignments('cc1,cc2,cc3')
        assert result == ['CC1', 'CC2', 'CC3']

    def test_semicolon_input(self):
        result = normalize_cc_assignments('cc1;cc2;cc3')
        assert result == ['CC1', 'CC2', 'CC3']

    def test_mixed_separators(self):
        result = normalize_cc_assignments('cc1,cc2;cc3')
        assert result == ['CC1', 'CC2', 'CC3']

    def test_duplicates_removed(self):
        result = normalize_cc_assignments('cc1,CC1,cc1')
        assert result == ['CC1']

    def test_whitespace_normalized(self):
        result = normalize_cc_assignments('  cc 1  , cc  2  ')
        assert result == ['CC 1', 'CC 2']

    def test_empty_string(self):
        assert normalize_cc_assignments('') == []

    def test_none(self):
        assert normalize_cc_assignments(None) == []

    def test_only_separators(self):
        assert normalize_cc_assignments(',,,;;;') == []


class TestBuildSoftlandCcMatchClause:
    def test_single_token(self):
        clause, placeholders = build_softland_cc_match_clause('OC', 1)
        assert 'OC' in clause
        assert '?' in clause
        assert len(placeholders) == 2  # DescCC + CodiCC

    def test_multiple_tokens(self):
        clause, placeholders = build_softland_cc_match_clause('T', 3)
        assert 'T' in clause
        # Retorna [ph_desc, ph_codi] donde cada ph tiene N placeholders
        assert len(placeholders) == 2  # DescCC placeholders + CodiCC placeholders

    def test_zero_tokens(self):
        clause, placeholders = build_softland_cc_match_clause('X', 0)
        assert clause == '1=0'
        assert placeholders == []
