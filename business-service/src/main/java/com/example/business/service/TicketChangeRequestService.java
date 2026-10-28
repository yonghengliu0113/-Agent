package com.example.business.service;

import com.example.business.entity.SupportTicket;
import com.example.business.entity.TicketChangeRequest;
import com.example.business.entity.TicketStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

/**
 * 履约变更申请服务，负责已锁定或已关闭工单的改约申请与坐席审核。
 *
 * <p>变更申请以“父工单 + 幂等键”去重，审核同意后才恢复原工单并写入新的履约偏好；
 * 拒绝和补充材料都不会改动原工单，保证历史安排可审计。</p>
 */
@Service
public class TicketChangeRequestService {

    private final JdbcTemplate jdbcTemplate;
    private final TicketRepository ticketRepository;

    public TicketChangeRequestService(JdbcTemplate jdbcTemplate, TicketRepository ticketRepository) {
        this.jdbcTemplate = jdbcTemplate;
        this.ticketRepository = ticketRepository;
    }

    /**
     * 为不可直接修改的履约字段创建或复用变更申请。
     *
     * <p>变更申请以“父工单 + 幂等键”去重，避免客户重复发送或 Agent 重试时产生多条改约任务。</p>
     *
     * @param ticket 原工单
     * @param requestedReturnMethod 申请的新退回方式
     * @param requestedPickupTimeWindow 申请的新取件时间
     * @param idempotencyKey 幂等键
     * @param now 本次操作时间
     * @return 已存在或新建的变更申请
     */
    public TicketChangeRequest createOrReuseChangeRequest(
            SupportTicket ticket,
            String requestedReturnMethod,
            String requestedPickupTimeWindow,
            String idempotencyKey,
            LocalDateTime now
    ) {
        TicketChangeRequest existing = findChangeRequest(ticket.ticketNo(), idempotencyKey);
        if (existing != null) {
            return existing;
        }
        String requestNo = "CR" + now.format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))
                + String.format("%06d", Math.abs(System.nanoTime() % 1_000_000));
        String changeType = requestedPickupTimeWindow != null ? "PICKUP_TIME_CHANGE" : "RETURN_METHOD_CHANGE";
        jdbcTemplate.update(
                """
                INSERT INTO ticket_change_request (
                    request_no, parent_ticket_no, customer_id, external_session_no, change_type,
                    previous_return_method, previous_pickup_time_window,
                    requested_return_method, requested_pickup_time_window,
                    parent_ticket_status, status, idempotency_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(parent_ticket_no, idempotency_key) DO NOTHING
                """,
                requestNo,
                ticket.ticketNo(),
                ticket.customerId(),
                ticket.externalSessionNo(),
                changeType,
                ticket.returnMethod(),
                ticket.pickupTimeWindow(),
                requestedReturnMethod,
                requestedPickupTimeWindow,
                ticket.status(),
                "PENDING_REVIEW",
                idempotencyKey,
                TicketRowMappers.toTimestamp(now),
                TicketRowMappers.toTimestamp(now)
        );
        TicketChangeRequest created = findChangeRequest(ticket.ticketNo(), idempotencyKey);
        if (created == null) {
            throw new IllegalStateException("履约变更申请创建失败");
        }
        return created;
    }

    /**
     * 查询当前客户已提交的同一幂等变更申请。
     *
     * <p>查询条件同时带父工单号和幂等键，避免跨工单或跨客户读取到别人的改约记录。</p>
     *
     * @param ticketNo 父工单编号
     * @param idempotencyKey 幂等键
     * @return 变更申请，不存在时返回 null
     */
    public TicketChangeRequest findChangeRequest(String ticketNo, String idempotencyKey) {
        List<TicketChangeRequest> requests = jdbcTemplate.query(
                """
                SELECT * FROM ticket_change_request
                WHERE parent_ticket_no = ? AND idempotency_key = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                TicketRowMappers.CHANGE_REQUEST,
                ticketNo,
                idempotencyKey
        );
        return requests.isEmpty() ? null : requests.get(0);
    }

    /**
     * 查询某张工单下的履约变更申请。
     * <p>归属校验由 Controller 在调用前完成，避免 Service 混入访问者身份语义。</p>
     *
     * @param ticketNo 父工单编号
     * @return 该工单下的全部变更申请
     */
    public List<TicketChangeRequest> listChangeRequests(String ticketNo) {
        return jdbcTemplate.query(
                """
                SELECT * FROM ticket_change_request
                WHERE parent_ticket_no = ?
                ORDER BY updated_at DESC, id DESC
                """,
                TicketRowMappers.CHANGE_REQUEST,
                ticketNo
        );
    }

    /**
     * 座席审核已锁定或已关闭工单的履约变更。
     * <p>同意后才恢复原工单并写入新的客户偏好；拒绝和补充材料不会改写原工单。</p>
     *
     * @param ticketNo 父工单编号
     * @param requestNo 变更申请编号
     * @param staffId 审核坐席 ID
     * @param decision 审核结论
     * @param customerMessage 给客户的审核说明
     * @return 审核后的变更申请
     */
    public TicketChangeRequest decideChangeRequest(
            String ticketNo,
            String requestNo,
            Long staffId,
            String decision,
            String customerMessage
    ) {
        SupportTicket parentTicket = ticketRepository.mustFind(ticketNo);
        TicketChangeRequest request = findChangeRequestByRequestNo(ticketNo, requestNo);
        if (request == null) {
            throw new IllegalArgumentException("履约变更申请不存在或不属于该工单");
        }
        if (!"PENDING_REVIEW".equals(request.status())) {
            throw new IllegalArgumentException("该履约变更申请当前不可重复审核");
        }

        String normalizedDecision = decision == null ? "" : decision.trim().toUpperCase();
        String normalizedMessage = TicketTextSupport.clean(customerMessage, 500);
        String targetStatus = switch (normalizedDecision) {
            case "APPROVE", "APPROVED" -> "APPROVED";
            case "REJECT", "REJECTED" -> "REJECTED";
            case "NEED_MORE_INFO", "WAITING_CUSTOMER" -> "WAITING_CUSTOMER";
            default -> throw new IllegalArgumentException("不支持的履约变更审核结果");
        };
        LocalDateTime now = LocalDateTime.now();

        // 只有审核同意才允许恢复原工单并应用新的履约偏好，避免客户消息直接覆盖既有安排。
        if ("APPROVED".equals(targetStatus)) {
            String returnMethod = request.requestedReturnMethod() == null
                    ? parentTicket.returnMethod() : request.requestedReturnMethod();
            String pickupTime = "self_ship".equalsIgnoreCase(returnMethod)
                    ? null
                    : (request.requestedPickupTimeWindow() == null
                    ? parentTicket.pickupTimeWindow() : request.requestedPickupTimeWindow());
            String pickupStatus = "self_ship".equalsIgnoreCase(returnMethod)
                    ? "NOT_REQUIRED" : "PREFERENCE_RECORDED";
            String restoredStatus = TicketStatus.CLOSED.name().equals(parentTicket.status())
                    ? TicketStatus.REOPENED.name() : parentTicket.status();
            String audit = "\n\n[履约变更已审核 "
                    + now.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
                    + "] 变更申请：" + request.requestNo()
                    + "；退回方式：" + (returnMethod == null ? "未变更" : returnMethod)
                    + "；取件时间偏好：" + (pickupTime == null ? "不适用" : pickupTime);
            jdbcTemplate.update(
                    """
                    UPDATE support_ticket
                    SET return_method = ?, pickup_time_window = ?, pickup_status = ?,
                        status = ?, content = ?, ai_summary = ?, updated_at = ?
                    WHERE ticket_no = ?
                    """,
                    returnMethod,
                    pickupTime,
                    pickupStatus,
                    restoredStatus,
                    TicketTextSupport.append(parentTicket.content(), audit),
                    TicketTextSupport.append(parentTicket.aiSummary(), audit),
                    TicketRowMappers.toTimestamp(now),
                    ticketNo
            );
        }

        jdbcTemplate.update(
                """
                UPDATE ticket_change_request
                SET status = ?, reviewed_by = ?, customer_message = ?, reviewed_at = ?, updated_at = ?
                WHERE request_no = ? AND parent_ticket_no = ?
                """,
                targetStatus,
                staffId,
                normalizedMessage,
                TicketRowMappers.toTimestamp(now),
                TicketRowMappers.toTimestamp(now),
                requestNo,
                ticketNo
        );
        TicketChangeRequest updated = findChangeRequestByRequestNo(ticketNo, requestNo);
        if (updated == null) {
            throw new IllegalStateException("履约变更审核结果保存失败");
        }
        return updated;
    }

    /** 通过申请编号查找父工单下的子申请，防止跨工单审核。 */
    private TicketChangeRequest findChangeRequestByRequestNo(String ticketNo, String requestNo) {
        List<TicketChangeRequest> requests = jdbcTemplate.query(
                """
                SELECT * FROM ticket_change_request
                WHERE parent_ticket_no = ? AND request_no = ?
                LIMIT 1
                """,
                TicketRowMappers.CHANGE_REQUEST,
                ticketNo,
                requestNo
        );
        return requests.isEmpty() ? null : requests.get(0);
    }
}
