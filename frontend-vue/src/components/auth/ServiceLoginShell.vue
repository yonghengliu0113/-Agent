<script setup lang="ts">
import {
  ChatDotRound,
  CircleCheckFilled,
  Hide,
  InfoFilled,
  Reading,
  Service,
  Tickets,
  View
} from '@element-plus/icons-vue'
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
  workspaceName: string
  subtitle: string
  capabilityText: string
  accounts: DemoAccount[]
  features: Array<{ title: string; description: string; icon: 'chat' | 'ticket' | 'service' | 'knowledge' }>
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

const loginButtonText = computed(() => props.role === 'customer' ? '立即登录' : '登录工作台')
const homePath = computed(() => props.role === 'customer' ? '/customer' : '/staff')
// 货运平台普遍提供多角色业务入口，这里把客户自助与座席工作台两个登录入口互相连通。
const switchRoleText = computed(() => props.role === 'customer' ? '客服与座席人员' : '客户')
const switchEntryText = computed(() => props.role === 'customer' ? '前往座席端登录' : '前往客户自助服务')
const switchEntryPath = computed(() => props.role === 'customer' ? '/staff/login' : '/customer/login')

// 安全与合规说明只描述系统真实具备的能力（鉴权、脱敏、留痕），不做超出实现的资质承诺。
const trustItems = ['数据脱敏', '权限隔离', '操作留痕']
// 备案与热线均为占位：货运行业页脚必备 ICP 备案、公安备案、客服热线，上线前替换为真实信息。
const compliance = {
  icp: '京ICP备XXXXXXXX号-1',
  police: '京公网安备110105XXXXXXXX号',
  hotline: '400-XXX-XXXX'
}

/** 选择真实存在的演示账号，便于面试或本地演示时快速进入对应角色工作台。 */
function useDemoAccount(account: DemoAccount) {
  form.username = account.username
  form.password = account.password
  ElMessage.success(`已填入${account.label}账号`)
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
    '演示环境暂不提供自助重置密码。请联系管理员重置正式账号，或使用页面展示的演示账号体验系统。',
    '找回密码',
    { confirmButtonText: '我知道了' }
  )
}

function featureIcon(type: string) {
  return { chat: ChatDotRound, ticket: Tickets, service: Service, knowledge: Reading }[type] || CircleCheckFilled
}
</script>

<template>
  <main class="service-login-page" :class="`service-login-page--${role}`">
    <section class="login-brand" aria-label="平台介绍">
      <div class="brand-head">
        <span class="brand-mark" aria-hidden="true"><span class="brand-robot"><i /><i /></span></span>
        <span class="brand-name">智能客服中心</span>
      </div>

      <div class="brand-intro">
        <div class="brand-copy">
          <h1>{{ workspaceName }}</h1>
          <p>{{ capabilityText }}</p>
        </div>

        <ul class="brand-list">
          <li v-for="feature in features" :key="feature.title">
            <el-icon><component :is="featureIcon(feature.icon)" /></el-icon>
            <div><strong>{{ feature.title }}</strong><span>{{ feature.description }}</span></div>
          </li>
        </ul>
      </div>

      <p class="brand-foot">{{ subtitle }}</p>
      <p class="brand-hotline">客服热线 <b>{{ compliance.hotline }}</b></p>
      <ul class="brand-trust">
        <li v-for="item in trustItems" :key="item"><el-icon><CircleCheckFilled /></el-icon>{{ item }}</li>
      </ul>
    </section>

    <section class="login-main">
      <div class="login-column">
        <header class="form-head">
          <h2>{{ title }}</h2>
          <p>欢迎回来，请登录继续使用平台服务</p>
        </header>

        <section class="demo-accounts" aria-label="测试账号">
          <span class="demo-label"><el-icon><InfoFilled /></el-icon>测试账号</span>
          <div class="demo-chips">
            <button v-for="account in accounts" :key="account.username" type="button" @click="useDemoAccount(account)">
              <b>{{ account.username }}</b><em>/</em><span>{{ account.password }}</span>
            </button>
          </div>
        </section>

        <el-form class="login-form" label-position="top" @submit.prevent="handleLogin">
          <el-form-item label="用户名">
            <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名" size="large" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              placeholder="请输入密码"
              size="large"
              @keyup.enter="handleLogin"
            >
              <template #suffix>
                <el-icon
                  class="password-toggle"
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
          </el-form-item>

          <div class="login-options">
            <el-checkbox v-model="remember">记住我</el-checkbox>
            <button type="button" @click="showForgotPassword">忘记密码？</button>
          </div>

          <p class="login-consent">
            登录即代表您已阅读并同意
            <button type="button" @click="showTerms = true">《服务条款》</button>
            与
            <button type="button" @click="showPolicy = true">《隐私政策》</button>
          </p>

          <el-button class="login-submit" :loading="loading" native-type="submit" type="primary">{{ loginButtonText }}</el-button>
          <el-button class="login-guest" text @click="startPreview">访客体验</el-button>
        </el-form>

        <p class="role-switch">{{ switchRoleText }}<router-link :to="switchEntryPath">{{ switchEntryText }}</router-link></p>

        <footer class="login-foot">
          <div class="foot-links">
            <span>© 2026 智能客服中心</span>
            <i />
            <button type="button" @click="showPolicy = true">隐私政策</button>
            <i />
            <button type="button" @click="showTerms = true">服务条款</button>
          </div>
          <p class="foot-filing">
            <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener">{{ compliance.icp }}</a>
            <i />
            <a href="https://beian.gov.cn/" target="_blank" rel="noopener">{{ compliance.police }}</a>
          </p>
        </footer>
      </div>
    </section>

    <el-dialog v-model="showPolicy" title="隐私政策" width="min(520px, calc(100vw - 32px))">
      <p>系统仅在完成登录、会话服务和工单处理所必需的范围内处理账号与业务数据；客户侧不会展示内部风控、工具原始结果或模型提示词。</p>
    </el-dialog>
    <el-dialog v-model="showTerms" title="服务条款" width="min(520px, calc(100vw - 32px))">
      <p>智能客服回复仅作为服务协助。退款、赔付、订单状态变更等业务结果以平台审核和业务系统记录为准。</p>
    </el-dialog>
  </main>
</template>

<style scoped>
/*
 * 登录页设计约束（对齐货运/物流行业实测规范）：
 * 1. 配色锁定单一品牌蓝 #0b66ff（深色品牌区为同色系深藏青），文字链接使用同色加深档 #0a58d8 以满足 AA 对比度。
 * 2. 圆角规则固定为：控件 8px / 标签胶囊 999px / 品牌标识 12px，全页不出现第二套圆角语言。
 * 3. 标题字号封顶 30px：行业登录页标题区间为 24px 至 32px，不使用官网营销页级别的超大标题。
 * 4. 登录页为零动效区：只保留 hover 换色、焦点环与一次性淡入，不做粒子、玻璃拟态和滚动动画。
 * 5. 根类名使用 service-login-page，避免与全局遗留样式 .login-page 的居中内边距冲突。
 */
.service-login-page { --el-color-primary: #0b66ff; --el-border-radius-base: 8px; min-height: 100vh; min-height: 100dvh; display: grid; grid-template-columns: minmax(400px, 44%) minmax(0, 1fr); color: #0f172a; background: #f5f8fd; }

/* 品牌区按“标识 / 居中说明 / 底部标语与合规说明”排布，避免中部出现大片空白。 */
.login-brand { position: relative; display: grid; grid-template-rows: auto 1fr auto auto auto; padding: clamp(32px, 5vw, 64px); overflow: hidden; color: #fff; background: linear-gradient(178deg, #071c3d 0%, #0a2a5e 68%, #0f3576 100%); }
.login-brand::after { position: absolute; right: -160px; bottom: -180px; width: 460px; height: 460px; border-radius: 50%; content: ''; background: radial-gradient(circle, rgb(84 150 240 / 20%), transparent 70%); pointer-events: none; }
.brand-intro { position: relative; z-index: 1; display: grid; gap: 32px; align-self: center; }

.brand-head { position: relative; z-index: 1; display: flex; align-items: center; gap: 12px; }
.brand-mark { display: grid; place-items: center; width: 42px; height: 42px; border: 1px solid rgb(255 255 255 / 24%); border-radius: 12px; background: rgb(255 255 255 / 10%); }
.brand-name { font-size: 17px; font-weight: 600; letter-spacing: .06em; }
.brand-robot { position: relative; display: flex; justify-content: space-around; align-items: center; width: 21px; height: 16px; border: 2px solid #fff; border-radius: 7px; }
.brand-robot::before { position: absolute; top: -7px; left: 50%; width: 2px; height: 5px; margin-left: -1px; background: #fff; content: ''; }
.brand-robot::after { position: absolute; top: -13px; left: 50%; width: 6px; height: 6px; margin-left: -3px; border-radius: 50%; background: #fff; content: ''; }
.brand-robot i { width: 3px; height: 3px; border-radius: 50%; background: #fff; }

.brand-copy { position: relative; z-index: 1; }
.brand-copy h1 { margin: 0; font-size: clamp(23px, 2.1vw, 30px); font-weight: 600; line-height: 1.3; letter-spacing: -.01em; }
.brand-copy p { margin: 14px 0 0; color: #bcd2f2; font-size: 15px; line-height: 1.7; }

.brand-list { position: relative; z-index: 1; display: grid; gap: 18px; margin: 0; padding: 0; list-style: none; }
.brand-list li { display: flex; align-items: flex-start; gap: 12px; }
.brand-list .el-icon { flex: 0 0 auto; margin-top: 2px; color: #7fb2ff; font-size: 18px; }
.brand-list strong { display: block; font-size: 15px; font-weight: 600; }
.brand-list span { display: block; margin-top: 4px; color: #a8c2e8; font-size: 13px; line-height: 1.6; }
.brand-foot { position: relative; z-index: 1; align-self: end; margin: 0; padding-top: 24px; color: #93aed8; font-size: 13px; line-height: 1.6; }

/* 客服热线是货运平台页脚/品牌的必备信息，放在深色品牌区保证辨识度。 */
.brand-hotline { position: relative; z-index: 1; margin: 10px 0 0; color: #93aed8; font-size: 13px; }
.brand-hotline b { color: #fff; font-weight: 600; letter-spacing: .02em; }

/* 合规说明只陈述系统已实现的安全能力，样式与品牌区其他元素保持同一蓝色体系。 */
.brand-trust { position: relative; z-index: 1; display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 0; padding: 0; list-style: none; }
.brand-trust li { display: inline-flex; align-items: center; gap: 5px; padding: 5px 10px; border: 1px solid rgb(255 255 255 / 15%); border-radius: 999px; color: #bcd2f2; font-size: 12px; line-height: 1.2; }
.brand-trust .el-icon { color: #7fb2ff; font-size: 13px; }

.login-main { display: grid; place-items: center; padding: 40px 24px; }
.login-column { width: min(384px, 100%); }
.form-head h2 { margin: 0; font-size: 28px; font-weight: 600; line-height: 1.5; letter-spacing: -.01em; }
.form-head p { margin: 10px 0 0; color: #64748b; font-size: 14px; }

.demo-accounts { margin-top: 26px; }
.demo-label { display: inline-flex; align-items: center; gap: 6px; color: #64748b; font-size: 12px; }
.demo-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.demo-chips button { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border: 1px solid #d7e2f1; border-radius: 999px; background: #fff; color: #334155; font-size: 13px; cursor: pointer; transition: border-color .18s ease, color .18s ease, background-color .18s ease; }
.demo-chips button:hover, .demo-chips button:focus-visible { border-color: #0b66ff; color: #0a58d8; background: #f2f7ff; outline: none; }
.demo-chips b { font-weight: 600; }
.demo-chips em { color: #cbd5e1; font-style: normal; }
.demo-chips span { color: #64748b; }

.login-form { display: grid; gap: 16px; margin-top: 20px; }
.login-form :deep(.el-form-item) { margin-bottom: 0; }
.login-form :deep(.el-form-item__label) { padding-bottom: 6px; color: #475569; font-size: 13px; font-weight: 500; line-height: 1.4; }
.login-form :deep(.el-input__wrapper) { min-height: 48px; padding: 0 14px; border: 1px solid #d7e2f1; border-radius: 8px; background: #fff; box-shadow: none; transition: border-color .18s ease, box-shadow .18s ease; }
.login-form :deep(.el-input__wrapper:hover) { border-color: #b9cdea; }
.login-form :deep(.el-input__wrapper.is-focus) { border-color: #0b66ff; box-shadow: 0 0 0 2px rgb(11 102 255 / 22%); }
.login-form :deep(.el-input__inner) { color: #0f172a; font-size: 16px; }
.login-form :deep(.el-input__inner::placeholder) { color: #6b7a90; }

.password-toggle { color: #64748b; cursor: pointer; outline: none; }
.password-toggle:hover, .password-toggle:focus-visible { color: #0a58d8; }

.login-options { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: -2px; }
.login-options button, .login-foot button { padding: 0; border: 0; background: transparent; color: #0a58d8; font-size: 13px; cursor: pointer; }
.login-options button:hover, .login-foot button:hover { color: #0747b8; text-decoration: underline; text-underline-offset: 3px; }

.login-consent { margin: 0; color: #6b7a90; font-size: 12px; line-height: 1.6; }
.login-consent button { padding: 0; border: 0; background: transparent; color: #0a58d8; font-size: 12px; cursor: pointer; }
.login-consent button:hover { color: #0747b8; text-decoration: underline; text-underline-offset: 3px; }

.login-submit.el-button { width: 100%; height: 50px; margin: 4px 0 0; border: 0; border-radius: 8px; background: #0b66ff; font-size: 18px; font-weight: 600; letter-spacing: .02em; box-shadow: 0 10px 22px rgb(11 102 255 / 20%); transition: background-color .2s ease, box-shadow .2s ease, transform .12s ease; }
.login-submit.el-button:hover, .login-submit.el-button:focus { background: #0757e0; box-shadow: 0 12px 26px rgb(11 102 255 / 26%); }
.login-submit.el-button:active { transform: translateY(1px); box-shadow: none; }
.login-guest.el-button { width: 100%; height: 40px; margin: 0; color: #475569; font-size: 14px; }
.login-guest.el-button:hover, .login-guest.el-button:focus { color: #0a58d8; background: #eef4ff; }

.role-switch { margin: 16px 0 0; color: #64748b; font-size: 13px; text-align: center; }
.role-switch a { margin-left: 6px; color: #0a58d8; font-weight: 500; }
.role-switch a:hover { color: #0747b8; text-decoration: underline; text-underline-offset: 3px; }

.login-foot { display: grid; gap: 8px; justify-items: center; margin-top: 24px; color: #5a6b80; font-size: 12px; }
.foot-links, .foot-filing { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 10px; }
.foot-filing { margin: 0; color: #6b7a90; }
.foot-filing a { color: #6b7a90; text-decoration: none; }
.foot-filing a:hover { color: #0a58d8; text-decoration: underline; text-underline-offset: 3px; }
.login-foot i { width: 1px; height: 11px; background: #dbe4f0; }
.login-foot button { color: #5a6b80; }

/* 登录页不做循环或位移动效，只保留一次性淡入，符合行业“登录页零动效区”的惯例。 */
.brand-head, .brand-intro, .brand-foot, .brand-trust, .login-column { animation: login-fade .4s ease-out both; }
@keyframes login-fade { from { opacity: 0; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; } }

/* 矮屏（1366x768 笔记本、投影等）压缩两侧留白，保证登录页不出现纵向滚动。 */
@media (max-height: 800px) {
  .login-brand { padding: 32px clamp(28px, 4vw, 44px); }
  .brand-intro { gap: 16px; }
  .brand-foot { padding-top: 14px; }
  .login-main { padding: 20px 24px; }
  .demo-accounts { margin-top: 14px; }
  .login-form { gap: 12px; margin-top: 16px; }
  .login-form :deep(.el-input__wrapper) { min-height: 46px; }
  .role-switch { margin-top: 10px; }
  .login-foot { margin-top: 10px; }
}

/* 更矮的窗口再收一档内边距，保证首屏完整可见。 */
@media (max-height: 700px) {
  .login-brand { padding: 24px clamp(24px, 3vw, 36px); }
  .login-main { padding: 16px 24px; }
}

/* 窄屏只保留品牌标识，把首屏空间让给登录操作本身。 */
@media (max-width: 960px) {
  /* align-content: start 阻止品牌行被网格拉伸，避免移动端顶部出现过高色块。 */
  .service-login-page { grid-template-columns: 1fr; align-content: start; }
  .login-brand { display: flex; align-items: center; justify-content: space-between; padding: 20px 24px; }
  .login-brand::after { display: none; }
  .brand-intro, .brand-foot, .brand-trust { display: none; }
  .brand-hotline { margin: 0; font-size: 12px; }
  .brand-mark { width: 36px; height: 36px; border-radius: 10px; }
  .brand-name { font-size: 16px; }
  .login-main { place-items: start center; padding: 36px 20px 56px; }
  .login-column { width: min(420px, 100%); }
}

@media (max-width: 520px) {
  .login-main { padding: 28px 16px 44px; }
  .form-head h2 { font-size: 23px; }
  .login-foot { gap: 8px; }
}

/* 超窄屏优先保证品牌标识完整，隐藏热线避免顶栏换行。 */
@media (max-width: 360px) {
  .brand-hotline { display: none; }
}
</style>
