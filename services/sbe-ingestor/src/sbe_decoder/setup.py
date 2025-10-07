#!/usr/bin/env python3
"""
Setup script for Binance SBE decoder using official patterns.

This builds a C++ extension that follows the official Binance SBE sample app
patterns but adapted for stream template IDs used in the Bitcoin pipeline.
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
        ],
        include_dirs=[
            # Path to pybind11 headers
            pybind11.get_include(),
            # Local headers
            "include/",
            "include/spot_sbe/",
            "include/official/",
        ],
        language='c++',
        cxx_std=20,  # C++20 for std::span support
        define_macros=[
            ('VERSION_INFO', '"1.0.0"'),
            ('BINANCE_SBE_SCHEMA_VERSION', '0'),  # Schema 1:0
            ('BINANCE_SBE_SCHEMA_ID', '1'),
        ],
        # High performance optimization flags
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
    description="SBE decoder using official Binance patterns for stream data",
    long_description="C++ extension following official Binance SBE decoder patterns, adapted for WebSocket stream template IDs",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.8",
    install_requires=[
        "pybind11>=2.6.0",
    ],
)