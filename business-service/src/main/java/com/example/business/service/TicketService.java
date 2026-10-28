package com.example.business.service;

import com.example.business.dto.TicketSupplementRequest;
import com.example.business.dto.TicketSupplementResult;
import com.example.business.entity.SupportTicket;
import com.example.business.entity.TicketChangeRequest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Set;

/**
 * 工单服务门面，对外保持工单生命周期的统一入口。
 *
 * <p>原 TicketService 同时承担建单、查询、状态流转、履约补充和变更审核，职责过载。
 * 拆分后本类只做委托，把请求分发给按业务职责内聚的领域服务；
 * TicketController、StaffTicketController、InternalTicketController 的调用签名保持不变，
 * 因此 HTTP 契约、事务边界和异常语义都不受影响。</p>
 */
@Service
public class TicketService {

    private final TicketQueryService ticketQueryService;
    private final TicketCreationService ticketCreationService;
    private final TicketWorkflowService ticketWorkflowService;
    private final TicketSupplementService ticketSupplementService;
    private final TicketUrgeService ticketUrgeService;
    private final TicketChangeRequestService ticketChangeRequestService;

    /**
     * Spring 容器装配入口。
     *
     * <p>表结构初始化也在这里触发，时机与拆分前一致；PostgreSQL 由 Flyway 接管，
     * 初始化器内部会按驱动类型跳过 SQLite 的 DDL。</p>
     */
    @Autowired
    public TicketService(
            TicketQueryService ticketQueryService,
            TicketCreationService ticketCreationService,
            TicketWorkflowService ticketWorkflowService,
            TicketSupplementService ticketSupplementService,
            TicketUrgeService ticketUrgeService,
            TicketChangeRequestService ticketChangeRequestService,
            TicketSchemaInitializer ticketSchemaInitializer
    ) {
        this.ticketQueryService = ticketQueryService;
        this.ticketCreationService = ticketCreationService;
        this.ticketWorkflowService = ticketWorkflowService;
        this.ticketSupplementService = ticketSupplementService;
        this.ticketUrgeService = ticketUrgeService;
        this.ticketChangeRequestService = ticketChangeRequestService;
        ticketSchemaInitializer.initialize();
    }

    /**
     * 非 Spring 场景装配入口，保留既有单元测试和脚本直接 new 的用法。
     *
     * <p>各领域服务共享同一个 JdbcTemplate 与仓储实例，行为与容器装配一致。</p>
     */
    public TicketService(JdbcTemplate jdbcTemplate, String driverClassName) {
        TicketRepository ticketRepository = new TicketRepository(jdbcTemplate);
        TicketQueryService queryService = new TicketQueryService(jdbcTemplate, ticketRepository);
        TicketChangeRequestService changeRequestService =
                new TicketChangeRequestService(jdbcTemplate, ticketRepository);
        this.ticketQueryService = queryService;
        this.ticketCreationService = new TicketCreationService(jdbcTemplate, ticketRepository, queryService);
        this.ticketWorkflowService = new TicketWorkflowService(jdbcTemplate, ticketRepository);
        this.ticketSupplementService = new TicketSupplementService(jdbcTemplate, queryService, changeRequestService);
        this.ticketUrgeService = new TicketUrgeService(jdbcTemplate, queryService);
        this.ticketChangeRequestService = changeRequestService;
        // 单元测试使用内存 SQLite，没有容器生命周期，需要显式补齐本地表结构。
        new TicketSchemaInitializer(jdbcTemplate, driverClassName).initialize();
    }

    /** 查询全部工单，供内部排查和坐席工作台使用。 */
    public List<SupportTicket> list() {
        return ticketQueryService.list();
    }

    /** 按状态查询工单，statuses 为空时返回全部。 */
    public List<SupportTicket> listByStatuses(Set<String> statuses) {
        return ticketQueryService.listByStatuses(statuses);
    }

    /** 查询普通坐席可见工单：本人、未分配以及待分派工单。 */
    public List<SupportTicket> listVisibleForStaff(Long handlerId, Set<String> statuses) {
        return ticketQueryService.listVisibleForStaff(handlerId, statuses);
    }

    /** 查询坐席当前活跃工单，供自动派单计算实时负载。 */
    public List<SupportTicket> listActiveTicketsByHandler(Long handlerId) {
        return ticketQueryService.listActiveTicketsByHandler(handlerId);
    }

    /** 查询指定客户的工单列表，客户侧只能看到自己的工单。 */
    public List<SupportTicket> listByCustomerId(Long customerId) {
        return ticketQueryService.listByCustomerId(customerId);
    }

    /** 创建工单并补齐系统字段，客户归属沿用草稿中的 customerId。 */
    public SupportTicket create(SupportTicket ticket) {
        return ticketCreationService.createForCustomer(ticket, ticket.customerId());
    }

    /** 为当前登录客户创建工单，忽略请求体中可能伪造的 customerId。 */
    public SupportTicket createForCustomer(SupportTicket ticket, Long customerId) {
        return ticketCreationService.createForCustomer(ticket, customerId);
    }

    /**
     * 为人工会话按需创建异步跟进工单，同一会话存在未关闭工单时返回原工单。
     *
     * <p>保留 synchronized 与事务注解，保证并发建单和幂等查询仍在同一临界区内完成。</p>
     */
    @Transactional
    public synchronized SupportTicket createHandoffFollowUp(
            Long customerId,
            String externalSessionNo,
            String title,
            String content,
            String priority
    ) {
        return ticketCreationService.createHandoffFollowUp(
                customerId, externalSessionNo, title, content, priority);
    }

    /** 按工单号查询工单详情。 */
    public SupportTicket detail(String ticketNo) {
        return ticketQueryService.detail(ticketNo);
    }

    /** 查询客户自己的工单详情，防止越权读取。 */
    public SupportTicket detailForCustomer(String ticketNo, Long customerId) {
        return ticketQueryService.detailForCustomer(ticketNo, customerId);
    }

    /** 客户催办自己的工单，写入催办日志并更新催办摘要。 */
    public SupportTicket urgeForCustomer(String ticketNo, Long customerId, String reason) {
        return ticketUrgeService.urgeForCustomer(ticketNo, customerId, reason);
    }

    /**
     * 向客户自己的在途工单追加信息。
     *
     * <p>事务边界仍在本方法入口：补充审计、变更申请和工单正文要么一起成功，要么一起回滚。</p>
     */
    @Transactional
    public TicketSupplementResult appendSupplementForCustomer(
            String ticketNo,
            Long customerId,
            TicketSupplementRequest request,
            String idempotencyKey
    ) {
        return ticketSupplementService.appendSupplementForCustomer(
                ticketNo, customerId, request, idempotencyKey);
    }

    /** 坐席手动领取或分派工单。 */
    public SupportTicket assign(String ticketNo, Long handlerId, String assignedGroup) {
        return ticketWorkflowService.assign(ticketNo, handlerId, assignedGroup);
    }

    /** 根据自动派单决策写入处理人和派单说明。 */
    public SupportTicket assignAutomatically(
            String ticketNo,
            Long handlerId,
            String assignedGroup,
            String assignedBy,
            String assignmentReason,
            Integer assignmentScore
    ) {
        return ticketWorkflowService.assignAutomatically(
                ticketNo, handlerId, assignedGroup, assignedBy, assignmentReason, assignmentScore);
    }

    /** 手动转派工单到其他处理组或处理人。 */
    public SupportTicket transfer(String ticketNo, String assignedGroup, Long handlerId) {
        return ticketWorkflowService.transfer(ticketNo, assignedGroup, handlerId);
    }

    /** 推进工单状态，例如开始处理。 */
    public SupportTicket updateStatus(String ticketNo, String targetStatus) {
        return ticketWorkflowService.updateStatus(ticketNo, targetStatus);
    }

    /** 关闭已处理完成的工单。 */
    public SupportTicket close(String ticketNo) {
        return ticketWorkflowService.close(ticketNo);
    }

    /** 重开已关闭工单。 */
    public SupportTicket reopen(String ticketNo) {
        return ticketWorkflowService.reopen(ticketNo);
    }

    /** Agent 内部自动结单：AI 已完整答复的会话工单直接关闭并写入处理结果。 */
    public SupportTicket resolveByAi(String ticketNo, String processingResult) {
        return ticketWorkflowService.resolveByAi(ticketNo, processingResult);
    }

    /** 统计坐席当前待处理和处理中工单数，用于最少负载派单。 */
    public int countActiveTicketsByHandler(Long handlerId) {
        return ticketQueryService.countActiveTicketsByHandler(handlerId);
    }

    /** 查询同一客户最近由坐席处理过的工单，用于熟客优先。 */
    public SupportTicket findRecentHandledTicket(Long customerId, String currentTicketNo) {
        return ticketQueryService.findRecentHandledTicket(customerId, currentTicketNo);
    }

    /** 查询某张工单下的履约变更申请。 */
    public List<TicketChangeRequest> listChangeRequests(String ticketNo) {
        return ticketChangeRequestService.listChangeRequests(ticketNo);
    }

    /**
     * 座席审核已锁定或已关闭工单的履约变更。
     *
     * <p>事务边界仍在本方法入口：审核结论与原工单恢复必须原子提交。</p>
     */
    @Transactional
    public TicketChangeRequest decideChangeRequest(
            String ticketNo,
            String requestNo,
            Long staffId,
            String decision,
            String customerMessage
    ) {
        return ticketChangeRequestService.decideChangeRequest(
                ticketNo, requestNo, staffId, decision, customerMessage);
    }
}
