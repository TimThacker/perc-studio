from blackbox.logparse import parse_log


def codes(text):
    return {f.code for f in parse_log(text)}


def test_a_user_model_that_is_not_accessible_is_recognized():
    line = 'BUS 100001 [SRC         138.00] LD 1  USER DEFINED LOAD RELATED MODEL "PERCBL" NOT ACCESSIBLE'
    assert "model_not_accessible" in codes(line)


def test_a_dll_that_does_not_load_is_recognized():
    text = 'Messages for api ADDMODELLIBRARY\nLibrary not found   (000352)\n"PERC2_v35_v2p3.dll"'
    assert "dll_not_loaded" in codes(text)
