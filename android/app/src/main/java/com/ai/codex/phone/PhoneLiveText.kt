package com.ai.codex.phone

import com.ai.codex.phone.a11y.StatusLines

/** Uses exactly the overlay's localized prefix parser. No Android/UI dependencies. */
internal object PhoneLiveText {
    fun action(raw: String?, waived: String, acting: String): String =
        StatusLines(waived, acting).parse(raw ?: "Codex 正在操作手机").text

    fun detail(action: String, app: String?, paused: Boolean, prompt: PromptKind?, recent: List<String>): String {
        val headline = when {
            prompt == PromptKind.HANDOFF -> "等待接管"
            prompt != null -> "等待确认"
            paused -> "操控已暂停"
            else -> action
        }
        return buildList {
            add(headline)
            if (headline != action) add("当前动作：$action")
            if (!app.isNullOrBlank()) add("当前应用：$app")
            if (recent.isNotEmpty()) add("最近操作：" + recent.joinToString(" → "))
        }.joinToString("\n")
    }
}

/** Bounded per-task recent actions survive notification coalescing, never cross task owners. */
internal class PhoneLiveHistory {
    private var taskId = 0L
    private var current: String? = null
    private val previous = ArrayDeque<String>()
    fun record(id: Long, line: String) {
        if (id != taskId) { taskId = id; current = null; previous.clear() }
        if (line == current) return
        current?.takeIf { it.startsWith("点") || it.startsWith("长按") || it.startsWith("输入") || it.startsWith("按") || it.contains("滚动") }?.let {
            previous.addLast(it)
            while (previous.size > 3) previous.removeFirst()
        }
        current = line
    }
    fun recent(): List<String> = previous.toList()
}
