package com.example.business.service;

import com.example.business.dto.TicketSupplementRequest;
import com.example.business.dto.TicketSupplementResult;
import com.example.business.entity.SupportTicket;
import com.example.business.entity.TicketChangeRequest;
import com.example.business.entity.TicketStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Set;

/**
 * 客户工单补充服务，负责在途工单的信息追加与履约偏好更新。
 *
 * <p>退货原因等说明始终以审计记录追加；取件方式和取件时间只有在尚未分派且未锁定
 * 履约安排时才直接更新。工单一旦分派给工作人员或进入承运阶段，就只登记变更申请，
 * 避免临近取件时覆盖原安排。</p>
 */
@Service
public class TicketSupplementService {

    /** 只有仍处于待分派阶段的工单才允许直接改写取件偏好。 */
    private static final Set<String> DIRECT_FULFILLMENT_UPDATE_STATUSES = Set.of(
            TicketStatus.PENDING_ASSIGN.name()
    );
    /** 承运已确认、已预约等取件状态视为履约已锁定，后续变更必须走审核。 */
    private static final Set<String> LOCKED_PICKUP_STATUSES = Set.of(
            "CONFIRMED", "SCHEDULED", "COURIER_ASSIGNED", "PICKED_UP", "COMPLETED"
    );

    private final JdbcTemplate jdbcTemplate;
    private final TicketQueryService ticketQueryService;
    private final TicketChangeRequestService ticketChangeRequestService;

    public TicketSupplementService(
            JdbcTemplate jdbcTemplate,
            TicketQueryService ticketQueryService,
            TicketChangeRequestService ticketChangeRequestService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.ticketQueryService = ticketQueryService;
        this.ticketChangeRequestService = ticketChangeRequestService;
    }

    /**
     * 向客户自己的在途工单追加退货信息，并依据履约阶段决定是否允许直接修改取件偏好。
     *
     * <p>幂等键写入 ticket_supplement 的唯一约束，Worker 重试命中同一键时只返回已有结果，
     * 不会重复追加正文或重复修改履约字段。已关闭工单只允许生成独立变更申请。</p>
     *
     * @param ticketNo 工单编号
     * @param customerId 登录态客户 ID
     * @param request 客户补充内容
     * @param idempotencyKey 本次追加幂等键
     * @return 追加结果和最新工单
     */
    public TicketSupplementResult appendSupplementForCustomer(
            String ticketNo,
            Long customerId,
            TicketSupplementRequest request,
            String idempotencyKey
    ) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            throw new IllegalArgumentException("追加工单信息必须提供 Idempotency-Key");
        }
        SupportTicket ticket = ticketQueryService.detailForCustomer(ticketNo, customerId);

        String content = TicketTextSupport.clean(request == null ? null : request.content(), 1000);
        String reason = TicketTextSupport.clean(request == null ? null : request.afterSaleReason(), 500);
        String returnMethod = TicketTextSupport.clean(request == null ? null : request.returnMethod(), 32);
        String pickupTimeWindow = TicketTextSupport.clean(request == null ? null : request.pickupTimeWindow(), 128);
        if (content == null && reason == null && returnMethod == null && pickupTimeWindow == null) {
            throw new IllegalArgumentException("没有可追加的工单信息");
        }

        String existingContent = (ticket.content() == null ? "" : ticket.content())
                + "\n" + (ticket.aiSummary() == null ? "" : ticket.aiSummary());
        boolean reasonIsNew = reason != null
                && !existingContent.contains("after_sale_reason: " + reason)
                && !existingContent.contains("退货原因：" + reason);
        boolean contentIsNew = content != null && !existingContent.contains(content);
        boolean returnMethodChanged = returnMethod != null && !returnMethod.equalsIgnoreCase(
                ticket.returnMethod() == null ? "" : ticket.returnMethod()
        );
        boolean pickupTimeChanged = pickupTimeWindow != null && !pickupTimeWindow.equals(
                ticket.pickupTimeWindow() == null ? "" : ticket.pickupTimeWindow()
        );
        boolean fulfillmentChangeRequested = returnMethodChanged || pickupTimeChanged;
        boolean fulfillmentLocked = ticket.pickupStatus() != null
                && LOCKED_PICKUP_STATUSES.contains(ticket.pickupStatus().trim().toUpperCase());
        // 只有待分派且取件安排未锁定时才允许直接落库，其余阶段一律转为待审核申请。
        boolean fulfillmentUpdated = fulfillmentChangeRequested
                && DIRECT_FULFILLMENT_UPDATE_STATUSES.contains(ticket.status())
                && !fulfillmentLocked;
        // 已关闭工单只能生成独立的履约变更申请，普通补充不允许改写历史工单。
        boolean changeRequestRequired = fulfillmentChangeRequested && !fulfillmentUpdated;
        if (TicketStatus.CLOSED.name().equals(ticket.status()) && !changeRequestRequired) {
            throw new IllegalArgumentException("已关闭工单仅支持提交取件方式或取件时间变更申请");
        }
        boolean hasNewInformation = reasonIsNew || contentIsNew || fulfillmentChangeRequested;
        String updateMode = !hasNewInformation
                ? "UNCHANGED"
                : (changeRequestRequired ? "REVIEW_REQUIRED" : "APPLIED");

        LocalDateTime now = LocalDateTime.now();
        String normalizedKey = idempotencyKey.trim();
        // 依靠唯一约束做幂等：重复键插入 0 行，后续只读取已有审计结果。
        int inserted = jdbcTemplate.update(
                """
                INSERT INTO ticket_supplement (
                    ticket_no, customer_id, idempotency_key, content, after_sale_reason,
                    requested_return_method, requested_pickup_time_window, update_mode, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticket_no, idempotency_key) DO NOTHING
                """,
                ticketNo,
                customerId,
                normalizedKey,
                content,
                reason,
                returnMethod,
                pickupTimeWindow,
                updateMode,
                TicketRowMappers.toTimestamp(now)
        );
        if (inserted == 0) {
            // Worker 重试命中同一幂等键时只返回已有结果，不重复追加正文或重复修改履约字段。
            String existingMode = jdbcTemplate.queryForObject(
                    "SELECT update_mode FROM ticket_supplement WHERE ticket_no = ? AND idempotency_key = ?",
                    String.class,
                    ticketNo,
                    normalizedKey
            );
            String resolvedMode = existingMode == null ? "APPLIED" : existingMode;
            return new TicketSupplementResult(
                    ticketQueryService.detailForCustomer(ticketNo, customerId),
                    resolvedMode,
                    "APPLIED".equals(resolvedMode) && fulfillmentChangeRequested,
                    true,
                    ticketChangeRequestService.findChangeRequest(ticketNo, normalizedKey)
            );
        }

        if ("UNCHANGED".equals(updateMode)) {
            // 完全重复的业务信息只留下幂等审计，不改写工单正文和更新时间。
            return new TicketSupplementResult(ticket, updateMode, false, false, null);
        }

        TicketChangeRequest changeRequest = changeRequestRequired
                ? ticketChangeRequestService.createOrReuseChangeRequest(
                        ticket, returnMethod, pickupTimeWindow, normalizedKey, now)
                : null;
        if (TicketStatus.CLOSED.name().equals(ticket.status())) {
            // 已关闭工单只新增子申请与审计记录，绝不改写原工单内容、状态或履约字段。
            return new TicketSupplementResult(ticket, updateMode, false, false, changeRequest);
        }

        String supplementSummary = buildSupplementSummary(
                contentIsNew ? content : null,
                reasonIsNew ? reason : null,
                returnMethodChanged ? returnMethod : null,
                pickupTimeChanged ? pickupTimeWindow : null,
                updateMode
        );
        String marker = "\n\n[客户补充 " + now.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")) + "] ";
        String updatedContent = TicketTextSupport.append(ticket.content(), marker + supplementSummary);
        String updatedAiSummary = TicketTextSupport.append(ticket.aiSummary(), marker + supplementSummary);

        String updatedReturnMethod = ticket.returnMethod();
        String updatedPickupTimeWindow = ticket.pickupTimeWindow();
        String updatedPickupStatus = ticket.pickupStatus();
        if (fulfillmentUpdated) {
            if (returnMethod != null) {
                updatedReturnMethod = returnMethod;
            }
            if ("self_ship".equalsIgnoreCase(updatedReturnMethod)) {
                // 改为自行寄回后清除旧取件时间，避免坐席继续按已取消的上门偏好处理。
                updatedPickupTimeWindow = null;
                updatedPickupStatus = "NOT_REQUIRED";
            } else {
                if (pickupTimeWindow != null) {
                    updatedPickupTimeWindow = pickupTimeWindow;
                }
                updatedPickupStatus = "PREFERENCE_RECORDED";
            }
        }

        jdbcTemplate.update(
                """
                UPDATE support_ticket
                SET content = ?, ai_summary = ?, return_method = ?, pickup_time_window = ?,
                    pickup_status = ?, updated_at = ?
                WHERE ticket_no = ? AND customer_id = ?
                """,
                updatedContent,
                updatedAiSummary,
                updatedReturnMethod,
                updatedPickupTimeWindow,
                updatedPickupStatus,
                TicketRowMappers.toTimestamp(now),
                ticketNo,
                customerId
        );
        return new TicketSupplementResult(
                ticketQueryService.detailForCustomer(ticketNo, customerId),
                updateMode,
                fulfillmentUpdated,
                false,
                changeRequest
        );
    }

    /** 组装写入工单正文的审计摘要，只包含本轮真正新增或变更的字段。 */
    private String buildSupplementSummary(
            String content,
            String reason,
            String returnMethod,
            String pickupTimeWindow,
            String updateMode
    ) {
        StringBuilder summary = new StringBuilder();
        if (reason != null) {
            summary.append("退货原因：").append(reason).append("；");
        }
        if (content != null) {
            summary.append("客户说明：").append(content).append("；");
        }
        if (returnMethod != null) {
            summary.append("申请退回方式：").append(returnMethod).append("；");
        }
        if (pickupTimeWindow != null) {
            summary.append("申请取件时间：").append(pickupTimeWindow).append("；");
        }
        if ("REVIEW_REQUIRED".equals(updateMode)) {
            summary.append("履约变更需人工确认，原安排暂不覆盖；");
        }
        return summary.toString();
    }
}
