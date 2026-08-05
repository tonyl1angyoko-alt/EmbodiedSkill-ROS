from glob import glob

from setuptools import find_packages, setup

setup(
    name="embodied-skill-ros",
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/embodied_skill_ros"]),
        ("share/embodied_skill_ros", ["package.xml"]),
        ("share/embodied_skill_ros/config", glob("config/*.yaml")),
        ("share/embodied_skill_ros/docs", glob("docs/*.md")),
    ],
    install_requires=[],
    zip_safe=True,
)
