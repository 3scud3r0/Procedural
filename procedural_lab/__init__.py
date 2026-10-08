"""Procedural Lab: compiler, bounded VM and reproducible experiments."""

from .compiler import compile_source
from .bytecode import Program
from .vm import VirtualMachine, Limits

__version__ = "0.1.0"
__all__ = ["compile_source", "Program", "VirtualMachine", "Limits"]
