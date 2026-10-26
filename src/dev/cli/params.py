"""`perc-studio params generate|validate|show` - create, schema-validate, and
inspect LoadCase parameterizations without touching the GUI."""

from __future__ import annotations

import click

from dev.validation.case_model import (
    BLOCK_NAMES,
    FacilityInfo,
    LoadComposition,
    case_from_model_defaults,
    case_from_preset,
    case_with_overrides,
    from_json,
    schema_problems,
    to_dict,
    to_json,
)
from load_models import DEFAULT_BLOCK_MODELS

from ._output import SchemaInvalidError, UsageError, cli_result, pretty_option


def _parse_override(spec: str) -> tuple:
    if "=" not in spec:
        raise UsageError(f"invalid --override {spec!r}; expected BLOCK.CON=VALUE, e.g. it.VDPA=0.75")
    left, raw_value = spec.split("=", 1)
    if "." not in left:
        raise UsageError(f"invalid --override {spec!r}; expected BLOCK.CON=VALUE, e.g. it.VDPA=0.75")
    block, name = left.split(".", 1)
    if block not in BLOCK_NAMES:
        raise UsageError(f"invalid --override block {block!r} in {spec!r}; expected one of {', '.join(BLOCK_NAMES)}")
    try:
        value = int(raw_value) if raw_value.lstrip("-").isdigit() else float(raw_value)
    except ValueError:
        raise UsageError(f"invalid --override value {raw_value!r} in {spec!r}; expected a number") from None
    return block, name, value


@click.group("params")
def params_group():
    """Create, validate, and inspect LoadCase parameterizations."""


@params_group.command("generate")
@click.option(
    "--source", type=click.Choice(["preset", "defaults", "overrides"]), required=True,
    help="How to build the case. 'defaults' puts one block at --model's own default CONs.",
)
@click.option(
    "--model", "model_id", default=None, metavar="MODEL_ID",
    help="Load model for the it/vfd blocks (--source preset) or the single block (--source defaults). "
    f"Defaults to {DEFAULT_BLOCK_MODELS['it']}. See `perc-studio models list`.",
)
@click.option(
    "--block", "defaults_block", type=click.Choice(list(BLOCK_NAMES)), default="it",
    help="Which block --source defaults fills.",
)
@click.option("--preset-id", default=None, help="ridethrough_presets.RIDE_THROUGH_PRESETS key (--source preset).")
@click.option(
    "--base-case", type=click.Path(exists=True, dir_okay=False), default=None,
    help="Existing case JSON to apply --override values onto (--source overrides).",
)
@click.option(
    "--override", "overrides", multiple=True, metavar="BLOCK.CON=VALUE",
    help="Explicit CON override, e.g. it.VDPA=0.75. Repeatable.",
)
@click.option("--facility-name", default="Example Data Center")
@click.option("--bus-number", type=int, default=100001)
@click.option("--bus-name", default="DC_POI")
@click.option("--use-case", default="AI Training")
@click.option("--use-case-pct", type=int, default=100)
@click.option("--total-mw", type=float, default=300.0)
@click.option("--power-factor", type=float, default=0.99)
@click.option("--pct-it", type=float, default=70.0)
@click.option("--pct-vfd", type=float, default=20.0)
@click.option("--pct-motor", type=float, default=5.0)
@click.option("--pct-other", type=float, default=5.0)
@click.option("--include-vfd/--no-include-vfd", default=True)
@click.option("--include-motor/--no-include-motor", default=True)
@click.option("--motor-facility-type", default="Mixed - moderate mix of large & small motors")
@click.option("--motor-has-lighting", is_flag=True, default=False)
@click.option("--case-id", default=None)
@click.option("--out", type=click.Path(dir_okay=False), default=None, help="Write the case JSON here.")
@pretty_option
def generate(
    source, model_id, defaults_block, preset_id, base_case, overrides, facility_name, bus_number, bus_name,
    use_case, use_case_pct, total_mw, power_factor, pct_it, pct_vfd, pct_motor, pct_other,
    include_vfd, include_motor, motor_facility_type, motor_has_lighting, case_id, out, pretty,
):
    with cli_result("params generate", pretty) as result:
        if source in ("preset", "defaults"):
            facility = FacilityInfo(
                name=facility_name, bus_number=bus_number, bus_name=bus_name,
                use_case=use_case, use_case_pct=use_case_pct, total_mw=total_mw, power_factor=power_factor,
            )
            load_composition = LoadComposition(
                pct_it=pct_it, pct_cooling_vfd=pct_vfd, pct_cooling_motor=pct_motor, pct_other=pct_other,
            )
            model_id = model_id or DEFAULT_BLOCK_MODELS["it"]
            if source == "preset" and not preset_id:
                raise UsageError("--preset-id is required for --source preset")
            try:
                if source == "defaults":
                    case = case_from_model_defaults(
                        model_id, facility=facility, load_composition=load_composition,
                        block_name=defaults_block, case_id=case_id,
                    )
                else:
                    case = case_from_preset(
                        preset_id, facility=facility, load_composition=load_composition, model_id=model_id,
                        include_vfd=include_vfd, include_motor=include_motor,
                        motor_facility_type=motor_facility_type, motor_has_lighting=motor_has_lighting,
                        case_id=case_id,
                    )
            except (KeyError, ValueError) as exc:
                raise UsageError(str(exc).strip('"')) from exc

        else:  # overrides
            if not base_case:
                raise UsageError("--base-case is required for --source overrides")
            case = from_json(base_case)
            grouped: dict = {}
            for spec in overrides:
                block, name, value = _parse_override(spec)
                grouped.setdefault(block, {})[name] = value
            for block, cons in grouped.items():
                try:
                    case = case_with_overrides(case, block, cons)
                except ValueError as exc:
                    raise UsageError(str(exc)) from exc

        if out:
            to_json(case, out)
        result["data"] = {"case": to_dict(case), "out": out}


@params_group.command("validate")
@click.argument("case_json", type=click.Path(exists=True, dir_okay=False))
@pretty_option
def validate(case_json, pretty):
    """Schema-level validation: every block's CONs match its load model,
    load-split==100, schema_version. Does NOT run anything - see `perc-studio validate results`
    for expected-vs-actual behavioral validation."""
    with cli_result("params validate", pretty) as result:
        case = from_json(case_json)
        problems = schema_problems(case)
        if problems:
            raise SchemaInvalidError("; ".join(problems))
        result["data"] = {"case_id": case.case_id, "valid": True}


@params_group.command("show")
@click.argument("case_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--human", is_flag=True, default=False, help="Print a formatted summary before the JSON.")
@click.option("--block", "only_block", type=click.Choice(list(BLOCK_NAMES)), default=None,
              help="Return only this block's CONs (data.block) instead of the whole case.")
@pretty_option
def show(case_json, human, only_block, pretty):
    with cli_result("params show", pretty) as result:
        case = from_json(case_json)
        if only_block:
            block = case.block(only_block)
            if block is None:
                raise UsageError(f"case {case.case_id!r} has no {only_block} block")
            result["data"] = {"case_id": case.case_id, "block_name": only_block, "block": to_dict(case)[f"{only_block}_block"]}
            return
        if human:
            lines = [
                f"case_id: {case.case_id}",
                f"facility: {case.facility.name} (bus {case.facility.bus_number}/{case.facility.bus_name})",
                f"total_mw: {case.facility.total_mw}  load split valid: {case.is_load_split_valid}",
            ]
            for name, block in case.blocks().items():
                lines.append(
                    f"{name}_block: model={block.model_id} source={block.source} preset_id={block.preset_id}"
                )
            click.echo("\n".join(lines))
        result["data"] = {"case": to_dict(case)}


def _block_diff(name: str, a, b) -> dict | None:
    """What differs between two cases' `name` block, or None when they are the same."""
    if a is None and b is None:
        return None
    if a is None or b is None:
        return {"block": name, "only_in": "b" if a is None else "a"}
    if a.model_id != b.model_id:
        return {"block": name, "model_id": {"a": a.model_id, "b": b.model_id}}
    changed = {
        con: {"a": a.cons.get(con), "b": b.cons.get(con)}
        for con in sorted(set(a.cons) | set(b.cons)) if a.cons.get(con) != b.cons.get(con)
    }
    return {"block": name, "model_id": a.model_id, "changed": changed} if changed else None


@params_group.command("diff")
@click.argument("case_a", type=click.Path(exists=True, dir_okay=False))
@click.argument("case_b", type=click.Path(exists=True, dir_okay=False))
@click.option("--block", "only_block", type=click.Choice(list(BLOCK_NAMES)), default=None,
              help="Compare only this block.")
@pretty_option
def diff(case_a, case_b, only_block, pretty):
    """Which CONs differ between two cases, block by block (exit 0 either way; see data.identical)."""
    with cli_result("params diff", pretty) as result:
        a, b = from_json(case_a), from_json(case_b)
        names = [only_block] if only_block else list(BLOCK_NAMES)
        blocks = [d for d in (_block_diff(n, a.block(n), b.block(n)) for n in names) if d]
        result["data"] = {
            "case_a": a.case_id, "case_b": b.case_id, "identical": not blocks,
            "changed_cons": sum(len(d.get("changed", {})) for d in blocks), "blocks": blocks,
        }
