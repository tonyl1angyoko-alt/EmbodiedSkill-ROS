from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package="embodied_skill_ros",
            executable="mock_bridge",
            name="embodied_skill_mock_bridge",
            output="screen",
        ),
    ])
