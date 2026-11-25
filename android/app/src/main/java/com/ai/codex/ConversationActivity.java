package com.ai.codex;

import java.util.HashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONObject;

/** Only paired, real engine events change the live response state. */
public final class ConversationActivity {
    private static final String UUID = "[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}";
    private static final Pattern ROLLOUT = Pattern.compile("rollout-[^/\\\\]*?-(" + UUID + ")(?:_" + UUID + ")?\\.jsonl");
    /** A fork/continuation suffix is a storage identity, not the canonical thread id. */
    public static String threadFromRollout(String name) {
        if (name == null) return null;
        Matcher match = ROLLOUT.matcher(name);
        return match.matches() ? match.group(1) : null;
    }
    public enum Change { NONE, STARTED, UPDATED, COMPLETED, INTERRUPTED }
    private final Map<String, String> active = new HashMap<>();
    private final Map<String, String> progress = new HashMap<>();
    public int activeCount() { return active.size(); }
    public String status(String thread) { return progress.getOrDefault(thread, "正在思考"); }
    public Change accept(String thread, JSONObject record) {
        boolean response = "response_item".equals(record.optString("type"));
        if (!response && !"event_msg".equals(record.optString("type"))) return Change.NONE;
        JSONObject event = record.optJSONObject("payload");
        if (event == null) return Change.NONE;
        String type = event.optString("type"), turn = event.optString("turn_id");
        if (!response && "task_started".equals(type) && !turn.isEmpty()) {
            if (turn.equals(active.put(thread, turn))) return Change.NONE;
            progress.put(thread, "正在思考");
            return Change.STARTED;
        }
        String running = active.get(thread);
        if (running == null || (!turn.isEmpty() && !running.equals(turn))) return Change.NONE;
        if (response) return update(thread, responseStatus(event));
        if ("task_complete".equals(type)) {
            if (turn.isEmpty()) return Change.NONE;
            active.remove(thread);
            progress.remove(thread);
            return Change.COMPLETED;
        }
        if ("turn_aborted".equals(type)) {
            active.remove(thread);
            progress.remove(thread);
            return Change.INTERRUPTED;
        }
        String next = switch (type) {
            case "agent_reasoning", "agent_reasoning_raw_content" -> "正在思考";
            case "exec_command_begin" -> "正在执行命令";
            case "patch_apply_begin" -> "正在修改文件";
            case "web_search_begin" -> "正在搜索资料";
            case "mcp_tool_call_begin" -> {
                JSONObject invocation = event.optJSONObject("invocation");
                yield invocation != null && "phone".equals(invocation.optString("server"))
                    ? "正在操控手机" : "正在调用工具";
            }
            case "exec_command_end", "patch_apply_end", "mcp_tool_call_end", "web_search_end" -> "正在整理结果";
            case "agent_message" -> "正在回复";
            case "item_completed" -> completedStatus(event.optJSONObject("item"));
            default -> null;
        };
        return update(thread, next);
    }
    private Change update(String thread, String next) {
        if (next != null && !next.equals(progress.put(thread, next))) return Change.UPDATED;
        return Change.NONE;
    }
    private static String responseStatus(JSONObject item) {
        return switch (item.optString("type")) {
            case "custom_tool_call", "function_call" -> toolStatus(item.optString("name"));
            case "custom_tool_call_output", "function_call_output" -> "正在整理结果";
            case "reasoning" -> "正在思考";
            case "message" -> "assistant".equals(item.optString("role")) ? "正在回复" : null;
            default -> null;
        };
    }
    private static String toolStatus(String name) {
        if (name.startsWith("mcp__phone__")) return "正在操控手机";
        return switch (name) {
            case "exec", "exec_command", "shell", "shell_command", "write_stdin" -> "正在执行命令";
            case "apply_patch" -> "正在修改文件";
            case "web", "web.run", "web_search" -> "正在搜索资料";
            default -> "正在调用工具";
        };
    }
    private static String completedStatus(JSONObject item) {
        if (item == null) return null;
        return switch (item.optString("type")) {
            case "CommandExecution", "FileChange", "McpToolCall", "WebSearch" -> "正在整理结果";
            case "Reasoning" -> "正在思考";
            case "AgentMessage" -> "正在回复";
            default -> null;
        };
    }
}
