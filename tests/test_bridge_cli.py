"""python -m helm.bridge argument handling: where the firstmate home comes from."""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helm.bridge import __main__ as cli


class HomeArgument(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="helm-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_main(self, argv, env):
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                cli.main(argv)
        return raised.exception.code, err.getvalue()

    def test_without_home_or_fm_home_it_says_how_to_pick_one(self):
        code, err = self.run_main(["--once"], env={})
        self.assertEqual(code, 2)
        self.assertIn("pass --home or set FM_HOME", err)

    def test_fm_home_is_the_default_home(self):
        not_a_home = self.tmp / "from-env"
        code, err = self.run_main(["--once"], env={"FM_HOME": str(not_a_home)})
        self.assertEqual(code, 2)
        self.assertIn("not a firstmate home (no state/ directory): %s" % not_a_home, err)

    def test_home_flag_wins_over_fm_home(self):
        flag_home = self.tmp / "from-flag"
        code, err = self.run_main(["--once", "--home", str(flag_home)], env={"FM_HOME": str(self.tmp / "from-env")})
        self.assertEqual(code, 2)
        self.assertIn(str(flag_home), err)
        self.assertNotIn("from-env", err)


if __name__ == "__main__":
    unittest.main()
