<script setup lang="ts">
import ServiceLoginShell from '@/components/auth/ServiceLoginShell.vue'

/** 客户登录页只配置角色与账号，通用登录交互由共享外壳统一实现。 */
const accounts = [
  { username: 'demo', password: '123456', label: '演示客户' },
  { username: 'buyer', password: '123456', label: '测试买家' }
]
</script>

<template>
  <ServiceLoginShell role="customer" title="客户登录" :accounts="accounts" />
</template>
