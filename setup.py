from glob import glob

from setuptools import find_packages, setup

setup(
    name="embodied_skill_ros",
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/embodied_skill_ros"]),
        ("share/embodied_skill_ros", ["package.xml"]),
        ("share/embodied_skill_ros/config", glob("config/*.yaml")),
        ("share/embodied_skill_ros/docs", glob("docs/*.md")),
        ("share/embodied_skill_ros/launch", glob("launch/*.launch.py")),
    ],
    install_requires=[],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "mock_bridge = embodied_skill_ros.ros2.mock_bridge_node:main",
        ],
    },
)
