package com.example.business.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * 本地工单库表结构初始化器。
 *
 * <p>SQLite 本地开发库没有 Flyway 迁移，启动时需要按幂等方式补齐表、索引和增量列；
 * PostgreSQL 的结构由 src/main/resources/db/migration 下的脚本管理，必须跳过这里的 DDL。</p>
 */
@Component
public class TicketSchemaInitializer {

    private final JdbcTemplate jdbcTemplate;
    private final String driverClassName;

    public TicketSchemaInitializer(
            JdbcTemplate jdbcTemplate,
            @Value("${spring.datasource.driver-class-name:org.sqlite.JDBC}") String driverClassName
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.driverClassName = driverClassName;
    }

    /**
     * 按数据库类型初始化表结构。
     *
     * <p>只有非 PostgreSQL 的本地库才执行 SQLite 语法；判断逻辑保持与拆分前一致，
     * 防止在生产库执行 AUTOINCREMENT/PRAGMA 兼容逻辑。</p>
     */
    public void initialize() {
        // PostgreSQL 由 Flyway 管理结构，禁止执行 SQLite 的 AUTOINCREMENT/PRAGMA 兼容逻辑。
        if (!driverClassName.toLowerCase().contains("postgresql")) {
            initTables();
        }
    }

    /** 创建工单、催办、补充审计和履约变更申请四张表及本地索引。 */
    private void initTables() {
        jdbcTemplate.execute(
                """
                CREATE TABLE IF NOT EXISTS support_ticket (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_no VARCHAR(64) UNIQUE,
                    title VARCHAR(128),
                    ticket_type VARCHAR(64),
                    priority VARCHAR(32),
                    customer_id BIGINT NOT NULL,
                    order_no VARCHAR(64),
                    session_id BIGINT,
                    external_session_no VARCHAR(64),
                    content CLOB,
                    ai_summary CLOB,
                    return_method VARCHAR(32),
                    pickup_time_window VARCHAR(128),
                    pickup_status VARCHAR(32),
                    assigned_group VARCHAR(128),
                    handler_id BIGINT,
                    assigned_by VARCHAR(32),
                    assignment_reason CLOB,
                    assignment_score INTEGER,
                    assigned_at TIMESTAMP,
                    status VARCHAR(32) NOT NULL,
                    sla_deadline TIMESTAMP,
                    source VARCHAR(64),
                    urge_count INTEGER DEFAULT 0,
                    last_urged_at TIMESTAMP,
                    last_urge_reason CLOB,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """
        );
        jdbcTemplate.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_urge_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_no VARCHAR(64) NOT NULL,
                    customer_id BIGINT NOT NULL,
                    reason CLOB,
                    created_at TIMESTAMP NOT NULL
                )
                """
        );
        jdbcTemplate.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_supplement (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_no VARCHAR(64) NOT NULL,
                    customer_id BIGINT NOT NULL,
                    idempotency_key VARCHAR(128) NOT NULL,
                    content CLOB,
                    after_sale_reason VARCHAR(500),
                    requested_return_method VARCHAR(32),
                    requested_pickup_time_window VARCHAR(128),
                    update_mode VARCHAR(32) NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    UNIQUE(ticket_no, idempotency_key)
                )
                """
        );
        jdbcTemplate.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_change_request (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_no VARCHAR(64) NOT NULL UNIQUE,
                    parent_ticket_no VARCHAR(64) NOT NULL,
                    customer_id BIGINT NOT NULL,
                    external_session_no VARCHAR(128),
                    change_type VARCHAR(32) NOT NULL,
                    previous_return_method VARCHAR(32),
                    previous_pickup_time_window VARCHAR(128),
                    requested_return_method VARCHAR(32),
                    requested_pickup_time_window VARCHAR(128),
                    parent_ticket_status VARCHAR(32) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    idempotency_key VARCHAR(128) NOT NULL,
                    reviewed_by BIGINT,
                    customer_message VARCHAR(500),
                    reviewed_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    UNIQUE(parent_ticket_no, idempotency_key)
                )
                """
        );
        jdbcTemplate.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ticket_urge_log_ticket_created
                ON ticket_urge_log(ticket_no, created_at)
                """
        );
        jdbcTemplate.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ticket_supplement_ticket_created
                ON ticket_supplement(ticket_no, created_at)
                """
        );
        jdbcTemplate.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ticket_change_request_parent_updated
                ON ticket_change_request(parent_ticket_no, updated_at)
                """
        );
        jdbcTemplate.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_support_ticket_customer_updated
                ON support_ticket(customer_id, updated_at)
                """
        );
        jdbcTemplate.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_support_ticket_status_updated
                ON support_ticket(status, updated_at)
                """
        );
        jdbcTemplate.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_support_ticket_external_session
                ON support_ticket(external_session_no)
                """
        );
        ensureColumn("assigned_by", "VARCHAR(32)");
        ensureColumn("assignment_reason", "CLOB");
        ensureColumn("assignment_score", "INTEGER");
        ensureColumn("assigned_at", "TIMESTAMP");
        ensureColumn("urge_count", "INTEGER DEFAULT 0");
        ensureColumn("last_urged_at", "TIMESTAMP");
        ensureColumn("last_urge_reason", "CLOB");
        // 旧版 SQLite 数据库启动时补齐退货履约字段，避免要求开发者手工重建数据库。
        ensureColumn("return_method", "VARCHAR(32)");
        ensureColumn("pickup_time_window", "VARCHAR(128)");
        ensureColumn("pickup_status", "VARCHAR(32)");
        // SQLite 本地开发库也需要补齐子申请审核字段，避免升级后读取旧表时报列不存在。
        ensureChangeRequestColumn("reviewed_by", "BIGINT");
        ensureChangeRequestColumn("customer_message", "VARCHAR(500)");
        ensureChangeRequestColumn("reviewed_at", "TIMESTAMP");
    }

    /** 按 PRAGMA 检查并补齐 support_ticket 的增量列，保证旧库可直接升级。 */
    private void ensureColumn(String columnName, String columnType) {
        Boolean exists = jdbcTemplate.query(
                "PRAGMA table_info(support_ticket)",
                rs -> {
                    while (rs.next()) {
                        if (columnName.equalsIgnoreCase(rs.getString("name"))) {
                            return true;
                        }
                    }
                    return false;
                }
        );
        if (!Boolean.TRUE.equals(exists)) {
            jdbcTemplate.execute("ALTER TABLE support_ticket ADD COLUMN " + columnName + " " + columnType);
        }
    }

    /** 为本地 SQLite 的履约变更申请表补齐增量审核字段。 */
    private void ensureChangeRequestColumn(String columnName, String columnType) {
        Boolean exists = jdbcTemplate.query(
                "PRAGMA table_info(ticket_change_request)",
                rs -> {
                    while (rs.next()) {
                        if (columnName.equalsIgnoreCase(rs.getString("name"))) {
                            return true;
                        }
                    }
                    return false;
                }
        );
        if (!Boolean.TRUE.equals(exists)) {
            jdbcTemplate.execute("ALTER TABLE ticket_change_request ADD COLUMN " + columnName + " " + columnType);
        }
    }
}
