package com.example.business.service;

import com.example.business.entity.SupportTicket;
import com.example.business.entity.TicketStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Set;

/**
 * 工单状态流转服务，负责分派、抢单、转派、推进、关闭、重开与 AI 自动结单。
 *
 * <p>所有入口都先校验当前状态再更新，状态机规则集中在 validateTransition 与 assertStatusIn，
 * 保证拆分后坐席端、内部端和自动派单不会走出不同的流转路径。</p>
 */
@Service
public class TicketWorkflowService {

    private final JdbcTemplate jdbcTemplate;
    private final TicketRepository ticketRepository;

    public TicketWorkflowService(JdbcTemplate jdbcTemplate, TicketRepository ticketRepository) {
        this.jdbcTemplate = jdbcTemplate;
        this.ticketRepository = ticketRepository;
    }

    /**
     * 坐席手动领取或分派工单。
     *
     * @param ticketNo 工单编号
     * @param handlerId 处理人 ID
     * @param assignedGroup 处理组
     * @return 分派后的工单
     */
    public SupportTicket assign(String ticketNo, Long handlerId, String assignedGroup) {
        SupportTicket ticket = ticketRepository.mustFind(ticketNo);
        assertStatusIn(ticket, "分派", Set.of(
                TicketStatus.PENDING_ASSIGN.name(),
                TicketStatus.PENDING_PROCESS.name(),
                TicketStatus.TRANSFERRED.name(),
                TicketStatus.REOPENED.name()
        ));
        return ticketRepository.replace(ticketRepository.rebuild(
                ticket,
                assignedGroup,
                handlerId,
                "MANUAL",
                "坐席手动领取或分派工单",
                null,
                LocalDateTime.now(),
                TicketStatus.PENDING_PROCESS.name()
        ));
    }

    /**
     * 根据自动派单决策写入处理人和派单说明。
     *
     * <p>只接受待分派、已转派、已重开三种状态，其他状态直接原样返回，
     * 避免自动派单覆盖正在处理中的工单归属。</p>
     *
     * @param ticketNo 工单编号
     * @param handlerId 推荐处理人，为空时只记录未派出原因
     * @param assignedGroup 推荐处理组
     * @param assignedBy 派单来源
     * @param assignmentReason 派单原因
     * @param assignmentScore 派单分
     * @return 更新后的工单
     */
    public SupportTicket assignAutomatically(
            String ticketNo,
            Long handlerId,
            String assignedGroup,
            String assignedBy,
            String assignmentReason,
            Integer assignmentScore
    ) {
        SupportTicket ticket = ticketRepository.mustFind(ticketNo);
        if (!Set.of(
                TicketStatus.PENDING_ASSIGN.name(),
                TicketStatus.TRANSFERRED.name(),
                TicketStatus.REOPENED.name()
        ).contains(ticket.status())) {
            return ticket;
        }

        if (handlerId == null) {
            // 没有可接单坐席时仍写入派单说明，工单保持原状态继续待在队列中。
            return ticketRepository.replace(ticketRepository.rebuild(
                    ticket,
                    assignedGroup,
                    null,
                    assignedBy,
                    assignmentReason,
                    assignmentScore,
                    null,
                    ticket.status()
            ));
        }

        return ticketRepository.replace(ticketRepository.rebuild(
                ticket,
                assignedGroup,
                handlerId,
                assignedBy,
                assignmentReason,
                assignmentScore,
                LocalDateTime.now(),
                TicketStatus.PENDING_PROCESS.name()
        ));
    }

    /**
     * 手动转派工单到其他处理组或处理人。
     *
     * @param ticketNo 工单编号
     * @param assignedGroup 新处理组
     * @param handlerId 新处理人
     * @return 转派后的工单
     */
    public SupportTicket transfer(String ticketNo, String assignedGroup, Long handlerId) {
        SupportTicket ticket = ticketRepository.mustFind(ticketNo);
        assertStatusIn(ticket, "转派", Set.of(
                TicketStatus.PENDING_PROCESS.name(),
                TicketStatus.PROCESSING.name(),
                TicketStatus.REOPENED.name()
        ));
        return ticketRepository.replace(ticketRepository.rebuild(
                ticket,
                assignedGroup,
                handlerId,
                "MANUAL",
                "坐席手动转派工单",
                null,
                LocalDateTime.now(),
                TicketStatus.TRANSFERRED.name()
        ));
    }

    /**
     * 推进工单状态，例如开始处理。
     *
     * @param ticketNo 工单编号
     * @param targetStatus 目标状态
     * @return 更新后的工单
     */
    public SupportTicket updateStatus(String ticketNo, String targetStatus) {
        SupportTicket ticket = ticketRepository.mustFind(ticketNo);
        TicketStatus status = parseStatus(targetStatus);
        validateTransition(ticket.status(), status.name());
        return ticketRepository.replace(
                ticketRepository.rebuildWithExistingAssignment(ticket, status.name())
        );
    }

    /**
     * 关闭已处理完成的工单。
     *
     * @param ticketNo 工单编号
     * @return 关闭后的工单
     */
    public SupportTicket close(String ticketNo) {
        SupportTicket ticket = ticketRepository.mustFind(ticketNo);
        assertStatusIn(ticket, "关闭", Set.of(
                TicketStatus.PENDING_PROCESS.name(),
                TicketStatus.PROCESSING.name(),
                TicketStatus.TRANSFERRED.name(),
                TicketStatus.REOPENED.name()
        ));
        return ticketRepository.replace(
                ticketRepository.rebuildWithExistingAssignment(ticket, TicketStatus.CLOSED.name())
        );
    }

    /**
     * 重开已关闭工单。
     *
     * @param ticketNo 工单编号
     * @return 重开后的工单
     */
    public SupportTicket reopen(String ticketNo) {
        SupportTicket ticket = ticketRepository.mustFind(ticketNo);
        assertStatusIn(ticket, "重开", Set.of(TicketStatus.CLOSED.name()));
        return ticketRepository.replace(
                ticketRepository.rebuildWithExistingAssignment(ticket, TicketStatus.REOPENED.name())
        );
    }

    /**
     * Agent 内部自动结单：AI 已完整答复且无需人工介入的会话工单直接关闭，
     * 避免纯自动对话的工单积压在坐席待分派队列。
     *
     * <p>先关闭工单再追加 AI 处理结果正文，两步都落在同一个事务边界内；
     * 处理结果为空时使用默认文案，保证客户侧始终能看到结单说明。</p>
     *
     * @param ticketNo 工单编号
     * @param processingResult AI 自动处理结果说明
     * @return 自动结单后的工单
     */
    public SupportTicket resolveByAi(String ticketNo, String processingResult) {
        SupportTicket ticket = ticketRepository.mustFind(ticketNo);
        assertStatusIn(ticket, "AI 自动结单", Set.of(TicketStatus.PENDING_ASSIGN.name()));
        ticketRepository.replace(
                ticketRepository.rebuildWithExistingAssignment(ticket, TicketStatus.CLOSED.name())
        );
        String merged = ((ticket.content() == null || ticket.content().isBlank()) ? "" : ticket.content() + "\n\n")
                + "AI 自动处理结果：" + (processingResult == null ? "AI 已自动答复" : processingResult);
        jdbcTemplate.update("UPDATE support_ticket SET content = ? WHERE ticket_no = ?", merged, ticketNo);
        return ticketRepository.mustFind(ticketNo);
    }

    /** 解析状态字符串，非法值统一转换为业务异常，避免把 500 暴露给调用方。 */
    private TicketStatus parseStatus(String status) {
        if (status == null || status.isBlank()) {
            throw new IllegalArgumentException("工单状态不能为空");
        }
        try {
            return TicketStatus.valueOf(status.trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("不支持的工单状态：" + status);
        }
    }

    /**
     * 校验普通状态推进是否合法。
     *
     * <p>只放行待处理→处理中、已转派→待处理、已重开→处理中三类流转，
     * 关闭、重开等动作必须走各自的受控入口，防止页面直接跳转破坏生命周期。</p>
     */
    private void validateTransition(String currentStatus, String targetStatus) {
        if (currentStatus.equals(targetStatus)) {
            return;
        }
        if (TicketStatus.PENDING_PROCESS.name().equals(currentStatus)
                && TicketStatus.PROCESSING.name().equals(targetStatus)) {
            return;
        }
        if (TicketStatus.TRANSFERRED.name().equals(currentStatus)
                && TicketStatus.PENDING_PROCESS.name().equals(targetStatus)) {
            return;
        }
        if (TicketStatus.REOPENED.name().equals(currentStatus)
                && TicketStatus.PROCESSING.name().equals(targetStatus)) {
            return;
        }
        throw new IllegalArgumentException("非法工单状态流转：" + currentStatus + " -> " + targetStatus);
    }

    /** 校验当前状态是否属于该动作允许的集合，错误文案保持历史格式。 */
    private void assertStatusIn(SupportTicket ticket, String action, Set<String> allowedStatuses) {
        if (!allowedStatuses.contains(ticket.status())) {
            throw new IllegalArgumentException("当前状态不允许" + action + "：" + ticket.status());
        }
    }
}
