from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def _fake_robot(lane: str) -> Node:
    return Node(
        package="embodied_skill_ros",
        executable="fake_robot",
        name=f"comparison_{lane}_fake_robot",
        output="log",
        remappings=[
            ("/embodied_skill/state", f"/comparison/{lane}/state"),
            ("/embodied_skill/runtime_events", f"/comparison/{lane}/runtime_events"),
            ("/embodied_skill/execute_skill", f"/comparison/{lane}/execute_skill"),
            ("/embodied_skill/get_capabilities", f"/comparison/{lane}/get_capabilities"),
            ("/embodied_skill/safe_stop", f"/comparison/{lane}/safe_stop"),
            (
                "/embodied_skill/test/get_hidden_state",
                f"/comparison/{lane}/test/get_hidden_state",
            ),
        ],
    )


def _robot_state_publisher(lane: str, prefix: str, xacro_path) -> Node:
    robot_description = {
        "robot_description": ParameterValue(
            Command([
                FindExecutable(name="xacro"),
                " ",
                xacro_path,
                " ",
                f"prefix:={prefix}",
            ]),
            value_type=str,
        )
    }
    return Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        namespace=f"comparison/{lane}",
        name="robot_state_publisher",
        parameters=[robot_description],
        output="log",
    )


def generate_launch_description() -> LaunchDescription:
    package_share = FindPackageShare("embodied_skill_ros")
    xacro_path = PathJoinSubstitution(
        [package_share, "description", "embodied_skill_comparison_robot.urdf.xacro"]
    )
    rviz_config = PathJoinSubstitution(
        [package_share, "config", "embodied_skill_comparison.rviz"]
    )
    comparison_case = LaunchConfiguration("comparison_case")
    use_rviz = LaunchConfiguration("use_rviz")

    return LaunchDescription([
        DeclareLaunchArgument(
            "comparison_case",
            default_value="repair",
            description="Comparison case: repair or false_success",
        ),
        DeclareLaunchArgument(
            "use_rviz",
            default_value="true",
            description="Start RViz; false keeps the two-process comparison headless",
        ),
        _fake_robot("baseline"),
        _fake_robot("embodied"),
        _robot_state_publisher("baseline", "baseline_", xacro_path),
        _robot_state_publisher("embodied", "embodied_", xacro_path),
        Node(
            package="embodied_skill_ros",
            executable="rviz_comparison_bridge",
            name="embodied_skill_rviz_comparison_bridge",
            parameters=[{"comparison_case": comparison_case}],
            output="log",
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            name="embodied_skill_comparison_rviz",
            arguments=["-d", rviz_config],
            condition=IfCondition(use_rviz),
            output="log",
        ),
        TimerAction(
            period=3.0,
            actions=[
                Node(
                    package="embodied_skill_ros",
                    executable="rviz_comparison",
                    name="embodied_skill_rviz_comparison_runner",
                    arguments=["--case", comparison_case],
                    output="screen",
                )
            ],
        ),
    ])
