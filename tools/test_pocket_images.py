import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1]/'lineage/pocket-images/package.py'
spec = importlib.util.spec_from_file_location('pocket_images', SOURCE)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PocketImagesTest(unittest.TestCase):
    def fixture(self, root):
        apk = root/'input.apk'
        with zipfile.ZipFile(apk, 'w') as z:
            for name, data in {
                'system/bin/pocket-init-api28': b'init',
                'system/bin/pocket-loader': b'loader',
                'system/etc/pocket-magisk/getprop': b'\x7fELFhelper',
                'system/build.prop': b'ro.build.version.sdk=28\n',
                'system/usr/keychars/Virtual.kcm': b'keys',
            }.items():
                z.writestr(package.PREFIX+name+'.payload', data)
            z.writestr('assets/default-guest/private-legacy.payload', b'excluded')
        recipe = dict(schema=1, profile='api28-direct', sdk=28, abi='arm64-v8a', runtime=1, version='1.0',
                      bootstrap=dict(kind='pocket-apk', version='1', sha256=package.digest_file(apk)))
        return apk, recipe

    def test_reproduce_archive_from_locked_root_and_changed_timestamps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);apk, recipe = self.fixture(root)
            first = package.package(recipe, root/'a', 'https://example.com/releases/v1', apk=apk)
            materialized = root/'image'
            with zipfile.ZipFile(root/'a/pocket-api28-arm64-1.0.zip') as archive:
                archive.extractall(materialized)
            second = package.package(recipe, root/'b', 'https://different.example/releases/v1',
                                     root=materialized, inputs=root/'a/image-inputs.lock.json')
            self.assertEqual(first['sha256'], second['sha256'])
            self.assertEqual((root/'a/pocket-api28-arm64-1.0.zip').read_bytes(), (root/'b/pocket-api28-arm64-1.0.zip').read_bytes())
            self.assertEqual(len(first['manifest']['entries']), 5)
            self.assertTrue(all(v['mode'] == 0o755 for v in first['manifest']['entries'].values()))
            self.assertNotEqual(first['url'], second['url'])
            (materialized/'system/bin/pocket-loader').write_bytes(b'modified')
            with self.assertRaises(ValueError):
                package.package(recipe, root/'c', 'https://example.com/v1', root=materialized, inputs=root/'a/image-inputs.lock.json')

    def test_bootstrap_pin_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);apk, recipe = self.fixture(root)
            recipe['bootstrap']['sha256'] = '0'*64
            with self.assertRaises(ValueError):
                package.package(recipe, root/'a', 'https://example.com/v1', apk=apk)
        for name in ('system/../data/private', '/system/bin/init', 'system//bin/init', 'system/./bin/init', 'vendor\\bad'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                package.safe_path(name)

    def test_http_requires_loopback_and_rejects_empty_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);apk, recipe = self.fixture(root)
            with self.assertRaises(ValueError):
                package.package(recipe, root/'a', 'http://example.com/v1', apk=apk)
            package.package(recipe, root/'b', 'http://127.0.0.1:8000', apk=apk)


if __name__ == '__main__':
    unittest.main()
