"""Verify the fresh image's real guest source closure without building Debian."""
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("build_phone_image", Path(__file__).with_name("build-phone-image.py"))
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class GuestSourceTests(unittest.TestCase):
    def test_fresh_image_has_the_launchers_mcp_and_audio_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder.install_guest_sources(root)
            for name in (
                "usr/local/bin/codex-session", "usr/local/bin/codex-native",
                "usr/local/lib/codex/codex_phone_profile.py", "usr/local/lib/codex/install_phone_mcp.py",
                "usr/local/lib/codex/codex_native_dialogs.py", "usr/local/lib/codex/codex-phone-dialogs.css",
                "usr/local/lib/codex/install-workspace-provider.py", "usr/local/lib/codex/codex-workspace-provider.cjs",
                "usr/local/lib/codex/codex_ime.py", "usr/local/lib/codex/keyboard-focus.js",
                "usr/local/share/codex/pulseaudio.pa"):
                with self.subTest(name=name):
                    self.assertGreater((root / name).stat().st_size, 0)
            self.assertTrue((root / "usr/local/bin/codex-session").stat().st_mode & stat.S_IXUSR)
            self.assertEqual(list((root / "usr/local/share/codex").glob("**/auth.json")), [])


if __name__ == "__main__":
    unittest.main()
