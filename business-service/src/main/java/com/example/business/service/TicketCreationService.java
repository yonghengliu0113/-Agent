package com.example.business.service;

import com.example.business.entity.SupportTicket;
import com.example.business.entity.TicketStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

/**
 * 工单创建服务，负责建单字段补齐与人工会话建单幂等。
 *
 * <p>工单号、默认状态、SLA 截止时间和催办计数在这里统一生成；
 * 人工会话按 external_session_no 去重，保证 Agent 重试不会重复建单。</p>
 */
@Service
public class TicketCreationService {

    private final JdbcTemplate jdbcTemplate;
    private final TicketRepository ticketRepository;
    private final TicketQueryService ticketQueryService;

    public TicketCreationService(
            JdbcTemplate jdbcTemplate,
            TicketRepository ticketRepository,
            TicketQueryService ticketQueryService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.ticketRepository = ticketRepository;
        this.ticketQueryService = ticketQueryService;
    }

    /**
     * 为当前登录客户创建工单，忽略请求体中可能伪造的 customerId。
     *
     * <p>无论前端还是 Agent 提交，客户归属只认鉴权层解析出的 customerId；
     * 新工单一律进入 PENDING_ASSIGN，SLA 截止时间固定为 24 小时后。</p>
     *
     * @param ticket Agent 提交的工单草稿
     * @param customerId Token 中解析出的客户 ID
     * @return 新建工单
     */
    public SupportTicket createForCustomer(SupportTicket ticket, Long customerId) {
        LocalDateTime now = LocalDateTime.now();
        String ticketNo = "T" + now.format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))
                + String.format("%06d", Math.abs(System.nanoTime() % 1_000_000));
        SupportTicket draft = new SupportTicket(
                null,
                ticketNo,
                ticket.title(),
                ticket.ticketType(),
                ticket.priority(),
                customerId,
                ticket.orderNo(),
                ticket.sessionId(),
                ticket.externalSessionNo(),
                ticket.content(),
                ticket.aiSummary(),
                ticket.returnMethod(),
                ticket.pickupTimeWindow(),
                ticket.pickupStatus(),
                ticket.assignedGroup(),
                ticket.handlerId(),
                ticket.assignedBy(),
                ticket.assignmentReason(),
                ticket.assignmentScore(),
                ticket.assignedAt(),
                TicketStatus.PENDING_ASSIGN.name(),
                now.plusHours(24),
                ticket.source(),
                0,
                null,
                null,
                now,
                now
        );

        ticketRepository.insertDraft(draft);
        return ticketQueryService.detail(ticketNo);
    }

    /**
     * 为人工会话按需创建异步跟进工单。
     *
     * <p>同一 external_session_no 存在未关闭工单时直接返回原工单，避免重复建单；
     * 同时校验原工单归属，防止其他客户复用同一会话编号读取他人工单。</p>
     *
     * @param customerId 由 Agent 会话归属读取的客户 ID
     * @param externalSessionNo Agent 会话编号，作为幂等业务键
     * @param title 工单标题
     * @param content 客户问题摘要
     * @param priority 工单优先级
     * @return 已存在或新创建的真实业务工单
     */
    public SupportTicket createHandoffFollowUp(
            Long customerId,
            String externalSessionNo,
            String title,
            String content,
            String priority
    ) {
        if (customerId == null || externalSessionNo == null || externalSessionNo.isBlank()) {
            throw new IllegalArgumentException("人工会话客户和会话编号不能为空");
        }
        List<SupportTicket> existing = jdbcTemplate.query(
                """
                SELECT * FROM support_ticket
                WHERE external_session_no = ?
                  AND status NOT IN ('CLOSED', 'CANCELLED', 'REJECTED')
                ORDER BY id DESC
                LIMIT 1
                """,
                TicketRowMappers.SUPPORT_TICKET,
                externalSessionNo.trim()
        );
        if (!existing.isEmpty()) {
            SupportTicket ticket = existing.get(0);
            // 同一会话编号只能归属一个客户，否则视为越权复用会话键。
            if (!customerId.equals(ticket.customerId())) {
                throw new IllegalArgumentException("人工会话工单归属不一致");
            }
            return ticket;
        }
        SupportTicket draft = new SupportTicket(
                null, null,
                title == null || title.isBlank() ? "人工客服异步跟进" : title.trim(),
                "人工跟进", priority == null || priority.isBlank() ? "medium" : priority.trim(),
                customerId, null, null, externalSessionNo.trim(),
                content == null || content.isBlank() ? "客户请求人工客服异步跟进" : content.trim(),
                null, null, null, null, "customer-service", null, null,
                null, null, null, null, null, "HUMAN_HANDOFF", 0, null, null, null, null
        );
        return createForCustomer(draft, customerId);
    }
}
