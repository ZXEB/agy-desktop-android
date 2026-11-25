package com.ai.codex;

/** Complete action phrases for the chip; full details stay in the expanded card. */
public final class LiveNotificationText {
    private LiveNotificationText() { }
    public static String chip(String text, long frame) {
        if (text == null || text.isBlank()) return "Codex";
        String line = text.split("\\n", 2)[0].replaceAll("[\\p{Cntrl}\\p{Cf}]+", " ").trim();
        line = line.split(" · ", 2)[0];
        if (line.startsWith("Codex ")) line = line.substring(6).trim();
        if (line.contains("等待确认")) return "等待确认";
        if (line.contains("等待接管")) return "等待接管";
        if (line.contains("暂停")) return "已暂停";
        if (line.contains("后台屏")) return "看后台屏";
        if (line.contains("看屏幕") || line.contains("读取屏幕")) return "看屏幕";
        if (line.startsWith("长按") || line.startsWith("点「")) {
            String action = line.startsWith("长按") ? "长按" : "点";
            int begin = line.indexOf('「'), end = line.lastIndexOf('」');
            if (begin >= 0 && end > begin) {
                String target = line.substring(begin + 1, end);
                String phrase = action + target;
                if (phrase.codePointCount(0, phrase.length()) <= 5) return phrase;
                if (Math.floorMod(frame, 2) == 1) return fit(target);
            }
            return action.equals("长按") ? "正在长按" : "正在点击";
        }
        if (line.startsWith("输入")) return "正在输入";
        if (line.contains("滚动") || line.contains("滑动")) return "正在滑动";
        if (line.startsWith("按")) return fit(line);
        if (line.contains("思考")) return "正在思考";
        if (line.contains("执行命令")) return "执行命令";
        if (line.contains("修改文件")) return "修改文件";
        if (line.contains("搜索资料")) return "搜索资料";
        if (line.contains("整理结果")) return "整理结果";
        if (line.contains("调用工具")) return "调用工具";
        if (line.contains("操控手机") || line.contains("操作手机")) return "操控手机";
        if (line.contains("回复")) return "正在回复";
        return fit(line);
    }
    private static String fit(String text) {
        if (text.codePointCount(0, text.length()) <= 5) return text;
        return text.substring(0, text.offsetByCodePoints(0, 4)) + "…";
    }
}
