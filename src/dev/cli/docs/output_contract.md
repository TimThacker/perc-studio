# Output contract

[perc-studio](../README.md) > Output contract

Every command prints exactly one JSON object to stdout:

```json
{
  "ok": true,
  "command": "params generate",
  "data": { "...": "command-specific payload" },
  "errors": [],
  "warnings": []
}
```

- `ok` is `false` only for a genuine failure (usage error, schema error, runner unavailable, unexpected exception).
  It is `true` even for a **validation mismatch**, because the tool did its job and produced a real result.
- `command` names the subcommand, for a caller dispatching on output from several invocations.
- `data` is the payload; its shape is documented per command.
- `errors` and `warnings` are always lists of strings. `warnings` carries non-fatal notes: a `.dyr` value outside its
  usual range (`dyr show`, `dyr to-case`), a case without channel data skipped by `results plot`, or the "N of M
  failed" line that accompanies exit 5.
- `--pretty` indents the output; the default is one compact line, which is what you want when piping into `jq`.

## Exit codes

| Code | Meaning | Raised by |
|---|---|---|
| 0 | Success. | |
| 1 | Unexpected/unhandled error (`errors[0]` is `ExceptionType: message`). | any |
| 2 | Usage error: bad arguments, unknown preset/model/case/channel id, malformed `--override`, missing file, unreadable spec. | any |
| 3 | A `LoadCase` failed schema-level validation. | `params validate` |
| 4 | The requested runner or PSS/E selection is unavailable. | `run`/`sweep --runner psse`, `psse check`, `blackbox` |
| 5 | **Validation mismatch**: the command ran to completion but expected behavior did not match actual behavior, or the inspected thing has problems. `ok` is still `true` and `data` is fully populated. | `validate results`, `sweep`, `blackbox` (stopped early), `dll inspect` |

Exit 5 is deliberately not a tool failure. A script that only needs a pass/fail boolean can branch on the exit code
without parsing JSON; one that needs to know *what* failed reads `data`.

`sweep`'s exit code is the worst across every case: 5 if any failed validation, 0 if all passed. A genuine tool
error partway through (an unknown preset id in the spec) keeps its own code (2, 4, ...) rather than being absorbed
into the pass/fail count.

## Click-level errors

A malformed invocation that Click rejects before the command's own code runs - a missing required option, an invalid
choice, a path that does not exist where the option is declared `exists=True`, the wrong number of positional
arguments - prints Click's plain-text usage message to **stderr** (not a JSON envelope) and exits 2. An error the
command's own logic raises (an unknown preset id, a malformed `--override`) goes through the JSON envelope. Both are
exit 2; only one is JSON. If you parse stdout, treat "stdout empty or not JSON, exit 2" as a Click-level usage error
and read stderr.

## Scripting patterns

Branch on the exit code, read the payload with `jq`:

```bash
perc-studio validate results --case case.json --result result.json > verdict.json
case $? in
  0) echo "all scenarios behaved as the preset requires" ;;
  5) jq -r '.data.report.points[] | select(.passed|not) | "\(.scenario_id): \(.expected_reason)"' verdict.json ;;
  *) jq -r '.errors[]' verdict.json; exit 1 ;;
esac
```

Fail a CI job on any non-zero code but keep the artifacts:

```bash
perc-studio sweep spec.json --output-dir out/ci > sweep.json || code=$?
jq '.data.summary | {total_cases, failed_cases}' sweep.json    # the summary is in the envelope either way
exit ${code:-0}
```

From Python, call `main` instead of shelling out. It prints the envelope and then raises `SystemExit` with the exit code (Click's standalone mode), so catch it:

```python
import io, json, contextlib
from dev.cli.main import main

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    try:
        main(["presets", "list", "--with-frequency"])
        code = 0
    except SystemExit as exc:
        code = exc.code
envelope = json.loads(buf.getvalue())
```
