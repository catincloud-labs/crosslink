"""Admit a built wheel and sdist only when they are what an upload should carry.

    python3 .github/release/check-dist.py <dist-directory> \\
        --project <distribution-name> --package <import-name>
    python3 .github/release/check-dist.py --arms

Run by the `build` job in `.github/workflows/publish.yml` on the files an
upload job will upload, before any upload, and by hand the same way. It reads
the files, never `pyproject.toml`, because the build backend assembles the
metadata an index stores.

What it refuses, each named in the error it prints:

  - a directory that does not hold exactly one wheel and one sdist, each
    named for the project and the version the wheel's METADATA carries
  - a METADATA, or an sdist's PKG-INFO, whose `Name` is not the project, that has no
    `License-Expression: Apache-2.0`, no `License-File: LICENSE` or no
    `Development Status :: 3 - Alpha` classifier, that carries a `License ::`
    classifier (PEP 639 excludes one beside an expression), or whose headers
    or the description below them are not ASCII. The description is the
    README, so this is the README read from the file an index will show
  - a `Requires-Dist` that names a URL: a direct reference, which an index
    refuses and which would make an install fetch from somewhere the index
    does not vouch for
  - a wheel with no `conformance` extra that requires pytest, since the
    contract the package ships imports it
  - a wheel without the package, its contract or its calibration, or with a
    file outside the package and its own `.dist-info`
  - an sdist with a file outside the package, `pyproject.toml`, `README.md`
    and `LICENSE`, the list `pyproject.toml` gives the sdist, beside the
    `PKG-INFO` and `.gitignore` the build backend adds
  - a wheel whose `<package>/__init__.py` says a `__version__` other than the
    METADATA's `Version`: the tree writes its version twice, and the tag is
    compared with only one of them (check-version.sh)
  - a file that records what a document used to say (`*.history.md`), in
    either archive
  - an sdist whose PKG-INFO disagrees with the wheel on name or version

Exit codes: 0 admitted; 1 refused, with each cause printed; 64 usage.

`--arms` shows the refusals before the check is trusted: it writes a wheel and
an sdist that pass, then one pair per refusal above, each wrong in one way,
and runs this same check on each. An arm is decided by its exit code and by
the cause printed, so one refusal cannot stand in for another, and the pair
built right is read last.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

ADMITTED = 0
REFUSED = 1
USAGE = 64

VERSION_LINE = re.compile(r'^__version__ = "([^"]+)"$', re.M)

#: What an sdist holds beside the package: the list `pyproject.toml` gives
#: it, and the two files the build backend adds.
SDIST_FILES = ("pyproject.toml", "README.md", "LICENSE", "PKG-INFO", ".gitignore")


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"check-dist.py: {message}", file=sys.stderr)
        sys.exit(USAGE)


def headers_of(metadata: str) -> list[str]:
    return metadata.replace("\r\n", "\n").split("\n\n", 1)[0].splitlines()


def value_of(headers: list[str], field: str) -> str | None:
    found = [line.split(": ", 1)[1] for line in headers if line.startswith(f"{field}: ")]
    return found[0] if len(found) == 1 else None


def judge_headers(headers: list[str], project: str, what: str = "METADATA") -> list[str]:
    return [problem.replace("METADATA", what) for problem in judge_metadata(headers, project)]


def judge_description(whole: str, headers: list[str], what: str) -> list[str]:
    """The text below the headers, judged apart from them so each has its own cause."""
    if "\n".join(headers).isascii() and not whole.isascii():
        return [f"{what}'s description is not ASCII"]
    return []


def judge_metadata(headers: list[str], project: str) -> list[str]:
    problems = []
    if value_of(headers, "Name") != project:
        problems.append(f"METADATA names the distribution {value_of(headers, 'Name')!r}, expected {project!r}")
    for line in ("License-Expression: Apache-2.0", "License-File: LICENSE", "Classifier: Development Status :: 3 - Alpha"):
        if line not in headers:
            problems.append(f"METADATA has no line {line!r}")
    problems += [f"METADATA carries {line!r}, which PEP 639 excludes" for line in headers if line.startswith("Classifier: License ::")]
    requirements = [line for line in headers if line.startswith("Requires-Dist: ")]
    problems += [f"METADATA: {line!r} names a URL, a direct reference" for line in requirements if "@" in line or "://" in line]
    if "Provides-Extra: conformance" not in headers or not any(
        re.match(r"Requires-Dist: pytest(?![\w.-]).*; extra == .conformance.$", line) for line in requirements
    ):
        problems.append("METADATA has no `conformance` extra that requires pytest")
    if not "\n".join(headers).isascii():
        problems.append("METADATA's headers are not ASCII")
    return problems


def judge_wheel(wheel: Path, project: str, package: str) -> tuple[list[str], str | None]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            return [f"{wheel.name} holds {len(metadata)} METADATA files"], None
        whole = archive.read(metadata[0]).decode("utf-8")
        headers = headers_of(whole)
        root = f"{package}/__init__.py"
        source = archive.read(root).decode("utf-8") if root in names else ""
    for line in headers:
        print(line)
    version = value_of(headers, "Version")
    problems = judge_headers(headers, project) + judge_description(whole, headers, "METADATA")
    problems += [f"the wheel has no {member}" for member in (root, f"{package}/conformance.py", f"{package}/conformance_calibration.py") if member not in names]
    said = VERSION_LINE.findall(source)
    if root in names and said != [version]:
        problems.append(f"{root} says __version__ {said}, and METADATA says Version {version!r}")
    problems += [f"the wheel carries {name}, a history file" for name in names if name.endswith(".history.md")]
    own = (f"{package}/", f"{project.replace('-', '_')}-{version}.dist-info/")
    problems += [f"the wheel carries {name}, outside the package and its dist-info" for name in names if not name.startswith(own)]
    return problems, version


def judge_sdist(sdist: Path, project: str, package: str, version: str | None) -> list[str]:
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        info = [name for name in names if name.count("/") == 1 and name.endswith("/PKG-INFO")]
        if len(info) != 1:
            return [f"{sdist.name} holds {len(info)} top-level PKG-INFO files"]
        member = archive.extractfile(info[0])
        whole = member.read().decode("utf-8") if member else ""
        headers = headers_of(whole)
    problems = [f"the sdist carries {name}, a history file" for name in names if name.endswith(".history.md")]
    root = f"{project.replace('-', '_')}-{version}"
    listed = (f"{root}/src/{package}/", *(f"{root}/{name}" for name in SDIST_FILES))
    problems += [
        f"the sdist carries {name}, outside the list pyproject.toml gives it"
        for name in names
        if name != root and not name.startswith(listed[0]) and name not in listed[1:] and name not in (f"{root}/src", f"{root}/src/{package}")
    ]
    problems += judge_headers(headers, project, "PKG-INFO") + judge_description(whole, headers, "PKG-INFO")
    if value_of(headers, "Name") != project or value_of(headers, "Version") != version:
        problems.append(
            f"the sdist's PKG-INFO says {value_of(headers, 'Name')!r} {value_of(headers, 'Version')!r}, "
            f"and the wheel says {project!r} {version!r}"
        )
    return problems


def judge(directory: Path, project: str, package: str) -> list[str]:
    files = sorted(path.name for path in directory.iterdir()) if directory.is_dir() else []
    wheels = [name for name in files if name.endswith(".whl")]
    sdists = [name for name in files if name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(files) != 2:
        return [f"{directory} holds {files}, expected exactly one wheel and one sdist"]
    problems, version = judge_wheel(directory / wheels[0], project, package)
    stem = project.replace("-", "_")
    want = sorted([f"{stem}-{version}-py3-none-any.whl", f"{stem}-{version}.tar.gz"])
    if files != want:
        problems.append(f"the files are named {files}, expected {want}")
    return problems + judge_sdist(directory / sdists[0], project, package, version)


# --- the arms ---------------------------------------------------------------

PROJECT = "catincloud-example"
PACKAGE = "example"
GOOD_METADATA = (
    "Metadata-Version: 2.4\n"
    "Name: catincloud-example\n"
    "Version: 1.2.3\n"
    "License-Expression: Apache-2.0\n"
    "License-File: LICENSE\n"
    "Classifier: Development Status :: 3 - Alpha\n"
    "Requires-Dist: pyyaml>=6.0\n"
    "Provides-Extra: conformance\n"
    "Requires-Dist: pytest>=8.4; extra == 'conformance'\n"
    "\n"
    "The description, which may say anything: name @ https://example.invalid\n"
)
GOOD_MEMBERS = {
    "example/__init__.py": '__version__ = "1.2.3"\n',
    "example/conformance.py": "",
    "example/conformance_calibration.py": "",
}


def write_pair(
    directory: Path,
    metadata: str = GOOD_METADATA,
    members: dict[str, str] | None = None,
    pkg_info: str | None = None,
    sdist_extra: str | None = None,
    wheel_name: str = "catincloud_example-1.2.3-py3-none-any.whl",
) -> None:
    directory.mkdir(parents=True)
    members = GOOD_MEMBERS if members is None else members
    with zipfile.ZipFile(directory / wheel_name, "w") as wheel:
        for name, text in members.items():
            wheel.writestr(name, text)
        wheel.writestr("catincloud_example-1.2.3.dist-info/METADATA", metadata)
    with tarfile.open(directory / "catincloud_example-1.2.3.tar.gz", "w:gz") as sdist:
        entries = {"catincloud_example-1.2.3/PKG-INFO": GOOD_METADATA if pkg_info is None else pkg_info}
        if sdist_extra:
            entries[f"catincloud_example-1.2.3/{sdist_extra}"] = "old text\n"
        for name, text in entries.items():
            data = text.encode("utf-8")
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            sdist.addfile(entry, io.BytesIO(data))


def changed(old: str, new: str) -> str:
    assert old in GOOD_METADATA, old
    return GOOD_METADATA.replace(old, new)


def without(member: str) -> dict[str, str]:
    return {name: text for name, text in GOOD_MEMBERS.items() if name != member}


#: (the arm, the cause its refusal must print, how its pair is written)
ARMS: tuple[tuple[str, str, Callable[[Path], None]], ...] = (
    ("another distribution name", "METADATA names the distribution 'example'",
     lambda d: write_pair(d, changed("Name: catincloud-example", "Name: example"))),
    ("no licence expression", "no line 'License-Expression: Apache-2.0'",
     lambda d: write_pair(d, changed("License-Expression: Apache-2.0\n", ""))),
    ("a licence classifier", "which PEP 639 excludes",
     lambda d: write_pair(d, changed("Classifier: Dev", "Classifier: License :: OSI Approved\nClassifier: Dev"))),
    ("no development status", "no line 'Classifier: Development Status :: 3 - Alpha'",
     lambda d: write_pair(d, changed("3 - Alpha", "4 - Beta"))),
    ("a requirement on a git URL", "METADATA: 'Requires-Dist: other @ git",
     lambda d: write_pair(d, changed("Requires-Dist: pyyaml>=6.0", "Requires-Dist: other @ git+https://example.invalid/other@abc"))),
    ("an extra on a git URL", "METADATA: \"Requires-Dist: other@ git",
     lambda d: write_pair(d, GOOD_METADATA.replace("\n\n", "\nRequires-Dist: other@ git+https://example.invalid/o ; extra == 'service'\n\n", 1))),
    ("no conformance extra", "no `conformance` extra that requires pytest",
     lambda d: write_pair(d, changed("Provides-Extra: conformance\nRequires-Dist: pytest>=8.4; extra == 'conformance'\n", ""))),
    ("pytest under another extra", "no `conformance` extra that requires pytest",
     lambda d: write_pair(d, changed("extra == 'conformance'", "extra == 'test'"))),
    ("a header that is not ASCII", "headers are not ASCII",
     lambda d: write_pair(d, changed("Requires-Dist: pyyaml>=6.0", "Summary: caf" + chr(233) + "\nRequires-Dist: pyyaml>=6.0"))),
    ("a description that is not ASCII", "METADATA's description is not ASCII",
     lambda d: write_pair(d, changed("The description, which", "The description, caf" + chr(233) + ", which"))),
    ("a description that is not ASCII in the sdist alone", "PKG-INFO's description is not ASCII",
     lambda d: write_pair(d, pkg_info=changed("The description, which", "The description, caf" + chr(233) + ", which"))),
    ("no contract in the wheel", "the wheel has no example/conformance.py",
     lambda d: write_pair(d, members=without("example/conformance.py"))),
    ("no calibration in the wheel", "the wheel has no example/conformance_calibration.py",
     lambda d: write_pair(d, members=without("example/conformance_calibration.py"))),
    ("the package says another version", "says __version__ ['1.2.4']",
     lambda d: write_pair(d, members={**GOOD_MEMBERS, "example/__init__.py": '__version__ = "1.2.4"\n'})),
    ("the package says no version", "says __version__ []",
     lambda d: write_pair(d, members={**GOOD_MEMBERS, "example/__init__.py": ""})),
    ("a history file in the wheel", "the wheel carries example/NOTES.history.md",
     lambda d: write_pair(d, members={**GOOD_MEMBERS, "example/NOTES.history.md": "old\n"})),
    ("a history file in the sdist", "the sdist carries catincloud_example-1.2.3/src/example/NOTES.history.md, a history file",
     lambda d: write_pair(d, sdist_extra="src/example/NOTES.history.md")),
    ("a file the sdist is not given", "the sdist carries catincloud_example-1.2.3/AGENTS.md, outside the list",
     lambda d: write_pair(d, sdist_extra="AGENTS.md")),
    ("a second package in the wheel", "the wheel carries other/__init__.py, outside the package",
     lambda d: write_pair(d, members={**GOOD_MEMBERS, "other/__init__.py": ""})),
    ("a plugin of pytest, not pytest", "no `conformance` extra that requires pytest",
     lambda d: write_pair(d, changed("Requires-Dist: pytest>=8.4; extra", "Requires-Dist: pytest-cov>=8.4; extra"))),
    ("a git URL in the sdist alone", "PKG-INFO: 'Requires-Dist: other @ git+https://example.invalid/other@abc' names a URL",
     lambda d: write_pair(d, pkg_info=changed("Requires-Dist: pyyaml>=6.0", "Requires-Dist: other @ git+https://example.invalid/other@abc"))),
    ("a header that is not ASCII in the sdist alone", "PKG-INFO's headers are not ASCII",
     lambda d: write_pair(d, pkg_info=changed("Requires-Dist: pyyaml>=6.0", "Summary: caf" + chr(233) + "\nRequires-Dist: pyyaml>=6.0"))),
    ("an sdist for another version", "the sdist's PKG-INFO says 'catincloud-example' '1.2.4'",
     lambda d: write_pair(d, pkg_info=GOOD_METADATA.replace("Version: 1.2.3", "Version: 1.2.4"))),
    ("a wheel named for another version", "the files are named",
     lambda d: write_pair(d, wheel_name="catincloud_example-1.2.4-py3-none-any.whl")),
    ("a third file", "expected exactly one wheel and one sdist",
     lambda d: (write_pair(d), (d / "notes.txt").write_text("x", encoding="utf-8"))[0]),
    ("no files", "expected exactly one wheel and one sdist", lambda d: d.mkdir(parents=True)),
)


def run_arms() -> int:
    red = 0
    with tempfile.TemporaryDirectory() as temp:
        for index, (name, cause, write) in enumerate(ARMS):
            directory = Path(temp) / f"arm-{index:02d}"
            write(directory)
            print(f"::group::{name}", flush=True)
            problems = judge(directory, PROJECT, PACKAGE)
            for problem in problems:
                print(problem)
            print("::endgroup::", flush=True)
            # Exactly one cause, and the one built: an arm wrong in two ways
            # shows only that one of them is caught.
            as_built = len(problems) == 1 and cause in problems[0]
            print(f"{'ok  ' if as_built else 'RED '} refused: {name}")
            if not as_built:
                print(f"::error::{name}: expected the one cause {cause!r}, got {problems}")
                red += 1
        admitted = Path(temp) / "admitted"
        write_pair(admitted)
        problems = judge(admitted, PROJECT, PACKAGE)
        print(f"{'ok  ' if not problems else 'RED '} admitted: the pair built right")
        if problems:
            print(f"::error::the pair built right was refused: {problems}")
            red += 1
    return ADMITTED if red == 0 else REFUSED


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("directory", nargs="?", type=Path)
    parser.add_argument("--project")
    parser.add_argument("--package")
    parser.add_argument("--arms", action="store_true")
    args = parser.parse_args(argv)
    if args.arms:
        if args.directory or args.project or args.package:
            parser.error("--arms takes no other argument")
        return run_arms()
    if not (args.directory and args.project and args.package):
        parser.error("a directory, --project and --package are required")
    problems = judge(args.directory, args.project, args.package)
    for problem in problems:
        print(f"::error::{problem}")
    print("admitted" if not problems else "refused")
    return ADMITTED if not problems else REFUSED


if __name__ == "__main__":
    sys.exit(main())
