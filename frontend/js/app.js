/* PromptSutra AI frontend — vanilla JS, same-origin FastAPI JSON API. */
const $ = (id) => document.getElementById(id);
const state = { user: null, config: null, csrf: '', conversations: [], currentId: null,
  messages: [], prompts: [], currentPrompt: null, busy: false, editMode: false, section: 'chat' };

const toast = (message) => {
  const el = $('toast'); el.textContent = message; el.classList.add('show');
  clearTimeout(window.__toastTimer); window.__toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
};

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && typeof options.body !== 'string') {
    headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body);
  }
  if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  let response;
  try { response = await fetch('/api' + path, { credentials: 'same-origin', ...options, headers }); }
  catch { throw new Error('Network error. Is the Python server running?'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
  return data;
}
function setBusy(busy) {
  state.busy = busy;
  ['send-button','generate-button','new-chat'].forEach((id) => { $(id).disabled = busy; });
  $('send-button').textContent = busy ? '⋯' : '↑';
  $('generate-button').innerHTML = busy ? '✦ Working...' : '✦ <span>Generate Prompt</span>';
}
function showAuth() { $('auth-screen').hidden = false; $('workspace').hidden = true; }
function showWorkspace() { $('auth-screen').hidden = true; $('workspace').hidden = false;
  $('profile-name').textContent = state.user.name; $('profile-email').textContent = state.user.email;
  $('avatar').textContent = (state.user.name || 'U')[0].toUpperCase(); }

async function bootstrap() {
  try {
    const token = await api('/auth/csrf'); state.csrf = token.token;
    state.config = await api('/config');
    $('api-status').textContent = state.config.gemini_configured ? '● Gemini configured' : '● Add Gemini API key';
    $('api-status').classList.toggle('bad', !state.config.gemini_configured);
    $('google-login').disabled = !state.config.google_login_enabled;
    $('google-login').title = state.config.google_login_enabled ? 'Continue with Google' : 'Set up Firebase in .env to enable Google login';
    $('auth-note').textContent = state.config.email_mode === 'development-console'
      ? 'Local test mode: OTP will appear in the Python terminal (not in Gmail).'
      : '';
    try {
      const me = await api('/auth/me'); state.user = me.user;
      showWorkspace(); await refreshConversations();
      if (state.conversations.length) await openConversation(state.conversations[0].id);
    } catch { showAuth(); }
  } catch (error) { toast(error.message); }
}

$('email-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('email-submit'); button.disabled = true;
  try {
    const email = $('email-input').value.trim();
    const data = await api('/auth/email/request', { method: 'POST', body: { email } });
    $('email-form').hidden = true; $('otp-form').hidden = false;
    $('auth-note').textContent = data.message;
    $('otp-input').focus(); toast(data.message);
  } catch (error) { toast(error.message); } finally { button.disabled = false; }
});
$('back-email').addEventListener('click', () => { $('otp-form').hidden = true; $('email-form').hidden = false; });
$('otp-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const result = await api('/auth/email/verify', { method: 'POST', body: { email: $('email-input').value.trim(), otp: $('otp-input').value.trim() } });
    state.user = result.user; showWorkspace(); await refreshConversations();
    $('otp-input').value = ''; toast('Welcome to PromptSutra AI!');
  } catch (error) { toast(error.message); }
});
$('google-login').addEventListener('click', async () => {
  if (!state.config?.google_login_enabled) return toast('Configure Firebase to activate Google Sign-In.');
  try {
    const [{ initializeApp }, { getAuth, GoogleAuthProvider, signInWithPopup, signOut }] = await Promise.all([
      import('https://www.gstatic.com/firebasejs/13.1.0/firebase-app.js'),
      import('https://www.gstatic.com/firebasejs/13.1.0/firebase-auth.js')
    ]);
    const auth = getAuth(initializeApp(state.config.firebase));
    const credential = await signInWithPopup(auth, new GoogleAuthProvider());
    const id_token = await credential.user.getIdToken();
    const data = await api('/auth/google', { method: 'POST', body: { id_token } });
    await signOut(auth); // Our own secured server cookie is the authenticated session.
    state.user = data.user; showWorkspace(); await refreshConversations(); toast('Google sign-in successful!');
  } catch (error) { toast(error.message || 'Google sign-in failed.'); }
});
$('sign-out').addEventListener('click', async () => {
  try { await api('/auth/logout', { method: 'POST' }); } catch (error) { toast(error.message); }
  state.user = null; state.currentId = null; state.messages = []; state.currentPrompt = null;
  $('otp-form').hidden = true; $('email-form').hidden = false; showAuth();
});

function closeSidebar() { $('sidebar').classList.remove('open'); $('mobile-scrim').hidden = true; }
$('open-sidebar').addEventListener('click', () => { $('sidebar').classList.add('open'); $('mobile-scrim').hidden = false; });
$('close-sidebar').addEventListener('click', closeSidebar);
$('mobile-scrim').addEventListener('click', closeSidebar);

function showSection(section) {
  state.section = section; $('chat-view').hidden = section !== 'chat'; $('library-view').hidden = section !== 'library';
  $('nav-chat').classList.toggle('active', section === 'chat'); $('nav-library').classList.toggle('active', section === 'library');
  $('page-name').textContent = section === 'chat' ? 'AI Prompt Builder' : 'Prompt Library'; closeSidebar();
}
$('nav-chat').addEventListener('click', () => showSection('chat'));
$('nav-library').addEventListener('click', async () => { showSection('library'); await refreshPrompts(); });
$('library-create').addEventListener('click', newChat);
$('new-chat').addEventListener('click', newChat);
$('refresh-history').addEventListener('click', refreshConversations);

function newChat() {
  if (state.busy) return;
  state.currentId = null; state.messages = []; $('messages').replaceChildren();
  $('welcome').hidden = false; $('chat-ready').textContent = ''; $('chat-error').hidden = true;
  $('category-select').disabled = false; showSection('chat'); renderConversations(); $('chat-input').focus();
}
async function refreshConversations() {
  try { state.conversations = (await api('/conversations')).conversations; renderConversations(); }
  catch (error) { toast(error.message); }
}
function renderConversations() {
  const list = $('history-list'); list.replaceChildren();
  if (!state.conversations.length) { const empty = document.createElement('div'); empty.className = 'hint-text'; empty.textContent = 'Your chats will appear here.'; list.append(empty); }
  for (const c of state.conversations) {
    const row = document.createElement('div'); row.className = 'history-item' + (c.id === state.currentId ? ' active' : '');
    const open = document.createElement('button'); open.className = 'history-open'; open.title = c.title;
    const bullet = document.createElement('span'); bullet.textContent = '◌';
    const title = document.createElement('span'); title.textContent = c.title;
    open.append(bullet, title); open.addEventListener('click', () => openConversation(c.id));
    const del = document.createElement('button'); del.className = 'history-delete'; del.title = 'Delete chat'; del.setAttribute('aria-label', 'Delete conversation'); del.textContent = '×';
    del.addEventListener('click', async () => {
      if (!confirm('Delete this conversation and its generated prompts?')) return;
      try { await api(`/conversations/${encodeURIComponent(c.id)}`, { method: 'DELETE' });
        if (state.currentId === c.id) newChat(); await refreshConversations(); toast('Conversation deleted.'); }
      catch (error) { toast(error.message); }
    });
    row.append(open, del); list.append(row);
  }
}
async function openConversation(id) {
  if (state.busy) return;
  try {
    const result = await api(`/conversations/${encodeURIComponent(id)}`);
    state.currentId = id; state.messages = result.messages;
    $('category-select').value = result.conversation.category;
    $('category-select').disabled = true;
    $('chat-ready').textContent = result.conversation.ready ? '✓ Ready to generate' : '';
    $('chat-error').hidden = true; $('welcome').hidden = state.messages.length > 0;
    $('messages').replaceChildren(); state.messages.forEach(renderMessage);
    showSection('chat'); renderConversations(); scrollBottom();
  } catch (error) { toast(error.message); }
}
function scrollBottom() { requestAnimationFrame(() => { $('chat-scroll').scrollTop = $('chat-scroll').scrollHeight; }); }
function renderMessage(message) {
  const row = document.createElement('div'); row.className = `message ${message.role === 'user' ? 'user' : 'assistant'}`;
  if (message.role !== 'user') {
    const avatar = document.createElement('span'); avatar.className = 'message-avatar'; avatar.textContent = '✦'; row.append(avatar);
  }
  const bubble = document.createElement('div'); bubble.className = 'bubble';
  if (message.role !== 'user') { const title = document.createElement('div'); title.className = 'message-bot-label'; title.textContent = 'PromptSutra AI'; bubble.append(title); }
  const content = document.createElement('div'); content.textContent = message.content; bubble.append(content); row.append(bubble);
  $('messages').append(row); scrollBottom();
}
function renderThinking() {
  const row = document.createElement('div'); row.className = 'message assistant'; row.id = 'thinking-row';
  const avatar = document.createElement('span'); avatar.className = 'message-avatar'; avatar.textContent = '✦';
  const bubble = document.createElement('div'); bubble.className = 'bubble thinking'; bubble.textContent = 'Understanding your requirements';
  row.append(avatar, bubble); $('messages').append(row); scrollBottom();
}
async function sendMessage(message) {
  const content = message.trim(); if (!content || state.busy) return;
  $('chat-error').hidden = true; setBusy(true);
  try {
    if (!state.currentId) {
      const response = await api('/conversations', { method: 'POST', body: { category: $('category-select').value } });
      state.currentId = response.conversation.id; $('category-select').disabled = true;
    }
    $('welcome').hidden = true; $('chat-input').value = ''; $('char-count').textContent = '0 / 4000';
    renderMessage({ role: 'user', content }); renderThinking();
    const result = await api(`/conversations/${encodeURIComponent(state.currentId)}/messages`, { method: 'POST', body: { content } });
    $('thinking-row')?.remove(); renderMessage(result.message);
    $('chat-ready').textContent = result.ready ? '✓ Ready to generate' : '';
    await refreshConversations();
  } catch (error) {
    $('thinking-row')?.remove(); $('chat-error').textContent = error.message; $('chat-error').hidden = false;
    // The server may have saved the user message before the model failed. Reload to avoid duplicates.
    if (state.currentId) await openConversationUnsafe(state.currentId);
  } finally { setBusy(false); $('chat-input').focus(); }
}
async function openConversationUnsafe(id) {
  try {
    const data = await api(`/conversations/${encodeURIComponent(id)}`);
    state.messages = data.messages; $('messages').replaceChildren(); data.messages.forEach(renderMessage);
    await refreshConversations();
  } catch { /* Preserve visible error. */ }
}
$('send-button').addEventListener('click', () => sendMessage($('chat-input').value));
$('chat-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendMessage($('chat-input').value); }
});
$('chat-input').addEventListener('input', () => { $('char-count').textContent = `${$('chat-input').value.length} / 4000`; });
document.querySelectorAll('[data-idea]').forEach((btn) => btn.addEventListener('click', () => sendMessage(btn.dataset.idea)));

$('generate-button').addEventListener('click', async () => {
  if (state.busy) return;
  if (!state.currentId) return toast('Tell the AI your idea first.');
  const options = { detail: $('detail-select').value, tone: $('tone-select').value, language: $('language-select').value, platform: $('platform-select').value };
  setBusy(true);
  try {
    const result = await api(`/conversations/${encodeURIComponent(state.currentId)}/generate`, { method: 'POST', body: options });
    openPrompt(result.prompt); toast('Prompt generated and saved!');
  } catch (error) { toast(error.message); }
  finally { setBusy(false); }
});

async function refreshPrompts() {
  try { state.prompts = (await api('/prompts')).prompts; renderLibrary(); }
  catch (error) { toast(error.message); }
}
function renderLibrary() {
  const grid = $('library-grid'); grid.replaceChildren();
  const query = $('library-search').value.trim().toLowerCase();
  const filtered = state.prompts.filter((p) => (!$('only-favorites').checked || p.favorite) && (p.title.toLowerCase().includes(query) || p.content.toLowerCase().includes(query)));
  if (!filtered.length) { const empty = document.createElement('div'); empty.className = 'empty-state'; empty.textContent = 'No prompts found. Start a conversation to create your first one.'; grid.append(empty); return; }
  for (const p of filtered) {
    const card = document.createElement('article'); card.className = 'library-card';
    const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = p.category.toUpperCase() + (p.favorite ? '  ★' : '');
    const title = document.createElement('h3'); title.textContent = p.title;
    const description = document.createElement('p'); description.textContent = p.content;
    const actions = document.createElement('div'); actions.className = 'library-card-actions';
    const open = document.createElement('button'); open.textContent = 'Open prompt'; open.addEventListener('click', () => openPrompt(p));
    const copy = document.createElement('button'); copy.textContent = '⧉ Copy'; copy.addEventListener('click', () => copyText(p.content));
    const del = document.createElement('button'); del.textContent = '×'; del.title = 'Delete prompt';
    del.addEventListener('click', async () => {
      if (!confirm('Delete this saved prompt?')) return;
      try { await api(`/prompts/${encodeURIComponent(p.id)}`, { method: 'DELETE' }); await refreshPrompts(); toast('Prompt deleted.'); }
      catch (error) { toast(error.message); }
    });
    actions.append(open, copy, del); card.append(tag, title, description, actions); grid.append(card);
  }
}
$('library-search').addEventListener('input', renderLibrary);
$('only-favorites').addEventListener('change', renderLibrary);

function openPrompt(prompt) {
  state.currentPrompt = prompt; state.editMode = false;
  $('prompt-modal').hidden = false; $('prompt-content').readOnly = true;
  $('prompt-content').value = prompt.content; $('prompt-modal-title').textContent = prompt.title;
  $('prompt-version-label').textContent = `Version ${prompt.version} · Saved automatically`;
  $('favorite-prompt').textContent = prompt.favorite ? '★ Favorited' : '☆ Favorite';
  $('edit-prompt').textContent = '✎ Edit'; $('versions-area').hidden = true;
}
$('close-prompt').addEventListener('click', () => { $('prompt-modal').hidden = true; });
$('prompt-modal').addEventListener('click', (event) => { if (event.target.id === 'prompt-modal') $('prompt-modal').hidden = true; });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') { $('prompt-modal').hidden = true; closeSidebar(); }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'n' && state.user) { event.preventDefault(); newChat(); }
});
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('Copied to clipboard!'); }
  catch { toast('Clipboard unavailable. Select and copy the text manually.'); }
}
$('copy-prompt').addEventListener('click', () => copyText($('prompt-content').value));
$('download-prompt').addEventListener('click', () => {
  const blob = new Blob([$('prompt-content').value], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
  anchor.href = url; anchor.download = 'promptsutra-prompt.txt'; document.body.append(anchor); anchor.click(); anchor.remove();
  URL.revokeObjectURL(url);
});
$('favorite-prompt').addEventListener('click', async () => {
  const p = state.currentPrompt; if (!p) return;
  try { const data = await api(`/prompts/${encodeURIComponent(p.id)}`, { method: 'PATCH', body: { favorite: !p.favorite } });
    openPrompt(data.prompt); if (state.section === 'library') refreshPrompts(); }
  catch (error) { toast(error.message); }
});
$('edit-prompt').addEventListener('click', async () => {
  const p = state.currentPrompt; if (!p) return;
  if (!state.editMode) {
    state.editMode = true; $('prompt-content').readOnly = false; $('edit-prompt').textContent = '✓ Save edits'; $('prompt-content').focus(); return;
  }
  try {
    const data = await api(`/prompts/${encodeURIComponent(p.id)}`, { method: 'PATCH', body: { content: $('prompt-content').value } });
    openPrompt(data.prompt); toast('Edits saved!'); if (state.section === 'library') refreshPrompts();
  } catch (error) { toast(error.message); }
});
$('refine-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const p = state.currentPrompt; if (!p) return;
  const button = $('refine-form').querySelector('button'); button.disabled = true;
  try { const result = await api(`/prompts/${encodeURIComponent(p.id)}/refine`, { method: 'POST', body: { instruction: $('refine-input').value.trim() } });
    $('refine-input').value = ''; openPrompt(result.prompt); toast('Prompt refined and saved!'); if (state.section === 'library') refreshPrompts();
  } catch (error) { toast(error.message); } finally { button.disabled = false; }
});
$('versions-prompt').addEventListener('click', async () => {
  if (!state.currentPrompt) return;
  if (!$('versions-area').hidden) { $('versions-area').hidden = true; return; }
  try { const result = await api(`/prompts/${encodeURIComponent(state.currentPrompt.id)}/versions`);
    const area = $('versions-area'); area.replaceChildren();
    result.versions.forEach((v) => {
      const button = document.createElement('button'); button.className = 'version-row'; button.textContent = `Version ${v.number}`;
      button.addEventListener('click', () => { $('prompt-content').value = v.content; $('prompt-version-label').textContent = `Viewing version ${v.number} (not saved over latest)`; area.hidden = true; });
      area.append(button);
    }); area.hidden = false;
  } catch (error) { toast(error.message); }
});

function initTheme() {
  const stored = localStorage.getItem('promptsutra-theme');
  if (stored === 'light') document.documentElement.classList.add('light');
}
$('theme-toggle').addEventListener('click', () => {
  document.documentElement.classList.toggle('light');
  localStorage.setItem('promptsutra-theme', document.documentElement.classList.contains('light') ? 'light' : 'dark');
});
initTheme(); bootstrap();
