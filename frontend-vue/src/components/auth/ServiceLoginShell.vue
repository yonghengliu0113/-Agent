<script setup lang="ts">
import { Headset, Hide, Loading, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

type LoginRole = 'customer' | 'staff'

interface DemoAccount {
  username: string
  password: string
  label: string
}

const props = defineProps<{
  role: LoginRole
  title: string
  accounts: DemoAccount[]
}>()

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const remember = ref(true)
const showPassword = ref(false)
const showPolicy = ref(false)
const showTerms = ref(false)
const form = reactive({
  username: props.accounts[0]?.username || '',
  password: props.accounts[0]?.password || ''
})

const homePath = computed(() => (props.role === 'customer' ? '/customer' : '/staff'))
const switchPath = computed(() => (props.role === 'customer' ? '/staff/login' : '/customer/login'))
const switchText = computed(() => (props.role === 'customer' ? '坐席登录' : '客户登录'))

/** 选择演示账号，便于本地演示时快速进入对应角色。 */
function useDemoAccount(account: DemoAccount) {
  form.username = account.username
  form.password = account.password
}

/** 校验账号角色并完成登录；记住我决定 Token 写入 localStorage 还是 sessionStorage。 */
async function handleLogin() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const user = await auth.login(form.username.trim(), form.password, remember.value)
    if (user.role !== props.role) {
      auth.logout()
      ElMessage.error(props.role === 'customer' ? '该账号不是客户账号' : '该账号没有坐席权限')
      return
    }
    await router.push(homePath.value)
  } catch {
    ElMessage.error('登录失败，请检查账号、密码和后端服务状态')
  } finally {
    loading.value = false
  }
}

/** 访客体验仍走真实鉴权，避免未授权访问客户或坐席工作台。 */
async function startPreview() {
  const demo = props.accounts[0]
  if (!demo) return
  useDemoAccount(demo)
  remember.value = false
  await handleLogin()
}

async function showForgotPassword() {
  await ElMessageBox.alert(
    '演示环境暂不提供自助重置密码。请联系管理员重置正式账号，或使用下方演示账号体验系统。',
    '找回密码',
    { confirmButtonText: '我知道了' }
  )
}
</script>

<template>
  <main class="login-stage">
    <!--
      背景为程序化图形（分层径向渐变 + 点阵 + 航线曲线），不是位图素材。
      选择程序化背景的原因：不依赖外部图片请求、可随视口自适应、无版权风险。
    -->
    <svg class="login-stage__art" viewBox="0 0 1200 800" aria-hidden="true" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id="route-line" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#8fb7ff" stop-opacity="0" />
          <stop offset="0.45" stop-color="#8fb7ff" stop-opacity="0.65" />
          <stop offset="1" stop-color="#8fb7ff" stop-opacity="0" />
        </linearGradient>
        <linearGradient id="route-line-2" x1="1" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#7ee0d0" stop-opacity="0" />
          <stop offset="0.5" stop-color="#7ee0d0" stop-opacity="0.4" />
          <stop offset="1" stop-color="#7ee0d0" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path
        d="M-60 610 C 200 540, 300 330, 600 320 S 960 470, 1260 350"
        fill="none"
        stroke="url(#route-line)"
        stroke-width="1.3"
      />
      <path
        d="M-40 250 C 260 200, 420 430, 700 470 S 1010 300, 1240 250"
        fill="none"
        stroke="url(#route-line-2)"
        stroke-width="1.1"
      />
      <path
        d="M120 820 C 260 600, 520 560, 700 640 S 980 800, 1120 860"
        fill="none"
        stroke="url(#route-line)"
        stroke-width="1"
        opacity="0.55"
      />
      <path
        d="M-80 120 C 180 60, 340 260, 520 300 S 760 210, 980 120"
        fill="none"
        stroke="url(#route-line-2)"
        stroke-width="1"
        opacity="0.6"
      />
      <!-- 航线节点：只表达"路径与节点"，不做装饰性散点 -->
      <g fill="#8fb7ff">
        <circle cx="300" cy="330" r="2.6" opacity="0.85" />
        <circle cx="600" cy="320" r="3.4" opacity="0.95" />
        <circle cx="960" cy="470" r="2.6" opacity="0.7" />
        <circle cx="420" cy="430" r="2.2" opacity="0.6" />
      </g>
    </svg>

    <section class="login-card">
      <header class="login-card__head">
        <span class="login-mark" aria-hidden="true">
          <el-icon><Headset /></el-icon>
        </span>
        <span class="login-brand">智能客服中心</span>
      </header>

      <h1 class="login-title">{{ title }}</h1>

      <div class="login-demo" aria-label="演示账号">
        <button
          v-for="account in accounts"
          :key="account.username"
          type="button"
          :title="`使用${account.label}账号`"
          @click="useDemoAccount(account)"
        >
          {{ account.username }}
        </button>
      </div>

      <form class="login-form" @submit.prevent="handleLogin">
        <label class="login-field">
          <span>用户名</span>
          <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名" size="large" />
        </label>
        <label class="login-field">
          <span>密码</span>
          <el-input
            v-model="form.password"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password"
            placeholder="请输入密码"
            size="large"
          >
            <template #suffix>
              <el-icon
                class="login-eye"
                role="button"
                tabindex="0"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                @click.stop="showPassword = !showPassword"
                @keydown.enter="showPassword = !showPassword"
              >
                <View v-if="showPassword" />
                <Hide v-else />
              </el-icon>
            </template>
          </el-input>
        </label>

        <div class="login-row">
          <el-checkbox v-model="remember">记住我</el-checkbox>
          <button type="button" class="login-link" @click="showForgotPassword">忘记密码</button>
        </div>

        <button class="login-submit" type="submit" :disabled="loading">
          <el-icon v-if="loading" class="is-loading"><Loading /></el-icon>
          {{ loading ? '登录中' : '登录' }}
        </button>
      </form>

      <div class="login-actions">
        <button type="button" class="login-link" @click="startPreview">访客体验</button>
        <span class="login-divider" />
        <router-link class="login-link" :to="switchPath">{{ switchText }}</router-link>
      </div>

      <p class="login-consent">
        登录即代表同意
        <button type="button" @click="showTerms = true">《服务条款》</button>
        与
        <button type="button" @click="showPolicy = true">《隐私政策》</button>
      </p>
    </section>

    <el-dialog v-model="showPolicy" title="隐私政策" width="min(520px, calc(100vw - 32px))">
      <p>系统仅在完成登录、会话服务和工单处理所必需的范围内处理账号与业务数据；客户侧不会展示内部风控、工具原始结果或模型提示词。</p>
    </el-dialog>
    <el-dialog v-model="showTerms" title="服务条款" width="min(520px, calc(100vw - 32px))">
      <p>智能客服回复仅作为服务协助。退款、赔付、订单状态变更等业务结果以平台审核和业务系统记录为准。</p>
    </el-dialog>
  </main>
</template>


