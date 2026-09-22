const state = { questions: [], selected: null, session: null, streaming: false };
const $ = (selector) => document.querySelector(selector);
const elements = {
  status: $("#connection-status"), list: $("#question-list"), empty: $("#empty-state"), interview: $("#interview-state"),
  title: $("#question-title"), meta: $("#question-meta"), mode: $("#mode-label"), transcript: $("#transcript"),
  prompt: $("#prompt-label"), answer: $("#answer"), submit: $("#submit-answer"), finish: $("#finish-session"),
  submitStatus: $("#submit-status"), evaluation: $("#evaluation"), dialog: $("#mode-dialog"), dialogTitle: $("#dialog-question-title"),
};

function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
function setStatus(message, error = false) { elements.status.textContent = message; elements.status.classList.toggle("error", error); }
function sessionPrompt(session) { return session.current_question || session.turns?.at(-1)?.next_question || "请作答"; }
function renderQuestions() {
  elements.list.innerHTML = state.questions.map((question) => `<button class="question-card" data-question-id="${escapeHtml(question.id)}"><strong>${escapeHtml(question.id)} · ${escapeHtml(question.title)}</strong><small>${escapeHtml(question.module)} · ${escapeHtml(question.difficulty)}${question.latest_score != null ? ` · 最近 ${question.latest_score}/10` : ""}${question.practiced ? " · 已练习" : ""}</small></button>`).join("") || "<p>题库为空。</p>";
  elements.list.querySelectorAll("[data-question-id]").forEach((button) => button.addEventListener("click", () => chooseQuestion(button.dataset.questionId)));
}
async function loadQuestions() {
  const response = await fetch("/questions?page=1&page_size=100");
  if (!response.ok) throw new Error("题库加载失败");
  state.questions = (await response.json()).items;
  renderQuestions(); setStatus("本地服务已连接");
}
function chooseQuestion(questionId) {
  state.selected = state.questions.find((question) => question.id === questionId);
  elements.dialogTitle.textContent = state.selected.title;
  elements.dialog.showModal();
}
async function startSession(mode) {
  if (!state.selected) return;
  const response = await fetch("/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question_id: state.selected.id, mode }) });
  if (!response.ok) throw new Error((await response.json()).detail || "创建会话失败");
  state.session = await response.json(); elements.dialog.close(); elements.answer.value = ""; elements.evaluation.hidden = true;
  renderSession(); elements.answer.focus();
}
function turnMarkup(role, text, className = "") { return `<article class="turn ${className}"><span class="role">${role}</span>${escapeHtml(text)}</article>`; }
function renderSession(liveFeedback = "") {
  const session = state.session; if (!session) return;
  elements.empty.hidden = true; elements.interview.hidden = false;
  elements.title.textContent = session.title; elements.meta.textContent = `${state.selected?.module || "技术面试"} · ${state.selected?.difficulty || ""}`; elements.mode.textContent = session.mode === "deep" ? "深入面试" : "单题评分";
  const transcript = [];
  for (const turn of session.turns || []) { transcript.push(turnMarkup("面试问题", turn.question)); transcript.push(turnMarkup("你的回答", turn.answer, "candidate")); if (turn.feedback) transcript.push(turnMarkup("即时反馈", turn.feedback, "feedback")); }
  if (liveFeedback) transcript.push(turnMarkup("正在生成反馈", liveFeedback, "feedback"));
  elements.transcript.innerHTML = transcript.join("");
  const ended = session.status !== "active"; elements.prompt.textContent = sessionPrompt(session); elements.answer.disabled = ended || state.streaming; elements.submit.disabled = ended || state.streaming; elements.finish.disabled = ended || state.streaming;
  elements.submit.textContent = state.streaming ? "生成中…" : "提交回答"; elements.finish.hidden = session.mode !== "deep" || ended;
  if (session.final_evaluation) renderEvaluation(session.final_evaluation);
}
function renderEvaluation(evaluation) {
  const list = (title, items) => items?.length ? `<h3>${title}</h3><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "";
  elements.evaluation.innerHTML = `<p class="eyebrow">最终评分 ${escapeHtml(evaluation.score)} / 10</p><h2>${escapeHtml(evaluation.verdict)}</h2><p>${escapeHtml(evaluation.interviewer_feedback)}</p>${list("做得好", evaluation.strengths)}${list("需要补强", evaluation.issues)}${list("下一次如何升级回答", evaluation.answer_upgrade_suggestions)}${list("建议继续练习", evaluation.follow_up_questions)}`;
  elements.evaluation.hidden = false;
}
async function consumeSse(response) {
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ""; let liveFeedback = "";
  while (true) { const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const messages = buffer.split("\n\n"); buffer = messages.pop();
    for (const message of messages) { const line = message.split("\n").find((item) => item.startsWith("data: ")); if (!line) continue; const event = JSON.parse(line.slice(6));
      if (event.event === "delta") { liveFeedback += event.text; renderSession(liveFeedback); }
      if (event.event === "completed") { state.session = event.payload.session; liveFeedback = ""; elements.answer.value = ""; elements.submitStatus.textContent = event.payload.ended ? "评分已保存到本地记录。" : "已收到下一轮追问。"; renderSession(); await loadQuestions(); }
      if (event.event === "error") throw new Error(event.message || "流式请求失败");
    }
  }
}
async function submitAnswer() {
  const answer = elements.answer.value.trim(); if (!answer || !state.session || state.streaming) return; state.streaming = true; elements.submitStatus.textContent = "模型正在生成反馈…"; renderSession();
  try { const response = await fetch(`/sessions/${state.session.id}/turns/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) }); if (!response.ok) throw new Error((await response.json()).detail || "提交失败"); await consumeSse(response); } finally { state.streaming = false; renderSession(); }
}
async function finishSession() {
  if (!state.session || state.streaming) return; state.streaming = true; elements.submitStatus.textContent = "正在生成最终评分…"; renderSession();
  try { const response = await fetch(`/sessions/${state.session.id}/finish`, { method: "POST" }); if (!response.ok) throw new Error((await response.json()).detail || "结束会话失败"); const result = await response.json(); state.session = result.session; elements.submitStatus.textContent = "评分已保存到本地记录。"; renderSession(); await loadQuestions(); } finally { state.streaming = false; renderSession(); }
}
$("#reload-questions").addEventListener("click", () => loadQuestions().catch(showError)); $("#deep-mode").addEventListener("click", () => startSession("deep").catch(showError)); $("#single-mode").addEventListener("click", () => startSession("single").catch(showError)); elements.submit.addEventListener("click", () => submitAnswer().catch(showError)); elements.finish.addEventListener("click", () => finishSession().catch(showError)); elements.answer.addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); submitAnswer().catch(showError); } });
function showError(error) { state.streaming = false; elements.submitStatus.textContent = error.message || "发生未知错误"; setStatus("本地服务出现错误", true); renderSession(); }
loadQuestions().catch(showError);
