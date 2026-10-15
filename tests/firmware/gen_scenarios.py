"""Turns tests/scenarios.json into a C++ include for the firmware unit tests.

Run by the Makefile; you don't need to call it directly.
"""
import json
import sys
from pathlib import Path

FIELDS = [("solarV", 1), ("z1", 2), ("z2", 4), ("tankPct", 8), ("tempC", 16),
          ("pumpA", 32), ("flowLpm", 64), ("floatHigh", 128)]


def num(v):
    if v is None:
        return "NAN"
    if isinstance(v, bool):
        return "1" if v else "0"
    return repr(float(v)) + "f"


def inset(d):
    mask = 0
    vals = []
    for name, bit in FIELDS:
        if name in d:
            mask |= bit
            vals.append(num(d[name]))
        else:
            vals.append("0")
    return "{%d, %s}" % (mask, ", ".join(vals))


def cstr(v):
    return "nullptr" if v is None else json.dumps(v)


def tri(v):
    return "-1" if v is None else ("1" if v else "0")


def rng(v):
    if v is None:
        return "false, {0, 0}"
    return "true, {%r, %r}" % (float(v[0]), float(v[1]))


def expect(e):
    return "{%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s}" % (
        cstr(e.get("phase")), cstr(e.get("source")), cstr(e.get("relay")),
        cstr(e.get("fault")), cstr(e.get("mode")),
        tri(e.get("pump")), tri(e.get("valve1")), tri(e.get("valve2")), tri(e.get("alertLed")),
        str(e.get("switches", -1)),
        rng(e.get("solarWh")), rng(e.get("gridWh")), rng(e.get("litres")))


def main(src, dst):
    spec = json.loads(Path(src).read_text())
    out = ["// Generated from tests/scenarios.json by gen_scenarios.py. Do not edit.", ""]
    out.append("static const uint32_t TICK_MS = %d;" % spec["tickMs"])
    out.append("static const float METER_VOLTS = %sf;" % float(spec["meter"]["volts"]))
    out.append("static const float METER_PF = %sf;" % float(spec["meter"]["powerFactor"]))
    out.append("static const InSet DEFAULTS = %s;" % inset(spec["defaults"]))
    out.append("")
    for i, sc in enumerate(spec["scenarios"]):
        out.append("static const Step STEPS_%d[] = {" % i)
        for st in sc["steps"]:
            out.append("  {%d, %s, %s, %s, %s}," % (
                st["ms"], inset(st.get("in", {})), cstr(st.get("cmd")),
                expect(st.get("expect", {})), cstr(",".join(st.get("events", [])))))
        out.append("};")
    out.append("")
    out.append("static const Scenario SCENARIOS[] = {")
    for i, sc in enumerate(spec["scenarios"]):
        out.append("  {%s, %s, STEPS_%d, %d}," % (
            json.dumps(sc["name"]), inset(sc.get("init", {})), i, len(sc["steps"])))
    out.append("};")
    out.append("static const int SCENARIO_COUNT = %d;" % len(spec["scenarios"]))
    Path(dst).write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
