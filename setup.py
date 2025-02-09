from setuptools import setup, find_packages

setup(
    name="tello_lib",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "opencv-contrib-python",
        "numpy",
    ],
    author="Your Name",
    author_email="your.email@example.com",
    description="A library for controlling Tello drones",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/tello_lib",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)
