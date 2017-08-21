
from unittest.mock import patch, Mock
from nio.modules.persistence import Persistence
from niocore.testing.test_case import NIOCoreTestCase

from ..manager import ProjectManager


class TestProjectManager(NIOCoreTestCase):

    @patch(ProjectManager.__module__ + ".chdir")
    @patch(ProjectManager.__module__ + ".subprocess")
    def test_clone_blocks_not_ok(self, subprocess_patch, chdir_patch):
        """ Asserts upon configuration configured blocks are cloned
        """

        blocks_count = 10
        blocks = []
        for i in range(blocks_count):
            blocks.append({"url": "block_{}".format(i)})

        Persistence().save({"blocks": blocks}, 'blocks')

        # make subprocess calls succeed so that clone block succeed for each
        subprocess_patch.call = Mock(return_value=0)

        project_manager = ProjectManager()
        self._orig_clone_block = project_manager.clone_block
        project_manager.clone_block = self._my_clone_block
        project_manager._get_abs_blocks_paths = Mock()
        project_manager._get_abs_blocks_paths.return_value = ["path1"]

        self._cloned_blocks = []
        project_manager.configure(Mock())

        # reload blocks and assert that the list kept the count
        blocks_loaded = Persistence().load("blocks")
        self.assertEqual(len(blocks_loaded["blocks"]), blocks_count)
        self.assertEqual(len(self._cloned_blocks), blocks_count)

        # assert that each block was cloned with expected url
        for i in range(blocks_count):
            block_found = False
            for cloned_block in self._cloned_blocks:
                if cloned_block == "block_{}".format(i):
                    block_found = True
                    break
            self.assertTrue(block_found)

    def _my_clone_block(self, url, tag=None, path_to_block=None, branch=None):
        self._cloned_blocks.append(url)
        self._orig_clone_block(url, tag, path_to_block, branch)