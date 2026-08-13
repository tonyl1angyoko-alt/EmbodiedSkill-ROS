from glob import glob

from setuptools import find_packages, setup

setup(
    name="embodied_skill_ros",
    version="0.3.1",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/embodied_skill_ros"]),
        ("share/embodied_skill_ros", ["package.xml"]),
        ("share/embodied_skill_ros/config", glob("config/*.yaml")),
        ("share/embodied_skill_ros/docs", glob("docs/*.md")),
        ("share/embodied_skill_ros/launch", glob("launch/*.launch.py")),
    ],
    install_requires=[],
    tests_require=["pytest"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "mock_bridge = embodied_skill_ros.ros2.mock_bridge_node:main",
            "fake_robot = embodied_skill_ros.ros2.fake_robot_node:main",
            "validate_runtime = embodied_skill_ros.ros2.runtime_validation:main",
            "jaka_kargo_probe = embodied_skill_ros.integrations.jaka_kargo.integration_probe:main",
            "jaka_kargo_stub = embodied_skill_ros.integrations.jaka_kargo.legacy_stub_node:main",
            "validate_jaka_kargo = embodied_skill_ros.integrations.jaka_kargo.runtime_validation:main",
        ],
    },
)
