from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package="embodied_skill_ros",
            executable="fake_robot",
            name="embodied_skill_fake_robot",
            output="screen",
        ),
    ])
