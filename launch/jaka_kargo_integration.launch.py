"""Read-only JAKA/Kargo integration probe.

Motion is deliberately not exposed by this launch file. Deployment applications
must construct ``JakaKargoBackend`` with explicit calibration and safety evidence.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    timeout = LaunchConfiguration("service_timeout_s")
    return LaunchDescription([
        DeclareLaunchArgument("service_timeout_s", default_value="1.0"),
        Node(
            package="embodied_skill_ros",
            executable="jaka_kargo_probe",
            name="embodied_skill_jaka_kargo_probe",
            output="screen",
            arguments=["--timeout", timeout],
        ),
    ])
