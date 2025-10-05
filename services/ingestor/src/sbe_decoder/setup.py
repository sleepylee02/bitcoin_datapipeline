#!/usr/bin/env python3
"""
Setup script for Binance SBE C++ decoder extension.

This builds a fast C++ extension for decoding Binance SBE binary messages
following the official Binance SBE C++ sample app patterns.

Based on: https://github.com/binance/binance-sbe-cpp-sample-app
"""

from pybind11.setup_helpers import Pybind11Extension, build_ext
from pybind11 import get_cmake_dir
import pybind11
from setuptools import setup, Extension
import os

# Define the extension module
ext_modules = [
    Pybind11Extension(
        "sbe_decoder_cpp",
        [
            "src/sbe_decoder.cpp",
            "src/binance_messages.cpp",
        ],
        include_dirs=[
            # Path to pybind11 headers
            pybind11.get_include(),
            # Local source headers
            "src/",
        ],
        language='c++',
        cxx_std=20,  # C++20 for std::span and performance features
        define_macros=[
            ('VERSION_INFO', '"1.0.0"'),
            ('BINANCE_SBE_SCHEMA_VERSION', '0'),  # Schema 1:0
            ('BINANCE_SBE_SCHEMA_ID', '1'),
        ],
        # Optimization flags for performance-critical trading applications
        extra_compile_args=[
            '-O3',              # Maximum optimization
            '-march=native',    # Optimize for current CPU
            '-ffast-math',      # Fast math operations
            '-DNDEBUG',         # Disable debug assertions
        ],
    ),
]

setup(
    name="binance_sbe_decoder",
    version="1.0.0",
    author="Bitcoin Pipeline Team",
    description="High-performance C++ SBE decoder for Binance WebSocket streams",
    long_description="Fast C++ extension for decoding Binance SBE binary market data from WebSocket streams (schema 3:1)",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.8",
    install_requires=[
        "pybind11>=2.6.0",
    ],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: C++",
        "Topic :: Office/Business :: Financial :: Investment",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
