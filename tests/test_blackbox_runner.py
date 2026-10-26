"""PSS/E selection, the worker and the supervisor, run against tests/fixtures/fake_psse."""

import sys

import pytest

from blackbox.psse_install import (
    PsseSelection,
    check_install,
    default_install_dir,
    inspect_install,
    parse_version,
)
from blackbox.supervisor import CaseSpec, Session


def fake_record(name="FAKETRIP", cons=None):
    # VUV TUV VOV TOV FLO FHI TF VREC TREC TRAMP NP DELTMAX CADENCE CYCLEMAX
    cons = cons or [0.7, 0.2, 1.2, 1.0, 57.0, 63.0, 0.5, 0.9, 1.0, 2.0, 0, 0, 0, 0]
    body = " ".join(f"{c:g}" for c in cons)
    return f"{{BUS}} 'USRLOD' '1' '{name}' 12 1 0 {len(cons)} 0 0 {body} /"


def sag(depth, duration, start=0.5, t_end=6.0, name="FAKETRIP", cons=None, **kw):
    return CaseSpec(records=(fake_record(name, cons),),
                    segments=((0.0, 1.0, 60.0), (start, depth, 60.0), (start + duration, 1.0, 60.0)),
                    t_end=t_end, label=f"sag {depth} {duration}", **kw)


def test_version_parsing_and_default_paths():
    assert parse_version("35.6") == (35, 6)
    assert parse_version("36.7.1") == (36, 7)
    with pytest.raises(ValueError):
        parse_version("v35")
    assert default_install_dir("36.7") == r"C:\Program Files\PTI\PSSE36\36.7"


def test_inspect_install_reports_missing_parts(tmp_path, fake_psse_install):
    layout = inspect_install(fake_psse_install.install_dir)
    assert layout.ok and layout.pspy_folders[0][1] == sys.version_info[:2]
    assert not inspect_install(str(tmp_path)).ok
    assert "is not a folder" in inspect_install(str(tmp_path / "nope")).problems[0]


def test_check_install_passes_on_a_working_install(fake_psse_install):
    result = check_install(fake_psse_install)
    assert result.ok, result.message
    assert result.psse_version == "35.6.4"


def test_check_install_rejects_a_version_mismatch(fake_psse_install):
    wrong = PsseSelection("36.7", fake_psse_install.install_dir, fake_psse_install.python_exe,
                          fake_psse_install.pspy_folder)
    result = check_install(wrong)
    assert not result.ok and "35.6.4, not 36.7" in result.message


def test_check_install_reports_a_license_failure(fake_psse_install, monkeypatch):
    monkeypatch.setenv("FAKE_PSSE_LICENSE", "fail")
    result = check_install(fake_psse_install)
    assert not result.ok and "psseinit" in result.message


@pytest.fixture
def session(fake_psse_install, tmp_path):
    return Session(fake_psse_install, tmp_path / "session", workers=2)


def test_a_case_runs_and_traces_the_trip(session):
    ride = session.run_one(sag(0.5, 0.1))
    trip = session.run_one(sag(0.5, 0.5))
    assert ride.ok and trip.ok, (ride.meta, trip.meta)
    assert min(ride.p) > 0.4  # constant power: P holds through the sag
    assert min(trip.p) == pytest.approx(0.0, abs=1e-9)
    assert trip.meta["sampling"] == "outfile"
    assert trip.meta["run_calls"] < 10  # event to event, not every step


def test_results_are_cached(session):
    first = session.run_one(sag(0.5, 0.1))
    again = session.run_one(sag(0.5, 0.1))
    assert not first.cached and again.cached
    assert again.p == first.p


def test_failures_are_classified(session, tmp_path):
    missing = session.run_one(sag(0.5, 0.1, name="NOSUCH"))
    assert missing.status == "dyre_error" and "NOT FOUND" in missing.log
    crash = session.run_one(sag(0.5, 0.1, name="FAKECRASH"))
    assert crash.status == "crashed"
    bad_dll = session.run_one(sag(0.5, 0.1, dlls=(str(tmp_path / "missing.dll"),)))
    assert bad_dll.status == "dll_error"


def test_a_hanging_case_is_stopped(session, monkeypatch):
    import blackbox.supervisor as sup

    monkeypatch.setattr(sup, "MIN_TIMEOUT_S", 3.0)
    monkeypatch.setattr(sup, "TIMEOUT_PER_SIM_SECOND", 0.1)
    result = session.run_one(sag(0.5, 0.1, name="FAKEHANG"))
    assert result.status == "timeout"
    assert result.meta["process_wall_seconds"] < 20


def test_run_many_runs_in_parallel(session):
    results = session.run_many([sag(0.5, d) for d in (0.05, 0.1, 0.15, 0.3)])
    assert [r.ok for r in results] == [True] * 4
    assert session.cases_run == 4


def test_a_relative_work_folder_still_runs_cases(tmp_path, monkeypatch, fake_psse_install):
    """`--out out\run` (relative) once crashed every case: the worker's path was resolved again from the case folder."""
    monkeypatch.chdir(tmp_path)
    result = Session(fake_psse_install, "rel_session", workers=1).run_one(sag(0.5, 0.1))
    assert result.ok, result.meta


def test_a_model_record_that_pse_ignores_is_not_an_ok_case(session):
    """Real PSS/E 35.6 answers an unknown model with RECORD IGNORED and return code 0, then simulates the load
    without it; without this check a whole validation ran 150 cases against a model that was not there."""
    result = session.run_one(sag(0.5, 0.1, name="IGNOREDMD"))
    assert result.status == "dyre_error" and "RECORD IGNORED" in result.log, (result.status, result.meta)
    assert "ignored the dynamics record" in result.meta["error"]


def test_a_user_model_that_is_not_accessible_is_not_an_ok_case(session):
    """Both real PSS/E versions answer a user model with no DLL with NOT ACCESSIBLE and return code 0 (B1)."""
    result = session.run_one(sag(0.5, 0.1, name="NOACCESSMD"))
    assert result.status == "dyre_error" and "NOT ACCESSIBLE" in result.log, (result.status, result.meta)
    assert "not accessible" in result.meta["error"]


def test_the_worker_says_which_reader_it_used(session):
    """The fake's channel file is not a real .outx, so the internal reader refuses it and dyntools (the fake) reads
    it; on real PSS/E the same field says `internal`."""
    assert session.run_one(sag(0.5, 0.1)).meta["sampling_reader"] == "dyntools"


def test_the_cache_key_covers_the_reader_as_well_as_the_worker(tmp_path, monkeypatch):
    from blackbox import supervisor

    before = supervisor.worker_hash()
    changed = tmp_path / "outx.py"
    changed.write_text(supervisor.reader_source().read_text() + "\n# changed\n")
    monkeypatch.setattr(supervisor, "reader_source", lambda: changed)
    assert supervisor.worker_hash() != before


def test_the_reader_is_staged_next_to_the_worker(tmp_path):
    from blackbox import supervisor

    script = supervisor.stage_worker(tmp_path / "w")
    assert script.exists() and (tmp_path / "w" / "outx.py").exists()


class _Folder:
    """Stands in for the finished case folder: refuses to be renamed `refusals` times, as Windows can."""

    def __init__(self, refusals):
        self.refusals, self.calls = refusals, 0

    def replace(self, _target):
        self.calls += 1
        if self.calls <= self.refusals:
            raise PermissionError("[WinError 5] Access is denied")


def test_a_refused_rename_is_retried_and_then_succeeds(monkeypatch):
    from blackbox import supervisor

    monkeypatch.setattr(supervisor.time, "sleep", lambda _s: None)
    folder = _Folder(refusals=3)
    supervisor._publish(folder, "target")
    assert folder.calls == 4


def test_a_rename_that_is_always_refused_is_reported_not_hidden(monkeypatch):
    from blackbox import supervisor

    monkeypatch.setattr(supervisor.time, "sleep", lambda _s: None)
    folder = _Folder(refusals=10**6)
    with pytest.raises(PermissionError):
        supervisor._publish(folder, "target")
    assert folder.calls == supervisor.PUBLISH_RETRIES
