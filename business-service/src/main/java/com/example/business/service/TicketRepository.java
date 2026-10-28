package com.example.business.service;

import com.example.business.entity.SupportTicket;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 工单主表读写仓储，是工单生命周期的持久化底座。
 *
 * <p>只负责单条工单的读取、草稿插入与整行更新；列表查询、状态机校验、履约补充
 * 分别由上层服务负责，避免仓储层混入业务判断。</p>
 */
@Repository
public class TicketRepository {

    private final JdbcTemplate jdbcTemplate;

    public TicketRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    /**
     * 按工单号读取工单。
     *
     * <p>查不到时抛出 IllegalArgumentException，异常类型与文案是既有对外契约，
     * 控制器依赖它转换为 400 响应，不能改成返回 null。</p>
     *
     * @param ticketNo 工单编号
     * @return 工单记录
     */
    public SupportTicket mustFind(String ticketNo) {
        List<SupportTicket> result = jdbcTemplate.query(
                "SELECT * FROM support_ticket WHERE ticket_no = ?",
                TicketRowMappers.SUPPORT_TICKET,
                ticketNo
        );
        if (result.isEmpty()) {
            throw new IllegalArgumentException("工单不存在：" + ticketNo);
        }
        return result.get(0);
    }

    /**
     * 插入新工单草稿。
     *
     * <p>工单号、默认状态、SLA 截止时间等系统字段由创建服务生成后传入，
     * 仓储层只做字段映射，不重新计算。</p>
     *
     * @param ticket 待插入的工单
     */
    public void insertDraft(SupportTicket ticket) {
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement(
                    """
                    INSERT INTO support_ticket (
                        ticket_no, title, ticket_type, priority, customer_id, order_no,
                        session_id, external_session_no, content, ai_summary,
                        return_method, pickup_time_window, pickup_status, assigned_group,
                        handler_id, assigned_by, assignment_reason, assignment_score, assigned_at,
                        status, sla_deadline, source, urge_count, last_urged_at, last_urge_reason, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
            );
            ps.setString(1, ticket.ticketNo());
            ps.setString(2, ticket.title());
            ps.setString(3, ticket.ticketType());
            ps.setString(4, ticket.priority());
            ps.setObject(5, ticket.customerId());
            ps.setString(6, ticket.orderNo());
            ps.setObject(7, ticket.sessionId());
            ps.setString(8, ticket.externalSessionNo());
            ps.setString(9, ticket.content());
            ps.setString(10, ticket.aiSummary());
            ps.setString(11, ticket.returnMethod());
            ps.setString(12, ticket.pickupTimeWindow());
            ps.setString(13, ticket.pickupStatus());
            ps.setString(14, ticket.assignedGroup());
            ps.setObject(15, ticket.handlerId());
            ps.setString(16, ticket.assignedBy());
            ps.setString(17, ticket.assignmentReason());
            ps.setObject(18, ticket.assignmentScore());
            ps.setTimestamp(19, TicketRowMappers.toTimestamp(ticket.assignedAt()));
            ps.setString(20, ticket.status());
            ps.setTimestamp(21, TicketRowMappers.toTimestamp(ticket.slaDeadline()));
            ps.setString(22, ticket.source());
            ps.setObject(23, ticket.urgeCount());
            ps.setTimestamp(24, TicketRowMappers.toTimestamp(ticket.lastUrgedAt()));
            ps.setString(25, ticket.lastUrgeReason());
            ps.setTimestamp(26, TicketRowMappers.toTimestamp(ticket.createdAt()));
            ps.setTimestamp(27, TicketRowMappers.toTimestamp(ticket.updatedAt()));
            return ps;
        });
    }

    /**
     * 整行覆盖更新工单，并返回数据库中的最新记录。
     *
     * <p>更新的影响行数为 0 说明工单已被删除，这里沿用历史异常文案，
     * 保证调用方看到的错误语义不变。</p>
     *
     * @param updated 已重建的工单
     * @return 更新后的工单
     */
    public SupportTicket replace(SupportTicket updated) {
        int rows = jdbcTemplate.update(
                """
                UPDATE support_ticket
                SET title = ?, ticket_type = ?, priority = ?, customer_id = ?, order_no = ?,
                    session_id = ?, external_session_no = ?, content = ?, ai_summary = ?,
                    return_method = ?, pickup_time_window = ?, pickup_status = ?,
                    assigned_group = ?, handler_id = ?, assigned_by = ?, assignment_reason = ?,
                    assignment_score = ?, assigned_at = ?, status = ?, sla_deadline = ?,
                    source = ?, urge_count = ?, last_urged_at = ?, last_urge_reason = ?,
                    created_at = ?, updated_at = ?
                WHERE ticket_no = ?
                """,
                updated.title(),
                updated.ticketType(),
                updated.priority(),
                updated.customerId(),
                updated.orderNo(),
                updated.sessionId(),
                updated.externalSessionNo(),
                updated.content(),
                updated.aiSummary(),
                updated.returnMethod(),
                updated.pickupTimeWindow(),
                updated.pickupStatus(),
                updated.assignedGroup(),
                updated.handlerId(),
                updated.assignedBy(),
                updated.assignmentReason(),
                updated.assignmentScore(),
                TicketRowMappers.toTimestamp(updated.assignedAt()),
                updated.status(),
                TicketRowMappers.toTimestamp(updated.slaDeadline()),
                updated.source(),
                updated.urgeCount(),
                TicketRowMappers.toTimestamp(updated.lastUrgedAt()),
                updated.lastUrgeReason(),
                TicketRowMappers.toTimestamp(updated.createdAt()),
                TicketRowMappers.toTimestamp(updated.updatedAt()),
                updated.ticketNo()
        );
        if (rows == 0) {
            throw new IllegalArgumentException("工单不存在：" + updated.ticketNo());
        }
        return mustFind(updated.ticketNo());
    }

    /**
     * 在保留原分派信息的前提下重建工单，用于纯状态推进。
     *
     * @param ticket 原工单
     * @param status 目标状态
     * @return 状态已替换的工单
     */
    public SupportTicket rebuildWithExistingAssignment(SupportTicket ticket, String status) {
        return rebuild(
                ticket,
                ticket.assignedGroup(),
                ticket.handlerId(),
                ticket.assignedBy(),
                ticket.assignmentReason(),
                ticket.assignmentScore(),
                ticket.assignedAt(),
                status
        );
    }

    /**
     * 基于原工单重建一份内存记录，用于状态和分派信息的一次性更新。
     *
     * <p>分派组和分派人只在传入非空时覆盖，避免自动派单或状态推进把已有归组清空；
     * 更新时间统一刷新为当前时间，作为工单最近变更依据。</p>
     *
     * @param ticket 原工单
     * @param assignedGroup 新处理组，为空时保留原值
     * @param handlerId 新处理人，为空时保留原值
     * @param assignedBy 派单来源
     * @param assignmentReason 派单原因
     * @param assignmentScore 派单分
     * @param assignedAt 分派时间
     * @param status 目标状态
     * @return 重建后的工单
     */
    public SupportTicket rebuild(
            SupportTicket ticket,
            String assignedGroup,
            Long handlerId,
            String assignedBy,
            String assignmentReason,
            Integer assignmentScore,
            LocalDateTime assignedAt,
            String status
    ) {
        return new SupportTicket(
                ticket.id(),
                ticket.ticketNo(),
                ticket.title(),
                ticket.ticketType(),
                ticket.priority(),
                ticket.customerId(),
                ticket.orderNo(),
                ticket.sessionId(),
                ticket.externalSessionNo(),
                ticket.content(),
                ticket.aiSummary(),
                ticket.returnMethod(),
                ticket.pickupTimeWindow(),
                ticket.pickupStatus(),
                assignedGroup == null || assignedGroup.isBlank() ? ticket.assignedGroup() : assignedGroup,
                handlerId == null ? ticket.handlerId() : handlerId,
                assignedBy,
                assignmentReason,
                assignmentScore,
                assignedAt,
                status,
                ticket.slaDeadline(),
                ticket.source(),
                ticket.urgeCount(),
                ticket.lastUrgedAt(),
                ticket.lastUrgeReason(),
                ticket.createdAt(),
                LocalDateTime.now()
        );
    }
}
