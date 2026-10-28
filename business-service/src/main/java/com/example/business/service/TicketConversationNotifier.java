package com.example.business.service;

import com.example.business.entity.SupportTicket;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.Map;

/**
 * 工单状态成功变更后，以最佳努力通知关联的 Agent 客户会话。
 *
 * <p>默认的 JDK HTTP 客户端会向明文 http:// 目标发送 HTTP/2 的 h2c 升级请求，
 * 而 Agent 服务(uvicorn/h11)只支持 HTTP/1.1，会拒绝升级并中断连接，
 * 导致客户会话收不到“工单状态已更新”的系统消息。这里强制 HTTP/1.1 并做一次重试。
 */
@Service
public class TicketConversationNotifier {
    private static final Logger log = LoggerFactory.getLogger(TicketConversationNotifier.class);

    /** 强制 HTTP/1.1 的通知客户端，避免 cleartext h2c 升级被 Agent 服务拒绝。 */
    private final RestClient restClient = RestClient.builder()
            .requestFactory(new JdkClientHttpRequestFactory(
                    HttpClient.newBuilder()
                            .version(HttpClient.Version.HTTP_1_1)
                            .connectTimeout(Duration.ofSeconds(3))
                            .build()))
            .build();
    private final String agentUrl;
    private final String internalSecret;

    public TicketConversationNotifier(
            @Value("${agent.service-url:http://127.0.0.1:8000}") String agentUrl,
            @Value("${agent.internal-secret:enterprise-customer-agent-demo-internal-secret}") String internalSecret) {
        this.agentUrl = agentUrl.replaceAll("/$", "");
        this.internalSecret = internalSecret;
    }

    /**
     * 通知失败不回滚 Java 已落库的真实工单状态；做一次快速重试，仍失败只记录告警。
     * 客户侧仍可通过工单列表/详情接口回源 Java 查看最新状态，不依赖该通知。
     *
     * @param ticket 状态已变更的工单
     */
    public void notifyStatusChanged(SupportTicket ticket) {
        if (ticket.externalSessionNo() == null || ticket.externalSessionNo().isBlank()) return;
        try {
            notifyOnce(ticket);
        } catch (Exception first) {
            // 网络抖动类失败重试一次；重试仍失败仅告警，不阻塞坐席关闭工单的主流程。
            try {
                Thread.sleep(200);
                notifyOnce(ticket);
            } catch (Exception second) {
                log.warn("工单状态会话通知失败(ticket={}, error={})", ticket.ticketNo(), second.getMessage());
            }
        }
    }

    /** 发送一次状态同步请求；4xx/5xx 与网络异常统一抛出，由调用方决定重试与告警。 */
    private void notifyOnce(SupportTicket ticket) {
        restClient.post().uri(agentUrl + "/api/internal/tickets/status-sync")
                .header("X-Agent-Internal-Secret", internalSecret)
                .body(Map.of(
                        "ticketNo", ticket.ticketNo(),
                        "customerId", ticket.customerId(),
                        "externalSessionNo", ticket.externalSessionNo(),
                        "status", ticket.status()))
                .retrieve().toBodilessEntity();
    }
}
