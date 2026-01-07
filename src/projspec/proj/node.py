import re

from projspec.proj.base import ProjectSpec
from projspec.content.package import NodePackage
from projspec.artifact.process import Process
from projspec.content.executable import Command
from projspec.utils import AttrDict


class Node(ProjectSpec):
    """Node.js project, managed by NPM

    This is a project that contains a package.json file.
    """

    spec_doc = "https://docs.npmjs.com/cli/v11/configuring-npm/package-json"

    def match(self):
        return "package.json" in self.proj.basenames

    def parse0(self):
        from projspec.content.environment import Environment, Stack, Precision
        from projspec.content.metadata import DescriptiveMetadata
        from projspec.artifact.python_env import LockFile

        import json

        with self.proj.fs.open(f"{self.proj.url}/package.json", "rt") as f:
            pkg_json = json.load(f)
        self.meta = pkg_json

        # Metadata
        name = pkg_json.get("name")
        version = pkg_json.get("version")
        description = pkg_json.get("description")
        # Dependencies
        dependencies = pkg_json.get("dependencies")
        dev_dependencies = pkg_json.get("devDependencies")
        # Entry points for runtime execution: CLI
        scripts = pkg_json.get("scripts", {})
        bin = pkg_json.get("bin")
        # Entry points for importable code: library
        main = pkg_json.get("main")
        module = pkg_json.get("module")
        # TBD: exports?
        # Package manager
        package_manager = pkg_json.get("packageManager", "npm@latest")
        if isinstance(package_manager, str):
            package_manager_name = package_manager.split("@")[0]
        else:
            package_manager_name = package_manager.get("name", "npm")

        # Commands
        bin_entry = {}
        if bin and isinstance(bin, str):
            bin_entry = {name: bin}
        elif bin and isinstance(bin, dict):
            bin_entry = bin

        # Contents
        conts = AttrDict(
            {
                "descriptive_metadata": DescriptiveMetadata(
                    proj=self.proj,
                    meta={
                        "name": name,
                        "version": version,
                        "description": description,
                        "main": main,
                        "module": module,
                    },
                    artifacts=set(),
                ),
            },
        )

        cmd = AttrDict()
        for name, path in bin_entry.items():
            cmd[name] = Command(
                proj=self.proj, cmd=["node", f"{self.proj.url}/{path}"], artifacts=set()
            )

        # Artifacts
        arts = AttrDict()
        for script_name, script_cmd in scripts.items():
            if script_name == "build":
                arts["build"] = Process(
                    proj=self.proj, cmd=[package_manager_name, "run", script_name]
                )
            else:
                cmd[script_name] = Command(
                    proj=self.proj,
                    cmd=[package_manager_name, "run", script_name],
                    artifacts=set(),
                )

        if "package-lock.json" in self.proj.basenames:
            arts["lock_file"] = LockFile(
                proj=self.proj,
                artifacts={},
                cmd=["npm", "install"],
                fn=self.proj.basenames["package-lock.json"],
            )
            # TODO: load lockfile and make environment
        conts.setdefault("environment", {})["node"] = Environment(
            proj=self.proj,
            artifacts=set(),
            stack=Stack.NPM,
            packages=dependencies,
            precision=Precision.SPEC,
        )
        conts.setdefault("environment", {})["node_dev"] = Environment(
            proj=self.proj,
            artifacts=set(),
            stack=Stack.NPM,
            packages=dev_dependencies,  # + dependencies?
            precision=Precision.SPEC,
        )

        conts["node_package"] = (
            NodePackage(name=name, proj=self.proj, artifacts=set()),
        )
        conts["command"] = (cmd,)
        self._artifacts = arts
        self._contents = conts

    def parse(self):
        self.parse0()


class Yarn(Node):
    """A node project that uses `yarn` for building"""

    spec_doc = "https://yarnpkg.com/configuration/yarnrc"

    def match(self):
        return ".yarnrc.yml" in self.proj.basenames

    def parse(self):
        from projspec.content.environment import Environment, Stack, Precision
        from projspec.artifact.python_env import LockFile

        super().parse0()

        with self.proj.fs.open(f"{self.proj.url}/yarn.lock", "rt") as f:
            txt = f.read()
        hits = re.findall(r'resolution: "(.*?)"', txt, flags=re.MULTILINE)

        self.artifacts["lock_file"] = LockFile(
            proj=self.proj,
            cmd=["yarn", "install"],
            fn=self.proj.basenames["yarn.lock"],
        )
        self.contents.setdefault("environment", {})["yarn_lock"] = Environment(
            proj=self.proj,
            artifacts=set(),
            stack=Stack.NPM,
            packages=hits,
            precision=Precision.LOCK,
        )


class JLabExtension(Node):
    """JupyterLab extension project

    JupyterLab extensions are Node.js packages with special 'jupyterlab' field
    in package.json. They may include Python companion packages for server
    extensions.

    https://jupyterlab.readthedocs.io/en/latest/extension/extension_dev.html
    """

    spec_doc = "https://jupyterlab.readthedocs.io/en/latest/extension/extension_dev.html"

    def match(self):
        """Match if package.json exists and has jupyterlab field"""
        if "package.json" not in self.proj.basenames:
            return False

        import json
        try:
            with self.proj.fs.open(f"{self.proj.url}/package.json", "rt") as f:
                pkg_json = json.load(f)
            # Check for jupyterlab field which indicates this is a JupyterLab extension
            return "jupyterlab" in pkg_json
        except Exception:
            return False

    def parse(self):
        import toml
        from projspec.artifact.python_env import LockFile
        from projspec.content.package import PythonPackage
        from projspec.utils import PickleableTomlDecoder

        # Parse base Node.js package info
        super().parse0()

        # Extract JupyterLab-specific metadata
        jlab_meta = self.meta.get("jupyterlab", {})

        # Determine extension type
        extension_types = []
        if jlab_meta.get("extension"):
            extension_types.append("frontend")
        if jlab_meta.get("mimeExtension"):
            extension_types.append("mime-renderer")
        if jlab_meta.get("themePath"):
            extension_types.append("theme")
        if jlab_meta.get("discovery"):
            extension_types.append("server")

        # Add extension type to metadata
        if hasattr(self, '_contents') and 'descriptive_metadata' in self._contents:
            existing_meta = self._contents['descriptive_metadata'].meta
            existing_meta.update({
                "jupyterlab": {
                    "extension_types": extension_types,
                    "output_dir": jlab_meta.get("outputDir"),
                    "schema_dir": jlab_meta.get("schemaDir"),
                    "theme_path": jlab_meta.get("themePath"),
                }
            })

        # Update lock file command to use jlpm if yarn.lock exists
        if "yarn.lock" in self.proj.basenames:
            self._artifacts["lock_file"] = LockFile(
                proj=self.proj,
                cmd=["jlpm", "install"],
                fn=self.proj.basenames["yarn.lock"],
            )

        # Add JupyterLab-specific commands
        scripts = self.meta.get("scripts", {})

        # Development mode installation
        if not hasattr(self, '_contents'):
            self._contents = AttrDict()
        if 'command' not in self._contents:
            self._contents['command'] = (AttrDict(),)

        cmd_dict = self._contents['command'][0] if isinstance(self._contents['command'], tuple) else self._contents['command']

        # jupyter labextension develop
        cmd_dict['labextension_develop'] = Command(
            proj=self.proj,
            cmd=["jupyter", "labextension", "develop", ".", "--overwrite"],
            artifacts=set()
        )

        # jupyter labextension list
        cmd_dict['labextension_list'] = Command(
            proj=self.proj,
            cmd=["jupyter", "labextension", "list"],
            artifacts=set()
        )

        # jupyter lab build
        cmd_dict['lab_build'] = Command(
            proj=self.proj,
            cmd=["jupyter", "lab", "build"],
            artifacts=set()
        )

        # jlpm watch (if watch script exists)
        if "watch" in scripts:
            cmd_dict['jlpm_watch'] = Command(
                proj=self.proj,
                cmd=["jlpm", "run", "watch"],
                artifacts=set()
            )

        # Check for Python companion package
        has_python_package = False
        if "pyproject.toml" in self.proj.basenames:
            has_python_package = True
            # Add Python package reference
            try:
                with self.proj.fs.open(f"{self.proj.url}/pyproject.toml", "rt") as f:
                    pyproject = toml.load(f, decoder=PickleableTomlDecoder())

                pkg_name = None
                if "project" in pyproject:
                    pkg_name = pyproject["project"].get("name")
                elif "tool" in pyproject and "poetry" in pyproject["tool"]:
                    pkg_name = pyproject["tool"]["poetry"].get("name")

                if pkg_name and not hasattr(self._contents, 'python_package'):
                    self._contents['python_package'] = PythonPackage(
                        name=pkg_name,
                        proj=self.proj,
                        artifacts=set()
                    )
            except Exception:
                pass  # If we can't parse it, that's okay

        elif "setup.py" in self.proj.basenames:
            has_python_package = True

        # Update metadata with Python package info
        if has_python_package and hasattr(self, '_contents') and 'descriptive_metadata' in self._contents:
            self._contents['descriptive_metadata'].meta.setdefault("jupyterlab", {})["has_python_package"] = True
