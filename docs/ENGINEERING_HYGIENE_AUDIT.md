# v0.3.1 Engineering Hygiene Audit

- Audit date: 2026-08-09
- Host: macOS, Python 3.9.6
- Baseline: `main` and `v0.3.0` at `60f79fcbe4222818004bc3d5666bc47217a1944a`
- Candidate branch: `codex/v0.3.1-engineering-hygiene`

This was an audit-first hardening pass. The repository structure, architecture,
metadata, tests, evidence, and frozen manifest were inspected before treating any
third-party criticism as fact. No ROS2, vendor SDK, or hardware result was generated
on macOS.

## Independent findings

| Finding | Evidence | Severity | Reproduced? | Fix? | Reason |
|---|---|---:|---|---|---|
| No automated portable gate | `.github/workflows/` absent on v0.3.0 | High | Yes | Yes | Add Python 3.9–3.11 unittest CI plus static/contract checks |
| Local reruns overwrite canonical evidence by default | benchmark and runtime CLI defaults target tracked JSON | Medium | Yes | Yes | Default to ignored `local_validation_outputs/`; explicit paths remain available for release regeneration |
| No lint baseline | no Ruff configuration or CI command | Medium | Yes | Yes | Add correctness-oriented Ruff rules; exclude the 12 frozen files from style-driven drift |
| No type baseline | no Pyright configuration or CI command | Medium | Yes | Yes | Scope Pyright to portable, non-frozen JAKA integration and support code |
| Release metadata currently agrees | `pyproject.toml`, `setup.py`, `package.xml`, `CITATION.cff` all report `0.3.0` | Medium if regressed | No drift | Preventive | Add automated consistency verification |
| YAML mirror currently agrees with Python | five names, parameters, ranges, resources, preconditions, effects, timeouts match | Medium if regressed | No drift | Preventive | Add automated registry mirror verification |
| Executor is difficult to audit | 333-line file; 221-line `execute`; nested observe/repair/retry/replan paths | Medium | Yes | Docs only | Frozen semantics prohibit structural refactoring in this candidate |
| STOP is not a physical-stop certificate | four initial grounding/repair exits do not call `backend.stop()`; JAKA stop is AGV-only | High semantic risk | Yes | Docs only | Preserve frozen behavior and document exact transmission boundary |
| Ament script layout affects dev CLI discovery | `setup.cfg` installs scripts under `lib/embodied_skill_ros` | Low | Yes | CI accommodation | Preserve ROS2 package layout; CI explicitly adds that directory to `PATH` |

## Third-party claim matrix

| Third-party claim | Reproduced? | Severity | Action |
|---|---|---:|---|
| 128 vs 144 tests | **NOT REPRODUCED** | Low | v0.3.0 discovers 128 tests, not 144; add dynamic inventory and retain environment-qualified 107/128 release records |
| No CI | **CONFIRMED** | High | Add portable GitHub Actions; do not imply ROS2/JAKA/hardware execution |
| No lint | **CONFIRMED** | Medium | Add Ruff E4/E7/E9/F baseline with frozen exclusions and narrow intentional ignores |
| No typecheck | **CONFIRMED** | Medium | Add maintainable Pyright scope; do not rewrite frozen core or suppress a fake full-repo result |
| Empty Python dependency metadata is wrong | **DESIGN TRADEOFF** | Low | Keep zero mandatory runtime dependencies; ROS2 remains in `package.xml`; add optional dev tools |
| Tracked generated evidence is repository clutter | **PARTIALLY CONFIRMED** | Medium | Tracking canonical release evidence is correct; unsafe default overwrite behavior is fixed |
| `SkillExecutor` is too complex | **CONFIRMED / FUTURE WORK** | Medium | Document the real state machine and paths; no frozen refactor |
| Frozen core contains static-analysis debt | **CONFIRMED / FUTURE WORK** | Medium | Raw Pyright found frozen annotations/type issues; record and exclude, with zero hash changes |
| `JakaKargoBackend.stop()` bool is semantically weak | **CONFIRMED / FUTURE WORK** | High | Document AGV-only transmission and proposed structured receipt; no breaking API change |
| Two JAKA backends are unexplained duplication | **NOT REPRODUCED / DESIGN TRADEOFF** | Low | Existing architecture already distinguishes them; add a legacy module note without import warnings |
| ROS2 Humble skip is improperly hard-coded | **PARTIALLY CONFIRMED / DESIGN TRADEOFF** | Low | The guard exists, but matches the only runtime-validated distro; do not broaden test claims from macOS |
| `skills.yaml` has drifted from executable registry | **NOT REPRODUCED** | Medium if future | Add an executable consistency gate to prevent future drift |

## Test-count reproduction

The required macOS command on untouched v0.3.0 produced:

```text
discovered total: 128
passed: 121
failed: 0
skipped: 7
ROS2 Humble-gated skips: 6
external JAKA/Kargo interface skip: 1
```

The repository contains 14 `test*.py` files. The 128 tests comprise 121 portable
tests, six ROS2/Humble-gated runtime tests, and one external-interface-gated runtime
test. The third-party 144-test result has no corresponding commit or discovery result
on the v0.3.0 baseline.

## Static-analysis classification

An unconfigured full-repository Pyright run produced 92 errors. Most were missing
ROS2/generated-interface imports, optional-value assertions in tests, or two findings
inside the frozen reasoning core. A targeted run over portable non-frozen JAKA,
evaluation, and state-codec modules produced zero errors. The candidate codifies that
useful scope rather than claiming full strict typing.

An initial broad Ruff run produced predominantly import-order/style diagnostics and
findings in frozen files. The candidate enables correctness-oriented E4/E7/E9/F
checks, excludes the manifest-protected files, records intentional path-bootstrap
imports, and fixes only two harmless non-frozen import issues.

## Frozen and platform boundaries

- manifest: 12 files / 1,385 LOC;
- candidate frozen-file modifications: 0;
- existing v0.2.0 and v0.3.0 tags: unchanged;
- macOS evidence: unittest, lint, type baseline, metadata/YAML/freeze checks only;
- inherited release evidence: Ubuntu 22.04 / ROS2 Humble and exact-schema stub runs;
- still unverified: vendor-node runtime, JAKA hardware, Gazebo/MoveIt2, whole-robot
  stop confirmation, service-timeout physical cancellation, and atomic TOCTOU safety.

## Candidate macOS validation

| Check | Result |
|---|---|
| Python | 3.9.6 |
| `unittest discover` | 128 discovered; 121 passed; 0 failed; 7 skipped |
| Ruff 0.16.2 | pass |
| Pyright 1.1.411 scoped baseline | 0 errors, 0 warnings |
| Release metadata | `0.3.0` consistent across four files |
| YAML registry mirror | 5/5 executable contracts consistent |
| Freeze manifest | 12 files / 1,385 LOC; all hashes match |
| Frozen-file diff | 0 modified files |
| Standard wheel build/install/import | pass |
| Default benchmark output policy | wrote ignored local artifact; canonical evidence unchanged |
| `git diff --check` | pass |

These are portable engineering checks only. The seven skips were not converted into
passes and no skipped ROS2/JAKA runtime was represented as macOS validation.

## Deliberately deferred

`SkillExecutor` refactoring, universal stop funneling, caller-facing cancellation,
structured stop receipts, ROS2 distro expansion, and all runtime/robot semantic
changes require a separately validated future engineering release. They are not
hidden by this hygiene work and were not changed to make CI green.
