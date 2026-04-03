let isProcessing = false;
let chartIdx = 0;

// Auth state
let authToken = localStorage.getItem('dbchat_token') || null;
let currentUser = null; // { username, perms: {"*":["db_onboard"], "3":[...]} }

// Thread state
let currentThreadId = null;   // active thread UUID (null = new thread)
let selectedConnId = null;    // current DB connection

// Store last response data for the detail explorer
let lastResponseRows = [];
let lastResponseCols = [];

// Dashboard state
let currentDashboardId = null;
let dashboardPinCharts = {};  // { canvasId: Chart instance }
let dashboardPinData = {};    // { pinId: { columns: [...], rows: [...] } }

// Pin context (set when user interacts with chart/result)
let pinContext = { prompt: null, sql: null, chartType: null, chartConfig: null, chartTitle: null };

const chatUrl = () => document.getElementById('chatUrl').value;
const vizUrl  = () => document.getElementById('vizUrl').value;

// ═════════════════════════════════════════════════════
//  AUTH – Login / Logout / Token management
// ═════════════════════════════════════════════════════

function authHeaders() {
    const h = { 'Content-Type': 'application/json' };
    if (authToken) h['Authorization'] = 'Bearer ' + authToken;
    return h;
}

async function doLogin() {
    const userEl = document.getElementById('loginUser');
    const passEl = document.getElementById('loginPass');
    const errEl  = document.getElementById('loginError');
    const btn    = document.getElementById('loginBtn');
    if (!userEl || !passEl || !errEl || !btn) {
        try { console.error('Login form elements missing; cannot submit login'); } catch(_) {}
        return;
    }
    const u = userEl.value.trim(), p = passEl.value;
    errEl.textContent = '';
    if (!u || !p) { errEl.textContent = 'Please enter username and password'; return; }

    btn.disabled = true; btn.textContent = 'Signing in…';
    try {
        const r = await fetch(`${chatUrl()}/api/auth/login`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u, password: p }),
        });
        if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            errEl.textContent = d.detail || 'Invalid credentials';
            return;
        }
        const data = await r.json();
        authToken = data.access_token;
        localStorage.setItem('dbchat_token', authToken);
        currentUser = { username: data.username, perms: data.perms || {} };
        showApp();
    } catch (e) {
        errEl.textContent = 'Cannot reach server. Is it running?';
    } finally {
        btn.disabled = false; btn.textContent = 'Sign In';
    }
}

function doLogout() {
    authToken = null;
    currentUser = null;
    localStorage.removeItem('dbchat_token');
    clearChat();
    showLogin();
}

function showSignupForm() {
    document.getElementById('signinForm').style.display = 'none';
    document.getElementById('signupForm').style.display = '';
    document.getElementById('authSubtitle').textContent = 'Create a new account';
    document.getElementById('signupUser').focus();
    document.getElementById('signupError').textContent = '';
    document.getElementById('signupSuccess').textContent = '';
}

function showSigninForm() {
    document.getElementById('signupForm').style.display = 'none';
    document.getElementById('signinForm').style.display = '';
    document.getElementById('authSubtitle').textContent = 'Sign in to continue';
    document.getElementById('loginUser').focus();
    document.getElementById('loginError').textContent = '';
}

async function doSignup() {
    const userEl = document.getElementById('signupUser');
    const passEl = document.getElementById('signupPass');
    const pass2El = document.getElementById('signupPass2');
    const errEl  = document.getElementById('signupError');
    const succEl = document.getElementById('signupSuccess');
    const btn    = document.getElementById('signupBtn');

    const u = userEl.value.trim(), p = passEl.value, p2 = pass2El.value;
    errEl.textContent = ''; succEl.textContent = '';

    if (!u || !p) { errEl.textContent = 'Please enter username and password'; return; }
    if (p.length < 4) { errEl.textContent = 'Password must be at least 4 characters'; return; }
    if (p !== p2) { errEl.textContent = 'Passwords do not match'; return; }

    btn.disabled = true; btn.textContent = 'Creating account…';
    try {
        const r = await fetch(`${chatUrl()}/api/auth/signup`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u, password: p }),
        });
        const data = await r.json();
        if (!r.ok) {
            errEl.textContent = data.detail || 'Could not create account';
            return;
        }
        succEl.textContent = data.message || '✓ Account created! You can now sign in.';
        userEl.value = ''; passEl.value = ''; pass2El.value = '';
        setTimeout(() => {
            showSigninForm();
            document.getElementById('loginUser').value = u;
            document.getElementById('loginUser').focus();
        }, 1500);
    } catch (e) {
        errEl.textContent = 'Cannot reach server. Is it running?';
    } finally {
        btn.disabled = false; btn.textContent = 'Create Account';
    }
}

function showLogin() {
    document.getElementById('loginScreen').classList.remove('hidden');
    document.getElementById('loginScreen').style.display = '';
    document.getElementById('appShell').style.display = 'none';
    document.getElementById('signinForm').style.display = '';
    document.getElementById('signupForm').style.display = 'none';
    document.getElementById('authSubtitle').textContent = 'Sign in to continue';
    document.getElementById('loginUser').value = '';
    document.getElementById('loginPass').value = '';
    document.getElementById('loginError').textContent = '';
    document.getElementById('loginUser').focus();
}

function showApp() {
    document.getElementById('loginScreen').classList.add('hidden');
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('appShell').style.display = '';
    clearChat();
    renderUserBadge();
    loadDatabases();

    // Tab bar always visible; admin/reindex button only for privileged users
    document.getElementById('tabBar').style.display = '';
    const isAnyAdmin = _isAnyAdmin();
    const canOnboard = Object.entries(_perms()).some(([, v]) => v.includes('db_onboard'));
    const adminBtn = document.getElementById('tabAdmin');
    adminBtn.style.display = isAnyAdmin ? '' : 'none';
    adminBtn.textContent = canOnboard ? '👥 Admin' : '🔄 Reindex';
    // Activity tab button label: admins see "Activity", regular users see "My Activity"
    const actBtn = document.getElementById('tabActivity');
    actBtn.textContent = isAnyAdmin ? '📋 Activity' : '📋 My Activity';
    switchTab('chat');
}

// ── Permission helpers (client-side) ─────────────────
function _perms() { return (currentUser && currentUser.perms) || {}; }
function _isGlobalAdmin() { return (_perms()["*"] || []).includes("db_onboard"); }
function _isAnyAdmin() {
    const p = _perms();
    return Object.entries(p).some(([, v]) => v.includes("db_onboard") || v.includes("db_reindex"));
}

function renderUserBadge() {
    if (!currentUser) return;
    document.getElementById('userLabel').textContent = currentUser.username;
    const permsEl = document.getElementById('userPerms');
    permsEl.innerHTML = '';
    const perms = _perms();
    const isGlobal = _isGlobalAdmin();

    if (isGlobal) {
        permsEl.innerHTML = '<span class="perm-badge onboard">Global Admin</span>';
    } else {
        const dbKeys = Object.keys(perms).filter(k => k !== "*" && perms[k].length);
        const adminCount = dbKeys.filter(k => perms[k].includes("db_onboard")).length;
        const viewerCount = dbKeys.length - adminCount;
        if (adminCount > 0) permsEl.innerHTML += `<span class="perm-badge onboard">Admin (${adminCount} DB${adminCount > 1 ? 's' : ''})</span>`;
        if (viewerCount > 0) permsEl.innerHTML += `<span class="perm-badge query">Viewer (${viewerCount} DB${viewerCount > 1 ? 's' : ''})</span>`;
        if (dbKeys.length === 0) permsEl.innerHTML = '<span class="perm-badge" style="background:rgba(107,112,132,.15);color:#6b7084">No DB access</span>';
    }
}

// ─── Init: check stored token on page load ───────────
document.addEventListener('DOMContentLoaded', async () => {
    if (!authToken) { showLogin(); return; }
    try {
        const r = await fetch(`${chatUrl()}/api/auth/me`, { headers: authHeaders() });
        if (!r.ok) throw 0;
        const me = await r.json();
        currentUser = { username: me.username, perms: me.perms || {} };
        showApp();
    } catch {
        doLogout();
    }
});

// ─── Handle 401 responses globally ───────────────────
async function authFetch(url, opts = {}) {
    opts.headers = { ...authHeaders(), ...(opts.headers || {}) };
    const r = await fetch(url, opts);
    if (r.status === 401) {
        doLogout();
        throw new Error('Session expired – please log in again');
    }
    return r;
}

// ═════════════════════════════════════════════════════
//  DATABASE LOADING
// ═════════════════════════════════════════════════════

async function loadDatabases() {
    const sel = document.getElementById('dbSelector');
    try {
        const r = await authFetch(`${chatUrl()}/api/admin/databases`);
        if (!r.ok) throw 0;
        const dbs = await r.json();
        sel.innerHTML = '';
        if (!dbs.length) {
            sel.innerHTML = '<option value="">No databases available</option>';
            return;
        }

        const preferred = dbs.find(db => db.id === 3) || dbs.find(db => /neon|chinook/i.test(db.name));
        const sorted = preferred ? [preferred, ...dbs.filter(db => db.id !== preferred.id)] : dbs;

        sorted.forEach(db => {
            const o = document.createElement('option');
            o.value = db.id; o.textContent = db.name; sel.appendChild(o);
        });
        selectedConnId = sorted[0].id;
        sel.onchange = () => { selectedConnId = +sel.value; startNewThread(); loadThreads(); loadWelcome(); };

        // Load threads + welcome for initial DB
        await loadThreads();
        loadWelcome();
    } catch(e) {
        if (e.message && e.message.includes('Session expired')) return;
        sel.innerHTML = '<option value="">No databases</option>';
    }
}

// ─── Chips / auto-resize ─────────────────────────────
function askChip(btn) { document.getElementById('queryInput').value = btn.textContent.trim(); sendMessage(); }

document.addEventListener('DOMContentLoaded', () => {
    const ta = document.getElementById('queryInput');
    if (ta) ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'; });
});

// ─── Send ────────────────────────────────────────────
async function sendMessage() {
    const input = document.getElementById('queryInput');
    const q = input.value.trim();
    if (!q || isProcessing) return;
    isProcessing = true;
    document.getElementById('sendBtn').disabled = true;

    addUserMsg(q);
    input.value = ''; input.style.height = 'auto';
    setTyping(true);

    const body = {
        connection_id: selectedConnId || 3,
        prompt: q,
    };
    if (currentThreadId) body.thread_id = currentThreadId;

    // Try SSE streaming first, fallback to regular endpoint
    try {
        const sseOk = await _sendViaSSE(q, body);
        if (!sseOk) await _sendViaRegular(q, body);
    } catch(e) {
        setTyping(false);
        if (e.message && e.message.includes('Session expired')) {
            addBotError('Session expired – please log in again.');
        } else {
            addBotError('Could not reach backend. Is the service running?');
        }
    } finally {
        isProcessing = false;
        document.getElementById('sendBtn').disabled = false;
    }
}

async function _sendViaSSE(query, body) {
    try {
        const r = await fetch(`${chatUrl()}/api/chat/stream`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(body),
        });
        if (!r.ok || !r.body) return false;

        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let collected = { sql: null, answer: null, rows: null, columns: null,
                          row_count: 0, summary: null, thread_id: null,
                          execution_time_ms: 0, status: 'success', query_time_ms: null };

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            let eventType = null;
            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    eventType = line.slice(7).trim();
                } else if (line.startsWith('data: ') && eventType) {
                    const data = line.slice(6);
                    _handleSSEEvent(eventType, data, collected);
                    eventType = null;
                }
            }
        }

        setTyping(false);

        if (collected.thread_id) {
            currentThreadId = collected.thread_id;
            loadThreads();
        }

        if (collected.status === 'error' && !collected.sql) {
            addBotError(collected.answer || 'Something went wrong');
        } else {
            await addBotReply(query, collected);
            if (collected.summary) {
                _appendSummaryCard(collected.summary);
            }
        }
        return true;
    } catch (e) {
        console.warn('SSE stream failed, will fallback:', e.message);
        return false;
    }
}

function _handleSSEEvent(event, data, collected) {
    switch (event) {
        case 'status':
            break;
        case 'sql':
            collected.sql = data;
            break;
        case 'data':
            try {
                const d = JSON.parse(data);
                collected.columns = d.columns;
                collected.rows = d.rows;
                collected.row_count = d.row_count;
                collected.query_time_ms = d.query_time_ms;
            } catch {}
            break;
        case 'answer':
            collected.answer = data;
            break;
        case 'summary':
            collected.summary = data;
            break;
        case 'error':
            collected.status = 'error';
            collected.answer = data;
            break;
        case 'done':
            try {
                const d = JSON.parse(data);
                collected.thread_id = d.thread_id;
                collected.execution_time_ms = d.execution_time_ms || 0;
                collected.status = d.status || collected.status;
            } catch {}
            break;
    }
}

function _appendSummaryCard(summary) {
    const msgs = document.getElementById('messages');
    if (!msgs) return;
    const lastBot = msgs.querySelector('.bot-msg:last-of-type') || msgs.lastElementChild;
    if (!lastBot) return;
    const card = document.createElement('div');
    card.className = 'summary-card msg-in';
    card.innerHTML = `<h5>AI Insights</h5><p>${summary.replace(/\n/g, '<br>')}</p>`;
    const parent = lastBot.closest('.msg-in') || lastBot;
    parent.after(card);
}

async function _sendViaRegular(query, body) {
    try {
        const r = await authFetch(`${chatUrl()}/api/chat`, {
            method: 'POST',
            body: JSON.stringify(body)
        });
        const data = await r.json();
        setTyping(false);

        if (data.thread_id) {
            currentThreadId = data.thread_id;
            loadThreads();
        }

        if (r.status === 403) {
            addBotError('Permission denied: you don\'t have "prompt_query" access on this database.');
        } else if (data.status === 'error') {
            addBotError(data.error || 'Something went wrong');
        } else {
            await addBotReply(query, data);
        }
    } catch(e) {
        setTyping(false);
        throw e;
    }
}

// ─── Clear chat (reset to welcome) ───────────────────
function clearChat() {
    const el = document.getElementById('messages');
    el.innerHTML = `
        <div class="msg-in flex gap-3">
            <div class="w-8 h-8 rounded-lg bg-d-accent flex items-center justify-center text-white text-xs font-bold shrink-0 mt-1">DB</div>
            <div class="bot-msg" id="welcomeMsg"><p class="text-sm">👋 Hi! I'm <strong>DbChat</strong> — loading your database overview…</p>
                <div class="flex items-center gap-2 mt-3">
                    <div class="typing-dot w-2 h-2 bg-d-muted rounded-full"></div>
                    <div class="typing-dot w-2 h-2 bg-d-muted rounded-full"></div>
                    <div class="typing-dot w-2 h-2 bg-d-muted rounded-full"></div>
                </div>
            </div>
        </div>`;
    lastResponseRows = [];
    lastResponseCols = [];
    chartIdx = 0;
    // Do NOT reset currentThreadId here — that's managed by startNewThread/selectThread
}

// ─── Dynamic welcome: DB summary + LLM-generated suggestions ──
let welcomeCache = {};  // { connId: { summary, suggestions, table_count } }

async function loadWelcome() {
    if (!selectedConnId) return;
    const connId = selectedConnId;

    // Use cache if available
    if (welcomeCache[connId]) {
        renderWelcome(welcomeCache[connId]);
        return;
    }

    try {
        const r = await authFetch(`${chatUrl()}/api/chat/welcome?connection_id=${connId}`);
        if (!r.ok) { renderWelcomeFallback(); return; }
        const data = await r.json();
        welcomeCache[connId] = data;
        // Only render if user is still on the same DB and hasn't navigated away
        if (selectedConnId === connId && !currentThreadId) {
            renderWelcome(data);
        }
    } catch (e) {
        logger_warn('loadWelcome failed', e);
        renderWelcomeFallback();
    }
}

function renderWelcome(data) {
    const el = document.getElementById('welcomeMsg');
    if (!el) return;
    const chips = (data.suggestions || []).map(s =>
        `<button onclick="askChip(this)" class="chip">${esc(s)}</button>`
    ).join('');
    el.innerHTML = `
        <p class="text-sm">👋 Hi! I'm <strong>DbChat</strong> — ask me anything about your data in plain English.</p>
        <div class="mt-3 p-3 rounded-lg" style="background:#171a23;border:1px solid #252938">
            <p class="text-xs font-semibold text-d-accent mb-1">📊 Database Overview · ${data.table_count || '?'} tables</p>
            <p class="text-[13px] text-d-text leading-relaxed">${esc(data.summary || '')}</p>
        </div>
        <p class="text-xs text-d-muted mt-4 mb-2">💡 Try asking:</p>
        <div class="flex flex-wrap gap-2">${chips}</div>`;
}

function renderWelcomeFallback() {
    const el = document.getElementById('welcomeMsg');
    if (!el) return;
    el.innerHTML = `
        <p class="text-sm">👋 Hi! I'm <strong>DbChat</strong> — ask me anything about your data in plain English.</p>
        <div class="flex flex-wrap gap-2 mt-3">
            <button onclick="askChip(this)" class="chip">Show total revenue by country</button>
            <button onclick="askChip(this)" class="chip">Top 10 customers by spending</button>
            <button onclick="askChip(this)" class="chip">Monthly revenue trend</button>
        </div>`;
}

// ─── Load persisted chat history for current thread ──
async function loadChatHistory(threadId) {
    if (!selectedConnId) return;
    const tid = threadId || currentThreadId;
    if (!tid) return;  // no thread selected → keep welcome

    try {
        const r = await authFetch(`${chatUrl()}/api/chat/history?connection_id=${selectedConnId}&thread_id=${tid}&limit=50`);
        if (!r.ok) return;
        const items = await r.json();
        if (!items.length) return;         // keep welcome message

        // Replace welcome with history
        const el = document.getElementById('messages');
        el.innerHTML = '';

        // History header
        const hdr = document.createElement('div');
        hdr.className = 'flex items-center justify-between px-2 py-2 mb-2';
        const title = items[0]?.thread_title || items[0]?.prompt?.substring(0, 50) || 'Thread';
        hdr.innerHTML = `
            <span class="text-xs text-d-muted">🧵 ${esc(title)} · ${items.length} message${items.length > 1 ? 's' : ''}</span>
            <button onclick="clearChatHistory()" class="text-xs text-red-400 hover:text-red-300 underline">Clear thread</button>`;
        el.appendChild(hdr);

        for (const item of items) {
            // User prompt bubble
            addUserMsg(item.prompt);

            // Bot reply (reuse existing rendering logic)
            if (item.status === 'error' || item.error_message) {
                addBotError(item.error_message || 'Something went wrong');
            } else {
                // Build a data object that addBotReply expects
                const data = {
                    answer: item.answer,
                    sql: item.sql,
                    rows: item.rows || [],
                    columns: item.columns || [],
                    row_count: item.row_count,
                    execution_time_ms: item.execution_time_ms,
                    selected_tables: item.selected_tables || [],
                };
                await addBotReply(item.prompt, data);
            }
        }
        scrollEnd();
    } catch (e) {
        logger_warn('loadChatHistory failed', e);
    }
}

function logger_warn(msg, e) { try { console.warn(msg, e); } catch(_) {} }

async function clearChatHistory() {
    if (!selectedConnId) return;
    if (!confirm('Clear all messages in this thread?')) return;
    try {
        if (currentThreadId) {
            await authFetch(`${chatUrl()}/api/chat/threads/${currentThreadId}`, { method: 'DELETE' });
        } else {
            await authFetch(`${chatUrl()}/api/chat/history?connection_id=${selectedConnId}`, { method: 'DELETE' });
        }
    } catch (_) {}
    currentThreadId = null;
    clearChat();
    loadThreads();
}

// ═════════════════════════════════════════════════════
//  THREAD SIDEBAR – list, select, create, delete
// ═════════════════════════════════════════════════════

function startNewThread() {
    currentThreadId = null;
    clearChat();
    highlightActiveThread();
    loadWelcome();
    document.getElementById('queryInput')?.focus();
}

async function loadThreads() {
    if (!selectedConnId) return;
    const listEl = document.getElementById('threadList');
    try {
        const r = await authFetch(`${chatUrl()}/api/chat/threads?connection_id=${selectedConnId}`);
        if (!r.ok) { listEl.innerHTML = '<p class="text-[11px] text-d-muted p-3 text-center">No threads yet</p>'; return; }
        const threads = await r.json();

        if (!threads.length) {
            listEl.innerHTML = '<p class="text-[11px] text-d-muted p-3 text-center">No threads yet</p>';
            return;
        }

        let h = '';
        threads.forEach(t => {
            const title = t.thread_title || t.last_prompt?.substring(0, 40) || 'Untitled';
            const ago = relativeTime(new Date(t.last_at));
            const isActive = t.thread_id === currentThreadId;
            h += `<div class="thread-item${isActive ? ' active' : ''}" data-tid="${t.thread_id}" onclick="selectThread('${t.thread_id}')">
                <div style="flex:1;min-width:0">
                    <div class="thread-title" title="${escAttr(title)}">${esc(title)}</div>
                    <div class="thread-meta">${t.message_count} msg · ${ago}</div>
                </div>
                <span class="thread-del" onclick="event.stopPropagation();deleteThread('${t.thread_id}')" title="Delete thread">✕</span>
            </div>`;
        });
        listEl.innerHTML = h;
    } catch (e) {
        logger_warn('loadThreads failed', e);
    }
}

async function selectThread(threadId) {
    currentThreadId = threadId;
    clearChat();
    highlightActiveThread();
    await loadChatHistory(threadId);
}

function highlightActiveThread() {
    document.querySelectorAll('#threadList .thread-item').forEach(el => {
        el.classList.toggle('active', el.dataset.tid === currentThreadId);
    });
}

async function deleteThread(threadId) {
    if (!confirm('Delete this thread and all its messages?')) return;
    try {
        await authFetch(`${chatUrl()}/api/chat/threads/${threadId}`, { method: 'DELETE' });
        if (currentThreadId === threadId) {
            currentThreadId = null;
            clearChat();
        }
        loadThreads();
    } catch (e) {
        logger_warn('deleteThread failed', e);
    }
}

// ─── User bubble ─────────────────────────────────────
function addUserMsg(text) {
    const d = document.createElement('div');
    d.className = 'msg-in flex justify-end';
    d.innerHTML = `<div class="user-msg">${esc(text)}</div>`;
    document.getElementById('messages').appendChild(d);
    scrollEnd();
}

// ─── Error bubble ────────────────────────────────────
function addBotError(msg) {
    const d = document.createElement('div');
    d.className = 'msg-in flex gap-3';
    d.innerHTML = `<div class="w-8 h-8 rounded-lg bg-red-600/20 flex items-center justify-center text-red-400 text-xs font-bold shrink-0 mt-1">!</div>
        <div class="bot-msg border-red-900/40"><p class="text-sm text-red-300">${esc(msg)}</p></div>`;
    document.getElementById('messages').appendChild(d);
    scrollEnd();
}

// ─── Bot reply ───────────────────────────────────────
async function addBotReply(query, data) {
    lastResponseRows = data.rows || [];
    lastResponseCols = data.columns || [];

    const wrap = document.createElement('div');
    wrap.className = 'msg-in flex gap-3';
    const avatar = `<div class="w-8 h-8 rounded-lg bg-d-accent flex items-center justify-center text-white text-xs font-bold shrink-0 mt-1">DB</div>`;

    let h = '<div class="bot-msg space-y-4" style="min-width:0;width:100%">';

    if (data.answer) h += `<p class="text-sm leading-relaxed">${fmtAnswer(data.answer)}</p>`;

    const st = [];
    if (data.row_count != null) st.push(`<span class="text-d-accent font-semibold">${data.row_count}</span> rows`);
    if (data.selected_tables?.length) st.push(`Tables: <span class="text-d-accent font-semibold">${data.selected_tables.join(', ')}</span>`);
    if (data.execution_time_ms) st.push(`${(data.execution_time_ms/1000).toFixed(1)}s`);
    if (st.length) h += `<div class="flex flex-wrap gap-3 text-xs text-d-muted">${st.join(' · ')}</div>`;

    let exploreBtnId = null;
    let pinDataBtnId = null;
    let explainBtnId = null;
    let exportCsvBtnId = null;
    let exportJsonBtnId = null;
    let saveQueryBtnId = null;
    if (data.rows?.length && data.columns?.length) {
        h += buildTable(data.columns, data.rows, 25, data.row_count);
        h += `<div class="flex flex-wrap gap-2 mt-1">`;
        exploreBtnId = 'explore-' + Date.now();
        h += `<button id="${exploreBtnId}" class="chip">🔍 Explore (${Math.min(data.row_count||data.rows.length, 100)} rows)</button>`;
        exportCsvBtnId = 'csv-' + Date.now();
        h += `<button id="${exportCsvBtnId}" class="export-btn">⬇ CSV</button>`;
        exportJsonBtnId = 'json-' + Date.now();
        h += `<button id="${exportJsonBtnId}" class="export-btn">⬇ JSON</button>`;
        if (data.sql) {
            pinDataBtnId = 'pin-data-' + Date.now();
            h += `<button id="${pinDataBtnId}" class="chip" style="color:#fbbf24;border-color:rgba(251,191,36,.3)">📌 Pin</button>`;
            saveQueryBtnId = 'save-' + Date.now();
            h += `<button id="${saveQueryBtnId}" class="chip" style="color:#34d399;border-color:rgba(52,211,153,.3)">⭐ Save</button>`;
            explainBtnId = 'explain-' + Date.now();
            h += `<button id="${explainBtnId}" class="chip" style="color:#a78bfa;border-color:rgba(167,139,250,.3)">🧠 Explain</button>`;
        }
        h += `</div>`;
    } else if (data.sql) {
        explainBtnId = 'explain-' + Date.now();
        saveQueryBtnId = 'save-' + Date.now();
        h += `<div class="flex flex-wrap gap-2 mt-1">`;
        h += `<button id="${saveQueryBtnId}" class="chip" style="color:#34d399;border-color:rgba(52,211,153,.3)">⭐ Save</button>`;
        h += `<button id="${explainBtnId}" class="chip" style="color:#a78bfa;border-color:rgba(167,139,250,.3)">🧠 Explain</button>`;
        h += `</div>`;
    }

    const chartAreaId = 'crec-' + Date.now();
    h += `<div id="${chartAreaId}"></div>`;

    if (data.sql) {
        const sid = 'sq-' + Date.now();
        h += `<div><div class="toggle-hdr" onclick="toggle('${sid}',this)"><span class="arr">▶</span> View SQL</div>
            <div id="${sid}" class="collapse-body mt-2"><div class="sql-block relative"><button onclick="navigator.clipboard.writeText(this.nextElementSibling.textContent)" class="absolute top-2 right-2 text-[10px] text-d-muted hover:text-d-text bg-d-input px-2 py-0.5 rounded border border-d-border">Copy</button><code>${hlSQL(data.sql)}</code></div></div></div>`;
    }

    if (data.rows?.length) {
        const jid = 'js-' + Date.now();
        h += `<div><div class="toggle-hdr" onclick="toggle('${jid}',this)"><span class="arr">▶</span> Sample JSON (${Math.min(3, data.rows.length)} rows)</div>
            <div id="${jid}" class="collapse-body mt-2"><pre class="sql-block text-xs" style="color:#86efac">${esc(JSON.stringify(data.rows.slice(0,3), null, 2))}</pre></div></div>`;
    }

    h += '</div>';
    wrap.innerHTML = avatar + h;
    document.getElementById('messages').appendChild(wrap);
    scrollEnd();

    // Attach Explore full data handler so each message uses its own rows/columns
    if (exploreBtnId) {
        const exploreBtn = document.getElementById(exploreBtnId);
        if (exploreBtn) {
            exploreBtn.onclick = () => openDetailModal(data.columns, data.rows);
        }
    }

    // Attach pin-data button handler (uses closure for query/sql)
    if (pinDataBtnId) {
        const pinDataBtn = document.getElementById(pinDataBtnId);
        if (pinDataBtn) {
            pinDataBtn.onclick = () => openPinModal(query, data.sql, 'table', null, (query || '').substring(0, 60));
        }
    }

    // Attach explain button handler
    if (explainBtnId) {
        const explainBtn = document.getElementById(explainBtnId);
        if (explainBtn) {
            explainBtn.onclick = async () => {
                explainBtn.disabled = true;
                explainBtn.textContent = '🧠 Thinking…';
                try {
                    const r = await authFetch(`${chatUrl()}/api/chat/explain`, {
                        method: 'POST',
                        body: JSON.stringify({
                            connection_id: selectedConnId,
                            sql: data.sql,
                            prompt: query,
                            schema_context: data.schema_context || null,
                            columns: data.columns || null,
                            row_count: data.row_count || null
                        })
                    });
                    const result = await r.json();
                    if (!r.ok) throw new Error(result.detail || 'Explain failed');
                    openExplainModal(result.explanation, data.sql, query);
                } catch (err) {
                    console.error('Explain error:', err);
                    alert('Failed to generate explanation: ' + err.message);
                } finally {
                    explainBtn.disabled = false;
                    explainBtn.textContent = '🧠 Explain';
                }
            };
        }
    }

    // Attach export CSV handler
    if (exportCsvBtnId) {
        const csvBtn = document.getElementById(exportCsvBtnId);
        if (csvBtn) {
            csvBtn.onclick = () => exportCSV(data.columns, data.rows, 'dbchat_export_' + Date.now());
        }
    }

    // Attach export JSON handler
    if (exportJsonBtnId) {
        const jsonBtn = document.getElementById(exportJsonBtnId);
        if (jsonBtn) {
            jsonBtn.onclick = () => exportJSON(data.columns, data.rows, 'dbchat_export_' + Date.now());
        }
    }

    // Attach save query handler
    if (saveQueryBtnId) {
        const saveBtn = document.getElementById(saveQueryBtnId);
        if (saveBtn) {
            saveBtn.onclick = () => openSaveQueryModal(query, data.sql);
        }
    }

    if (data.rows?.length && data.columns?.length) {
        await fetchChartChips(chartAreaId, data.columns, data.rows, query, data.sql);
    }

    // F3: Auto-validate SQL
    if (data.sql && typeof validateQuery === 'function') {
        validateQuery(data.sql, selectedConnId);
    }

    // F4: Load follow-up suggestions
    if (typeof loadSuggestions === 'function') {
        loadSuggestions(query, data.sql);
    }
}

// ─── Build data table with pagination ─────────────────
let tablePageStates = {};

function buildTable(cols, rows, maxRows, totalRows, tableId) {
    const tid = tableId || ('tbl-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6));
    const pageSize = maxRows || 25;
    const total = rows.length;
    const totalPages = Math.ceil(total / pageSize);

    tablePageStates[tid] = { cols, rows, pageSize, currentPage: 1, totalRows: totalRows || total };

    let h = `<div id="${tid}-wrap">`;
    h += _renderTablePage(tid, 1);
    if (totalPages > 1) {
        h += _renderPageControls(tid, 1, totalPages, total);
    } else if (total > 0 && (totalRows || total) > total) {
        h += `<p class="text-xs text-d-muted mt-1">Showing ${total} of ${totalRows || total} rows</p>`;
    }
    h += `</div>`;
    return h;
}

function _renderTablePage(tid, page) {
    const state = tablePageStates[tid];
    if (!state) return '';
    const { cols, rows, pageSize } = state;
    const start = (page - 1) * pageSize;
    const show = rows.slice(start, start + pageSize);

    let h = `<div class="rounded-lg border border-d-border overflow-hidden" style="max-height:420px;overflow:auto">
        <table class="dt"><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>`;
    show.forEach(row => {
        h += '<tr>';
        cols.forEach(c => {
            const v = row[c]; const s = v != null ? String(v) : '—';
            const isN = typeof v === 'number' || (typeof v === 'string' && v !== '' && !isNaN(+v) && isFinite(v));
            h += `<td${isN?' class="num"':''}>${esc(s)}</td>`;
        });
        h += '</tr>';
    });
    h += '</tbody></table></div>';
    return h;
}

function _renderPageControls(tid, currentPage, totalPages, totalRows) {
    let h = `<div class="page-controls" id="${tid}-pages">`;
    h += `<button class="page-btn" onclick="goTablePage('${tid}',1)" ${currentPage===1?'disabled':''}>«</button>`;
    h += `<button class="page-btn" onclick="goTablePage('${tid}',${currentPage-1})" ${currentPage===1?'disabled':''}>‹</button>`;

    const maxBtns = 5;
    let startP = Math.max(1, currentPage - Math.floor(maxBtns / 2));
    let endP = Math.min(totalPages, startP + maxBtns - 1);
    if (endP - startP < maxBtns - 1) startP = Math.max(1, endP - maxBtns + 1);

    for (let p = startP; p <= endP; p++) {
        h += `<button class="page-btn${p===currentPage?' active':''}" onclick="goTablePage('${tid}',${p})">${p}</button>`;
    }

    h += `<button class="page-btn" onclick="goTablePage('${tid}',${currentPage+1})" ${currentPage===totalPages?'disabled':''}>›</button>`;
    h += `<button class="page-btn" onclick="goTablePage('${tid}',${totalPages})" ${currentPage===totalPages?'disabled':''}>»</button>`;
    h += `<span class="page-info">${totalRows} rows</span>`;
    h += `</div>`;
    return h;
}

function goTablePage(tid, page) {
    const state = tablePageStates[tid];
    if (!state) return;
    const totalPages = Math.ceil(state.rows.length / state.pageSize);
    if (page < 1 || page > totalPages) return;
    state.currentPage = page;

    const wrap = document.getElementById(tid + '-wrap');
    if (!wrap) return;

    let h = _renderTablePage(tid, page);
    h += _renderPageControls(tid, page, totalPages, state.rows.length);
    wrap.innerHTML = h;
}

// ─── Fetch chart recommendations → chips ─────────────
async function fetchChartChips(containerId, columns, rows, prompt, sql) {
    try {
        const numRows = rows.map(r => {
            const o = {};
            for (const [k,v] of Object.entries(r)) o[k] = typeof v==='string'&&v!==''&&!isNaN(+v)&&isFinite(v) ? +v : v;
            return o;
        });
        const vizCols = columns.map(name => {
            const s = numRows.find(r=>r[name]!=null);
            return {name, type: (s && typeof s[name]==='number') ? 'NUMERIC' : 'VARCHAR'};
        });
        const r = await fetch(`${vizUrl()}/analyze`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({data:{columns:vizCols, rows:numRows}, max_recommendations:3})
        });
        if (!r.ok) return;
        const vd = await r.json();
        if (vd.status !== 'success' || !vd.recommendations?.length) return;

        const el = document.getElementById(containerId);
        if (!el) return;

        const recs = vd.recommendations.slice(0, 3);
        const wrapper = document.createElement('div');
        wrapper.className = 'flex flex-wrap gap-2 mt-1';

        const icons = {
            bar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="12" width="4" height="9" rx="1"/><rect x="10" y="7" width="4" height="14" rx="1"/><rect x="17" y="3" width="4" height="18" rx="1"/></svg>',
            line: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 17 9 11 13 15 21 7"/></svg>',
            pie: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 3v9l6.5 3.5"/></svg>',
            scatter: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="7" cy="15" r="2"/><circle cx="14" cy="9" r="2"/><circle cx="18" cy="16" r="2"/></svg>',
            area: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 17 9 11 13 15 21 7"/><path d="M3 17 9 11 13 15 21 7v10H3z" fill="currentColor" opacity=".15"/></svg>',
        };

        recs.forEach((rec) => {
            if (rec.chart_type === 'table') return;
            const chip = document.createElement('button');
            chip.className = 'chart-chip';
            chip.innerHTML = (icons[rec.chart_type] || '') + esc(rec.title);
            chip.onclick = () => openChartModal(rec, prompt, sql);
            wrapper.appendChild(chip);
        });

        // Add pin button if we have SQL
        if (sql && wrapper.children.length) {
            const pinChip = document.createElement('button');
            pinChip.className = 'chart-chip';
            pinChip.style.cssText = 'color:#fbbf24;border-color:rgba(251,191,36,.3)';
            pinChip.innerHTML = '📌 Pin result';
            pinChip.onclick = () => {
                const firstRec = recs.find(r => r.chart_type !== 'table') || recs[0];
                openPinModal(prompt, sql, firstRec?.chart_type || 'table', firstRec?.config ? JSON.stringify(firstRec.config) : null, firstRec?.title || prompt?.substring(0, 50));
            };
            wrapper.appendChild(pinChip);
        }

        if (wrapper.children.length) {
            const label = document.createElement('p');
            label.className = 'text-xs text-d-muted mb-1';
            label.textContent = '📊 Available visualizations:';
            el.appendChild(label);
            el.appendChild(wrapper);
            scrollEnd();
        }
    } catch(e) {
        console.warn('Viz chips error:', e.message);
    }
}

// ═════════════════════════════════════════════════════
//  CHART MODAL
// ═════════════════════════════════════════════════════
let chartModalInstance = null;

function openChartModal(rec, prompt, sql) {
    // Store pin context for the 📌 Pin button inside the chart modal
    pinContext = {
        prompt: prompt || null,
        sql: sql || null,
        chartType: rec.chart_type,
        chartConfig: rec.config ? JSON.stringify(rec.config) : null,
        chartTitle: rec.title || '',
    };

    const overlay = document.getElementById('chartModal');
    document.getElementById('chartModalTitle').textContent = rec.title;
    // Show/hide pin button based on whether we have SQL
    const pinBtn = document.getElementById('chartPinBtn');
    if (pinBtn) pinBtn.style.display = sql ? '' : 'none';

    const canvas = document.getElementById('chartModalCanvas');
    if (chartModalInstance) { chartModalInstance.destroy(); chartModalInstance = null; }
    canvas.width = canvas.parentElement.clientWidth - 40;
    canvas.height = 450;
    overlay.classList.add('open');
    requestAnimationFrame(() => { chartModalInstance = renderChart(canvas, rec.chart_type, rec.config); });
}

function closeChartModal() {
    document.getElementById('chartModal').classList.remove('open');
    if (chartModalInstance) { chartModalInstance.destroy(); chartModalInstance = null; }
}

function renderChart(canvas, type, cfg) {
    const dOpts = {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color:'#8b8fa3', font:{size:12}, padding:14 } },
            tooltip: { backgroundColor:'#1b1e27', titleColor:'#dfe1e8', bodyColor:'#bfc4d8', borderColor:'#252938', borderWidth:1, padding:10, cornerRadius:8 }
        },
        scales: {
            x: { ticks:{color:'#6b7084',font:{size:11}}, grid:{color:'#1e2130'}, title:{display:true, color:'#8b8fa3', font:{size:12}} },
            y: { ticks:{color:'#6b7084',font:{size:11}}, grid:{color:'#1e2130'}, beginAtZero:true, title:{display:true, color:'#8b8fa3', font:{size:12}} }
        }
    };
    const palette = ['#7c6eff','#a78bfa','#34d399','#fbbf24','#f87171','#06b6d4','#ec4899','#8b5cf6','#f59e0b','#10b981','#ef4444','#3b82f6'];

    if (type === 'bar') {
        const xF = cfg.x_field || Object.keys(cfg.data[0]).find(k => typeof cfg.data[0][k] === 'string') || cfg.y_field;
        const yF = cfg.y_field || Object.keys(cfg.data[0]).find(k => typeof cfg.data[0][k] === 'number') || cfg.x_field;
        dOpts.scales.x.title.text = xF.replace(/_/g, ' ').toUpperCase();
        dOpts.scales.y.title.text = yF.replace(/_/g, ' ').toUpperCase();
        return new Chart(canvas, { type:'bar', data: {
            labels: cfg.data.map(d=>d[xF]),
            datasets: [{ label: yF.replace(/_/g,' '), data: cfg.data.map(d=>d[yF]),
                backgroundColor:'rgba(124,110,255,0.55)', borderColor:'#7c6eff', borderWidth:1, borderRadius:4 }]
        }, options: dOpts });
    }

    if (type === 'line' || type === 'area') {
        const xF = cfg.x_field, yF = cfg.y_field;
        dOpts.scales.x.title.text = (xF||'').replace(/_/g,' ').toUpperCase();
        dOpts.scales.y.title.text = (yF||'').replace(/_/g,' ').toUpperCase();
        return new Chart(canvas, { type:'line', data: {
            labels: cfg.data.map(d=> d[xF] ?? ''),
            datasets: [{ label: yF.replace(/_/g,' '), data: cfg.data.map(d=>d[yF]),
                borderColor:'#a78bfa', backgroundColor: type==='area'?'rgba(167,139,250,.15)':'transparent',
                tension:.35, fill:type==='area', pointRadius:3, pointBackgroundColor:'#a78bfa' }]
        }, options: dOpts });
    }

    if (type === 'pie') {
        const cF = cfg.category_field, vF = cfg.value_field;
        const labels = cfg.data.map(d=>d[cF]);
        const values = cfg.data.map(d=>d[vF]);
        const total = values.reduce((a,b)=>a+b, 0);
        return new Chart(canvas, { type:'doughnut', data: {
            labels, datasets:[{ data:values, backgroundColor:palette.slice(0,labels.length), borderWidth:0 }]
        }, options: {
            responsive:true, maintainAspectRatio:false,
            plugins: {
                legend: { position:'right', labels:{ color:'#8b8fa3', font:{size:12}, padding:12,
                    generateLabels: function(chart) {
                        const ds = chart.data.datasets[0];
                        return chart.data.labels.map((l,i) => {
                            const v = ds.data[i]; const pct = total > 0 ? ((v/total)*100).toFixed(1) : 0;
                            return { text: `${l}  —  ${Number(v).toLocaleString()} (${pct}%)`, fillStyle: ds.backgroundColor[i],
                                fontColor: '#8b8fa3', strokeStyle:'transparent', hidden: false, index: i };
                        });
                    }
                }},
                tooltip: {
                    backgroundColor:'#1b1e27', titleColor:'#dfe1e8', bodyColor:'#bfc4d8', borderColor:'#252938', borderWidth:1, padding:10, cornerRadius:8,
                    callbacks: {
                        label: function(ctx) {
                            const v = ctx.parsed; const pct = total > 0 ? ((v/total)*100).toFixed(1) : 0;
                            return ` ${ctx.label}: ${Number(v).toLocaleString()} (${pct}%)`;
                        }
                    }
                }
            }
        }});
    }

    if (type === 'scatter') {
        dOpts.scales.x.title.text = (cfg.x_field||'').replace(/_/g,' ').toUpperCase();
        dOpts.scales.y.title.text = (cfg.y_field||'').replace(/_/g,' ').toUpperCase();
        return new Chart(canvas, { type:'scatter', data: {
            datasets:[{ label:`${cfg.x_field} vs ${cfg.y_field}`, data: cfg.data.map(d=>({x:d[cfg.x_field],y:d[cfg.y_field]})),
                backgroundColor:'rgba(124,110,255,.55)', borderColor:'#7c6eff', borderWidth:1 }]
        }, options: dOpts });
    }

    return null;
}

// ═════════════════════════════════════════════════════
//  DETAIL EXPLORER MODAL
// ═════════════════════════════════════════════════════
let detailAllRows = [];
let detailCols = [];

function openDetailModal(cols, rows) {
    detailCols = cols || (lastResponseCols.length ? lastResponseCols : []);
    detailAllRows = (rows || lastResponseRows || []).slice(0, 100);

    const sel = document.getElementById('detailCol');
    sel.innerHTML = '<option value="__all__">All columns</option>';
    detailCols.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o); });

    document.getElementById('detailSearch').value = '';
    document.getElementById('detailRegexErr').classList.add('hidden');
    document.getElementById('detailCount').textContent = detailAllRows.length + ' rows';

    renderDetailTable(detailAllRows);
    document.getElementById('detailModal').classList.add('open');
}

function exportDetailCSV() {
    const filtered = _getFilteredDetailRows();
    exportCSV(detailCols, filtered, 'explorer_export_' + Date.now());
}

function exportDetailJSON() {
    const filtered = _getFilteredDetailRows();
    exportJSON(detailCols, filtered, 'explorer_export_' + Date.now());
}

function _getFilteredDetailRows() {
    const col = document.getElementById('detailCol').value;
    const rawPattern = document.getElementById('detailSearch').value;
    if (!rawPattern) return detailAllRows;
    try {
        const re = new RegExp(rawPattern, 'i');
        return detailAllRows.filter(row => {
            if (col === '__all__') return detailCols.some(c => re.test(String(row[c] ?? '')));
            return re.test(String(row[col] ?? ''));
        });
    } catch { return detailAllRows; }
}

function closeDetailModal() {
    document.getElementById('detailModal').classList.remove('open');
}

// ─── Explain Modal ───────────────────────────────────
function openExplainModal(explanation, sql, prompt) {
    const body = document.getElementById('explainBody');
    // Convert markdown-like formatting to HTML
    let html = explanation
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/^- /gm, '• ')
        .replace(/\n/g, '<br>');
    body.innerHTML = `
        <div style="margin-bottom:12px;color:#94a3b8;font-size:13px">
            <em>Question: "${esc(prompt)}"</em>
        </div>
        <div style="line-height:1.7;color:#e2e8f0;font-size:14px">${html}</div>
        <details style="margin-top:16px">
            <summary style="cursor:pointer;color:#64748b;font-size:12px">View SQL</summary>
            <pre style="background:#0f172a;padding:12px;border-radius:8px;
                        margin-top:8px;font-size:12px;color:#7c6eff;
                        overflow-x:auto">${esc(sql)}</pre>
        </details>`;
    document.getElementById('explainModal').classList.add('open');
}

function closeExplainModal() {
    document.getElementById('explainModal').classList.remove('open');
}

// Open the detail explorer for a dashboard pin
function openPinDetailModal(pinId) {
    const pinData = dashboardPinData[pinId];
    if (!pinData) { alert('No data available for this pin.'); return; }
    openDetailModal(pinData.columns, pinData.rows);
}

function filterDetailTable() {
    const col = document.getElementById('detailCol').value;
    const rawPattern = document.getElementById('detailSearch').value;
    const errEl = document.getElementById('detailRegexErr');
    errEl.classList.add('hidden');

    if (!rawPattern) {
        document.getElementById('detailCount').textContent = detailAllRows.length + ' rows';
        renderDetailTable(detailAllRows);
        return;
    }

    let re;
    try { re = new RegExp(rawPattern, 'i'); }
    catch(e) { errEl.textContent = 'Invalid regex: ' + e.message; errEl.classList.remove('hidden'); return; }

    const filtered = detailAllRows.filter(row => {
        if (col === '__all__') return detailCols.some(c => re.test(String(row[c] ?? '')));
        return re.test(String(row[col] ?? ''));
    });

    document.getElementById('detailCount').textContent = filtered.length + ' of ' + detailAllRows.length + ' rows';
    renderDetailTable(filtered, re, col);
}

let detailPage = 1;
const DETAIL_PAGE_SIZE = 50;

function renderDetailTable(rows, re, filterCol) {
    detailPage = 1;
    _renderDetailPage(rows, re, filterCol);
}

function _renderDetailPage(rows, re, filterCol) {
    const body = document.getElementById('detailBody');
    if (!rows.length || !detailCols.length) {
        body.innerHTML = '<p class="p-6 text-sm text-d-muted">No matching rows.</p>';
        return;
    }

    const totalPages = Math.ceil(rows.length / DETAIL_PAGE_SIZE);
    const start = (detailPage - 1) * DETAIL_PAGE_SIZE;
    const pageRows = rows.slice(start, start + DETAIL_PAGE_SIZE);

    let h = '<div style="overflow:auto;max-height:calc(88vh - 130px)"><table class="dt"><thead><tr>';
    h += '<th style="width:40px">#</th>';
    detailCols.forEach(c => h += `<th>${esc(c)}</th>`);
    h += '</tr></thead><tbody>';

    pageRows.forEach((row, idx) => {
        h += '<tr>';
        h += `<td style="color:#4a4f65">${start + idx + 1}</td>`;
        detailCols.forEach(c => {
            const v = row[c]; let s = v != null ? String(v) : '—';
            const isN = typeof v==='number'||(typeof v==='string'&&v!==''&&!isNaN(+v)&&isFinite(v));
            if (re && (filterCol === '__all__' || filterCol === c)) {
                s = esc(s).replace(re, m => `<span class="match-hl">${m}</span>`);
                h += `<td${isN?' class="num"':''}>${s}</td>`;
            } else {
                h += `<td${isN?' class="num"':''}>${esc(s)}</td>`;
            }
        });
        h += '</tr>';
    });
    h += '</tbody></table></div>';

    if (totalPages > 1) {
        h += `<div class="page-controls" style="padding:8px 0">`;
        h += `<button class="page-btn" onclick="goDetailPage(${detailPage-1})" ${detailPage===1?'disabled':''}>‹ Prev</button>`;
        for (let p = Math.max(1, detailPage-2); p <= Math.min(totalPages, detailPage+2); p++) {
            h += `<button class="page-btn${p===detailPage?' active':''}" onclick="goDetailPage(${p})">${p}</button>`;
        }
        h += `<button class="page-btn" onclick="goDetailPage(${detailPage+1})" ${detailPage===totalPages?'disabled':''}>Next ›</button>`;
        h += `<span class="page-info">Page ${detailPage}/${totalPages} · ${rows.length} rows</span>`;
        h += `</div>`;
    }

    body.innerHTML = h;
}

function goDetailPage(page) {
    const filteredRows = _getFilteredDetailRows();
    const totalPages = Math.ceil(filteredRows.length / DETAIL_PAGE_SIZE);
    if (page < 1 || page > totalPages) return;
    detailPage = page;

    const col = document.getElementById('detailCol').value;
    const rawPattern = document.getElementById('detailSearch').value;
    let re = null;
    try { if (rawPattern) re = new RegExp(rawPattern, 'i'); } catch {}
    _renderDetailPage(filteredRows, re, col);
}

// ═════════════════════════════════════════════════════
//  EXPORT UTILITIES (CSV / JSON)
// ═════════════════════════════════════════════════════

function exportCSV(columns, rows, filename) {
    if (!columns?.length || !rows?.length) return;
    const escapeCsv = (val) => {
        const s = val != null ? String(val) : '';
        return s.includes(',') || s.includes('"') || s.includes('\n') ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const header = columns.map(escapeCsv).join(',');
    const body = rows.map(row => columns.map(c => escapeCsv(row[c])).join(',')).join('\n');
    const blob = new Blob([header + '\n' + body], { type: 'text/csv;charset=utf-8;' });
    _downloadBlob(blob, (filename || 'export') + '.csv');
}

function exportJSON(columns, rows, filename) {
    if (!rows?.length) return;
    const blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json;charset=utf-8;' });
    _downloadBlob(blob, (filename || 'export') + '.json');
}

function _downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ═════════════════════════════════════════════════════
//  HELPERS
// ═════════════════════════════════════════════════════
function setTyping(on) { document.getElementById('typing').classList.toggle('hidden',!on); if(on) scrollEnd(); }
function scrollEnd() { const a=document.getElementById('chatArea'); if(a) requestAnimationFrame(()=>{a.scrollTop=a.scrollHeight}); }
function toggle(id, hdr) {
    const b=document.getElementById(id), open=hdr.classList.toggle('open');
    if(open){b.style.maxHeight=b.scrollHeight+'px';b.style.opacity='1';b.classList.add('show')}
    else{b.style.maxHeight='0';b.style.opacity='0';b.classList.remove('show')}
}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function fmtAnswer(a){return esc(a).replace(/^(Found \d+ results?\.?)/,'<span class="text-d-accent font-semibold">$1</span>')}
function hlSQL(sql){
    let s=esc(sql);
    ['SELECT','FROM','WHERE','JOIN','LEFT JOIN','RIGHT JOIN','INNER JOIN','GROUP BY','ORDER BY','HAVING','LIMIT','OFFSET',
     'AS','ON','AND','OR','NOT','IN','BETWEEN','LIKE','IS','NULL','CASE','WHEN','THEN','ELSE','END','DISTINCT','UNION',
     'ALL','WITH','EXISTS','DESC','ASC','EXTRACT','SUM','COUNT','AVG','MIN','MAX'].forEach(kw=>{
        s=s.replace(new RegExp(`\\b(${kw})\\b`,'gi'),'<span style="color:#c084fc;font-weight:600">$1</span>');
    });
    return s;
}

// ═════════════════════════════════════════════════════
//  TAB SWITCHING
// ═════════════════════════════════════════════════════
function switchTab(tab) {
    const tabs = ['chatTab', 'adminTab', 'activityTab', 'dashboardTab', 'savedTab',
                  'schemaTab', 'workbenchTab', 'lineageTab', 'intelligenceTab',
                  'templatesTab', 'crossdbTab', 'erdTab', 'qualityTab', 'optimizerTab',
                  'trainingTab', 'fileuploadTab', 'pipelineTab', 'apigenTab',
                  'migrationTab', 'embedTab'];
    const btns = ['tabChat', 'tabAdmin', 'tabActivity', 'tabDashboard', 'tabSaved',
                  'tabSchema', 'tabWorkbench', 'tabLineage', 'tabIntelligence',
                  'tabTemplates', 'tabCrossDb', 'tabErd', 'tabQuality', 'tabOptimizer',
                  'tabTraining', 'tabFileUpload', 'tabPipeline', 'tabApiGen',
                  'tabMigration', 'tabEmbed'];

    tabs.forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; });
    btns.forEach(id => { const el = document.getElementById(id); if (el) el.classList.remove('active'); });

    const simpleTabMap = {
        erd: { tab: 'erdTab', btn: 'tabErd', init: 'initErdTab' },
        quality: { tab: 'qualityTab', btn: 'tabQuality', init: 'initQualityTab' },
        optimizer: { tab: 'optimizerTab', btn: 'tabOptimizer', init: 'initOptimizerTab' },
        training: { tab: 'trainingTab', btn: 'tabTraining', init: 'initTrainingTab' },
        fileupload: { tab: 'fileuploadTab', btn: 'tabFileUpload', init: 'initFileUploadTab' },
        pipeline: { tab: 'pipelineTab', btn: 'tabPipeline', init: 'initPipelineTab' },
        apigen: { tab: 'apigenTab', btn: 'tabApiGen', init: 'initApiGenTab' },
        migration: { tab: 'migrationTab', btn: 'tabMigration', init: 'initMigrationTab' },
        embed: { tab: 'embedTab', btn: 'tabEmbed', init: 'initEmbedTab' },
    };

    if (tab === 'admin') {
        document.getElementById('adminTab').style.display = '';
        document.getElementById('tabAdmin').classList.add('active');
        const canOnboard = Object.entries(_perms()).some(([, v]) => v.includes('db_onboard'));
        const onboardSec = document.getElementById('adminOnboardSection');
        const userMgmtSec = document.getElementById('adminUserMgmtSection');
        if (onboardSec) onboardSec.style.display = canOnboard ? '' : 'none';
        if (userMgmtSec) userMgmtSec.style.display = canOnboard ? '' : 'none';
        populateAdminDbSelector();
        populateReindexDbSelector();
        if (typeof loadLlmProviderSettings === 'function') loadLlmProviderSettings();
    } else if (tab === 'activity') {
        document.getElementById('activityTab').style.display = '';
        document.getElementById('tabActivity').classList.add('active');
        initActivityTab();
    } else if (tab === 'dashboard') {
        document.getElementById('dashboardTab').style.display = '';
        document.getElementById('tabDashboard').classList.add('active');
        loadDashboardsList();
    } else if (tab === 'saved') {
        document.getElementById('savedTab').style.display = '';
        document.getElementById('tabSaved').classList.add('active');
        populateSavedQueryFilters();
        loadSavedQueries();
        if (typeof loadSchedules === 'function') loadSchedules();
        if (typeof loadWritebacks === 'function') loadWritebacks();
    } else if (tab === 'schema') {
        document.getElementById('schemaTab').style.display = '';
        document.getElementById('tabSchema').classList.add('active');
        loadSchemaExplorer();
    } else if (tab === 'workbench') {
        document.getElementById('workbenchTab').style.display = '';
        document.getElementById('tabWorkbench').classList.add('active');
        renderWorkbench();
    } else if (tab === 'lineage') {
        document.getElementById('lineageTab').style.display = '';
        document.getElementById('tabLineage').classList.add('active');
        loadLineage();
    } else if (tab === 'intelligence') {
        document.getElementById('intelligenceTab').style.display = '';
        document.getElementById('tabIntelligence').classList.add('active');
        loadIntelligence();
    } else if (tab === 'templates') {
        document.getElementById('templatesTab').style.display = '';
        document.getElementById('tabTemplates').classList.add('active');
        if (typeof loadTemplates === 'function') loadTemplates();
    } else if (tab === 'crossdb') {
        document.getElementById('crossdbTab').style.display = '';
        document.getElementById('tabCrossDb').classList.add('active');
        if (typeof loadCrossDbConnections === 'function') loadCrossDbConnections();
    } else if (simpleTabMap[tab]) {
        const m = simpleTabMap[tab];
        document.getElementById(m.tab).style.display = '';
        document.getElementById(m.btn).classList.add('active');
        if (typeof window[m.init] === 'function') window[m.init]();
    } else {
        document.getElementById('chatTab').style.display = '';
        document.getElementById('tabChat').classList.add('active');
    }
}

// ═════════════════════════════════════════════════════
//  ADMIN – DB ONBOARDING + PER-DB USER MANAGEMENT
// ═════════════════════════════════════════════════════
let adminUsers = [];
let adminSelectedDb = null;

async function submitRegisterDb() {
    const nameEl = document.getElementById('adminRegName');
    const hostEl = document.getElementById('adminRegHost');
    const portEl = document.getElementById('adminRegPort');
    const userEl = document.getElementById('adminRegUser');
    const passEl = document.getElementById('adminRegPass');
    const dbEl   = document.getElementById('adminRegDb');
    const typeEl = document.getElementById('adminRegType');
    const statusEl = document.getElementById('adminOnboardStatus');
    const btn = document.getElementById('adminOnboardBtn');

    if (!nameEl || !hostEl || !portEl || !userEl || !passEl || !dbEl || !typeEl || !statusEl || !btn) return;

    const name = nameEl.value.trim();
    const host = hostEl.value.trim();
    const port = parseInt(portEl.value.trim() || '0', 10);
    const username = userEl.value.trim();
    const password = passEl.value;
    const database = dbEl.value.trim();
    const database_type = typeEl.value || 'postgres';

    statusEl.className = 'text-xs text-d-muted';
    statusEl.textContent = '';

    if (!name || !host || !port || !username || !password || !database) {
        statusEl.className = 'text-xs text-red-400';
        statusEl.textContent = 'Please fill in all fields (name, host, port, username, password, database).';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Registering…';
    statusEl.textContent = 'Registering database…';

    try {
        const r = await authFetch(`${chatUrl()}/api/admin/register-db`, {
            method: 'POST',
            body: JSON.stringify({ name, host, port, username, password, database, database_type })
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
            const msg = data.detail || 'Failed to register database';
            throw new Error(msg);
        }
        statusEl.className = 'text-xs text-d-green';
        statusEl.textContent = `Registered "${data.name}" (id ${data.id}). Indexing scheduled in background.`;

        // Optionally clear sensitive fields
        passEl.value = '';

        // Refresh DB selectors so the new connection is immediately usable
        try { await loadDatabases(); } catch(_) {}
        try { populateAdminDbSelector(); } catch(_) {}
        try { populateReindexDbSelector(); } catch(_) {}
    } catch (e) {
        statusEl.className = 'text-xs text-red-400';
        statusEl.textContent = e.message || 'Failed to register database';
    } finally {
        btn.disabled = false;
        btn.textContent = '➕ Register Database';
    }
}

function populateReindexDbSelector() {
    const sel = document.getElementById('reindexDbSelector');
    if (!sel) return;
    sel.innerHTML = '<option value="">Select a database…</option>';
    const perms = _perms();
    const isGlobal = _isGlobalAdmin();
    const chatSel = document.getElementById('dbSelector');
    for (let i = 0; i < chatSel.options.length; i++) {
        const connId = chatSel.options[i].value;
        if (!connId) continue;
        const dbPerms = perms[connId] || [];
        if (isGlobal || dbPerms.includes('db_reindex') || dbPerms.includes('db_onboard')) {
            const o = document.createElement('option');
            o.value = connId;
            o.textContent = chatSel.options[i].textContent;
            sel.appendChild(o);
        }
    }
}

async function triggerReindex() {
    const sel = document.getElementById('reindexDbSelector');
    const statusEl = document.getElementById('reindexStatus');
    const btn = document.getElementById('reindexBtn');
    if (!sel || !statusEl || !btn) return;

    const connId = sel.value;
    if (!connId) {
        statusEl.className = 'text-xs text-red-400';
        statusEl.textContent = 'Please select a database first.';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Reindexing…';
    statusEl.className = 'text-xs text-d-muted';
    statusEl.textContent = 'Triggering reindex…';

    try {
        const r = await authFetch(`${chatUrl()}/api/admin/reindex/${connId}`, {
            method: 'POST'
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
            throw new Error(data.detail || 'Failed to trigger reindex');
        }
        statusEl.className = 'text-xs text-d-green';
        statusEl.textContent = `Reindexing started for connection ${connId}. Estimated ~${data.estimated_duration_seconds || 30}s.`;
    } catch (e) {
        statusEl.className = 'text-xs text-red-400';
        statusEl.textContent = e.message || 'Failed to trigger reindex';
    } finally {
        btn.disabled = false;
        btn.textContent = '🔄 Reindex';
    }
}

function populateAdminDbSelector() {
    const sel = document.getElementById('adminDbSelector');
    sel.innerHTML = '<option value="">Select a database…</option>';
    const perms = _perms();
    const isGlobal = _isGlobalAdmin();

    // Re-use already loaded database options from the chat DB selector
    const chatSel = document.getElementById('dbSelector');
    for (let i = 0; i < chatSel.options.length; i++) {
        const connId = chatSel.options[i].value;
        if (!connId) continue;
        const dbPerms = perms[connId] || [];
        if (isGlobal || dbPerms.includes('db_onboard')) {
            const o = document.createElement('option');
            o.value = connId;
            o.textContent = chatSel.options[i].textContent;
            sel.appendChild(o);
        }
    }

    // If a DB was previously selected, keep it
    if (adminSelectedDb) {
        sel.value = String(adminSelectedDb);
        if (sel.value) loadAdminUsersForDb();
    }
}

async function loadAdminUsersForDb() {
    const connId = document.getElementById('adminDbSelector').value;
    const listEl = document.getElementById('adminUserList');

    if (!connId) {
        listEl.innerHTML = '<p class="text-sm text-d-muted p-6">Select a database above to manage user permissions.</p>';
        adminSelectedDb = null;
        return;
    }

    adminSelectedDb = parseInt(connId);
    listEl.innerHTML = '<p class="text-sm text-d-muted p-6">Loading users…</p>';

    try {
        const r = await authFetch(`${chatUrl()}/api/auth/users/db/${connId}`);
        if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            throw new Error(d.detail || 'Failed to load users');
        }
        adminUsers = await r.json();
        renderAdminUsers();
    } catch(e) {
        listEl.innerHTML = `<p class="text-sm text-red-400 p-6">${esc(e.message)}</p>`;
    }
}

function renderAdminUsers() {
    const listEl = document.getElementById('adminUserList');
    if (!adminUsers.length) {
        listEl.innerHTML = '<p class="text-sm text-d-muted p-6">No users found.</p>';
        return;
    }

    const permDefs = [
        { key: 'db_onboard', cls: 'onboard', label: 'Admin' },
        { key: 'db_reindex', cls: 'reindex', label: 'Reindex' },
        { key: 'prompt_query', cls: 'query', label: 'Query' },
    ];

    let h = '';
    adminUsers.forEach((user, idx) => {
        h += `<div class="user-row" id="urow-${user.id}">`;
        h += `<span class="text-xs text-d-muted" style="width:40px">${idx + 1}</span>`;
        h += `<div style="flex:1"><span class="text-sm text-white font-medium">${esc(user.username)}</span>`;
        if (user.username === 'admin') h += ` <span class="text-[10px] text-d-muted">(default)</span>`;
        h += `</div>`;

        permDefs.forEach(pd => {
            const has = user.permissions.includes(pd.key);
            h += `<div style="width:100px;text-align:center">`;
            h += `<button class="perm-toggle ${pd.cls} ${has ? 'on' : 'off'}" `;
            h += `onclick="togglePerm(${user.id}, '${pd.key}', this)">${pd.label}</button>`;
            h += `</div>`;
        });

        // View Logs button (global admins can view any user's logs)
        if (_isGlobalAdmin()) {
            h += `<button onclick="openUserActivityModal(${user.id}, '${esc(user.username)}')" class="text-[10px] px-2 py-1 rounded border border-d-border text-d-muted hover:text-white hover:border-d-accent transition" style="width:70px" title="View this user's activity log">📋 Logs</button>`;
        } else {
            h += `<span style="width:70px"></span>`;
        }

        h += `<span class="save-status" id="save-${user.id}" style="width:60px;text-align:center">✓ Saved</span>`;
        h += `</div>`;
    });
    listEl.innerHTML = h;
}

async function togglePerm(userId, perm, btnEl) {
    const user = adminUsers.find(u => u.id === userId);
    if (!user || !adminSelectedDb) return;

    // Toggle permission locally
    const idx = user.permissions.indexOf(perm);
    if (idx >= 0) user.permissions.splice(idx, 1);
    else user.permissions.push(perm);

    const has = user.permissions.includes(perm);
    btnEl.classList.toggle('on', has);
    btnEl.classList.toggle('off', !has);

    // Save to backend (per-DB)
    try {
        const r = await authFetch(`${chatUrl()}/api/auth/users/${userId}/db-permissions`, {
            method: 'PUT',
            body: JSON.stringify({ connection_id: adminSelectedDb, permissions: user.permissions }),
        });
        if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            throw new Error(d.detail || 'Failed to update');
        }
        const data = await r.json();
        user.permissions = data.permissions;  // sync with server response

        // Flash saved indicator
        const saveEl = document.getElementById(`save-${userId}`);
        if (saveEl) {
            saveEl.classList.add('show');
            setTimeout(() => saveEl.classList.remove('show'), 1500);
        }
    } catch(e) {
        // Revert on error
        if (has) { user.permissions.splice(user.permissions.indexOf(perm), 1); }
        else { user.permissions.push(perm); }
        btnEl.classList.toggle('on', !has);
        btnEl.classList.toggle('off', has);
        alert('Error: ' + e.message);
    }
}

// ═════════════════════════════════════════════════════
//  ACTIVITY LOG (user-scoped + admin global)
// ═════════════════════════════════════════════════════
let activityOffset = 0;
const ACTIVITY_LIMIT = 50;
let activityDebounceTimer = null;
let activityScope = 'me';  // 'me' = own logs, 'all' = global (admin only)

function initActivityTab() {
    const isAdmin = _isGlobalAdmin();

    // Show scope toggle only for global admins
    const scopeToggle = document.getElementById('activityScopeToggle');
    if (scopeToggle) scopeToggle.style.display = isAdmin ? '' : 'none';

    // Show/hide DB & User filters depending on scope
    const dbFilter = document.getElementById('activityDbFilter')?.closest('div');
    const userFilter = document.getElementById('activityUserFilter')?.closest('div');
    if (!isAdmin) {
        activityScope = 'me';
        if (dbFilter) dbFilter.style.display = '';
        if (userFilter) userFilter.style.display = 'none';
    }

    setActivityScope(isAdmin ? activityScope : 'me');
}

function setActivityScope(scope) {
    activityScope = scope;
    activityOffset = 0;
    const isAdmin = _isGlobalAdmin();

    // Update scope buttons
    const meBtn = document.getElementById('scopeMe');
    const allBtn = document.getElementById('scopeAll');
    if (meBtn && allBtn) {
        meBtn.className = `px-3 py-1 text-xs font-medium ${scope === 'me' ? 'bg-d-accent text-white' : 'bg-d-card text-d-muted hover:text-white'}`;
        allBtn.className = `px-3 py-1 text-xs font-medium ${scope === 'all' ? 'bg-d-accent text-white' : 'bg-d-card text-d-muted hover:text-white'}`;
    }

    // Update title
    const title = document.getElementById('activityTitle');
    const subtitle = document.getElementById('activitySubtitle');
    if (scope === 'me') {
        if (title) title.textContent = 'My Activity';
        if (subtitle) subtitle.textContent = 'Your personal activity trail — every action you\'ve performed.';
    } else {
        if (title) title.textContent = 'All Activity';
        if (subtitle) subtitle.textContent = 'System-wide audit log — every user action across all databases.';
    }

    // Show/hide user filter (only in 'all' scope)
    const userFilter = document.getElementById('activityUserFilter')?.closest('div');
    if (userFilter) userFilter.style.display = (scope === 'all' && isAdmin) ? '' : 'none';

    populateActivityDbFilter();
    loadActivityLog();
}

function populateActivityDbFilter() {
    const sel = document.getElementById('activityDbFilter');
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '<option value="">All Databases</option>';
    const chatSel = document.getElementById('dbSelector');
    for (let i = 0; i < chatSel.options.length; i++) {
        const v = chatSel.options[i].value;
        if (!v) continue;
        const o = document.createElement('option');
        o.value = v;
        o.textContent = chatSel.options[i].textContent;
        sel.appendChild(o);
    }
    if (prev) sel.value = prev;
}

function onActivityFilterChange() {
    activityOffset = 0;
    loadActivityLog();
}

function debounceActivityLoad() {
    clearTimeout(activityDebounceTimer);
    activityDebounceTimer = setTimeout(() => { activityOffset = 0; loadActivityLog(); }, 400);
}

async function loadActivityLog() {
    const connId = document.getElementById('activityDbFilter')?.value || '';
    const action = document.getElementById('activityActionFilter')?.value || '';
    const status = document.getElementById('activityStatusFilter')?.value || '';
    const hours  = document.getElementById('activityTimeFilter')?.value || '24';
    const user   = document.getElementById('activityUserFilter')?.value.trim() || '';

    const logList = document.getElementById('activityLogList');
    if (!logList) return;
    logList.innerHTML = '<p class="text-sm text-d-muted p-6">Loading activity…</p>';

    // Build URL based on scope
    let url;
    if (activityScope === 'me') {
        url = `${chatUrl()}/api/activity/me`;
    } else if (connId) {
        url = `${chatUrl()}/api/activity/db/${connId}`;
    } else {
        url = `${chatUrl()}/api/activity/global`;
    }
    const params = new URLSearchParams();
    if (action) params.set('action', action);
    if (status) params.set('status', status);
    if (hours)  params.set('hours', hours);
    if (user && activityScope === 'all')   params.set('username', user);
    if (connId) params.set('connection_id', connId);
    params.set('limit', ACTIVITY_LIMIT);
    params.set('offset', activityOffset);
    url += '?' + params.toString();

    try {
        const r = await authFetch(url);
        if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            throw new Error(d.detail || `HTTP ${r.status}`);
        }
        const data = await r.json();
        renderActivityLog(data);
        renderActivityPagination(data.total || 0);
    } catch(e) {
        logList.innerHTML = `<p class="text-sm text-red-400 p-6">${esc(e.message)}</p>`;
    }

    // Also load stats
    loadActivityStats(connId);
}

function renderActivityLog(data) {
    const logList = document.getElementById('activityLogList');
    const logs = data.logs || [];
    if (!logs.length) {
        logList.innerHTML = '<p class="text-sm text-d-muted p-6">No activity found for the selected filters.</p>';
        return;
    }

    let h = '';
    logs.forEach(log => {
        const ts = new Date(log.created_at);
        const timeStr = ts.toLocaleString(undefined, { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit' });
        const relTime = relativeTime(ts);

        // Parse detail
        let detailHtml = '';
        if (log.detail) {
            try {
                const d = typeof log.detail === 'string' ? JSON.parse(log.detail) : log.detail;
                const entries = Object.entries(d).slice(0, 4);
                detailHtml = entries.map(([k,v]) => {
                    const val = typeof v === 'string' ? v : JSON.stringify(v);
                    return `<span class="text-d-muted">${esc(k)}:</span> ${esc(String(val).substring(0,80))}`;
                }).join(' · ');
                if (Object.keys(d).length > 4) detailHtml += ' …';
            } catch { detailHtml = esc(String(log.detail).substring(0, 120)); }
        }

        const durStr = log.duration_ms != null ? `${log.duration_ms}ms` : '—';

        h += `<div class="log-entry">`;
        h += `<span class="log-time" title="${esc(ts.toISOString())}">${esc(relTime)}</span>`;
        h += `<span class="log-user">${esc(log.username || '—')}</span>`;
        h += `<span class="log-action">${esc(log.action)}</span>`;
        h += `<span class="log-status ${log.status}">${esc(log.status)}</span>`;
        h += `<span class="log-detail" title="Click to expand">${detailHtml || '—'}</span>`;
        h += `<span class="log-dur">${durStr}</span>`;
        h += `</div>`;
    });
    logList.innerHTML = h;
}

function renderActivityPagination(total) {
    const pagEl = document.getElementById('activityPagination');
    if (!pagEl) return;
    if (total <= ACTIVITY_LIMIT && activityOffset === 0) {
        pagEl.innerHTML = `<span class="text-xs text-d-muted">${total} entries</span>`;
        return;
    }
    const page = Math.floor(activityOffset / ACTIVITY_LIMIT) + 1;
    const totalPages = Math.ceil(total / ACTIVITY_LIMIT);
    let h = '';
    if (activityOffset > 0) {
        h += `<button onclick="activityPage(-1)" class="px-3 py-1 text-xs rounded bg-d-card text-d-muted hover:text-white">← Prev</button>`;
    }
    h += `<span class="text-xs text-d-muted">Page ${page} of ${totalPages} (${total} entries)</span>`;
    if (activityOffset + ACTIVITY_LIMIT < total) {
        h += `<button onclick="activityPage(1)" class="px-3 py-1 text-xs rounded bg-d-card text-d-muted hover:text-white">Next →</button>`;
    }
    pagEl.innerHTML = h;
}

function activityPage(dir) {
    activityOffset += dir * ACTIVITY_LIMIT;
    if (activityOffset < 0) activityOffset = 0;
    loadActivityLog();
}

async function loadActivityStats(connId) {
    const statsEl = document.getElementById('activityStats');
    if (!statsEl) return;

    let url;
    if (activityScope === 'me') {
        url = `${chatUrl()}/api/activity/me/stats`;
    } else {
        url = `${chatUrl()}/api/activity/stats`;
    }
    const params = new URLSearchParams();
    const hours = document.getElementById('activityTimeFilter')?.value || '24';
    if (connId && activityScope !== 'me') params.set('connection_id', connId);
    if (hours) params.set('hours', hours);
    url += '?' + params.toString();

    try {
        const r = await authFetch(url);
        if (!r.ok) { statsEl.innerHTML = ''; return; }
        const data = await r.json();
        renderActivityStats(data);
    } catch {
        statsEl.innerHTML = '';
    }
}

function renderActivityStats(data) {
    const statsEl = document.getElementById('activityStats');
    if (!statsEl) return;

    const totalActions = data.total_events || Object.values(data.by_action || {}).reduce((a,b) => a+b, 0);
    const successCount = (data.by_status || {}).success || 0;
    const failedCount  = (data.by_status || {}).failed || 0;
    const deniedCount  = (data.by_status || {}).denied || 0;
    const topUsers = data.top_users || [];
    const topUser = topUsers.length ? topUsers[0] : null;

    let h = '';
    h += `<div class="stat-card"><span class="stat-val">${totalActions}</span><span class="stat-lbl">Total Actions</span></div>`;
    h += `<div class="stat-card"><span class="stat-val" style="color:#34d399">${successCount}</span><span class="stat-lbl">Success</span></div>`;
    h += `<div class="stat-card"><span class="stat-val" style="color:#f87171">${failedCount}</span><span class="stat-lbl">Failed</span></div>`;
    h += `<div class="stat-card"><span class="stat-val" style="color:#fbbf24">${deniedCount}</span><span class="stat-lbl">Denied</span></div>`;
    if (topUser) {
        h += `<div class="stat-card"><span class="stat-val">${esc(topUser.username)}</span><span class="stat-lbl">Most Active (${topUser.count})</span></div>`;
    }
    statsEl.innerHTML = h;
}

function relativeTime(date) {
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
    return `${Math.floor(diff/86400)}d ago`;
}

// ═════════════════════════════════════════════════════
//  USER ACTIVITY MODAL (admin: view any user's logs)
// ═════════════════════════════════════════════════════
let userModalUserId = null;
let userModalUsername = '';
let userModalOffset = 0;
const USER_MODAL_LIMIT = 50;

function openUserActivityModal(userId, username) {
    userModalUserId = userId;
    userModalUsername = username;
    userModalOffset = 0;
    document.getElementById('userModalTitle').textContent = `Activity: ${username}`;
    document.getElementById('userModalSubtitle').textContent = `User ID ${userId} — complete action history`;
    document.getElementById('userModalActionFilter').value = '';
    document.getElementById('userModalTimeFilter').value = '24';
    document.getElementById('userActivityModal').style.display = '';
    loadUserModalActivity();
    loadUserModalStats();
}

function closeUserActivityModal() {
    document.getElementById('userActivityModal').style.display = 'none';
    userModalUserId = null;
}

async function loadUserModalActivity() {
    if (!userModalUserId) return;
    const action = document.getElementById('userModalActionFilter')?.value || '';
    const hours  = document.getElementById('userModalTimeFilter')?.value || '24';
    const logList = document.getElementById('userModalLogList');
    logList.innerHTML = '<p class="text-sm text-d-muted p-6">Loading…</p>';

    const params = new URLSearchParams();
    if (action) params.set('action', action);
    if (hours)  params.set('hours', hours);
    params.set('limit', USER_MODAL_LIMIT);
    params.set('offset', userModalOffset);

    const url = `${chatUrl()}/api/activity/user/${userModalUserId}?${params}`;
    try {
        const r = await authFetch(url);
        if (!r.ok) { const d = await r.json().catch(()=>({})); throw new Error(d.detail || `HTTP ${r.status}`); }
        const data = await r.json();
        renderUserModalLogs(data);
        renderUserModalPagination(data.total || 0);
        document.getElementById('userModalCount').textContent = `${data.total} total`;
    } catch(e) {
        logList.innerHTML = `<p class="text-sm text-red-400 p-6">${esc(e.message)}</p>`;
    }
    loadUserModalStats();
}

function renderUserModalLogs(data) {
    const logList = document.getElementById('userModalLogList');
    const logs = data.logs || [];
    if (!logs.length) {
        logList.innerHTML = '<p class="text-sm text-d-muted p-6">No activity found for this user.</p>';
        return;
    }
    let h = '';
    logs.forEach(log => {
        const ts = new Date(log.created_at);
        const relTime = relativeTime(ts);
        let detailHtml = '';
        if (log.detail) {
            try {
                const d = typeof log.detail === 'string' ? JSON.parse(log.detail) : log.detail;
                const entries = Object.entries(d).slice(0, 4);
                detailHtml = entries.map(([k,v]) => {
                    const val = typeof v === 'string' ? v : JSON.stringify(v);
                    return `<span class="text-d-muted">${esc(k)}:</span> ${esc(String(val).substring(0,80))}`;
                }).join(' · ');
                if (Object.keys(d).length > 4) detailHtml += ' …';
            } catch { detailHtml = esc(String(log.detail).substring(0, 120)); }
        }
        const durStr = log.duration_ms != null ? `${log.duration_ms}ms` : '—';
        h += `<div class="log-entry-user">`;
        h += `<span class="log-time" title="${esc(ts.toISOString())}">${esc(relTime)}</span>`;
        h += `<span class="log-action">${esc(log.action)}</span>`;
        h += `<span class="log-status ${log.status}">${esc(log.status)}</span>`;
        h += `<span class="log-detail">${detailHtml || '—'}</span>`;
        h += `<span class="log-dur">${durStr}</span>`;
        h += `</div>`;
    });
    logList.innerHTML = h;
}

function renderUserModalPagination(total) {
    const pagEl = document.getElementById('userModalPagination');
    if (!pagEl) return;
    if (total <= USER_MODAL_LIMIT && userModalOffset === 0) {
        pagEl.innerHTML = `<span class="text-xs text-d-muted">${total} entries</span>`;
        return;
    }
    const page = Math.floor(userModalOffset / USER_MODAL_LIMIT) + 1;
    const totalPages = Math.ceil(total / USER_MODAL_LIMIT);
    let h = '';
    if (userModalOffset > 0) h += `<button onclick="userModalPage(-1)" class="px-3 py-1 text-xs rounded bg-d-card text-d-muted hover:text-white">← Prev</button>`;
    h += `<span class="text-xs text-d-muted">Page ${page} of ${totalPages}</span>`;
    if (userModalOffset + USER_MODAL_LIMIT < total) h += `<button onclick="userModalPage(1)" class="px-3 py-1 text-xs rounded bg-d-card text-d-muted hover:text-white">Next →</button>`;
    pagEl.innerHTML = h;
}

function userModalPage(dir) {
    userModalOffset += dir * USER_MODAL_LIMIT;
    if (userModalOffset < 0) userModalOffset = 0;
    loadUserModalActivity();
}

async function loadUserModalStats() {
    if (!userModalUserId) return;
    const statsEl = document.getElementById('userModalStats');
    const hours = document.getElementById('userModalTimeFilter')?.value || '24';
    try {
        const r = await authFetch(`${chatUrl()}/api/activity/user/${userModalUserId}/stats?hours=${hours}`);
        if (!r.ok) { statsEl.innerHTML = ''; return; }
        const data = await r.json();
        const s = data.by_status || {};
        let h = '';
        h += `<span class="text-xs font-semibold" style="color:#34d399">${s.success || 0} ✓</span>`;
        h += `<span class="text-xs font-semibold" style="color:#f87171">${s.failed || 0} ✗</span>`;
        h += `<span class="text-xs font-semibold" style="color:#fbbf24">${s.denied || 0} ⛔</span>`;
        statsEl.innerHTML = h;
    } catch { statsEl.innerHTML = ''; }
}

// ESC key closes modals
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeChartModal(); closeDetailModal(); closeUserActivityModal(); closePinModal(); closeCreateDashboardModal(); closeExplainModal(); closeSaveQueryModal(); }
});

// ═════════════════════════════════════════════════════
//  DASHBOARD – List, Create, Open, Refresh, Delete
// ═════════════════════════════════════════════════════

async function loadDashboardsList() {
    const grid = document.getElementById('dashboardGrid');
    grid.innerHTML = '<p class="text-sm text-d-muted">Loading dashboards…</p>';

    // Show list view, hide detail view
    document.getElementById('dashboardListView').style.display = '';
    document.getElementById('dashboardDetailView').style.display = 'none';

    try {
        const r = await authFetch(`${chatUrl()}/api/dashboards`);
        if (!r.ok) throw new Error('Failed to load dashboards');
        const dashboards = await r.json();

        if (!dashboards.length) {
            grid.innerHTML = `
                <div class="col-span-full text-center py-16">
                    <p class="text-4xl mb-3">📊</p>
                    <p class="text-d-muted text-sm mb-2">No dashboards yet</p>
                    <p class="text-d-muted text-xs mb-4">Create a dashboard and pin your favorite queries for quick access.</p>
                    <button onclick="openCreateDashboardModal()" class="chip" style="font-size:13px;padding:8px 18px">＋ Create your first dashboard</button>
                </div>`;
            return;
        }

        let h = '';
        dashboards.forEach(d => {
            const updatedAgo = relativeTime(new Date(d.updated_at));
            h += `<div class="bg-d-card border border-d-border rounded-xl p-5 cursor-pointer transition hover:border-d-accent" onclick="openDashboard(${d.id}, '${escAttr(d.name)}')">
                <div class="flex items-center justify-between mb-2">
                    <h3 class="text-sm font-semibold text-white truncate">${esc(d.name)}</h3>
                    <span class="text-[10px] text-d-muted">${esc(updatedAgo)}</span>
                </div>
                ${d.description ? `<p class="text-xs text-d-muted mb-3 truncate">${esc(d.description)}</p>` : ''}
                <div class="flex items-center gap-2">
                    <span class="text-xs text-d-accent font-semibold">${d.pin_count}</span>
                    <span class="text-xs text-d-muted">pinned ${d.pin_count === 1 ? 'query' : 'queries'}</span>
                </div>
            </div>`;
        });
        grid.innerHTML = h;
    } catch (e) {
        grid.innerHTML = `<p class="text-sm text-red-400">${esc(e.message)}</p>`;
    }
}

function escAttr(s) { return (s||'').replace(/'/g, "\\'").replace(/"/g, '&quot;'); }

function openCreateDashboardModal() {
    document.getElementById('newDashName').value = '';
    document.getElementById('newDashDesc').value = '';
    document.getElementById('createDashError').textContent = '';
    document.getElementById('createDashboardModal').classList.add('open');
    setTimeout(() => document.getElementById('newDashName').focus(), 100);
}

function closeCreateDashboardModal() {
    document.getElementById('createDashboardModal').classList.remove('open');
}

async function submitCreateDashboard() {
    const name = document.getElementById('newDashName').value.trim();
    const desc = document.getElementById('newDashDesc').value.trim();
    const errEl = document.getElementById('createDashError');
    errEl.textContent = '';

    if (!name) { errEl.textContent = 'Please enter a dashboard name'; return; }

    const btn = document.getElementById('createDashBtn');
    btn.disabled = true; btn.textContent = 'Creating…';
    try {
        const r = await authFetch(`${chatUrl()}/api/dashboards`, {
            method: 'POST',
            body: JSON.stringify({ name, description: desc || null }),
        });
        if (!r.ok) { const d = await r.json().catch(()=>({})); throw new Error(d.detail || 'Failed to create'); }
        closeCreateDashboardModal();
        loadDashboardsList();
    } catch (e) {
        errEl.textContent = e.message;
    } finally {
        btn.disabled = false; btn.textContent = 'Create Dashboard';
    }
}

async function openDashboard(id, name) {
    currentDashboardId = id;
    document.getElementById('dashboardListView').style.display = 'none';
    document.getElementById('dashboardDetailView').style.display = '';
    document.getElementById('dashboardDetailTitle').textContent = name || 'Dashboard';
    document.getElementById('dashboardLastUpdated').textContent = '';
    document.getElementById('dashboardPinsGrid').innerHTML = '<p class="text-sm text-d-muted p-4">Loading pins…</p>';
    document.getElementById('dashboardEmpty').classList.add('hidden');

    await refreshCurrentDashboard();
}

function showDashboardList() {
    currentDashboardId = null;
    // Destroy any pin chart instances and clear pin data
    Object.values(dashboardPinCharts).forEach(c => { try { c.destroy(); } catch(_){} });
    dashboardPinCharts = {};
    dashboardPinData = {};
    document.getElementById('dashboardDetailView').style.display = 'none';
    document.getElementById('dashboardListView').style.display = '';
    loadDashboardsList();
}

async function refreshCurrentDashboard() {
    if (!currentDashboardId) return;
    const grid = document.getElementById('dashboardPinsGrid');
    const emptyEl = document.getElementById('dashboardEmpty');
    const refreshBtn = document.getElementById('dashboardRefreshBtn');

    refreshBtn.disabled = true; refreshBtn.textContent = '⏳ Refreshing…';

    // Destroy old chart instances and clear stored pin data
    Object.values(dashboardPinCharts).forEach(c => { try { c.destroy(); } catch(_){} });
    dashboardPinCharts = {};
    dashboardPinData = {};

    try {
        const r = await authFetch(`${chatUrl()}/api/dashboards/${currentDashboardId}/refresh`, { method: 'POST' });
        if (!r.ok) { const d = await r.json().catch(()=>({})); throw new Error(d.detail || 'Refresh failed'); }
        const pins = await r.json();

        if (!pins.length) {
            grid.innerHTML = '';
            emptyEl.classList.remove('hidden');
            document.getElementById('dashboardLastUpdated').textContent = '';
            return;
        }

        emptyEl.classList.add('hidden');
        document.getElementById('dashboardLastUpdated').textContent = '🟢 Updated now';
        // Start fading the "Updated now" text
        startDashboardTimer();

        let h = '';
        pins.forEach(pin => {
            const canvasId = 'pin-chart-' + pin.pin_id;
            const statusColor = pin.status === 'success' ? '#34d399' : pin.status === 'denied' ? '#fbbf24' : '#f87171';
            const statusIcon = pin.status === 'success' ? '✓' : pin.status === 'denied' ? '⛔' : '✗';
            const statusText = pin.status === 'success' ? `${pin.row_count} rows · ${(pin.execution_time_ms/1000).toFixed(1)}s` : (pin.error || pin.status);

            h += `<div class="bg-d-card border border-d-border rounded-xl overflow-hidden" id="pin-card-${pin.pin_id}">
                <div class="flex items-center justify-between px-4 py-3 border-b border-d-border">
                    <div class="flex items-center gap-2 min-w-0">
                        <span class="text-sm">${pin.chart_type === 'table' ? '📋' : '📌'}</span>
                        <span class="text-sm font-semibold text-white truncate">${esc(pin.pin_name)}</span>
                        ${pin.chart_type === 'table' ? '<span class="text-[10px] px-1.5 py-0.5 rounded bg-d-input text-d-muted border border-d-border">TABLE</span>' : ''}
                    </div>
                    <div class="flex items-center gap-2 shrink-0">
                        <span class="text-[10px] font-semibold" style="color:${statusColor}">${statusIcon} ${esc(statusText)}</span>
                        <button onclick="removePin(${pin.pin_id})" class="text-d-muted hover:text-red-400 text-xs" title="Remove pin">✕</button>
                    </div>
                </div>`;

            if (pin.status === 'success' && pin.chart_type !== 'table') {
                h += `<div class="px-4 py-3" style="height:280px"><canvas id="${canvasId}" style="width:100%;height:100%"></canvas></div>`;
            }

            if (pin.status === 'success' && pin.rows?.length && pin.columns?.length) {
                const maxPinRows = pin.chart_type === 'table' ? 20 : 8;
                const maxH = pin.chart_type === 'table' ? '400px' : '200px';
                const showRows = pin.rows.slice(0, maxPinRows);
                h += `<div class="px-4 pb-3" style="max-height:${maxH};overflow:auto">
                    <table class="dt"><thead><tr>${pin.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>`;
                showRows.forEach(row => {
                    h += '<tr>';
                    pin.columns.forEach(c => {
                        const v = row[c]; const s = v != null ? String(v) : '—';
                        const isN = typeof v==='number'||(typeof v==='string'&&v!==''&&!isNaN(+v)&&isFinite(v));
                        h += `<td${isN?' class="num"':''}>${esc(s)}</td>`;
                    });
                    h += '</tr>';
                });
                h += '</tbody></table></div>';
                if (pin.rows.length > maxPinRows) h += `<p class="text-[10px] text-d-muted px-4 pb-2">Showing ${maxPinRows} of ${pin.row_count} rows</p>`;
            }

            if (pin.status !== 'success') {
                h += `<div class="px-4 py-6 text-center"><span class="text-xs" style="color:${statusColor}">${esc(pin.error || 'Error refreshing this pin')}</span></div>`;
            }

            // Footer with explore + export buttons
            h += `<div class="px-4 py-2 border-t border-d-border flex items-center gap-2">`;
            if (pin.status === 'success' && pin.rows?.length) {
                h += `<button onclick="openPinDetailModal(${pin.pin_id})" class="chip shrink-0" style="font-size:10px;padding:3px 8px">🔍 Explore</button>`;
                h += `<button onclick="exportPinCSV(${pin.pin_id})" class="export-btn" style="font-size:10px;padding:3px 8px">⬇ CSV</button>`;
                h += `<button onclick="exportPinJSON(${pin.pin_id})" class="export-btn" style="font-size:10px;padding:3px 8px">⬇ JSON</button>`;
            }
            h += `<p class="text-[10px] text-d-muted truncate flex-1" title="${escAttr(pin.prompt)}">💬 ${esc(pin.prompt)}</p>
            </div>`;

            h += `</div>`;
        });

        grid.innerHTML = h;

        // Store pin data for explore modals
        pins.forEach(pin => {
            if (pin.status === 'success' && pin.rows?.length && pin.columns?.length) {
                dashboardPinData[pin.pin_id] = { columns: pin.columns, rows: pin.rows };
            }
        });

        // Render charts for each pin
        requestAnimationFrame(() => {
            pins.forEach(pin => {
                if (pin.status !== 'success' || pin.chart_type === 'table') return;
                const canvas = document.getElementById('pin-chart-' + pin.pin_id);
                if (!canvas) return;
                try {
                    let config = pin.chart_config ? JSON.parse(pin.chart_config) : null;
                    if (config && pin.rows?.length) {
                        // Replace stored data with fresh data
                        config.data = pin.rows.map(r => {
                            const o = {};
                            for (const [k,v] of Object.entries(r)) o[k] = typeof v==='string'&&v!==''&&!isNaN(+v)&&isFinite(v) ? +v : v;
                            return o;
                        });
                    }
                    if (config) {
                        const chart = renderChart(canvas, pin.chart_type, config);
                        if (chart) dashboardPinCharts['pin-chart-' + pin.pin_id] = chart;
                    }
                } catch (e) {
                    console.warn('Pin chart render error:', pin.pin_id, e);
                }
            });
        });
    } catch (e) {
        grid.innerHTML = `<p class="text-sm text-red-400 p-4">${esc(e.message)}</p>`;
    } finally {
        refreshBtn.disabled = false; refreshBtn.textContent = '↻ Refresh All';
    }
}

let dashboardTimerInterval = null;
let dashboardRefreshTime = null;

function startDashboardTimer() {
    dashboardRefreshTime = new Date();
    if (dashboardTimerInterval) clearInterval(dashboardTimerInterval);
    dashboardTimerInterval = setInterval(() => {
        const el = document.getElementById('dashboardLastUpdated');
        if (!el || !dashboardRefreshTime) return;
        const ago = relativeTime(dashboardRefreshTime);
        el.textContent = `Updated ${ago}`;
    }, 30000);
}

async function deleteCurrentDashboard() {
    if (!currentDashboardId) return;
    if (!confirm('Delete this dashboard and all its pins?')) return;
    try {
        await authFetch(`${chatUrl()}/api/dashboards/${currentDashboardId}`, { method: 'DELETE' });
        showDashboardList();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function removePin(pinId) {
    if (!confirm('Remove this pin from the dashboard?')) return;
    try {
        await authFetch(`${chatUrl()}/api/dashboards/pins/${pinId}`, { method: 'DELETE' });
        const card = document.getElementById('pin-card-' + pinId);
        if (card) card.remove();
        // Destroy chart instance
        if (dashboardPinCharts['pin-chart-' + pinId]) {
            dashboardPinCharts['pin-chart-' + pinId].destroy();
            delete dashboardPinCharts['pin-chart-' + pinId];
        }
        // Check if grid is now empty
        const grid = document.getElementById('dashboardPinsGrid');
        if (grid && !grid.children.length) {
            document.getElementById('dashboardEmpty').classList.remove('hidden');
        }
    } catch (e) {
        alert('Error: ' + e.message);
    }
}


// ─── Export pin data as CSV/JSON ──────────────────────
function exportPinCSV(pinId) {
    const pd = dashboardPinData[pinId];
    if (!pd) { alert('No data available for this pin.'); return; }
    exportCSV(pd.columns, pd.rows, 'dashboard_pin_' + pinId);
}

function exportPinJSON(pinId) {
    const pd = dashboardPinData[pinId];
    if (!pd) { alert('No data available for this pin.'); return; }
    exportJSON(pd.columns, pd.rows, 'dashboard_pin_' + pinId);
}


// ═════════════════════════════════════════════════════
//  PIN MODAL – pin a chat result/chart to a dashboard
// ═════════════════════════════════════════════════════

function pinCurrentChart() {
    // Called from the 📌 button inside the chart modal
    openPinModal(
        pinContext.prompt,
        pinContext.sql,
        pinContext.chartType,
        pinContext.chartConfig,
        pinContext.chartTitle,
    );
}

async function openPinModal(prompt, sql, chartType, chartConfig, defaultName) {
    if (!sql) { alert('No SQL to pin — run a query first.'); return; }

    // Store context for submit
    pinContext.prompt = prompt;
    pinContext.sql = sql;
    pinContext.chartType = chartType || 'table';
    pinContext.chartConfig = chartConfig || null;

    // Pre-fill name
    document.getElementById('pinName').value = defaultName || (prompt || '').substring(0, 60);
    document.getElementById('pinError').textContent = '';

    // Load user's dashboards into dropdown
    const sel = document.getElementById('pinDashboardSelect');
    sel.innerHTML = '<option value="__new__">＋ Create new dashboard</option>';
    try {
        const r = await authFetch(`${chatUrl()}/api/dashboards`);
        if (r.ok) {
            const dashboards = await r.json();
            dashboards.forEach(d => {
                const o = document.createElement('option');
                o.value = d.id;
                o.textContent = d.name + (d.pin_count ? ` (${d.pin_count} pins)` : '');
                sel.appendChild(o);
            });
        }
    } catch (_) {}

    onPinDashboardChange();
    document.getElementById('pinModal').classList.add('open');
    setTimeout(() => document.getElementById('pinName').focus(), 100);
}

function closePinModal() {
    document.getElementById('pinModal').classList.remove('open');
}

function onPinDashboardChange() {
    const isNew = document.getElementById('pinDashboardSelect').value === '__new__';
    document.getElementById('pinNewDashboardWrap').style.display = isNew ? '' : 'none';
}

async function submitPin() {
    const pinName = document.getElementById('pinName').value.trim();
    const errEl = document.getElementById('pinError');
    errEl.textContent = '';

    if (!pinName) { errEl.textContent = 'Please enter a pin name'; return; }
    if (!pinContext.sql) { errEl.textContent = 'No SQL available to pin'; return; }

    const btn = document.getElementById('pinSubmitBtn');
    btn.disabled = true; btn.textContent = 'Pinning…';

    try {
        let dashboardId = document.getElementById('pinDashboardSelect').value;

        // Create new dashboard if needed
        if (dashboardId === '__new__') {
            const newName = document.getElementById('pinNewDashboardName').value.trim();
            if (!newName) { errEl.textContent = 'Please enter a name for the new dashboard'; btn.disabled = false; btn.textContent = '📌 Pin It'; return; }

            const cr = await authFetch(`${chatUrl()}/api/dashboards`, {
                method: 'POST',
                body: JSON.stringify({ name: newName }),
            });
            if (!cr.ok) { const d = await cr.json().catch(()=>({})); throw new Error(d.detail || 'Failed to create dashboard'); }
            const newDash = await cr.json();
            dashboardId = newDash.id;
        }

        // Add pin
        const pr = await authFetch(`${chatUrl()}/api/dashboards/${dashboardId}/pins`, {
            method: 'POST',
            body: JSON.stringify({
                connection_id: selectedConnId,
                pin_name: pinName,
                prompt: pinContext.prompt || '',
                sql: pinContext.sql,
                chart_type: pinContext.chartType || 'table',
                chart_config: pinContext.chartConfig || null,
            }),
        });
        if (!pr.ok) { const d = await pr.json().catch(()=>({})); throw new Error(d.detail || 'Failed to add pin'); }

        closePinModal();
        closeChartModal();

        // Show success toast
        showToast('📌 Pinned to dashboard!');
    } catch (e) {
        errEl.textContent = e.message;
    } finally {
        btn.disabled = false; btn.textContent = '📌 Pin It';
    }
}

// ═════════════════════════════════════════════════════
//  SAVED QUERIES – Save, List, Run, Delete, Favorite
// ═════════════════════════════════════════════════════

let saveQueryContext = { prompt: null, sql: null };

function openSaveQueryModal(prompt, sql) {
    if (!sql) { alert('No SQL to save.'); return; }
    saveQueryContext = { prompt, sql };
    document.getElementById('sqName').value = (prompt || '').substring(0, 80);
    document.getElementById('sqDesc').value = '';
    document.getElementById('sqFolder').value = '';
    document.getElementById('sqFavorite').checked = false;
    document.getElementById('sqError').textContent = '';

    // Load existing folders into datalist
    _loadFolderHints();

    document.getElementById('saveQueryModal').classList.add('open');
    setTimeout(() => document.getElementById('sqName').focus(), 100);
}

function closeSaveQueryModal() {
    document.getElementById('saveQueryModal').classList.remove('open');
}

async function _loadFolderHints() {
    try {
        const r = await authFetch(`${chatUrl()}/api/saved-queries/folders`);
        if (!r.ok) return;
        const folders = await r.json();
        const dl = document.getElementById('sqFolderList');
        dl.innerHTML = '';
        folders.forEach(f => {
            const o = document.createElement('option');
            o.value = f;
            dl.appendChild(o);
        });
    } catch (_) {}
}

async function submitSaveQuery() {
    const name = document.getElementById('sqName').value.trim();
    const desc = document.getElementById('sqDesc').value.trim();
    const folder = document.getElementById('sqFolder').value.trim();
    const isFav = document.getElementById('sqFavorite').checked;
    const errEl = document.getElementById('sqError');
    errEl.textContent = '';

    if (!name) { errEl.textContent = 'Please enter a query name'; return; }
    if (!saveQueryContext.sql) { errEl.textContent = 'No SQL to save'; return; }

    const btn = document.getElementById('sqSubmitBtn');
    btn.disabled = true; btn.textContent = 'Saving…';
    try {
        const r = await authFetch(`${chatUrl()}/api/saved-queries`, {
            method: 'POST',
            body: JSON.stringify({
                connection_id: selectedConnId,
                name,
                sql: saveQueryContext.sql,
                prompt: saveQueryContext.prompt || null,
                description: desc || null,
                folder: folder || null,
                is_favorite: isFav,
            }),
        });
        if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || 'Failed to save'); }
        closeSaveQueryModal();
        showToast('⭐ Query saved!');
    } catch (e) {
        errEl.textContent = e.message;
    } finally {
        btn.disabled = false; btn.textContent = '⭐ Save Query';
    }
}

function populateSavedQueryFilters() {
    const sel = document.getElementById('sqDbFilter');
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '<option value="">All databases</option>';
    const chatSel = document.getElementById('dbSelector');
    for (let i = 0; i < chatSel.options.length; i++) {
        const v = chatSel.options[i].value;
        if (!v) continue;
        const o = document.createElement('option');
        o.value = v;
        o.textContent = chatSel.options[i].textContent;
        sel.appendChild(o);
    }
    if (prev) sel.value = prev;

    // Load folder filter
    _loadFolderFilter();
}

async function _loadFolderFilter() {
    try {
        const r = await authFetch(`${chatUrl()}/api/saved-queries/folders`);
        if (!r.ok) return;
        const folders = await r.json();
        const sel = document.getElementById('sqFolderFilter');
        const prev = sel.value;
        sel.innerHTML = '<option value="">All folders</option>';
        folders.forEach(f => {
            const o = document.createElement('option');
            o.value = f; o.textContent = f;
            sel.appendChild(o);
        });
        if (prev) sel.value = prev;
    } catch (_) {}
}

async function loadSavedQueries() {
    const grid = document.getElementById('savedQueryGrid');
    if (!grid) return;
    grid.innerHTML = '<p class="text-sm text-d-muted">Loading saved queries…</p>';

    const connId = document.getElementById('sqDbFilter')?.value || '';
    const folder = document.getElementById('sqFolderFilter')?.value || '';
    const favOnly = document.getElementById('sqFavOnly')?.checked || false;

    const params = new URLSearchParams();
    if (connId) params.set('connection_id', connId);
    if (folder) params.set('folder', folder);
    if (favOnly) params.set('favorites_only', 'true');

    try {
        const r = await authFetch(`${chatUrl()}/api/saved-queries?${params}`);
        if (!r.ok) throw new Error('Failed to load saved queries');
        const queries = await r.json();

        if (!queries.length) {
            grid.innerHTML = `
                <div class="col-span-full text-center py-16">
                    <p class="text-4xl mb-3">⭐</p>
                    <p class="text-d-muted text-sm mb-2">No saved queries yet</p>
                    <p class="text-d-muted text-xs mb-4">Chat with your database and click <strong class="text-d-green">⭐ Save</strong> on any result to bookmark it.</p>
                </div>`;
            return;
        }

        // Get DB names for display
        const chatSel = document.getElementById('dbSelector');
        const dbNames = {};
        for (let i = 0; i < chatSel.options.length; i++) {
            dbNames[chatSel.options[i].value] = chatSel.options[i].textContent;
        }

        let h = '';
        queries.forEach(sq => {
            const ago = relativeTime(new Date(sq.updated_at));
            const dbName = dbNames[sq.connection_id] || `DB #${sq.connection_id}`;
            h += `<div class="sq-card" onclick="runSavedQuery(${sq.id}, '${escAttr(sq.name)}')">
                <div class="flex items-center gap-2 mb-2">
                    <span class="sq-fav${sq.is_favorite ? ' on' : ''}" onclick="event.stopPropagation();toggleSqFavorite(${sq.id})" title="Toggle favorite">★</span>
                    <h3 class="text-sm font-semibold text-white truncate flex-1">${esc(sq.name)}</h3>
                    <button onclick="event.stopPropagation();deleteSavedQuery(${sq.id})" class="text-d-muted hover:text-red-400 text-xs" title="Delete">✕</button>
                </div>
                ${sq.description ? `<p class="text-xs text-d-muted mb-2 truncate">${esc(sq.description)}</p>` : ''}
                <div class="text-[11px] text-d-muted mb-2 font-mono truncate" style="color:#a5b4fc">${esc(sq.sql.substring(0, 120))}</div>
                <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-[10px] text-d-muted">${esc(dbName)}</span>
                    ${sq.folder ? `<span class="sq-folder-badge">${esc(sq.folder)}</span>` : ''}
                    <span class="text-[10px] text-d-muted ml-auto">${sq.run_count} runs · ${ago}</span>
                </div>
                <div class="flex gap-1.5 mt-2 border-t border-d-border pt-2">
                    <button class="chip" onclick="event.stopPropagation();openScheduleModal(${sq.id},'${escAttr(sq.name)}')" title="Schedule">⏰ Schedule</button>
                    <button class="chip" onclick="event.stopPropagation();addAnnotation(null,${sq.id})" title="Add note">📝 Note</button>
                </div>
            </div>`;
        });
        grid.innerHTML = h;
    } catch (e) {
        grid.innerHTML = `<p class="text-sm text-red-400">${esc(e.message)}</p>`;
    }
}

async function runSavedQuery(queryId, queryName) {
    switchTab('chat');

    addUserMsg(`▶ Re-running: ${queryName}`);
    setTyping(true);

    try {
        const r = await authFetch(`${chatUrl()}/api/saved-queries/${queryId}/run?page=1&page_size=200`, { method: 'POST' });
        const result = await r.json();
        setTyping(false);

        if (!r.ok || !result.success) {
            addBotError(result.error || result.detail || 'Failed to run saved query');
            return;
        }

        const data = {
            status: 'success',
            answer: `Saved query "${queryName}" returned ${result.total_count ?? result.row_count} rows.`,
            sql: null,
            rows: result.rows,
            columns: result.columns,
            row_count: result.total_count ?? result.row_count,
            execution_time_ms: result.execution_time_ms,
            selected_tables: [],
        };
        await addBotReply(queryName, data);
    } catch (e) {
        setTyping(false);
        addBotError('Failed to run saved query: ' + e.message);
    }
}

async function toggleSqFavorite(queryId) {
    try {
        await authFetch(`${chatUrl()}/api/saved-queries/${queryId}/toggle-favorite`, { method: 'POST' });
        loadSavedQueries();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function deleteSavedQuery(queryId) {
    if (!confirm('Delete this saved query?')) return;
    try {
        await authFetch(`${chatUrl()}/api/saved-queries/${queryId}`, { method: 'DELETE' });
        loadSavedQueries();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}


// ═════════════════════════════════════════════════════
//  TOAST NOTIFICATION
// ═════════════════════════════════════════════════════
function showToast(message) {
    let toast = document.getElementById('dbchat-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'dbchat-toast';
        toast.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:999;background:#1b1e27;border:1px solid #7c6eff;color:#dfe1e8;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:500;opacity:0;transition:opacity .3s;pointer-events:none;box-shadow:0 8px 30px rgba(0,0,0,.4)';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.style.opacity = '1';
    setTimeout(() => { toast.style.opacity = '0'; }, 2500);
}
