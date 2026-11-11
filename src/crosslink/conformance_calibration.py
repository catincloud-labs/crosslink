# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Formats built wrong on purpose, so the contract can be watched going red.

:mod:`crosslink.conformance` ships so that an implementer outside this
repository can run it. A contract observed only to pass has not been shown to
be a control, so the cases built to make it fail ship beside it. Run one
through the contract and the arms its defect is for go red, and no others.

Three formats, each a thin wrapper around a real ``DagsterProject`` so each is
wrong in **exactly one way**. A subject wrong in two ways proves only that the
contract catches one of them.

- :class:`AFormatThatRefusesMalformedInput` raises where tier 1 says
  note-and-skip.
- :class:`AFormatThatSwallowsSilently` degrades without leaving a note.
- :class:`AFormatWithAnUnstableFingerprint` claims tier 2, and no two of its
  fingerprints agree.

:func:`a_conforming_core` builds the project all three wrap, with no defect.
It is the control's control: green on every arm, through the same runner.

Each format carries ``expected_reds``: every arm its defect is for, mapped to
the name of the exception class that arm ends in, and no other arm. It holds
when the format is wired to the tier it claims, which is
:class:`~crosslink.conformance.ProjectSourceContract` for the first two and
:class:`~crosslink.conformance.FingerprintedProjectContract` for the third.
The core's expected reds are none. :func:`observed_outcomes` runs every arm
of a contract instance directly and reports each as ``"pass"`` or the name of
the exception class it raised, and :func:`reds` keeps the failures. Each
format's constructor takes ``make_project``'s three arguments, so wiring one
to its tier is one method::

    from crosslink.conformance import ProjectSourceContract
    from crosslink.conformance_calibration import (
        AFormatThatSwallowsSilently,
        observed_outcomes,
        reds,
    )

    class SilentConformance(ProjectSourceContract):
        def make_project(self, declarations, semantics, sources):
            return AFormatThatSwallowsSilently(declarations, semantics, sources)

    observed = reds(observed_outcomes(SilentConformance()))
    assert observed == AFormatThatSwallowsSilently.expected_reds

``crosslink``'s own ``tests/test_conformance_calibration.py`` runs these
formats under that repository's CI and asserts each split twice: the observed
reds against a literal written in the test, and ``expected_reds`` against the
same literal, so a change to either side here goes red there. Like the
contract's, the names here are public surface once a format pins against
them, and renaming one is a breaking change.

Measures: src/crosslink/conformance.py, ProjectSourceContract
Measures: src/crosslink/conformance.py, FingerprintedProjectContract
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import ClassVar

import yaml

from .model import Fingerprint, ProjectDeclarations, ProjectModel
from .project import DagsterProject

__all__ = [
    "AFormatThatRefusesMalformedInput",
    "AFormatThatSwallowsSilently",
    "AFormatWithAnUnstableFingerprint",
    "a_conforming_core",
    "observed_outcomes",
    "reds",
]

_MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
)


def a_conforming_core(
    declarations: dict[str, str],
    semantics: dict[str, str],
    sources: dict[str, str],
) -> DagsterProject:
    """The conforming core every wrong format wraps.

    Delegating to the real thing is what keeps each subject wrong in exactly
    one way: every behaviour except the injected defect is the behaviour the
    contract already holds green.
    """

    return DagsterProject(
        _MODELS,
        name="calibration",
        declaration_sources=declarations,
        semantic_sources=semantics,
        source_declarations=sources,
    )


# --- the deliberately wrong formats -----------------------------------------


class AFormatThatRefusesMalformedInput:
    """Wrong in exactly one way: it raises where the contract says
    note-and-skip - the authoring-typo-becomes-an-outage anti-pattern the
    tier-1 docstring warns about, implemented verbatim. Its reds are its own
    ``ValueError`` surfacing through the never-raises arms, which call
    ``declarations()`` unguarded on purpose."""

    format = "calibrated-wrong"
    expected_reds: ClassVar[Mapping[str, str]] = MappingProxyType(
        {
            "test_malformed_input_never_raises": "ValueError",
            "test_malformed_input_is_explained_rather_than_silent": "ValueError",
            "test_a_malformed_source_declaration_never_raises_and_is_explained": "ValueError",
        }
    )

    def __init__(
        self,
        declarations: dict[str, str],
        semantics: dict[str, str],
        sources: dict[str, str],
    ) -> None:
        self._core = a_conforming_core(declarations, semantics, sources)
        self._texts = (
            list(declarations.values())
            + list(semantics.values())
            + list(sources.values())
        )

    def declarations(self) -> ProjectDeclarations:
        for text in self._texts:
            try:
                yaml.safe_load(text)
            except yaml.YAMLError:
                raise ValueError(
                    "refusing to describe a project with a malformed declaration"
                )
        return self._core.declarations()


class AFormatThatSwallowsSilently:
    """Wrong in exactly one way: it degrades without a note. Never raises -
    which is precisely why the never-raises arms alone cannot catch it, and
    the explained-rather-than-silent arms must, including the arm whose skip
    of a source with no system must be explained, and the arm whose note half
    a swallowing format cannot produce."""

    format = "calibrated-wrong"
    expected_reds: ClassVar[Mapping[str, str]] = MappingProxyType(
        {
            "test_malformed_input_is_explained_rather_than_silent": "AssertionError",
            "test_a_malformed_source_declaration_never_raises_and_is_explained": "AssertionError",
            "test_a_source_requires_a_system_it_cannot_invent": "AssertionError",
            "test_a_dangling_join_side_is_agreed_by_notes_and_findings": "AssertionError",
        }
    )

    def __init__(
        self,
        declarations: dict[str, str],
        semantics: dict[str, str],
        sources: dict[str, str],
    ) -> None:
        self._core = a_conforming_core(declarations, semantics, sources)

    def declarations(self) -> ProjectDeclarations:
        return replace(self._core.declarations(), notes=())


# Shared across instances on purpose: an unstable fingerprint must differ
# between two identical projects, not just between two calls on one.
_INSTABILITY = itertools.count()


class AFormatWithAnUnstableFingerprint:
    """Wrong in exactly one way: tier 2 claimed, but every fingerprint is
    unique - the drift baseline that reports drift against itself. Every
    tier-1 arm delegates to the conforming core and stays green."""

    format = "calibrated-wrong"
    expected_reds: ClassVar[Mapping[str, str]] = MappingProxyType(
        {
            "test_a_fingerprint_is_stable_across_calls": "AssertionError",
            "test_two_identical_projects_fingerprint_alike": "AssertionError",
        }
    )

    def __init__(
        self,
        declarations: dict[str, str],
        semantics: dict[str, str],
        sources: dict[str, str],
    ) -> None:
        self._core = a_conforming_core(declarations, semantics, sources)

    def declarations(self) -> ProjectDeclarations:
        return self._core.declarations()

    def fingerprint(self) -> Fingerprint:
        stable = self._core.fingerprint()
        return Fingerprint(
            layers={**stable.layers, "instability": str(next(_INSTABILITY))},
            models=stable.models,
        )


# --- reading the split ------------------------------------------------------


def observed_outcomes(contract: object) -> dict[str, str]:
    """Every contract arm, run directly: arm name -> 'pass' or the exception
    class name. Exception *types* are recorded, not just failure, so a
    subject failing for the wrong reason cannot masquerade as calibrated."""

    outcomes: dict[str, str] = {}
    for name in sorted(n for n in dir(contract) if n.startswith("test_")):
        try:
            getattr(contract, name)()
        except Exception as exc:  # noqa: BLE001 -- the outcome IS the datum: any exception an arm raises is recorded by type, never swallowed
            outcomes[name] = type(exc).__name__
        else:
            outcomes[name] = "pass"
    return outcomes


def reds(outcomes: dict[str, str]) -> dict[str, str]:
    """The arms that did not pass, with what each raised."""

    return {name: outcome for name, outcome in outcomes.items() if outcome != "pass"}
