<script setup lang="ts">
import ServiceLoginShell from '@/components/auth/ServiceLoginShell.vue'

/** 客户登录页只配置客户角色和客户自助服务文案，通用登录交互由共享外壳统一实现。 */
const accounts = [
  { username: 'demo', password: '123456', label: '演示客户' },
  { username: 'buyer', password: '123456', label: '测试买家' }
]
</script>

<template>
  <ServiceLoginShell
    role="customer"
    title="客户自助服务"
    workspace-name="货运售后自助服务平台"
    subtitle="7×24 小时货运售后支持，订单、物流与工单进度随时可查"
    capability-text="支持订单与物流查询、售后工单跟踪、在线咨询与帮助中心"
    :accounts="accounts"
    :features="[
      { title: '智能咨询', description: 'AI 智能客服 7×24 小时解答时效与售后问题', icon: 'chat' },
      { title: '售后工单', description: '破损、短少、拒收等异常工单全流程跟踪', icon: 'ticket' },
      { title: '物流查询', description: '订单状态、运输轨迹与签收信息随时可查', icon: 'service' }
    ]"
  />
</template>
