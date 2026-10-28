package com.example.business.service;

import com.example.business.entity.SupportTicket;
import com.example.business.entity.TicketStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Set;

/**
 * 工单查询服务，负责工单列表、详情和坐席负载等只读上下文。
 *
 * <p>客户侧与坐席侧的可视范围差异在这里收口：客户只能按自己的 customerId 读取，
 * 普通坐席只能看到本人、未分配以及待分派工单，避免拆分后各入口自行拼权限条件。</p>
 */
@Service
public class TicketQueryService {

    private final JdbcTemplate jdbcTemplate;
    private final TicketRepository ticketRepository;

    public TicketQueryService(JdbcTemplate jdbcTemplate, TicketRepository ticketRepository) {
        this.jdbcTemplate = jdbcTemplate;
        this.ticketRepository = ticketRepository;
    }

    /**
     * 查询全部工单，供内部排查和坐席工作台使用。
     *
     * @return 全部工单记录
     */
    public List<SupportTicket> list() {
        return jdbcTemplate.query(
                """
                SELECT * FROM support_ticket
                ORDER BY updated_at DESC, id DESC
                """,
                TicketRowMappers.SUPPORT_TICKET
        );
    }

    /**
     * 按状态查询工单，供坐席工作台队列筛选。
     *
     * @param statuses 目标状态集合，为空时返回全部工单
     * @return 匹配状态的工单记录
     */
    public List<SupportTicket> listByStatuses(Set<String> statuses) {
        return list().stream()
                .filter(ticket -> statuses == null || statuses.isEmpty() || statuses.contains(ticket.status()))
                .toList();
    }

    /**
     * 查询普通坐席可见工单：自己的工单，以及仍未分配的待分派工单。
     *
     * @param handlerId 当前坐席 ID
     * @param statuses 状态筛选
     * @return 坐席可见工单
     */
    public List<SupportTicket> listVisibleForStaff(Long handlerId, Set<String> statuses) {
        return listByStatuses(statuses).stream()
                .filter(ticket -> handlerId.equals(ticket.handlerId())
                        || ticket.handlerId() == null
                        || TicketStatus.PENDING_ASSIGN.name().equals(ticket.status()))
                .toList();
    }

    /**
     * 查询坐席当前活跃工单，供系统自动派单计算实时负载。
     *
     * @param handlerId 坐席 ID
     * @return 坐席当前未完成工单
     */
    public List<SupportTicket> listActiveTicketsByHandler(Long handlerId) {
        return jdbcTemplate.query(
                """
                SELECT * FROM support_ticket
                WHERE handler_id = ?
                  AND status IN ('PENDING_PROCESS', 'PROCESSING')
                ORDER BY updated_at DESC, id DESC
                """,
                TicketRowMappers.SUPPORT_TICKET,
                handlerId
        );
    }

    /**
     * 查询指定客户的工单列表，客户侧只能看到自己的工单。
     *
     * @param customerId 当前登录客户 ID
     * @return 客户名下工单
     */
    public List<SupportTicket> listByCustomerId(Long customerId) {
        return jdbcTemplate.query(
                """
                SELECT * FROM support_ticket
                WHERE customer_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                TicketRowMappers.SUPPORT_TICKET,
                customerId
        );
    }

    /**
     * 按工单号查询工单详情。
     *
     * @param ticketNo 工单编号
     * @return 工单详情
     */
    public SupportTicket detail(String ticketNo) {
        return ticketRepository.mustFind(ticketNo);
    }

    /**
     * 查询客户自己的工单详情，防止越权读取。
     *
     * <p>归属校验必须在服务层完成，不能依赖前端传入的 customerId；
     * 不属于当前客户时沿用原有业务异常文案。</p>
     *
     * @param ticketNo 工单编号
     * @param customerId 当前客户 ID
     * @return 工单详情
     */
    public SupportTicket detailForCustomer(String ticketNo, Long customerId) {
        SupportTicket ticket = ticketRepository.mustFind(ticketNo);
        if (!customerId.equals(ticket.customerId())) {
            throw new IllegalArgumentException("无权访问该工单：" + ticketNo);
        }
        return ticket;
    }

    /**
     * 统计坐席当前待处理和处理中工单数，用于最少负载派单。
     *
     * @param handlerId 坐席 ID
     * @return 当前活跃负载
     */
    public int countActiveTicketsByHandler(Long handlerId) {
        Integer count = jdbcTemplate.queryForObject(
                """
                SELECT COUNT(*) FROM support_ticket
                WHERE handler_id = ?
                  AND status IN ('PENDING_PROCESS', 'PROCESSING')
                """,
                Integer.class,
                handlerId
        );
        return count == null ? 0 : count;
    }

    /**
     * 查询同一客户最近由坐席处理过的工单，用于熟客优先。
     *
     * @param customerId 客户 ID
     * @param currentTicketNo 当前工单号
     * @return 最近历史工单，没有则返回 null
     */
    public SupportTicket findRecentHandledTicket(Long customerId, String currentTicketNo) {
        List<SupportTicket> result = jdbcTemplate.query(
                """
                SELECT * FROM support_ticket
                WHERE customer_id = ?
                  AND ticket_no <> ?
                  AND handler_id IS NOT NULL
                  AND status IN ('PENDING_PROCESS', 'PROCESSING', 'CLOSED')
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                TicketRowMappers.SUPPORT_TICKET,
                customerId,
                currentTicketNo
        );
        return result.isEmpty() ? null : result.get(0);
    }
}
