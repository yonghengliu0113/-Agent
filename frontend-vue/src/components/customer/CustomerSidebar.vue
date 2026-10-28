<script setup lang="ts">
import {
  Bell,
  ChatDotRound,
  ChatLineRound,
  DArrowLeft,
  DArrowRight,
  Headset,
  HomeFilled,
  MoreFilled,
  Notebook,
  QuestionFilled,
  SwitchButton,
  Tickets,
  UserFilled
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { customerApi } from '@/api/customer'
import { useAuthStore } from '@/stores/auth'
import type { ChatSession, CurrentUser } from '@/types/api'

/**
 * 客户侧主导航。
 *
 * 设计变更（相对改造前）：
 * - 用户信息从顶部移到左下角，符合"账号区固定在最下方"的通行习惯；
 * - 支持整栏折叠为图标栏，折叠状态存 localStorage，刷新后保持；
 * - 去掉品牌与条目上的 emoji，统一用图标组件，减少视觉噪音；
 * - 会话列表在折叠时隐藏，把宽度让给内容区。
 *
 * 对外 props / emits 与改造前完全一致，因此 6 个客户页面无需改动。
 */
const props = defineProps<{
  prototypeUser?: { name: string; level: string; points: string }
  user?: CurrentUser | null
  sessions?: ChatSession[]
  selectedSessionId?: string | null
}>()
const emit = defineEmits<{
  contactService: []
  unavailable: []
  selectSession: [sessionId: string]
  sessionsChanged: [payload: { sessionId: string; deleted: boolean }]
}>()

const router = useRouter()
const auth = useAuthStore()

const COLLAPSE_KEY = 'eca_sidebar_collapsed'
const showAllSessions = ref(false)
const unreadNotifications = ref(0)
/** 折叠状态持久化，避免每次进入页面都要手动收起 */
const collapsed = ref(localStorage.getItem(COLLAPSE_KEY) === '1')
let notificationTimer: number | undefined

const user = computed(
  () => props.prototypeUser || { name: props.user?.display_name || 'Demo Customer', level: '普通客户', points: '—' }
)

type SidebarSession = { title: string; desc: string; time: string; sessionId: string; pinned: boolean }

const sessions = computed<SidebarSession[]>(() => {
  const history =
    props.sessions?.map((session) => ({
      title: session.title || '智能助手',
      desc: session.ai_summary || session.intent || '暂无最新消息',
      time: session.updated_at.slice(5, 16),
      sessionId: session.session_id,
      pinned: Boolean(session.pinned_at)
    })) || []
  // 展开与收起始终复用真实会话数据，默认四条，保证底部用户区位置稳定
  if (history.length) return showAllSessions.value ? history : history.slice(0, 4)
  return []
})

const contextMenu = ref<{ x: number; y: number; session: SidebarSession } | null>(null)

const menuItems = [
  { label: '首页', icon: HomeFilled, path: '/customer' },
  { label: '我的订单', icon: Notebook, path: '/customer/orders' },
  { label: '我的工单', icon: Tickets, path: '/customer/tickets' },
  { label: '智能客服', icon: ChatLineRound, path: '/customer/service' },
  { label: '个人中心', icon: UserFilled, path: '/customer/profile' },
  { label: '帮助中心', icon: QuestionFilled, path: '/customer/help' }
]

/** 侧栏同时服务多个页面，高亮必须由当前路由决定。 */
function isActive(path?: string) {
  return Boolean(path && router.currentRoute.value.path === path)
}

function handleMenu(item: (typeof menuItems)[number]) {
  if (item.path) {
    if (router.currentRoute.value.path !== item.path) void router.push(item.path)
    return
  }
  emit('unavailable')
}

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  try {
    localStorage.setItem(COLLAPSE_KEY, collapsed.value ? '1' : '0')
  } catch {
    /* 存储不可用时仅保留本次会话内的状态 */
  }
}

function openSession(sessionId: string) {
  if (sessionId) emit('selectSession', sessionId)
  else emit('contactService')
}

function toggleAllSessions() {
  showAllSessions.value = !showAllSessions.value
}

async function logout() {
  try {
    await ElMessageBox.confirm('退出后将清除当前浏览器的登录状态，是否继续？', '退出登录', {
      confirmButtonText: '退出登录',
      cancelButtonText: '取消',
      type: 'warning'
    })
    auth.logout()
    ElMessage.success('已退出登录')
    await router.replace('/customer/login')
  } catch (error) {
    // 用户取消退出时保持当前页面和登录态，不额外提示
    if (error !== 'cancel' && error !== 'close') return
  }
}

function openContextMenu(event: MouseEvent, session: SidebarSession) {
  if (!session.sessionId) return
  contextMenu.value = { x: event.clientX, y: event.clientY, session }
}

function closeContextMenu() {
  contextMenu.value = null
}

async function togglePinned(session: SidebarSession) {
  closeContextMenu()
  try {
    await customerApi.setSessionPinned(session.sessionId, !session.pinned)
    ElMessage.success(session.pinned ? '已取消置顶会话' : '已置顶会话')
    emit('sessionsChanged', { sessionId: session.sessionId, deleted: false })
  } catch {
    // 请求拦截器已显示接口错误，侧栏保留当前可见数据
  }
}

async function deleteSession(session: SidebarSession) {
  closeContextMenu()
  try {
    await ElMessageBox.confirm(`确认删除“${session.title}”吗？删除后无法在客户侧恢复。`, '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await customerApi.deleteSession(session.sessionId)
    ElMessage.success('会话已删除')
    emit('sessionsChanged', { sessionId: session.sessionId, deleted: true })
  } catch (error) {
    // 取消确认不提示错误；接口失败由请求拦截器统一反馈
    if (error !== 'cancel' && error !== 'close') return
  }
}

async function loadUnreadNotifications() {
  try {
    unreadNotifications.value = (await customerApi.notificationUnreadCount()).data.count
  } catch {
    // 通知角标失败不影响客户主流程，进入通知页后仍会重新读取权威数据
  }
}

onMounted(() => {
  window.addEventListener('click', closeContextMenu)
  void loadUnreadNotifications()
  notificationTimer = window.setInterval(() => void loadUnreadNotifications(), 30_000)
})

onBeforeUnmount(() => {
  window.removeEventListener('click', closeContextMenu)
  window.clearInterval(notificationTimer)
})
</script>

<template>
  <aside :class="['cx-sidebar', collapsed ? 'is-collapsed' : '']">
    <div class="cx-brand">
      <span class="cx-brand__mark">
        <el-icon><Headset /></el-icon>
      </span>
      <span class="cx-brand__text">智能客服</span>
      <button
        class="ws-iconbtn"
        style="margin-left: auto"
        :title="collapsed ? '展开导航' : '收起导航'"
        :aria-label="collapsed ? '展开导航' : '收起导航'"
        @click.stop="toggleCollapsed"
      >
        <el-icon>
          <DArrowRight v-if="collapsed" />
          <DArrowLeft v-else />
        </el-icon>
      </button>
    </div>

    <nav class="cx-nav">
      <button
        v-for="item in menuItems"
        :key="item.label"
        :class="['cx-nav__item', isActive(item.path) ? 'is-active' : '']"
        :title="collapsed ? item.label : undefined"
        @click="handleMenu(item)"
      >
        <span class="cx-nav__icon"><el-icon><component :is="item.icon" /></el-icon></span>
        <span class="cx-nav__label">{{ item.label }}</span>
      </button>
      <button
        :class="['cx-nav__item', isActive('/customer/notifications') ? 'is-active' : '']"
        :title="collapsed ? '消息通知' : undefined"
        @click="router.push('/customer/notifications')"
      >
        <span class="cx-nav__icon"><el-icon><Bell /></el-icon></span>
        <span class="cx-nav__label">消息通知</span>
        <span v-if="unreadNotifications" class="cx-nav__badge">
          {{ unreadNotifications > 99 ? '99+' : unreadNotifications }}
        </span>
      </button>
    </nav>

    <!-- 会话列表占据剩余空间，用户区因此稳定停在左下角 -->
    <section class="cx-sessions">
      <div class="cx-sessions__head">
        <h2 class="cx-sessions__title">最近会话</h2>
        <button v-if="sessions.length > 4" class="cx-sessions__toggle" @click="toggleAllSessions">
          {{ showAllSessions ? '收起' : '全部' }}
        </button>
      </div>
      <button
        v-for="session in sessions"
        :key="session.sessionId || session.time"
        :class="['cx-session', session.sessionId === selectedSessionId ? 'is-active' : '']"
        @click="openSession(session.sessionId)"
        @contextmenu.prevent="openContextMenu($event, session)"
      >
        <span class="cx-session__dot" />
        <span class="cx-session__body">
          <span class="cx-session__title">
            <el-icon v-if="session.pinned" style="vertical-align: -2px"><ChatDotRound /></el-icon>
            {{ session.title }}
          </span>
          <span class="cx-session__time">{{ session.time }}</span>
        </span>
        <el-icon
          v-if="session.sessionId"
          class="cx-session__more"
          :aria-label="`${session.title} 更多操作`"
          @click.stop="openContextMenu($event, session)"
        >
          <MoreFilled />
        </el-icon>
      </button>
      <p v-if="!sessions.length" class="ws-composer__tip" style="padding: 8px">暂无历史会话</p>
      <button class="cx-nav__item" style="margin-top: 4px" @click="emit('contactService')">
        <span class="cx-nav__icon"><el-icon><Headset /></el-icon></span>
        <span class="cx-nav__label">联系客服</span>
      </button>
    </section>

    <!-- 用户区固定在左下角 -->
    <div class="cx-user">
      <span class="cx-user__avatar">{{ user.name.slice(0, 1) }}</span>
      <span class="cx-user__meta">
        <span class="cx-user__name">{{ user.name }}</span>
        <span class="cx-user__role">{{ user.level }}</span>
      </span>
      <el-tooltip content="退出登录" placement="top">
        <button class="ws-iconbtn" aria-label="退出登录" @click.stop="logout">
          <el-icon><SwitchButton /></el-icon>
        </button>
      </el-tooltip>
    </div>

    <div
      v-if="contextMenu"
      class="prototype-session-menu"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
      role="menu"
      @click.stop
    >
      <button role="menuitem" @click="togglePinned(contextMenu.session)">
        {{ contextMenu.session.pinned ? '取消置顶' : '置顶会话' }}
      </button>
      <button class="danger" role="menuitem" @click="deleteSession(contextMenu.session)">删除会话</button>
    </div>
  </aside>
</template>

<style scoped>
.cx-session__more {
  flex: 0 0 auto;
  margin-top: 4px;
  color: var(--ws-text-3);
  cursor: pointer;
}

.cx-session__more:hover {
  color: var(--ws-text);
}
</style>
