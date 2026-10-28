package com.example.business.service;

import com.example.business.entity.SupportTicket;
import com.example.business.entity.TicketStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.LocalDateTime;

/**
 * 客户催办服务，负责催办日志落库与工单最近催办摘要更新。
 *
 * <p>催办只允许客户对自己的工单发起，且已关闭工单不再接受催办；
 * 日志与工单摘要必须同时写入，坐席侧才能看到催办次数和最后一次原因。</p>
 */
@Service
public class TicketUrgeService {

    private final JdbcTemplate jdbcTemplate;
    private final TicketQueryService ticketQueryService;

    public TicketUrgeService(JdbcTemplate jdbcTemplate, TicketQueryService ticketQueryService) {
        this.jdbcTemplate = jdbcTemplate;
        this.ticketQueryService = ticketQueryService;
    }

    /**
     * 客户催办自己的工单，写入催办日志并更新工单最近催办摘要。
     *
     * @param ticketNo 工单编号
     * @param customerId 当前客户 ID
     * @param reason 客户催办原因或补充说明
     * @return 更新后的工单
     */
    public SupportTicket urgeForCustomer(String ticketNo, Long customerId, String reason) {
        SupportTicket ticket = ticketQueryService.detailForCustomer(ticketNo, customerId);
        // 已关闭工单的后续诉求必须走变更申请或新工单，不能再靠催办推动。
        if (TicketStatus.CLOSED.name().equals(ticket.status())) {
            throw new IllegalArgumentException("工单已关闭，暂不支持催办：" + ticketNo);
        }
        LocalDateTime now = LocalDateTime.now();
        String cleanedReason = reason == null || reason.isBlank() ? "客户催办处理进度" : reason.trim();
        jdbcTemplate.update(
                """
                INSERT INTO ticket_urge_log (ticket_no, customer_id, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                ticketNo,
                customerId,
                cleanedReason,
                Timestamp.valueOf(now)
        );
        int rows = jdbcTemplate.update(
                """
                UPDATE support_ticket
                SET urge_count = COALESCE(urge_count, 0) + 1,
                    last_urged_at = ?,
                    last_urge_reason = ?,
                    updated_at = ?
                WHERE ticket_no = ?
                """,
                Timestamp.valueOf(now),
                cleanedReason,
                Timestamp.valueOf(now),
                ticketNo
        );
        if (rows == 0) {
            throw new IllegalArgumentException("工单不存在：" + ticketNo);
        }
        return ticketQueryService.detailForCustomer(ticketNo, customerId);
    }
}
