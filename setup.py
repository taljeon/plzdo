"""Setuptools extension for fixed package-owned data, with no source mutation."""
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

from build_support import bundled_inputs, stage_resources


SOURCE = Path(__file__).parent


class BuildCore(build_py):
    def run(self):
        build_py.run(self)
        stage_resources(SOURCE, Path(self.build_lib))

    def get_outputs(self, include_bytecode=1):
        outputs = super().get_outputs(include_bytecode)
        destination = Path(self.build_lib) / "plzdo_local" / "_bundled"
        return outputs + [str(destination / path.relative_to(SOURCE))
                          for path in bundled_inputs(SOURCE)]


setup(cmdclass={"build_py": BuildCore})
