"""Write bounded fixture outcome metadata immediately, including partial runs."""
import json
import os


def pytest_runtest_logreport(report):
    destination = os.environ.get("COCHEM_PUBLICATION_EVENTS")
    if not destination:
        return
    result = {"nodeid": report.nodeid, "phase": report.when, "outcome": report.outcome, "duration_seconds": report.duration}
    if report.failed:
        result["failure_excerpt"] = report.longreprtext[-6000:]
    with open(destination, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True) + "\n")

