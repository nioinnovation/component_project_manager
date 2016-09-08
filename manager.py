"""

    Project Manager

"""
import subprocess
from os import listdir, path, remove, chdir
from shutil import rmtree

from nio.util.logging import get_nio_logger
from nio.util.versioning.dependency import DependsOn
from niocore.core.component import CoreComponent
from niocore.util.environment import NIOEnvironment
from nio import discoverable

from .handler import ProjectManagerHandler
import os.path


@DependsOn("niocore.components.rest", "0.1.0")
@discoverable
class ProjectManager(CoreComponent):

    """ Core component to handle project management functionality

    """

    _name = "ProjectManager"

    exclusions = ["__pycache__",
                  ".git",
                  "__init__.py",
                  "README.md",
                  ".DS_Store"]

    def __init__(self):
        """Initializes the component

        """
        super().__init__()
        self._handler = None

        # dependency components
        self._rest_manager = None

    def configure(self, context):
        """ Configures project manager

        Makes sure it gets a reference to its dependencies

        Args:
            context (CoreContext): component initialization context

        """

        super().configure(context)

        # Register dependencies to rest and service manager
        self._rest_manager = self.get_dependency("RESTManager")

    def start(self):
        """Starts component

        Creates and registers web handler

        """
        super().start()

        # create REST specific handlers
        self._handler = ProjectManagerHandler("/project", self)

        # Add handler to WebServer
        self._rest_manager.add_web_handler(self._handler)

    def stop(self):
        """Stops component

        Removes web handler

        """
        # Remove handler from WebServer
        self._rest_manager.remove_web_handler(self._handler)
        super().stop()

    def get_blocks_structure(self, get_branch_info=False):
        """ Get block structure from disk

        Args:
            get_branch_info: Show git branches for each block

        Returns:
           Structure with an Array of blocks
        """

        # Return
        ret = []

        # Blocks from path
        blocks_paths = self._get_abs_blocks_paths()

        # Each block
        for blocks_path in blocks_paths:
            for item in listdir(blocks_path):

                # -- Discard known exclusions
                if item in ProjectManager.exclusions:
                    continue

                # -- Make block full path
                block_full_path = path.join(blocks_path, item)

                # -- Folder or file
                block = None
                if path.isdir(block_full_path):
                    block = {"name": item, "type": "directory"}
                elif path.isfile(block_full_path):
                    block = {"name": path.splitext(item)[0], "type": "file"}

                # -- Get branch info?
                if get_branch_info:
                    block["branch"] = self._get_git_branch(block_full_path)

                # -- Add block
                if block is not None:
                    ret.append(block)

        return {"blocks": ret}

    def _get_git_branch(self, directory):
        """Get Git branch

        Args:
            directory: path to block to get Git branch for


        Returns:
           String of branch name or None

        """

        # Command
        cmd = "cd %s && git rev-parse --abbrev-ref HEAD" % directory

        # Get git branch name
        result = os.popen(cmd).read().strip()

        # Result
        if len(result):
            return result

        return None

    def _get_blocks(self, params):
        """Get blocks from params

        Consider url params to be block names, discard actual url param values

        Returns:
           Array of blocks

        """

        blocks = []
        for key, _ in params.items():
            blocks.extend([block.strip() for block in key.split(",")])

        return blocks

    def remove_blocks(self, blocks):
        """Remove blocks from disk

        Args:
            blocks: block folder

        Returns:
           Array of removed blocks

        """

        blocks_paths = self._get_abs_blocks_paths()
        removed = []
        for blocks_path in blocks_paths:
            for block in blocks:
                # create an absolute path and determine if it is valid
                block_full_path = path.join(blocks_path, block)
                if path.isdir(block_full_path):
                    self._remove_dir(block_full_path)
                    removed.append({"name": block,
                                    "type": "directory"})
                else:
                    # determine if it is a file
                    block_full_path_to_file = block_full_path + ".py"
                    if path.isfile(block_full_path_to_file):
                        self._remove_file(block_full_path_to_file)
                        removed.append({"name": block,
                                        "type": "file"})

        return removed

    def clone_block(self, url, path_to_block):
        """Clones a block from github's nio-blocks repository

        Args:
            url: Where to get block from, following are valid
                /project/blocks url=https://github.com/nio-blocks/util.git
                /project/blocks url=git@github.com:nio-blocks/util.git
                /project/blocks url=util
                /project/blocks url=nio-blocks/util

            path_to_block: If None, path is figured out by accessing
                "blocks" entry from environment configuration

        Returns:
            Operation status as a dictionary
        """

        # Processing url

        # Assume a .git ending
        if not url.endswith(".git"):
            url = "{0}.git".format(url)

        # Assume nio-blocks repository if no repo name
        # POST /project/blocks url=util
        if "nio-blocks" not in url:
            url = "nio-blocks/{0}".format(url)

        # Assume github.com for host
        # POST /project/blocks url=nio-blocks/util
        if "github.com" not in url:
            # target, git@github.com:nio-blocks/util.git
            url = "git@github.com:{0}".format(url)

        # Go to target path
        if not path_to_block:
            blocks_paths = self._get_abs_blocks_paths()
            if not blocks_paths:
                raise RuntimeError("Could not get a valid nio blocks path")
            # if no path specified, grab last path to blocks
            path_to_block = blocks_paths[len(blocks_paths)-1]
        try:
            chdir(path_to_block)
        except FileNotFoundError:
            self.logger.error("Path '{0}' is invalid".format(path_to_block))
            raise

        # Log
        self.logger.info("Cloning Git repository: {0}".format(url))

        # Get block from git
        res = self._subprocess_call("git clone --recursive {0}".format(url))

        # Get the directory that this was cloned into
        block_dir, block_dir_ext = os.path.splitext(os.path.basename(url))

        # Log
        self.logger.info("Cloning Git repository into directory: {0}"
                         .format(block_dir))

        # Update pip requirements
        if res == 0:
            self.pip_install_req("{0}/{1}".format(path_to_block, block_dir))

        # Get process return
        result = self._get_subprocess_return(res, "cloning block")
        return result

    def pip_install_req(self, path_to_block):
        """Updates PIP requirements.txt file for a block

        Args:
            path_to_block: If None, path is figured out by accessing "blocks"
                entry from environment configuration

        Returns:
            Operation True or False
        """

        # Make path to requirements
        path_req = "{0}/requirements.txt".format(path_to_block)

        # Log
        self.logger.info("Install PIP requirements at {0}".format(path_req))

        # If we do not have a file, we are good
        if not os.path.isfile(path_req):
            return True

        try:

            # Change directory to block
            chdir(path_to_block)

        except FileNotFoundError:
            self.logger.error("Path '{0}' is invalid".format(path_to_block))
            raise

        # Pip install
        res = self._subprocess_call("pip3 install -r requirements.txt")
        if res != 0:
            return False

        return True

    def update_block(self, blocks):
        """Pulls down block latest version and updates submodules

        Args:
            blocks: block folder

        Returns:
            Operation status as a dictionary
        """

        results = []

        blocks_paths = self._get_abs_blocks_paths()
        for blocks_path in blocks_paths:
            updates_in_path = False
            blocks_path_structure = self._get_block_path_structure(blocks_path)
            for block_structure in blocks_path_structure:
                if blocks and block_structure["name"] not in blocks:
                    # update was not requested for this block
                    continue

                if block_structure["type"] == "directory":
                    # cd to block directory
                    chdir(path.join(blocks_path, block_structure["name"]))
                else:
                    chdir(blocks_path)

                # update block
                result = self._get_subprocess_return(
                    self._subprocess_call(
                        "git fetch origin --progress --prune"),
                    "updating block")
                results.append({block_structure["name"]: result})
                updates_in_path = True

            # update submodules if there were any updates in path
            if updates_in_path:
                self._subprocess_call(
                    "git submodule update --init --recursive")

        if len(blocks):
            # warning about requested blocks that were not found
            self.logger.warning("Blocks: {0} are not installed".
                                format(blocks))

        return results

    @staticmethod
    def _get_subprocess_return(result, message):
        """Get subprocess results

        Args:
            result: Result from subprocess call
            message: Message to format result with

        Returns:
           Array with results of subprocess
        """

        if result < 0:
            result = {"status":
                      "while {0}, received killed by "
                      "signal: {1} status".format(message, result)}
        elif result > 0:
            result = {"status":
                      "while {0}, command failed with "
                      "return code: {0}".format(message, result)}
        else:
            # call is a success
            result = {"status": "ok"}

        return result

    @staticmethod
    def _get_abs_blocks_paths():
        """Get absolute path of blocks

        Returns:
           String with absolute path to blocks
        """

        blocks_resource_paths = NIOEnvironment.get_resource_paths('blocks',
                                                                  'blocks')
        abs_blocks_paths = []
        for blocks_resource_path in blocks_resource_paths:
            abs_block_path = NIOEnvironment.get_path(blocks_resource_path)
            if path.isdir(abs_block_path):
                abs_blocks_paths.append(abs_block_path)

        return abs_blocks_paths

    @staticmethod
    def _remove_dir(full_path):
        """Remove directory

        Args:
            full_path: Full path to directory

        Returns:
           True or false
        """

        try:

            # Sanity check
            if not path.isdir(full_path):
                return False

            # Delete directory
            rmtree(full_path)

        except Exception:

            # Log
            get_nio_logger("ProjectManager").exception(
                "Failure removing directory {0}".format(full_path))

            return False

        return True

    @staticmethod
    def _remove_file(file):
        """Remove file

        Args:
            file: Full path to file

        Returns:
           True or false
        """

        try:

            # Sanity check
            if not path.isfile(file):
                return False

            # Delete directory
            remove(file)

        except Exception:

            # Log
            get_nio_logger("ProjectManager").exception(
                "Failure removing file {0}".format(file))

            return False

        return True

    @staticmethod
    def _get_block_path_structure(blocks_path):
        """Return file structure under a given path

        Args:
            blocks_path: Path to blocks

        Returns:
            Array of blocks
        """

        blocks = []
        for item in listdir(blocks_path):
            # discard known exclusions
            if item in ProjectManager.exclusions:
                continue

            item_full_path = path.join(blocks_path, item)

            if path.isdir(item_full_path):
                blocks.append({"name": item,
                               "type": "directory"})
            elif path.isfile(item_full_path):
                blocks.append({"name": path.splitext(item)[0],
                               "type": "file"})

        return blocks

    @staticmethod
    def _subprocess_call(command):
        """Executes sub process command

        Returns:
           True or false
        """

        return subprocess.call(command, shell=True)

    @staticmethod
    def _subprocess_call_with_res(command):
        """Executes sub process command and returns response

        Returns:
           True or false
        """

        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
        res, err = process.communicate()

        return res
