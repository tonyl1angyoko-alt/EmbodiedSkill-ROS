# GitHub Release Report

Report date: 2026-08-06

## 1. Repository address

- Local repository: standalone Git repository in the `embodied_skill_ros` project directory.
- GitHub address: **not created**. The intended name is `EmbodiedSkill-ROS` under the authenticated user's account.
- Reason: GitHub CLI (`gh`) is not installed in the execution environment. No token, password, browser session, or alternate authentication path was requested or used.

## 2. Visibility

- Current remote visibility: not applicable; no remote exists.
- Required first GitHub visibility: **private**.
- Public conversion: not performed and not authorized.

## 3. Local commit history

All commits use their real creation time on 2026-08-06. No author or committer date environment variable was set.

1. `chore: initialize EmbodiedSkill-ROS project structure`
2. `feat: add embodied skill state and backend abstractions`
3. `feat: implement state-grounded closed-loop execution`
4. `test: add mock demos and automated test suite`
5. `bench: add reproducible A/B/C/D mock benchmark`
6. `docs: document architecture interfaces and release evidence`
7. `chore: prepare v0.1.0 private research release`

## 4. Tag and release

- Local tag: `v0.1.0`, annotated as an initial Mock-validated research prototype.
- GitHub tag: not pushed.
- GitHub Release: not created because no GitHub repository or CLI session is available.
- Required release note: “Initial Mock-validated research prototype. ROS2 Humble build and JAKA hardware execution remain unverified.”

## 5. Tests actually run

From an isolated `/tmp` copy of the final repository:

```bash
python3 -m compileall -q embodied_skill_ros examples benchmarks tests
python3 examples/normal_task.py
python3 examples/state_grounded_task.py
python3 examples/plan_repair_demo.py
python3 examples/recovery_demo.py
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 benchmarks/run_benchmark.py --output benchmark_outputs/release.json
python3 benchmarks/evaluate.py benchmark_outputs/release.json
```

Actual result: 48 tests passed, all four Mock demos completed, and all 30 benchmark scenarios were evaluated across four profiles.

## 6. Tests not run

- `python3 -m pytest`: system Python reported `No module named pytest`.
- `colcon build --symlink-install`: `colcon` is not installed.
- ROS2 Humble node/service/action/launch validation: not run.
- Gazebo/MoveIt2/RViz validation: not run.
- JAKA hardware execution: not run.

## 7. Removed or sanitized material

- Removed `.DS_Store`.
- Removed a parent-relative reference-workspace path from public documentation.
- Did not include the original reference source, SDK binaries, archives, robot IP addresses, network configuration, credentials, or logs.
- Replaced an invented maintainer placeholder with the locally verified contributor name and non-routable local identity.

## 8. Claims supported by evidence

- `MOCK-VERIFIED`: core execution architecture, four-component Mock behavior, plan repair, outcome verification, bounded recovery, demos, tests, and predefined benchmark.
- The full configuration achieved 96.67% task success on 30 predefined deterministic Mock scenarios.
- `STATICALLY-INSPECTED`: the optional JAKA adapter mapping boundary.

## 9. Claims not supported

- ROS2 Humble build or runtime success;
- JAKA hardware task success or safety certification;
- Gazebo/MoveIt2/RViz integration;
- 96.67% real-robot performance;
- unsupervised hardware-deployment readiness;
- independent hold-out generalization.

## 10. Manual checks before public visibility

1. Confirm author/copyright and preferred public maintainer contact.
2. Confirm rights to publish static analysis of the separately delivered reference system.
3. Review the Apache-2.0 choice and repository naming.
4. Review the private GitHub repository's secret-scanning result.
5. Update repository URLs in citation metadata if desired.
6. Keep the repository private until all checks in `docs/PUBLIC_RELEASE_AUDIT.md` are approved.

## Exact commands remaining for the repository owner

After installing GitHub CLI through the owner's normal trusted package-management process:

```bash
cd /path/to/embodied_skill_ros
gh auth login
gh repo create EmbodiedSkill-ROS \
  --private \
  --description "State-grounded planning and risk-aware closed-loop execution for ROS2 mobile manipulators." \
  --source . \
  --remote origin \
  --push
git push origin v0.1.0
gh release create v0.1.0 \
  --title "EmbodiedSkill-ROS v0.1.0" \
  --notes "Initial Mock-validated research prototype. ROS2 Humble build and JAKA hardware execution remain unverified."
```

Before `gh repo create`, the owner should run `gh repo view OWNER/EmbodiedSkill-ROS` and stop if a repository with that name already exists. Do not force-push or change visibility to public.
