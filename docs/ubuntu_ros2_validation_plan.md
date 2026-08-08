# Ubuntu 22.04 + ROS2 Humble Validation Plan

This plan is intentionally separate from macOS development evidence. It was
executed on 2026-08-08 on Ubuntu 22.04.5 with ROS2 Humble. Exact results are in
`docs/ROS2_RUNTIME_VALIDATION_REPORT.md`; commands remain here for reproduction.

## 1. Environment checks

```bash
set -euo pipefail
uname -a
uname -m
lsb_release -a
test "$(lsb_release -rs)" = "22.04"
test "$(dpkg --print-architecture)" = "amd64" -o "$(dpkg --print-architecture)" = "arm64"
```

If ROS2 Humble is already installed:

```bash
source /opt/ros/humble/setup.bash
test "$ROS_DISTRO" = "humble"
python3 --version
ros2 doctor --report
```

## 2. Dependency installation — run only on Ubuntu 22.04

Do not run this section on macOS.

```bash
sudo apt update
sudo apt install -y \
  git gh python3-pip python3-pytest python3-rosdep \
  python3-colcon-common-extensions \
  ros-humble-ros-base ros-humble-launch-ros \
  ros-humble-std-msgs ros-humble-std-srvs
test -f /etc/ros/rosdep/sources.list.d/20-default.list || sudo rosdep init
rosdep update --rosdistro humble
```

## 3. Private repository checkout without duplication

```bash
RESEARCH_BRANCH=codex/research-core-macos-frozen
mkdir -p "$HOME/embodied_skill_ws/src"
cd "$HOME/embodied_skill_ws/src"
if test -d EmbodiedSkill-ROS/.git; then
  cd EmbodiedSkill-ROS
  git remote -v
  git status --short --branch
  git fetch --prune origin
else
  gh auth status
  gh repo clone tonyl1angyoko-alt/EmbodiedSkill-ROS
  cd EmbodiedSkill-ROS
fi
git fetch --prune origin "$RESEARCH_BRANCH"
git switch --track -c "$RESEARCH_BRANCH" "origin/$RESEARCH_BRANCH" 2>/dev/null \
  || git switch "$RESEARCH_BRANCH"
test "$(git remote get-url origin)" = "https://github.com/tonyl1angyoko-alt/EmbodiedSkill-ROS.git" \
  -o "$(git remote get-url origin)" = "git@github.com:tonyl1angyoko-alt/EmbodiedSkill-ROS.git"
```

Use a reviewed commit SHA for recorded evidence:

```bash
git rev-parse HEAD
git status --porcelain=v1
```

The second command must print nothing.

## 4. Resolve dependencies and build with colcon

```bash
source /opt/ros/humble/setup.bash
cd "$HOME/embodied_skill_ws"
rosdep install --from-paths src --ignore-src -r -y --rosdistro humble
colcon build --symlink-install --packages-select embodied_skill_ros \
  --event-handlers console_direct+
source install/setup.bash
ros2 pkg prefix embodied_skill_ros
ros2 pkg executables embodied_skill_ros
```

Expected executables: `mock_bridge`, `fake_robot`, and `validate_runtime`.

## 5. Pure-Python and ROS2 tests

```bash
cd "$HOME/embodied_skill_ws/src/EmbodiedSkill-ROS"
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 -m pytest -q -m "not ros2"
source "$HOME/embodied_skill_ws/install/setup.bash"
python3 -m pytest -q -m ros2
cd "$HOME/embodied_skill_ws"
colcon test --packages-select embodied_skill_ros --event-handlers console_direct+
colcon test-result --all --verbose
```

Success criteria: all platform-independent tests pass; ROS2 tests execute rather
than skip; `colcon test-result` reports zero failures and a non-zero test count.

## 6. Launch and interface checks

Terminal A:

```bash
source /opt/ros/humble/setup.bash
source "$HOME/embodied_skill_ws/install/setup.bash"
ROS_LOG_DIR=/tmp/embodied_skill_ros_logs ROS_LOCALHOST_ONLY=1 \
  ros2 launch embodied_skill_ros fake_robot_validation.launch.py
```

Terminal B:

```bash
source /opt/ros/humble/setup.bash
source "$HOME/embodied_skill_ws/install/setup.bash"
ros2 node list
ros2 node info /embodied_skill_fake_robot
ros2 topic list -t
ros2 topic echo --once /embodied_skill/state std_msgs/msg/String
ros2 service list -t
ros2 service call /embodied_skill/get_capabilities std_srvs/srv/Trigger '{}'
ros2 action list -t
```

Expected interfaces:

| Kind | Name | Type / expectation |
|---|---|---|
| Node | `/embodied_skill_fake_robot` | running |
| Topic | `/embodied_skill/state` | `std_msgs/msg/String`, valid JSON state |
| Service | `/embodied_skill/get_capabilities` | `std_srvs/srv/Trigger`, `success: true` |
| Action | `/embodied_skill/execute_skill` | validation-only long-running/cancellable action lifecycle |

Stop Terminal A with `Ctrl-C`; shutdown must be clean with no Python traceback.

## 7. Process-separated runtime scenarios

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ROS_LOG_DIR=/tmp/embodied_skill_ros_logs ROS_LOCALHOST_ONLY=1 \
  ros2 run embodied_skill_ros validate_runtime \
  --output ros2_validation_outputs/runtime_scenarios.json
```

Success criteria: R1–R15 pass; the TOCTOU and fresh-spoof probes reproduce their
documented unsafe limitations; the fake process exits with code zero.

## 8. Benchmark integration tests

```bash
cd "$HOME/embodied_skill_ws/src/EmbodiedSkill-ROS"
python3 benchmarks/run_benchmark.py --output /tmp/benchmark_results.json
python3 benchmarks/evaluate.py /tmp/benchmark_results.json
python3 benchmarks/run_procedural_benchmark.py \
  --seed 20260808 --trials 200 --output /tmp/procedural_results.json
python3 benchmarks/run_benchmark_v2.py --output-dir /tmp/embodied_skill_benchmark_v2
python3 -c 'import json; d=json.load(open("/tmp/benchmark_results.json")); assert d["profiles"]["D_grounded_with_recovery"]["metrics"]["task_success_rate"] == 0.9333'
python3 -c 'import json; d=json.load(open("/tmp/procedural_results.json")); assert d["profiles"]["grounded_with_recovery"]["metrics"]["success_rate"] == 1.0'
python3 -c 'import json; d=json.load(open("/tmp/embodied_skill_benchmark_v2/adversarial_v2_results.json")); m=d["metrics"]; assert (m["overall_correct_decision_rate"],m["task_completion_rate"],m["feasible_task_completion_rate"],m["correct_safe_stop_rate"],m["unsafe_execution_rate"]) == (0.923077,0.384615,1.0,0.875,0.076923)'
python3 -c 'import json; d=json.load(open("/tmp/embodied_skill_benchmark_v2/holdout_results.json")); assert (sum(r["correct_decision"] for r in d["rows"]),sum(r["task_completion"] for r in d["rows"]),sum(r["correct_safe_stop"] for r in d["rows"]),sum(r["unsafe_execution"] for r in d["rows"])) == (72,30,42,6)'
```

These remain `BENCHMARK-VERIFIED`, not simulation or hardware evidence.

## 9. JAKA adapter checks without hardware

These commands construct no vendor client and send no motion command:

```bash
cd "$HOME/embodied_skill_ws/src/EmbodiedSkill-ROS"
python3 -m unittest tests.test_jaka_backend -v
python3 -c 'from embodied_skill_ros.backends import JakaRobotBackend; b=JakaRobotBackend(); print(b.capabilities()); assert b.observe().emergency_stop is None'
```

Success criteria: import succeeds with no vendor SDK; absent adapters remain unsupported
or `UNKNOWN`; no network address, ROS service, or robot motion is used.

## 10. Hardware-only validation — separately authorized session

Do not run this section during unattended CI. Before any movement, the deployment owner
must provide the vendor workspace, calibrated transport pose, measured state provider,
AGV odometry provider, physical workspace exclusion zone, and an operator at the
emergency stop.

Pre-motion gate:

```bash
test "$ROS_DISTRO" = "humble"
test "${EMBODIED_SKILL_ALLOW_HARDWARE:-0}" = "1"
test -n "${JAKA_TRANSPORT_POSE:-}"
test -n "${JAKA_STATE_PROVIDER_MODULE:-}"
test -n "${JAKA_AGV_ODOMETRY_PROVIDER_MODULE:-}"
```

No generic hardware motion command is provided by this repository because the vendor
objects and safe calibrated values are deployment-specific. The supervised deployment
test must separately record: command receipt, measured pre/post state, verifier result,
safe-stop behavior, operator approval, robot serial/configuration hash, and sanitized
trace. Only those trials may be labeled `HARDWARE-VERIFIED`.

## 11. Evidence promotion criteria

- `ROS2-RUNTIME-VERIFIED`: sections 1–9 pass on Ubuntu 22.04/Humble with logs and SHA.
- `SIMULATION-VERIFIED`: requires a real simulator backend and physics execution; the
  Mock bridge does not qualify.
- `HARDWARE-VERIFIED`: requires the supervised gate and measured physical outcomes.
- Any skipped, missing, or inferred result remains `UNVERIFIED`.
