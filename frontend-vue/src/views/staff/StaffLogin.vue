<script setup lang="ts">
import ServiceLoginShell from '@/components/auth/ServiceLoginShell.vue'

/** 坐席登录页使用实际初始化的坐席账号，避免原型账号与 Java 演示数据不一致。 */
const accounts = [
  { username: 'staff', password: '123456', label: '演示坐席' },
  { username: 'staff2', password: '123456', label: '售后坐席' }
]
</script>

<template>
  <ServiceLoginShell role="staff" title="坐席登录" :accounts="accounts" />
</template>
