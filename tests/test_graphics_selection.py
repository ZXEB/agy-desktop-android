"""Exercise the real shell selector; probes are test doubles, never GPU evidence."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name == "posix", "Requires bash/Linux")
class GraphicsSelectionTest(unittest.TestCase):
    def run_selector(self, mode, probe=None):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            prefix = home / 'gpu'
            for name in ['lib/libGL.so.1', 'lib/libEGL.so.1', 'lib/libvulkan_freedreno.so', 'share/vulkan/icd.d/freedreno_icd.aarch64.json']:
                file = prefix / name; file.parent.mkdir(parents=True, exist_ok=True); file.touch()
            device = home / 'kgsl'
            software_probe = home / 'software-probe.py'; software_probe.write_text('raise SystemExit(0)\n')
            if probe is not None:
                device.touch()
                file = prefix / 'bin/glx-clear-probe'; file.parent.mkdir(); file.write_text('#!/bin/bash\n' + probe + '\n'); file.chmod(0o700)
            script = 'source "$SELECTOR"; codex_select_graphics; result=$?; printf "RESULT=%s SW=%s GALLIUM=%s VK=%s LD=%s\\n" "$result" "${LIBGL_ALWAYS_SOFTWARE:-}" "${GALLIUM_DRIVER:-}" "${VK_DRIVER_FILES:-}" "${LD_LIBRARY_PATH:-}"; exit "$result"'
            env = dict(os.environ, HOME=str(home), SELECTOR=str(ROOT/'runtime/guest/codex-graphics.sh'),
                CODEX_GRAPHICS_MODE=mode, CODEX_GPU_PREFIX=str(prefix), CODEX_KGSL_DEVICE=str(device),
                CODEX_SOFTWARE_PROBE=str(software_probe),
                LD_LIBRARY_PATH=str(prefix/'lib')+':/keep-native-libs', VK_DRIVER_FILES='stale', LIBGL_ALWAYS_SOFTWARE='stale')
            return subprocess.run(['bash','-c',script], env=env, text=True, capture_output=True, timeout=15)

    def test_auto_without_kgsl_uses_software_and_clears_icd(self):
        run = self.run_selector('auto')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('SW=true GALLIUM=llvmpipe VK= LD=/keep-native-libs',run.stdout)
    def test_software_does_not_attempt_hardware(self):
        run = self.run_selector('software','exit 99')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('GALLIUM=llvmpipe',run.stdout)
    def test_failed_hardware_probe_falls_back_in_auto(self):
        run = self.run_selector('auto','exit 1')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('GALLIUM=llvmpipe',run.stdout)
    def test_passing_probe_selects_hardware_and_clears_software_override(self):
        run = self.run_selector('auto','exit 0')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('SW= GALLIUM=zink VK=',run.stdout)
    def test_explicit_acceleration_fails_clearly(self):
        run = self.run_selector('hardware','exit 1')
        self.assertNotEqual(run.returncode,0)
        self.assertIn('Select compatibility mode',run.stderr)
    def test_invalid_mode_is_rejected(self):
        self.assertNotEqual(self.run_selector('invalid').returncode,0)

if __name__ == '__main__': unittest.main()
