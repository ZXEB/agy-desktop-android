package com.ai.codex.runtime

import com.ai.codex.phone.skills.PhoneSkillDraft
/** One explicit save of a rendered, immutable local draft. Never accepts Markdown from Flutter. */
internal class PhoneSkillWrite(val document: PhoneSkillDraft.Ready,
    val bundle: PhoneSkillBundleInstaller.Document? = null) {
    enum class Phase { STAGING, COMMITTING, FINISHED, CANCELLED }
    private var phase = Phase.STAGING
    private var outcome: PhoneSkillInstallResult? = null
    /** Small immutable receipt metadata; no Markdown or route bytes. */
    data class SaveBinding(val identity: PhoneSkillBundleInstaller.Identity,
        val descriptors: Map<String, com.ai.codex.phone.skills.PhoneSkillRoute.Descriptor>)
    private var binding = bundle?.let { SaveBinding(it.identity, it.descriptors) }
    @Synchronized fun saveBinding(): SaveBinding? = binding

    @Synchronized fun canStage(): Boolean = phase == Phase.STAGING
    @Synchronized fun phase(): Phase = phase

    /** Short permission boundary. File IO must run after this monitor is released. */
    @Synchronized fun beginCommit(): Boolean {
        if (phase != Phase.STAGING) return false
        phase = Phase.COMMITTING
        return true
    }

    /** Once committing, closing the editor is not a promise to undo a saved file. */
    @Synchronized fun cancel(): Boolean {
        if (phase != Phase.STAGING) return false
        phase = Phase.CANCELLED
        return true
    }

    @Synchronized fun finish(result: PhoneSkillInstallResult) {
        if (outcome != null) return
        outcome = result
        phase = Phase.FINISHED
    }

    @Synchronized fun result(): PhoneSkillInstallResult? = outcome
}

internal sealed interface PhoneSkillInstallResult {
    data class Saved(val name: String) : PhoneSkillInstallResult {
        val relativePath: String get() = "skills/$name/SKILL.md"
    }
    data class BundleSaved(val identity: PhoneSkillBundleInstaller.Identity) : PhoneSkillInstallResult
    data class BundleUnverified(val identity: PhoneSkillBundleInstaller.Identity,
        val publication: PhoneSkillBundleInstaller.Publication, val code: PhoneSkillBundleInstaller.Verification) : PhoneSkillInstallResult
    enum class Refused : PhoneSkillInstallResult { STALE, NO_HOME, CONFLICT, IO }
}

