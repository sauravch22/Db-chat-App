// ══════════════════════════════════════════════════════
//  DbChat – Frontend App  (v6 — with Auth)
// ══════════════════════════════════════════════════════

let selectedConnId = null;
let isProcessing = false;
let chartIdx = 0;

// Auth state
let authToken = localStorage.getItem('dbchat_token') || null;
let currentUser = null; // { username, permissions }

// Store last response data for the detail explorer
let lastResponseRows = [];
let lastResponseCols = [];

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
        currentUser = { username: data.username, permissions: data.permissions };
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
        succEl.textContent = '✓ Account created! You can now sign in.';
        userEl.value = ''; passEl.value = ''; pass2El.value = '';
        // Auto-switch to sign in after 1.5s
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
    // Reset both forms
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
    renderUserBadge();
    loadDatabases();

    // Show admin tab if user has db_onboard
    const isAdmin = currentUser && currentUser.permissions && currentUser.permissions.includes('db_onboard');
    document.getElementById('tabBar').style.display = isAdmin ? '' : 'none';
    switchTab('chat');
}

function renderUserBadge() {
    if (!currentUser) return;
    document.getElementById('userLabel').textContent = currentUser.username;
    const permsEl = document.getElementById('userPerms');
    permsEl.innerHTML = '';
    const map = { db_onboard: ['onboard', 'Onboard'], db_reindex: ['reindex', 'Reindex'], prompt_query: ['query', 'Query'] };
    (currentUser.permissions || []).forEach(p => {
        const [cls, label] = map[p] || ['query', p];
        permsEl.innerHTML += `<span class="perm-badge ${cls}">${label}</span>`;
    });
}

// ─── Init: check stored token on page load ───────────
document.addEventListener('DOMContentLoaded', async () => {
    if (!authToken) { showLogin(); return; }
    // Validate token by hitting /api/auth/me
    try {
        const r = await fetch(`${chatUrl()}/api/auth/me`, { headers: authHeaders() });
        if (!r.ok) throw 0;
        const me = await r.json();
        currentUser = { username: me.username, permissions: me.permissions };
        showApp();
    } catch {
        // Token expired or invalid
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
        if (!dbs.length) { sel.innerHTML = '<option>No databases</option>'; return; }

        const preferred = dbs.find(db => db.id === 3) || dbs.find(db => /neon|chinook/i.test(db.name));
        const sorted = preferred ? [preferred, ...dbs.filter(db => db.id !== preferred.id)] : dbs;

        sorted.forEach(db => {
            const o = document.createElement('option');
            o.value = db.id; o.textContent = db.name; sel.appendChild(o);
        });
        selectedConnId = sorted[0].id;
        sel.onchange = () => { selectedConnId = +sel.value; };
    } catch(e) {
        if (e.message && e.message.includes('Session expired')) return;
        sel.innerHTML = '<option value="3">Chinook DB</option>';
        selectedConnId = 3;
    }
}

// ─── Chips / auto-resize ─────────────────────────────
function askChip(btn) { document.getElementById('queryInput').value = btn.textContent.trim(); sendMessage(); }

// Setup textarea auto-resize after DOM ready
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

    try {
        const r = await authFetch(`${chatUrl()}/api/chat`, {
            method: 'POST',
            body: JSON.stringify({ connection_id: selectedConnId || 3, prompt: q })
        });
        const data = await r.json();
        setTyping(false);
        if (r.status === 403) {
            addBotError('Permission denied: you need "prompt_query" permission to use chat.');
        } else if (data.status === 'error') {
            addBotError(data.error || 'Something went wrong');
        } else {
            await addBotReply(q, data);
        }
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

    if (data.rows?.length && data.columns?.length) {
        h += buildTable(data.columns, data.rows, 30, data.row_count);
        h += `<button onclick="openDetailModal()" class="chip mt-1">🔍 Explore full data (${Math.min(data.row_count||data.rows.length, 100)} rows)</button>`;
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

    if (data.rows?.length && data.columns?.length) {
        await fetchChartChips(chartAreaId, data.columns, data.rows);
    }
}

// ─── Build data table ────────────────────────────────
function buildTable(cols, rows, maxRows, totalRows) {
    const show = rows.slice(0, maxRows);
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
    if ((totalRows||rows.length) > maxRows) h += `<p class="text-xs text-d-muted mt-1">Showing ${maxRows} of ${totalRows||rows.length} rows</p>`;
    return h;
}

// ─── Fetch chart recommendations → chips ─────────────
async function fetchChartChips(containerId, columns, rows) {
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
            chip.onclick = () => openChartModal(rec);
            wrapper.appendChild(chip);
        });

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

function openChartModal(rec) {
    const overlay = document.getElementById('chartModal');
    document.getElementById('chartModalTitle').textContent = rec.title;
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
                                strokeStyle:'transparent', hidden: false, index: i };
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

function openDetailModal() {
    detailCols = lastResponseCols.length ? lastResponseCols : [];
    detailAllRows = (lastResponseRows || []).slice(0, 100);

    const sel = document.getElementById('detailCol');
    sel.innerHTML = '<option value="__all__">All columns</option>';
    detailCols.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o); });

    document.getElementById('detailSearch').value = '';
    document.getElementById('detailRegexErr').classList.add('hidden');
    document.getElementById('detailCount').textContent = detailAllRows.length + ' rows';

    renderDetailTable(detailAllRows);
    document.getElementById('detailModal').classList.add('open');
}

function closeDetailModal() {
    document.getElementById('detailModal').classList.remove('open');
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

function renderDetailTable(rows, re, filterCol) {
    const body = document.getElementById('detailBody');
    if (!rows.length || !detailCols.length) {
        body.innerHTML = '<p class="p-6 text-sm text-d-muted">No matching rows.</p>';
        return;
    }

    let h = '<div style="overflow:auto;max-height:calc(88vh - 80px)"><table class="dt"><thead><tr>';
    h += '<th style="width:40px">#</th>';
    detailCols.forEach(c => h += `<th>${esc(c)}</th>`);
    h += '</tr></thead><tbody>';

    rows.forEach((row, idx) => {
        h += '<tr>';
        h += `<td style="color:#4a4f65">${idx+1}</td>`;
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
    body.innerHTML = h;
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
    const chatTab = document.getElementById('chatTab');
    const adminTab = document.getElementById('adminTab');
    const btnChat = document.getElementById('tabChat');
    const btnAdmin = document.getElementById('tabAdmin');

    if (tab === 'admin') {
        chatTab.style.display = 'none';
        adminTab.style.display = '';
        btnChat.classList.remove('active');
        btnAdmin.classList.add('active');
        loadAdminUsers();
    } else {
        chatTab.style.display = '';
        adminTab.style.display = 'none';
        btnChat.classList.add('active');
        btnAdmin.classList.remove('active');
    }
}

// ═════════════════════════════════════════════════════
//  ADMIN – USER MANAGEMENT
// ═════════════════════════════════════════════════════
let adminUsers = [];

async function loadAdminUsers() {
    const listEl = document.getElementById('adminUserList');
    listEl.innerHTML = '<p class="text-sm text-d-muted p-6">Loading users…</p>';
    try {
        const r = await authFetch(`${chatUrl()}/api/auth/users`);
        if (!r.ok) throw new Error('Failed to load users');
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
        { key: 'db_onboard', cls: 'onboard', label: 'Onboard' },
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

        h += `<span class="save-status" id="save-${user.id}" style="width:60px;text-align:center">✓ Saved</span>`;
        h += `</div>`;
    });
    listEl.innerHTML = h;
}

async function togglePerm(userId, perm, btnEl) {
    // Find user in local state
    const user = adminUsers.find(u => u.id === userId);
    if (!user) return;

    // Toggle permission locally
    const idx = user.permissions.indexOf(perm);
    if (idx >= 0) {
        user.permissions.splice(idx, 1);
    } else {
        user.permissions.push(perm);
    }

    // Update button appearance
    const has = user.permissions.includes(perm);
    btnEl.classList.toggle('on', has);
    btnEl.classList.toggle('off', !has);

    // Save to backend
    try {
        const r = await authFetch(`${chatUrl()}/api/auth/users/${userId}/permissions`, {
            method: 'PUT',
            body: JSON.stringify({ permissions: user.permissions }),
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

        // Update own badge if editing self
        if (currentUser && parseInt(currentUser.sub || 0) === userId) {
            currentUser.permissions = data.permissions;
            renderUserBadge();
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

// ESC key closes modals
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeChartModal(); closeDetailModal(); }
});
