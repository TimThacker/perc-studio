from app.config import DEFAULTS


def test_defaults_include_facility_fields():
    assert "facility_name" in DEFAULTS
    assert DEFAULTS["total_mw"] == 300.0
