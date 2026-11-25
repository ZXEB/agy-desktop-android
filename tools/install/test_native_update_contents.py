"""ZIP/ELF admission tests for the current native update contract; no Android."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location('update_contents', Path(__file__).with_name('verify-apk-contents.py'))
contents = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contents)


class NativeUpdateContentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.apk = Path(self.temp.name) / 'candidate.apk'
        self.files = {'lib/arm64-v8a/' + n: b'native fixture' for n in
            contents.RUNTIME | {'libcodex-device-files.so', 'libcodex_tools_launcher.so'}}
        for name in ('codex-executor-manifest.json', 'codex-executor-evidence.json', 'codex-executor-qualification.json',
                     'codex-app-launch-build.json', 'codex-python-runtime.json', 'bionic-python/lib/python3.14/os.py',
                     'codex-tools/install-workspace-provider.py'):
            self.files['assets/' + name] = b'fixture'
        self.files['assets/codex-executor-deployment.json'] = json.dumps({'schema': 'codex.native.deployment.v2',
            'packageName': 'com.ai.codex', 'launchOrigin': 'android-app'}).encode()
        self.files['classes.dex'] = b'Lcom/ai/codex/LiveNotifications; Lcom/ai/codex/phone/PhoneControl; Lcom/termux/x11/CodexRuntimeService;'
        self.files['res/xml-v33/phone_accessibility_service.xml'] = b'compiled focus editor config fixture'
        self.manifest = {'schema': 'codex.gnu-engine.payload.v1', 'target': 'aarch64-unknown-linux-gnu', 'version': '0.169.0', 'files': []}
        for name in ('codex-native', 'codex-code-mode-host'):
            data = b'\x7fELF\x02\x01\x01' + bytes(11) + (183).to_bytes(2, 'little') + b'fixture'
            self.files['assets/gnu-engine/' + name] = data
            self.manifest['files'].append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})

    def write(self):
        self.files['assets/gnu-engine/manifest.json'] = json.dumps(self.manifest).encode()
        with zipfile.ZipFile(self.apk, 'w') as archive:
            for name, data in self.files.items():
                archive.writestr(name, data)

    def test_accepts_current_contract_without_claiming_historical_fixtures(self):
        self.write()
        result = contents.verify_native_update(self.apk)
        self.assertEqual(result['native_update_contents'], 'PASS')
        self.assertFalse(result['legacyDiagnosticFixturesQualified'])
        self.assertFalse(result['deviceQualified'])

    def test_rejects_missing_python_runtime_and_island_classes(self):
        for name in ('assets/bionic-python/lib/python3.14/os.py', 'classes.dex', 'res/xml-v33/phone_accessibility_service.xml'):
            data = self.files.pop(name)
            self.write()
            with self.assertRaises(ValueError):
                contents.verify_native_update(self.apk)
            self.files[name] = data

    def test_rejects_wrong_architecture_even_with_matching_declared_hash(self):
        name = 'assets/gnu-engine/codex-native'
        data = self.files[name][:18] + (62).to_bytes(2, 'little') + self.files[name][20:]
        self.files[name] = data
        self.manifest['files'][0]['sha256'] = hashlib.sha256(data).hexdigest()
        self.write()
        with self.assertRaisesRegex(ValueError, 'ARM64 ELF'):
            contents.verify_native_update(self.apk)

    def test_rejects_changed_engine_and_unlisted_companion(self):
        self.files['assets/gnu-engine/codex-native'] += b'changed'
        self.write()
        with self.assertRaisesRegex(ValueError, 'differs'):
            contents.verify_native_update(self.apk)
        self.files['assets/gnu-engine/codex-native'] = self.files['assets/gnu-engine/codex-native'][:-7]
        self.files['assets/gnu-engine/unlisted'] = b'extra'
        self.write()
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            contents.verify_native_update(self.apk)


if __name__ == '__main__':
    unittest.main()
