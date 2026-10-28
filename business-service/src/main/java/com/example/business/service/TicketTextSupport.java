package com.example.business.service;

/**
 * 工单文本处理工具。
 *
 * <p>客户补充内容和审计追加文本都会写入工单正文，统一在这里做去空白、限长和空值拼接，
 * 保证拆分后的客户追加、坐席审核两条链路使用同一套文本规则。</p>
 */
final class TicketTextSupport {

    private TicketTextSupport() {
    }

    /**
     * 清洗客户输入：去首尾空白、按上限截断，空内容表示本次未提供该字段。
     *
     * @param value 原始输入
     * @param maxLength 允许写入的最大字符数
     * @return 清洗后的文本，未提供时返回 null
     */
    static String clean(String value, int maxLength) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String cleaned = value.trim();
        return cleaned.length() <= maxLength ? cleaned : cleaned.substring(0, maxLength);
    }

    /**
     * 在原文本后追加审计内容，空原文本按空串处理，避免出现 "null" 字样。
     *
     * @param original 原文本
     * @param addition 追加内容
     * @return 拼接后的文本
     */
    static String append(String original, String addition) {
        return (original == null ? "" : original) + addition;
    }
}
