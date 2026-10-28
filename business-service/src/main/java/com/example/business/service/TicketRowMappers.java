package com.example.business.service;

import com.example.business.entity.SupportTicket;
import com.example.business.entity.TicketChangeRequest;
import org.springframework.jdbc.core.RowMapper;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDateTime;

/**
 * 工单相关数据行的统一映射工具。
 *
 * <p>工单主表与履约变更申请表的列读取、空值处理和时间类型转换集中在这里，
 * 避免拆分后的各个服务各写一份映射导致字段顺序错位。</p>
 */
final class TicketRowMappers {

    /** 工单主表行映射，字段顺序与 support_ticket 表列语义保持一致。 */
    static final RowMapper<SupportTicket> SUPPORT_TICKET = (rs, rowNum) -> new SupportTicket(
            nullableLong(rs, "id"),
            rs.getString("ticket_no"),
            rs.getString("title"),
            rs.getString("ticket_type"),
            rs.getString("priority"),
            nullableLong(rs, "customer_id"),
            rs.getString("order_no"),
            nullableLong(rs, "session_id"),
            rs.getString("external_session_no"),
            rs.getString("content"),
            rs.getString("ai_summary"),
            rs.getString("return_method"),
            rs.getString("pickup_time_window"),
            rs.getString("pickup_status"),
            rs.getString("assigned_group"),
            nullableLong(rs, "handler_id"),
            rs.getString("assigned_by"),
            rs.getString("assignment_reason"),
            nullableInteger(rs, "assignment_score"),
            toLocalDateTime(rs.getTimestamp("assigned_at")),
            rs.getString("status"),
            toLocalDateTime(rs.getTimestamp("sla_deadline")),
            rs.getString("source"),
            nullableInteger(rs, "urge_count"),
            toLocalDateTime(rs.getTimestamp("last_urged_at")),
            rs.getString("last_urge_reason"),
            toLocalDateTime(rs.getTimestamp("created_at")),
            toLocalDateTime(rs.getTimestamp("updated_at"))
    );

    /** 已锁定或已关闭工单的履约变更申请映射，原工单与申请保持独立。 */
    static final RowMapper<TicketChangeRequest> CHANGE_REQUEST = (rs, rowNum) -> new TicketChangeRequest(
            nullableLong(rs, "id"),
            rs.getString("request_no"),
            rs.getString("parent_ticket_no"),
            nullableLong(rs, "customer_id"),
            rs.getString("external_session_no"),
            rs.getString("change_type"),
            rs.getString("previous_return_method"),
            rs.getString("previous_pickup_time_window"),
            rs.getString("requested_return_method"),
            rs.getString("requested_pickup_time_window"),
            rs.getString("parent_ticket_status"),
            rs.getString("status"),
            rs.getString("idempotency_key"),
            nullableLong(rs, "reviewed_by"),
            rs.getString("customer_message"),
            toLocalDateTime(rs.getTimestamp("reviewed_at")),
            toLocalDateTime(rs.getTimestamp("created_at")),
            toLocalDateTime(rs.getTimestamp("updated_at"))
    );

    private TicketRowMappers() {
    }

    /** 业务时间转 JDBC 时间戳，空值保持为空。 */
    static Timestamp toTimestamp(LocalDateTime value) {
        return value == null ? null : Timestamp.valueOf(value);
    }

    /** JDBC 时间戳转业务时间，空值保持为空。 */
    static LocalDateTime toLocalDateTime(Timestamp value) {
        return value == null ? null : value.toLocalDateTime();
    }

    /** 读取可空 BIGINT 列，避免 getLong 把 NULL 误读成 0。 */
    private static Long nullableLong(ResultSet rs, String columnName) throws SQLException {
        long value = rs.getLong(columnName);
        return rs.wasNull() ? null : value;
    }

    /** 读取可空 INTEGER 列，避免 getInt 把 NULL 误读成 0。 */
    private static Integer nullableInteger(ResultSet rs, String columnName) throws SQLException {
        int value = rs.getInt(columnName);
        return rs.wasNull() ? null : value;
    }
}
