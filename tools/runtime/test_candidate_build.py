"""Real filesystem/ZIP admission regressions; never runs Gradle or Android."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

SPEC = importlib.util.spec_from_file_location("candidate_build", Path(__file__).with_name("build-production-candidate.py"))
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


class CandidateAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root_patch = patch.object(candidate, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def put(self, name, data=b"input"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def descriptor(self):
        inputs = {}
        for name in candidate.PAYLOADS + candidate.TOOLCHAINS:
            self.put(name + "/input")
            inputs[name] = {"path": name, "files": candidate.inventory(self.root / name)}
        value = {"schema": candidate.SCHEMA, "scope": "test", "sdk": "sdkPlatform", "gradle": "gradleHome/input",
                 "buildToolsVersion": "36.0.0", "sdkPlatformDirectory": "android-37.0", "inputs": inputs}
        path = self.put("inputs.json", candidate.canonical(value))
        return path, candidate.digest_file(path), value

    def test_reject_changed_descriptor_before_reading_any_input(self):
        path, _, _ = self.descriptor()
        with self.assertRaisesRegex(ValueError, "descriptor digest"):
            candidate.admit_inputs(path, "0" * 64)

    def test_reject_mutated_file_with_valid_descriptor(self):
        path, sha, _ = self.descriptor()
        self.put("executor/input", b"tampered")
        with self.assertRaisesRegex(ValueError, "inventory/hash differs: executor"):
            candidate.admit_inputs(path, sha)

    def test_reject_uninventoried_file(self):
        path, sha, _ = self.descriptor()
        self.put("executor/extra", b"new")
        with self.assertRaisesRegex(ValueError, "inventory/hash differs: executor"):
            candidate.admit_inputs(path, sha)

    def test_reject_missing_file(self):
        path, sha, _ = self.descriptor()
        (self.root / "executor/input").unlink()
        with self.assertRaisesRegex(ValueError, "empty"):
            candidate.admit_inputs(path, sha)

    def test_duplicate_json_fields_refused(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            candidate.strict_json(b'{"schema":1,"schema":2}')

    def test_existing_attempt_preserved_including_empty_directory(self):
        output = self.root / "work/attempt"
        output.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            candidate.output_path(output)
        self.assertEqual(list(output.iterdir()), [])

    def test_outputs_refuse_project_root_other_directory_and_escape(self):
        for value in (self.root, self.root / "android/output", self.root / "work/../../escape"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                candidate.output_path(value)

    def test_exclusive_manifest_write_preserves_previous_bytes(self):
        path = self.put("work/input.json", b"preserved")
        with self.assertRaises(FileExistsError):
            candidate.write_new(path, {"replacement": True})
        self.assertEqual(path.read_bytes(), b"preserved")

    def test_current_executor_source_required_even_with_matching_manifest(self):
        source = self.put("tools/executor/example.py", b"current\n")
        self.put("executor/assets/codex-executor/tools/executor/example.py", b"obsolete\n")
        self.put("executor/assets/codex-executor-manifest.json", candidate.canonical([
            {"path": "tools/executor/example.py", "sha256": hashlib.sha256(b"obsolete\n").hexdigest()}]))
        with self.assertRaisesRegex(ValueError, "restage"):
            candidate.validate_source_closure(self.root / "executor")
        source.write_bytes(b"obsolete\r\n")
        self.assertEqual(candidate.validate_source_closure(self.root / "executor"), 1)

    def test_packaged_payload_bytes_checked_independently(self):
        path = self.put("runtime/arm64-v8a/libproot.so", b"approved")
        descriptor = {"inputs": {name: {"files": {}} for name in candidate.PAYLOADS}}
        descriptor["inputs"]["runtimeJni"]["files"] = candidate.inventory(path.parent.parent)
        apk = self.root / "candidate.apk"
        with ZipFile(apk, "w") as archive:
            archive.writestr("lib/arm64-v8a/libproot.so", b"changed")
        with self.assertRaisesRegex(ValueError, "Packaged input differs"):
            candidate.verify_packaged_inputs(apk, descriptor)

    def test_stale_x11_provenance_refused(self):
        self.put("x11/build-manifest.json", candidate.canonical({"sha256": "0" * 64}))
        trees = {"runtimeJni": {name: {} for name in candidate.RUNTIME},
                 "transportJni": {name: {} for name in candidate.TRANSPORT},
                 "x11Jni": {"arm64-v8a/libXlorie.so": {"sha256": "1" * 64}, "build-manifest.json": {}}}
        with self.assertRaisesRegex(ValueError, "does not identify"):
            candidate.validate_payloads({"x11Jni": self.root / "x11"}, trees)

    def test_preflight_does_not_create_output_or_run_gradle(self):
        self.put("gradle/bin/gradle", b"gradle")
        self.put("executor/assets/codex-executor-qualification.json", candidate.canonical({}))
        descriptor = {"gradle": "gradle/bin/gradle", "buildToolsVersion": "36.0.0"}
        paths = {name: self.root / name for name in candidate.PAYLOADS}
        args = argparse.Namespace(candidate="r47", output=self.root / "work/new", inputs=self.root / "manifest",
                                  inputs_sha256="0" * 64, preflight_only=True)
        with patch.object(candidate, "admit_inputs", return_value=(descriptor, paths, {})), patch.object(candidate.subprocess, "run") as run:
            result = candidate.build_candidate(args)
        self.assertEqual(result["preflight"], "PASS")
        self.assertFalse(args.output.exists())
        run.assert_not_called()
        for prop in ("RuntimeJni", "X11Jni", "FrozenTransportJni", "DebugJni", "DebugAssets", "ExecutorAssets", "ExecutorJni"):
            self.assertTrue(any(arg.startswith("-Pcodex" + prop + "=") for arg in result["argv"]))

    def test_source_support_build_is_bound_to_selected_package(self):
        self.put("gradle/bin/gradle", b"gradle")
        build = self.put("support/build.json", candidate.canonical({"schema": "build-fixture"}))
        self.put("executor/assets/codex-executor-qualification.json", candidate.canonical({
            "sourceBuildInputs": {"supportBuild": {"path": "support",
                "buildManifestSha256": candidate.digest_file(build)}}}))
        descriptor = {"gradle": "gradle/bin/gradle", "buildToolsVersion": "36.0.0"}
        paths = {name: self.root / name for name in candidate.PAYLOADS}
        command = candidate.command_for(descriptor, paths)
        self.assertIn("-PcodexRuntimeSupportBuild=" + str(build.parent), command)
        build.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "support build differs"):
            candidate.command_for(descriptor, paths)

    def test_source_only_handoff_snapshots_sources_and_ignores_generated_files(self):
        self.put("android/app/src/main/Test.kt", b"source")
        self.put("android/app/build/generated/Test.kt", b"generated")
        self.put("android/local.properties", b"private workstation path")
        self.put("vendor/termux-x11/lorie/Native.c", b"native source")
        self.put("vendor/termux-x11/.git/config", b"git metadata")
        with patch.object(candidate.subprocess, "check_output", side_effect=subprocess.CalledProcessError(128, "git")):
            files = candidate.source_inventory()
        self.assertEqual(set(files), {"android/app/src/main/Test.kt", "vendor/termux-x11/lorie/Native.c"})
        self.put("android/app/src/main/Test.kt", b"changed")
        with patch.object(candidate.subprocess, "check_output", side_effect=subprocess.CalledProcessError(128, "git")):
            self.assertNotEqual(candidate.source_inventory(), files)

    def gnu_assets(self):
        self.put("recovery/engine/manifest.json", candidate.canonical({"base": "a" * 40, "tag": "rust-v0.169.0"}))
        rows = []
        for name in ("codex-native", "codex-code-mode-host"):
            path = self.put("gnu/gnu-engine/" + name, name.encode())
            rows.append({"name": name, "bytes": path.stat().st_size, "sha256": candidate.digest_file(path)})
        self.put("gnu/gnu-engine/manifest.json", candidate.canonical({"schema": "codex.gnu-engine.payload.v1",
            "target": "aarch64-unknown-linux-gnu", "sourceBase": "a" * 40, "version": "0.169.0", "files": rows}))
        return argparse.Namespace(gnu_engine_assets=self.root / "gnu", gradle_init_script=[])

    def test_gnu_pair_rejects_changed_bytes_and_other_version(self):
        args = self.gnu_assets()
        self.assertEqual(candidate.auxiliary_inputs(args)["gnuEngineAssets"]["version"], "0.169.0")
        self.put("gnu/gnu-engine/codex-native", b"tampered")
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            candidate.auxiliary_inputs(args)
        self.put("recovery/engine/manifest.json", candidate.canonical({"base": "b" * 40, "tag": "rust-v0.169.0"}))
        with self.assertRaisesRegex(ValueError, "version/base"):
            candidate.auxiliary_inputs(args)

    def test_packaged_gnu_pair_is_checked_against_actual_apk_bytes(self):
        args = self.gnu_assets()
        auxiliary = candidate.auxiliary_inputs(args)
        apk = self.root / "gnu.apk"
        with ZipFile(apk, "w") as archive:
            for name in auxiliary["gnuEngineAssets"]["files"]:
                archive.writestr("assets/" + name, b"changed")
        with self.assertRaisesRegex(ValueError, "Packaged GNU engine differs"):
            candidate.verify_auxiliary_apk(apk, auxiliary)

    def reuse_fixture(self):
        apk = self.root / 'installed.apk'
        data = b'original native bytes'
        with ZipFile(apk, 'w') as archive:
            archive.writestr('lib/arm64-v8a/libproot.so', data)
        descriptor = {'inputs': {name: {'files': {}} for name in candidate.PAYLOADS}}
        descriptor['inputs']['runtimeJni']['files'] = {'arm64-v8a/libproot.so': {
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}
        args = argparse.Namespace(gradle_init_script=[], gnu_engine_assets=None,
            reuse_native_apk=apk, reuse_native_apk_sha256=candidate.digest_file(apk), signing_cert_sha256='2' * 64)
        paths = {'jdk': self.root / 'jdk', 'sdkBuildTools': self.root / 'build-tools'}
        return args, descriptor, paths

    def test_reused_native_payload_must_match_the_signed_original_bytes(self):
        args, descriptor, paths = self.reuse_fixture()
        with patch.object(candidate.subprocess, 'check_output', return_value='Signer #1 certificate SHA-256 digest: ' + '2' * 64):
            result = candidate.auxiliary_inputs(args, descriptor, paths)
            self.assertFalse(result['reusedNativeInputs']['nativeRebuilt'])
            descriptor['inputs']['runtimeJni']['files']['arm64-v8a/libproot.so']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'Packaged input differs'):
                candidate.auxiliary_inputs(args, descriptor, paths)

    def test_reused_native_apk_requires_both_pinned_digest_and_original_certificate(self):
        args, descriptor, paths = self.reuse_fixture()
        with patch.object(candidate.subprocess, 'check_output', return_value='Signer #1 certificate SHA-256 digest: ' + '3' * 64) as verify:
            with self.assertRaisesRegex(ValueError, 'certificate differs'):
                candidate.auxiliary_inputs(args, descriptor, paths)
            args.reuse_native_apk_sha256 = '0' * 64
            verify.reset_mock()
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                candidate.auxiliary_inputs(args, descriptor, paths)
            verify.assert_not_called()

    def test_old_producer_paths_are_not_local_receipts_when_bytes_are_reused(self):
        self.put('gradle/bin/gradle', b'gradle')
        self.put('executor/assets/codex-executor-qualification.json', candidate.canonical({
            'sourceBuildInputs': {'supportBuild': {'path': 'old-computer/missing', 'buildManifestSha256': '0' * 64}}}))
        descriptor = {'gradle': 'gradle/bin/gradle', 'buildToolsVersion': '36.0.0'}
        paths = {name: self.root / name for name in candidate.PAYLOADS}
        with self.assertRaises(FileNotFoundError):
            candidate.command_for(descriptor, paths)
        self.assertFalse(any(x.startswith('-PcodexRuntimeSupportBuild=') for x in candidate.command_for(descriptor, paths, reuse_native=True)))


if __name__ == "__main__":
    unittest.main()
