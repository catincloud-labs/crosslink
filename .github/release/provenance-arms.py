"""The provenance identity check, shown refusing before it is trusted.

    python3 .github/release/provenance-arms.py --foreign <provenance.json> \\
        --repository <owner>/<repo> --workflow <file> --environment <name> \\
        --work <directory>

Run by the `identity` job in `.github/workflows/publish.yml`, which the upload
jobs need, and by hand the same way. `--foreign` is a provenance an index
really stored for a file some OTHER publisher uploaded: the job fetches one of
`catincloud-ration`'s from pypi.org. The other three name the publisher the upload
jobs expect.

Each arm is a provenance written into `--work`, handed to
`check-provenance.py` exactly as the upload jobs call it, and decided by its
exit code. The foreign provenance is refused as fetched. Every arm that
writes a provenance derives it from the foreign one, so each has the shape an
index really answers. The admitted arm is the foreign one with its publisher
rewritten to the expected one, and it is what shows the refusals are refusals
of a publisher, not of a shape the checker cannot read. Most refusing arms
change one field of the admitted publisher; two put another publisher's bundle
beside the expected one, in each order, so a checker that reads one bundle is
refused whichever it reads; two remove what an index might answer with (the
bundles, an attestation); two hand over no provenance at all; and one omits
`--environment` alone, so a checker that defaults it is refused.

Before any arm, a positive control: the foreign provenance holds at least one
bundle, each with at least one attestation, and names another repository, so
its refusal is a refusal of the publisher.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CHECKER = Path(__file__).resolve().parent / "check-provenance.py"

Document = dict[str, object]


@dataclass(frozen=True)
class Arm:
    name: str
    exit_code: int
    write: Callable[[Path], None]
    options: tuple[str, ...] | None = None


def dump(document: object) -> Callable[[Path], None]:
    return lambda path: path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def bundles(document: Document) -> list[dict[str, object]]:
    found = document.get("attestation_bundles")
    return found if isinstance(found, list) else []


def publisher_of(bundle: dict[str, object]) -> dict[str, object]:
    publisher = bundle.get("publisher")
    return publisher if isinstance(publisher, dict) else {}


def control(foreign: Document, expected: dict[str, str]) -> list[str]:
    found = bundles(foreign)
    problems = [] if found else ["the foreign provenance holds no bundle"]
    for index, bundle in enumerate(found):
        if not bundle.get("attestations"):
            problems.append(f"the foreign bundle {index} carries no attestation")
        publisher = bundle.get("publisher")
        print(f"foreign bundle {index} publisher: {json.dumps(publisher, sort_keys=True)}")
        if not isinstance(publisher, dict) or publisher.get("repository") == expected["repository"]:
            problems.append(f"the foreign bundle {index} does not name another repository")
    return problems


def ours(foreign: Document, expected: dict[str, str]) -> Document:
    admitted = copy.deepcopy(foreign)
    for bundle in bundles(admitted):
        bundle["publisher"] = {**publisher_of(bundle), **expected}
    return admitted


def changed(document: Document, field: str, value: object) -> Document:
    altered = copy.deepcopy(document)
    publisher = publisher_of(bundles(altered)[0])
    if value is None:
        publisher.pop(field, None)
    else:
        publisher[field] = value
    return altered


def arms(foreign: Document, expected: dict[str, str]) -> tuple[Arm, ...]:
    admitted = ours(foreign, expected)
    other_environment = "testpypi" if expected["environment"] != "testpypi" else "pypi"
    foreign_repository = str(publisher_of(bundles(foreign)[0]).get("repository"))
    mixed = copy.deepcopy(admitted)
    mixed["attestation_bundles"] = [*bundles(mixed), *copy.deepcopy(bundles(foreign))]
    reversed_mixed = copy.deepcopy(admitted)
    reversed_mixed["attestation_bundles"] = [*copy.deepcopy(bundles(foreign)), *bundles(reversed_mixed)]
    no_attestation = copy.deepcopy(admitted)
    bundles(no_attestation)[0]["attestations"] = []
    return (
        Arm("another publisher's provenance, as the index stored it", 5, dump(foreign)),
        Arm("another repository", 5, dump(changed(admitted, "repository", foreign_repository))),
        Arm(
            "a repository the expected one is a prefix of", 5,
            dump(changed(admitted, "repository", expected["repository"] + "-fork")),
        ),
        Arm(
            "the expected repository in another case", 5,
            dump(changed(admitted, "repository", expected["repository"].upper())),
        ),
        Arm("another workflow", 5, dump(changed(admitted, "workflow", "release.yml"))),
        Arm("another environment", 5, dump(changed(admitted, "environment", other_environment))),
        Arm(
            "an environment the expected one is a prefix of", 5,
            dump(changed(admitted, "environment", expected["environment"] + "-staging")),
        ),
        Arm("no environment", 5, dump(changed(admitted, "environment", None))),
        Arm("another kind of publisher", 5, dump(changed(admitted, "kind", "GitLab"))),
        Arm("the expected bundle, then another publisher's", 5, dump(mixed)),
        Arm("another publisher's bundle, then the expected one", 5, dump(reversed_mixed)),
        Arm("no bundle", 4, dump({**admitted, "attestation_bundles": []})),
        Arm("a bundle with no attestation", 4, dump(no_attestation)),
        Arm("not JSON", 3, lambda path: path.write_text("<html>not found</html>", encoding="utf-8")),
        Arm("no file", 3, lambda path: None),
        Arm(
            "no --environment given", 64, dump(admitted),
            (f"--repository={expected['repository']}", f"--workflow={expected['workflow']}"),
        ),
        # Last, so it is read only after every refusal above has been seen.
        Arm("the same provenance, naming the expected publisher", 0, dump(admitted)),
    )


def run_arm(arm: Arm, index: int, work: Path, expected: dict[str, str]) -> list[str]:
    path = work / f"arm-{index:02d}.json"
    path.unlink(missing_ok=True)
    arm.write(path)
    options = arm.options
    if options is None:
        options = tuple(f"--{field}={value}" for field, value in expected.items())
    command = [sys.executable, str(CHECKER), str(path), *options]
    print(f"::group::{arm.name}", flush=True)
    print("$ " + " ".join(command), flush=True)
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    print(done.stdout + done.stderr, flush=True)
    print("::endgroup::", flush=True)
    print(f"{arm.name}: exited {done.returncode}, expected {arm.exit_code}", flush=True)
    return [] if done.returncode == arm.exit_code else [f"exited {done.returncode}, expected {arm.exit_code}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--foreign", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--work", required=True, type=Path)
    args = parser.parse_args(argv)
    expected = {"repository": args.repository, "workflow": args.workflow, "environment": args.environment}
    foreign = json.loads(args.foreign.read_text(encoding="utf-8"))
    args.work.mkdir(parents=True, exist_ok=True)

    verdicts = {"control": control(foreign, expected)}
    if not verdicts["control"]:
        for index, arm in enumerate(arms(foreign, expected)):
            verdicts[arm.name] = run_arm(arm, index, args.work, expected)
    for name, problems in verdicts.items():
        print(f"{'ok  ' if not problems else 'RED '} {name}")
        for problem in problems:
            print(f"::error::{name}: {problem}")
    return 0 if len(verdicts) > 1 and not any(verdicts.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
