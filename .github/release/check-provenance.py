"""Admit a PyPI provenance only when every publisher in it is the one expected.

    python3 .github/release/check-provenance.py <provenance.json> \\
        --repository <owner>/<repo> --workflow <file> --environment <name>

`<provenance.json>` is what an index's integrity API answers for one file,
`<index>/integrity/<project>/<version>/<file>/provenance`: a list of
attestation bundles, each naming the trusted publisher that produced its
attestations. This reads the IDENTITY in it, not its presence. A provenance
naming another repository, another workflow or another environment is a
provenance, and a presence check would admit it.

One script, run by `.github/workflows/publish.yml` after each upload, by its
`identity` job against provenances that name another publisher, and by hand
against any file on an index. Each refusal has its own exit code, so an arm
that expects one refusal cannot be satisfied by another:

  0   every bundle's publisher is a GitHub publisher naming exactly the
      repository, workflow and environment given, and every bundle carries at
      least one attestation
  3   the file is missing, is not JSON, or has no `attestation_bundles` list,
      so there is no provenance to read
  4   the provenance holds no bundle, or a bundle with no attestation, so
      nothing in it vouches for the file
  5   a bundle's publisher is not the one expected
  64  usage

It checks the publisher the index stored beside each attestation, which the
index verified against the attestation's signing certificate at upload. It
does not verify the attestations' signatures itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

ADMITTED = 0
UNREADABLE = 3
NOTHING_VOUCHES = 4
ANOTHER_PUBLISHER = 5
USAGE = 64


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"check-provenance.py: {message}", file=sys.stderr)
        sys.exit(USAGE)


def bundles_of(path: Path) -> list[object] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"::error::{path} is not a provenance: {error}")
        return None
    bundles = document.get("attestation_bundles") if isinstance(document, dict) else None
    if not isinstance(bundles, list):
        print(f"::error::{path} has no attestation_bundles list.")
        return None
    return bundles


def mismatches(publisher: object, expected: dict[str, str]) -> list[str]:
    if not isinstance(publisher, dict):
        return [f"the publisher is {publisher!r}, not a mapping"]
    return [
        f"{field} is {publisher.get(field)!r}, expected {want!r}"
        for field, want in expected.items()
        if publisher.get(field) != want
    ]


def judge(bundles: list[object], expected: dict[str, str]) -> int:
    if not bundles:
        print("::error::The provenance holds no attestation bundle.")
        return NOTHING_VOUCHES
    verdict = ADMITTED
    for index, bundle in enumerate(bundles):
        publisher = bundle.get("publisher") if isinstance(bundle, dict) else None
        attestations = bundle.get("attestations") if isinstance(bundle, dict) else None
        print(f"bundle {index} publisher: {json.dumps(publisher, sort_keys=True)}")
        problems = mismatches(publisher, expected)
        if problems:
            print(f"::error::bundle {index}: " + "; ".join(problems))
            verdict = ANOTHER_PUBLISHER
        elif not isinstance(attestations, list) or not attestations:
            print(f"::error::bundle {index} carries no attestation.")
            verdict = max(verdict, NOTHING_VOUCHES)
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("provenance", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--environment", required=True)
    args = parser.parse_args(argv)
    expected = {
        "kind": "GitHub",
        "repository": args.repository,
        "workflow": args.workflow,
        "environment": args.environment,
    }
    print(f"expected publisher: {json.dumps(expected, sort_keys=True)}")
    bundles = bundles_of(args.provenance)
    if bundles is None:
        return UNREADABLE
    verdict = judge(bundles, expected)
    print("admitted" if verdict == ADMITTED else f"refused with {verdict}")
    return verdict


if __name__ == "__main__":
    sys.exit(main())
