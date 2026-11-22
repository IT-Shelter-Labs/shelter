import json
from pathlib import Path
import re
import unittest

from app_version import VERSION

ROOT = Path(__file__).resolve().parents[1]


class ProductVersion(unittest.TestCase):
    def test_product_versions_agree_and_are_prerelease(self):
        self.assertRegex(VERSION, r'^0\.\d+\.\d+-alpha\.\d+$')
        for name in ('app/package.json', 'app/src-tauri/tauri.conf.json'):
            self.assertEqual(json.loads((ROOT/name).read_text(encoding='utf8'))['version'], VERSION)
        cargo = (ROOT/'app/src-tauri/Cargo.toml').read_text(encoding='utf8')
        self.assertEqual(re.search(r'^version\s*=\s*"([^"]+)"', cargo, re.M)[1], VERSION)
        self.assertIn(f'"{VERSION}"', (ROOT/'app/src/lib/version.ts').read_text(encoding='utf8'))


if __name__ == '__main__':
    unittest.main()
