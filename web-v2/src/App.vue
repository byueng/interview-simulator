<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ChevronDown, ChevronRight, CircleAlert, Folder, PanelLeftClose, SendHorizontal, Sparkles, Sword, Wind } from 'lucide-vue-next'

type Mode = 'single' | 'deep'
interface Question { id: string; title: string; module: string; difficulty: string; practiced: boolean; latest_score: number | null }
interface Turn { round_no: number; question: string; answer: string; feedback: string; next_question: string | null; created_at: string }
interface Evaluation { score: number; verdict: string; interviewer_feedback: string; strengths: string[]; issues: string[] }
interface Session { id: string; question_id: string; mode: Mode; title: string; status: 'active' | 'completed'; current_question: string | null; started_at: string; final_score: number | null; final_evaluation: Evaluation | null; turns: Turn[] }
interface SubmitPayload { session: Session; ended: boolean }

const isSidebarCompact = ref(false)
const questions = ref<Question[]>([])
const selectedQuestion = ref<Question | null>(null)
const session = ref<Session | null>(null)
const answer = ref('')
const expandedModules = ref<Record<string, boolean>>({})
const connectionState = ref<'connecting' | 'connected' | 'error'>('connecting')
const errorMessage = ref('')
const isStreaming = ref(false)
const liveFeedback = ref('')
const conversation = ref<HTMLElement | null>(null)

const groupedQuestions = computed(() => {
  const groups = new Map<string, Question[]>()
  for (const question of questions.value) groups.set(question.module, [...(groups.get(question.module) ?? []), question])
  return [...groups.entries()].map(([module, items]) => ({ module, items }))
})
const isActiveSession = computed(() => session.value?.status === 'active')
const activePrompt = computed(() => session.value?.current_question ?? '')

function apiUrl(path: string): string { return `${import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''}${path}` }
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), init)
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail ?? `请求失败（HTTP ${response.status}）`)
  }
  return response.json() as Promise<T>
}
async function refreshLists(): Promise<void> {
  const questionPage = await request<{ items: Question[] }>('/questions?page=1&page_size=100')
  questions.value = questionPage.items
  for (const { module } of groupedQuestions.value) expandedModules.value[module] ??= true
}
async function loadInitialData(): Promise<void> {
  connectionState.value = 'connecting'; errorMessage.value = ''
  await refreshLists(); connectionState.value = 'connected'
}
function selectQuestion(question: Question): void { selectedQuestion.value = question; errorMessage.value = '' }
function toggleModule(module: string): void { expandedModules.value[module] = !expandedModules.value[module] }
async function startSession(mode: Mode): Promise<void> {
  if (!selectedQuestion.value || isStreaming.value) return
  try {
    const created = await request<Session>('/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question_id: selectedQuestion.value.id, mode }) })
    session.value = { ...created, turns: [] }; answer.value = ''; liveFeedback.value = ''; errorMessage.value = ''
    await refreshLists(); await scrollConversation()
  } catch (error) { showError(error) }
}
async function submitAnswer(): Promise<void> {
  const text = answer.value.trim()
  if (!session.value || !isActiveSession.value || !text || isStreaming.value) return
  isStreaming.value = true; liveFeedback.value = ''; errorMessage.value = ''
  try {
    const response = await fetch(apiUrl(`/sessions/${session.value.id}/turns/stream`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answer: text }) })
    if (!response.ok || !response.body) { const body = await response.json().catch(() => null) as { detail?: string } | null; throw new Error(body?.detail ?? '提交回答失败') }
    await consumeSse(response)
  } catch (error) { showError(error) } finally { isStreaming.value = false }
}
function handleAnswerKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void submitAnswer()
}
async function finishSession(): Promise<void> {
  if (!session.value || !isActiveSession.value || isStreaming.value) return
  isStreaming.value = true; liveFeedback.value = ''
  try { applyCompleted(await request<SubmitPayload>(`/sessions/${session.value.id}/finish`, { method: 'POST' })) } catch (error) { showError(error) } finally { isStreaming.value = false }
}
async function consumeSse(response: Response): Promise<void> {
  const reader = response.body?.getReader(); if (!reader) throw new Error('浏览器不支持流式响应')
  const decoder = new TextDecoder(); let buffer = ''
  while (true) {
    const { value, done } = await reader.read(); if (done) break
    buffer += decoder.decode(value, { stream: true }); const messages = buffer.split('\n\n'); buffer = messages.pop() ?? ''
    for (const message of messages) {
      const raw = message.split('\n').find((line) => line.startsWith('data: ')); if (!raw) continue
      const event = JSON.parse(raw.slice(6)) as { event: string; field?: string; text?: string; payload?: SubmitPayload; message?: string }
      if (event.event === 'delta' && (event.field === 'feedback' || event.field === 'interviewer_feedback')) { liveFeedback.value += event.text ?? ''; await scrollConversation() }
      else if (event.event === 'completed' && event.payload) applyCompleted(event.payload)
      else if (event.event === 'error') throw new Error(event.message ?? '模型流式请求失败')
    }
  }
}
function applyCompleted(result: SubmitPayload): void { session.value = result.session; answer.value = ''; liveFeedback.value = ''; void refreshLists().catch(showError); void scrollConversation() }
function showError(error: unknown): void { errorMessage.value = error instanceof Error ? error.message : '发生未知错误'; connectionState.value = 'error' }
async function scrollConversation(): Promise<void> { await nextTick(); conversation.value?.scrollTo({ top: conversation.value.scrollHeight, behavior: 'smooth' }) }
function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }
onMounted(() => { void loadInitialData().catch(showError) })
</script>

<template>
  <main class="app-shell" :class="{ 'sidebar-compact': isSidebarCompact }"><div class="frost-haze" aria-hidden="true" />
    <aside class="archive-panel" aria-label="题库导航">
      <div class="archive-brand"><div class="brand-mark"><Sword :size="17" /></div><div class="brand-copy"><span>INTERVIEW</span><strong>/ 02.0</strong></div><button class="icon-button compact-toggle" type="button" aria-label="收起题库" @click="isSidebarCompact = !isSidebarCompact"><PanelLeftClose :size="17" /></button></div>
      <div class="archive-heading"><span>QUESTION</span><strong>ARCHIVE</strong><em>{{ connectionState === 'connected' ? `${questions.length} QUESTIONS LOADED` : 'LOADING ARCHIVE…' }}</em></div>
      <nav class="folder-list" aria-label="题库">
        <div v-if="connectionState === 'connecting'" class="archive-empty"><Folder :size="16" /><p>正在读取题库</p><span>正在连接本地面试服务。</span></div>
        <div v-else-if="questions.length === 0" class="archive-empty"><Folder :size="16" /><p>题库为空</p><span>请检查 question_bank_path 配置。</span></div>
        <section v-for="group in groupedQuestions" :key="group.module" class="folder-group"><button class="folder-button" type="button" @click="toggleModule(group.module)"><ChevronDown v-if="expandedModules[group.module]" :size="14" /><ChevronRight v-else :size="14" /><Folder :size="14" /><span>{{ group.module }}</span></button><Transition name="archive-fold"><div v-if="expandedModules[group.module]" class="question-list"><button v-for="question in group.items" :key="question.id" class="question-button" :class="{ active: selectedQuestion?.id === question.id }" type="button" @click="selectQuestion(question)"><b>{{ question.id }}</b><span>{{ question.title }}</span></button></div></Transition></section>
      </nav>
    </aside>
    <section class="interview-stage">
      <header class="stage-header"><div class="eyebrow"><Wind :size="14" /> NORTHWIND / INTERVIEW SERVICE</div><div class="header-actions"><span class="status" :class="connectionState"><i />{{ connectionState === 'connected' ? 'API CONNECTED' : connectionState === 'error' ? 'API ERROR' : 'CONNECTING…' }}</span><button class="icon-button" type="button" aria-label="重新加载题库和历史" @click="loadInitialData().catch(showError)"><Sparkles :size="17" /></button></div></header>
      <section class="hero-heading"><p>{{ session ? (session.mode === 'deep' ? 'DEEP INTERVIEW' : 'SINGLE QUESTION') : 'INTERVIEW WORKSPACE' }}</p><div class="question-title"><span>{{ selectedQuestion?.id ?? '—' }}</span><strong>{{ session?.title ?? selectedQuestion?.title ?? '请选择一道题目开始' }}</strong></div><div v-if="selectedQuestion && !session" class="mode-actions"><button type="button" @click="startSession('single')">开始单题评分</button><button type="button" @click="startSession('deep')">开始深入面试</button></div></section>
      <section ref="conversation" class="conversation" aria-label="模拟面试对话">
        <div v-if="!session" class="empty-stage"><p>READY WHEN YOU ARE</p><h2>从左侧选择题目</h2><span>题目、会话记录、AI 追问与评分均从本地 FastAPI 接口获取。</span></div>
        <template v-else><div v-for="turn in session.turns" :key="turn.round_no" class="round-group"><button class="round-toggle" type="button"><span>ROUND / {{ String(turn.round_no).padStart(2, '0') }}</span><small>{{ formatTime(turn.created_at) }}</small></button><div class="round-content"><article class="message"><div class="message-meta"><span>INTERVIEWER</span></div><p>{{ turn.question }}</p></article><article class="message candidate"><div class="message-meta"><span>YOU</span></div><p>{{ turn.answer }}</p></article><article v-if="turn.feedback" class="message"><div class="message-meta"><span>FEEDBACK</span></div><p>{{ turn.feedback }}</p></article></div></div><article v-if="isActiveSession" class="message current-question"><div class="message-meta"><span>INTERVIEWER / CURRENT</span></div><p>{{ activePrompt }}</p></article><div v-if="isStreaming" class="thinking"><span /><span /><span />{{ liveFeedback || '模型正在生成反馈' }}</div><section v-if="session.final_evaluation" class="evaluation-card"><p class="eyebrow">FINAL SCORE / {{ session.final_evaluation.score }} · 10</p><h2>{{ session.final_evaluation.verdict }}</h2><p>{{ session.final_evaluation.interviewer_feedback }}</p><div class="evaluation-columns"><div><h3>做得好</h3><ul><li v-for="item in session.final_evaluation.strengths" :key="item">{{ item }}</li></ul></div><div><h3>需要补强</h3><ul><li v-for="item in session.final_evaluation.issues" :key="item">{{ item }}</li></ul></div></div></section></template>
      </section>
      <form class="composer" @submit.prevent="submitAnswer"><textarea v-model="answer" rows="2" :disabled="!isActiveSession || isStreaming" :placeholder="isActiveSession ? '输入你的回答…' : '选择题目并开始会话后可作答…'" aria-label="输入回答" @keydown="handleAnswerKeydown" /><div class="composer-footer"><span v-if="errorMessage" class="composer-error"><CircleAlert :size="13" />{{ errorMessage }}</span><span v-else-if="isActiveSession">Enter 提交 · Shift + Enter 换行</span><span v-else>SELECT A QUESTION TO BEGIN</span><div class="composer-buttons"><button v-if="session?.mode === 'deep' && isActiveSession" type="button" :disabled="isStreaming" @click="finishSession">结束并评分</button><button type="submit" :disabled="!isActiveSession || isStreaming || !answer.trim()">{{ isStreaming ? 'GENERATING…' : '提交回答' }} <SendHorizontal :size="16" /></button></div></div></form>
    </section>
  </main>
</template>
