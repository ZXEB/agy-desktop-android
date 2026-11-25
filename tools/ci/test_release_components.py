"""Exercise portable completed inputs and independent cache invalidation."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import release_components as components

release = components.release


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.producer = self.root / "producer"
        self.consumer = self.root / "consumer"
        self.producer.mkdir()
        self.consumer.mkdir()
        self.selected = {"base": "a" * 40, "sha256": "b" * 64, "tag": "rust-v9.8.7", "patch": "engine.patch"}
        self.plan = {"engine": self.selected, "rustToolchain": "stable", "desktopSelector": "latest",
                     "sourceCommit": "c" * 40, "versionCode": 123, "releaseTag": "v123"}
        self.write_plan(self.producer)

    def write_plan(self, work, **updates):
        release.save(work / "plan.json", dict(copy.deepcopy(self.plan), **updates))

    def switch(self, work):
        return patch.object(release, "WORK", work)

    def transfer(self, name):
        destination = self.consumer / "components" / name
        shutil.copytree(self.producer / "components" / name, destination)
        # GitHub artifacts reset file permissions. The ELF files remain inside
        # the verified tar, so their original executable modes still survive.
        for path in destination.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        self.write_plan(self.consumer, sourceCommit="d" * 40, versionCode=456, releaseTag="v456")
        return destination

    def mesa(self):
        archive = self.producer / "fresh-mesa.tar.gz"
        archive.write_bytes(b"a completed GPU build")
        self.write_plan(self.producer, gpuArchive=str(archive), gpuSha256=release.digest(archive))
        with self.switch(self.producer):
            components.pack("mesa", "mesa-recipe")

    def engine(self, *, member=None, different_base=False):
        source = self.producer / "upstream/codex-rs"
        source.mkdir(parents=True)
        (source / "Cargo.toml").write_text('[workspace.package]\nversion = "9.8.7"\n')
        files = {name: b"ELF fixture bytes " * 4 for name in ("codex", "codex-code-mode-host")}
        descriptor = {"sourceBase": "f" * 40 if different_base else self.selected["base"],
                      "patchSha256": self.selected["sha256"], "target": release.TARGET,
                      "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                                for name, data in files.items()]}
        files["manifest.json"] = json.dumps(descriptor).encode()
        if member:
            files[member] = b"must not escape"
        archive = self.producer / "engine.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            for name, data in files.items():
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode = len(data), 0o755
                output.addfile(entry, io.BytesIO(data))
        state = self.producer / "original-build-state.json"
        release.save(state, {"buildCompleted": True, "packageCompleted": True, "buildExitCode": 0,
                            "source": str(source.parent), "sourceBase": self.selected["base"],
                            "package": str(archive), "packageSha256": release.digest(archive)})
        self.write_plan(self.producer, engineBuildState=str(state), rustCompiler="rustc fixture",
                        engineVersionOutput="codex-cli 9.8.7")
        with self.switch(self.producer):
            components.pack("engine", "engine-recipe")

    def test_only_relevant_recipe_or_selected_backend_invalidates_a_component(self):
        recipes = self.root / "recipes"
        for patterns in components.RECIPES.values():
            for pattern in patterns:
                path = recipes / pattern.replace("*", "fixture")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("original build recipe")
        original = components.keys(self.plan, recipes)
        (recipes / "android").mkdir()
        (recipes / "android/Activity.java").write_text("application UI update")
        (recipes / "README.md").write_text("documentation update")
        self.assertEqual(original, components.keys(dict(self.plan, sourceCommit="e" * 40), recipes))
        changed_backend = copy.deepcopy(self.plan)
        changed_backend["engine"]["base"] = "e" * 40
        updated = components.keys(changed_backend, recipes)
        self.assertNotEqual(original["engine"], updated["engine"])
        for name in ("mesa", "base", "native"):
            self.assertEqual(original[name], updated[name])
        (recipes / "tools/gpu/mesa-fixture.patch").write_text("updated GPU patch")
        updated = components.keys(self.plan, recipes)
        self.assertNotEqual(original["mesa"], updated["mesa"])
        self.assertEqual(original["base"], updated["base"])
        self.assertEqual(original["engine"], updated["engine"])

    def test_base_moves_between_hosts_without_the_old_bootstrap_directory(self):
        archive = self.producer / "debian-release/rootfs-original.tar.gz"
        archive.parent.mkdir()
        archive.write_bytes(b"completed pristine rootfs archive")
        (archive.parent / "debian-13-arm64-provenance.tar.gz").write_bytes(b"public provenance")
        release.save(archive.parent / "manifest.json", {"rootfs": {"sha256": release.digest(archive)}})
        self.write_plan(self.producer, baseArchive=str(archive), baseSha256=release.digest(archive),
                        baseBuildDirectory="/var/tmp/no-longer-existing-bootstrap")
        with self.switch(self.producer):
            components.pack("base", "base-recipe")
        self.transfer("base")
        shutil.rmtree(archive.parent)
        with self.switch(self.consumer):
            components.unpack("base", "base-recipe")
            value = release.state()
        self.assertTrue(Path(value["baseArchive"]).is_relative_to(self.consumer))
        self.assertEqual(Path(value["baseArchive"]).read_bytes(), b"completed pristine rootfs archive")
        self.assertNotIn("baseBuildDirectory", value)
        self.assertEqual(value["sourceCommit"], "d" * 40)
        self.assertEqual(value["versionCode"], 456)

    def test_tampered_cached_binary_is_rejected_before_import(self):
        self.mesa()
        directory = self.transfer("mesa")
        (directory / "mesa.tar.gz").write_bytes(b"tampered")
        with self.switch(self.consumer), self.assertRaisesRegex(ValueError, "completed inventory"):
            components.unpack("mesa", "mesa-recipe")

    def test_unrecorded_cached_file_is_rejected(self):
        self.mesa()
        directory = self.transfer("mesa")
        (directory / "unrecorded.txt").write_text("not an admitted release input")
        with self.switch(self.consumer), self.assertRaisesRegex(ValueError, "completed inventory"):
            components.unpack("mesa", "mesa-recipe")

    def test_cache_for_a_different_recipe_is_not_a_fallback(self):
        self.mesa()
        self.transfer("mesa")
        with self.switch(self.consumer), self.assertRaisesRegex(ValueError, "selected build inputs"):
            components.unpack("mesa", "a-different-mesa-recipe")

    def test_engine_is_restaged_in_a_new_job_without_source_or_cargo_outputs(self):
        self.engine()
        self.transfer("engine")
        shutil.rmtree(self.producer / "upstream")
        with self.switch(self.consumer):
            components.unpack("engine", "engine-recipe")
            state = json.loads(Path(release.state()["engineBuildState"]).read_text())
        self.assertTrue(Path(state["build"]).is_relative_to(self.consumer))
        if os.name == "posix":
            self.assertEqual((Path(state["build"]) / "package/codex").stat().st_mode & 0o777, 0o755)
        payload = json.loads((self.consumer / "gnu-assets/gnu-engine/manifest.json").read_text())
        self.assertEqual(payload["version"], "9.8.7")
        self.assertEqual(payload["sourceBase"], self.selected["base"])

    def test_selected_backend_cannot_be_replaced_by_another_component(self):
        self.engine(different_base=True)
        self.transfer("engine")
        with self.switch(self.consumer), self.assertRaisesRegex(ValueError, "different sources"):
            components.unpack("engine", "engine-recipe")

    def test_engine_tar_cannot_write_outside_its_package(self):
        self.engine(member="../escaped.txt")
        self.transfer("engine")
        with self.switch(self.consumer), self.assertRaisesRegex(ValueError, "Unexpected engine package member"):
            components.unpack("engine", "engine-recipe")
        self.assertFalse((self.consumer / "imported-engine/escaped.txt").exists())

    def test_apk_cannot_mix_a_different_engine_with_its_completed_image(self):
        self.engine()
        self.transfer("engine")
        self.write_plan(self.consumer, components={"engine": {"sha256": "e" * 64}})
        with self.switch(self.consumer), self.assertRaisesRegex(ValueError, "same engine component"):
            components.unpack("engine", "engine-recipe")

    def test_image_roundtrip_preserves_its_versions_but_not_the_old_apk_identity(self):
        assets = self.producer / "phone-image/assets/phone-runtime"
        assets.mkdir(parents=True)
        for name in ("release.json", "inventory.json", "codex-phone-rootfs.tar.gz"):
            (assets / name).write_text("completed image fixture")
        versions = {name: "frozen-" + name for name in components.IMAGE_FIELDS}
        self.write_plan(self.producer, **versions, components={"engine": {"sha256": "f" * 64}})
        with self.switch(self.producer):
            components.pack("image", None)
        self.transfer("image")
        with self.switch(self.consumer):
            components.unpack("image")
            value = release.state()
        self.assertEqual(value["desktopVersion"], versions["desktopVersion"])
        self.assertEqual(value["versionCode"], 456)
        self.assertEqual(value["releaseTag"], "v456")
        self.assertEqual(value["components"]["engine"]["sha256"], "f" * 64)
        self.assertTrue((self.consumer / "phone-image/assets/phone-runtime/codex-phone-rootfs.tar.gz").is_file())


if __name__ == "__main__":
    unittest.main()
