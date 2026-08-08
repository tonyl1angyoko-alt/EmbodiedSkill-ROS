from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    package_share = FindPackageShare("embodied_skill_ros")
    xacro_path = PathJoinSubstitution(
        [package_share, "description", "embodied_skill_demo_robot.urdf.xacro"]
    )
    rviz_config = PathJoinSubstitution(
        [package_share, "config", "embodied_skill_demo.rviz"]
    )
    robot_description = {
        "robot_description": ParameterValue(
            Command([FindExecutable(name="xacro"), " ", xacro_path]),
            value_type=str,
        )
    }
    demo_case = LaunchConfiguration("demo_case")
    use_rviz = LaunchConfiguration("use_rviz")

    return LaunchDescription([
        DeclareLaunchArgument(
            "demo_case",
            default_value="repair",
            description="Demo case: repair or false_success",
        ),
        DeclareLaunchArgument(
            "use_rviz",
            default_value="true",
            description="Start RViz; set false for a headless ROS graph smoke test",
        ),
        Node(
            package="embodied_skill_ros",
            executable="fake_robot",
            name="embodied_skill_fake_robot",
            output="log",
        ),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="embodied_skill_demo_robot_state_publisher",
            parameters=[robot_description],
            output="log",
        ),
        Node(
            package="embodied_skill_ros",
            executable="rviz_demo_bridge",
            name="embodied_skill_rviz_demo_bridge",
            output="log",
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            name="embodied_skill_demo_rviz",
            arguments=["-d", rviz_config],
            condition=IfCondition(use_rviz),
            output="log",
        ),
        TimerAction(
            period=3.0,
            actions=[
                Node(
                    package="embodied_skill_ros",
                    executable="rviz_demo",
                    name="embodied_skill_rviz_demo_runner",
                    arguments=["--case", demo_case],
                    output="screen",
                )
            ],
        ),
    ])
