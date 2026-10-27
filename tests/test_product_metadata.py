"""Product identity must survive staging and Windows resource generation."""
import io
import ast
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from tools import build_wbex_updater as builder
from tools import wbex_updater_app as app
from tools import wbex_updater_version as product


class ProductMetadataTests(unittest.TestCase):
    def test_version_and_company_are_shared_with_cli(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as result:
            app.main(["--version"])
        self.assertEqual(0, result.exception.code)
        self.assertIn("1.1.0", output.getvalue())
        self.assertIn("Intelligent Efficiency Team", output.getvalue())

    def test_windows_version_resource_contains_release_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "version-info.txt"
            builder.write_version_info(path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
            fixed = next(node for node in calls if getattr(node.func, "id", "") == "FixedFileInfo")
            versions = {entry.arg: ast.literal_eval(entry.value) for entry in fixed.keywords}
            self.assertEqual((1, 1, 0, 0), versions["filevers"])
            strings = {ast.literal_eval(node.args[0]): ast.literal_eval(node.args[1])
                       for node in calls if getattr(node.func, "id", "") == "StringStruct"}
            self.assertEqual(product.COMPANY, strings["CompanyName"])
            self.assertEqual(product.COPYRIGHT, strings["LegalCopyright"])
            self.assertEqual(product.VERSION, strings["FileVersion"])


if __name__ == "__main__":
    unittest.main()
