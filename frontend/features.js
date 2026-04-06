// ═══════════════════════════════════════════════════════════
//  FEATURES.JS – 10 new features for DbChat
//  F1: Query History Search   F2: Schema Explorer
//  F3: Query Validation       F4: Smart Suggestions
//  F5: Annotations            F6: Scheduled Queries
//  F7: Write-Back             F8: Multi-Query Workbench
//  F9: Data Lineage           F10: Connection Intelligence
// ═══════════════════════════════════════════════════════════

// ═══════ F1: Query History Search ═══════════════════════

async function searchHistory() {
    const q = document.getElementById('historySearchInput')?.value?.trim() || '';
    if (!selectedConnId) return;
    const r = await authFetch(`${chatUrl()}/api/chat/history/search?connection_id=${selectedConnId}&q=${encodeURIComponent(q)}&limit=30`);
    if (!r.ok) return;
    const items = await r.json();
    const list = document.getElementById('historySearchResults');
    if (!list) return;
    if (!items.length) {
        list.innerHTML = '<p class="text-xs text-d-muted p-3">No results found</p>';
        return;
    }
    list.innerHTML = items.map(i => `
        <div class="p-2 border-b border-d-border hover:bg-d-hover cursor-pointer" onclick="loadThreadFromSearch('${i.thread_id}')">
            <div class="text-xs text-d-text truncate">${_esc(i.prompt)}</div>
            <div class="text-[10px] text-d-muted mt-0.5">${i.sql ? i.sql.substring(0, 60) + '…' : ''}</div>
            <div class="text-[10px] text-d-muted">${_timeAgo(i.created_at)}</div>
        </div>
    `).join('');
}

function loadThreadFromSearch(threadId) {
    if (threadId && threadId !== 'null') {
        currentThreadId = threadId;
        loadThreadMessages(threadId);
        closeHistorySearch();
    }
}

let historySearchTimeout;
function debounceHistorySearch() {
    clearTimeout(historySearchTimeout);
    historySearchTimeout = setTimeout(searchHistory, 300);
}

function openHistorySearch() {
    const p = document.getElementById('historySearchPanel');
    if (p) { p.style.display = ''; }
    document.getElementById('historySearchInput')?.focus();
}
function closeHistorySearch() {
    const p = document.getElementById('historySearchPanel');
    if (p) { p.style.display = 'none'; }
}

// ═══════ F2: Schema Explorer ════════════════════════════

let schemaData = null;

async function loadSchemaExplorer() {
    if (!selectedConnId) return;
    const container = document.getElementById('schemaExplorerContent');
    if (!container) return;
    container.innerHTML = '<p class="text-sm text-d-muted p-6">Loading schema…</p>';
    try {
        const r = await authFetch(`${chatUrl()}/api/schema/explorer/${selectedConnId}`);
        if (!r.ok) throw new Error('Failed to load');
        schemaData = await r.json();
        renderSchemaExplorer(schemaData);
    } catch (e) {
        container.innerHTML = `<p class="text-sm text-d-red p-6">Error: ${e.message}</p>`;
    }
}

function renderSchemaExplorer(data) {
    const container = document.getElementById('schemaExplorerContent');
    const searchVal = (document.getElementById('schemaSearchInput')?.value || '').toLowerCase();

    let tables = data.tables;
    if (searchVal) {
        tables = tables.filter(t =>
            t.name.toLowerCase().includes(searchVal) ||
            t.columns.some(c => c.name.toLowerCase().includes(searchVal))
        );
    }

    let html = `<div class="mb-4 flex items-center gap-3">
        <span class="text-xs text-d-muted">${data.table_count} tables · ${data.foreign_keys.length} relationships</span>
    </div>`;

    // FK graph mini visualization
    if (data.foreign_keys.length > 0) {
        html += `<div class="mb-4 p-3 bg-d-surface border border-d-border rounded-xl">
            <h4 class="text-xs font-semibold text-d-muted uppercase mb-2">Relationships</h4>
            <div class="flex flex-wrap gap-2">
                ${data.foreign_keys.map(fk => `
                    <div class="text-[11px] bg-d-input border border-d-border rounded-lg px-3 py-1.5">
                        <span class="text-d-accent">${_esc(fk.source_table)}</span>.<span class="text-d-text">${_esc(fk.source_column)}</span>
                        <span class="text-d-muted mx-1">→</span>
                        <span class="text-d-accent">${_esc(fk.target_table)}</span>.<span class="text-d-text">${_esc(fk.target_column)}</span>
                    </div>
                `).join('')}
            </div>
        </div>`;
    }

    html += `<div class="grid gap-3" style="grid-template-columns:repeat(auto-fill,minmax(320px,1fr))">`;
    for (const t of tables) {
        const pkCols = t.columns.filter(c => c.is_primary_key);
        html += `<div class="bg-d-card border border-d-border rounded-xl overflow-hidden">
            <div class="px-4 py-3 border-b border-d-border flex items-center justify-between">
                <div>
                    <span class="text-sm font-semibold text-white">${_esc(t.name)}</span>
                    <span class="text-[10px] text-d-muted ml-2">${t.column_count} cols${t.row_count ? ' · ~' + t.row_count + ' rows' : ''}</span>
                </div>
                <button class="chip" onclick="askAboutTable('${_esc(t.name)}')" title="Ask about this table">💬</button>
            </div>
            ${t.summary ? `<div class="px-4 py-2 text-xs text-d-muted border-b border-d-border">${_esc(t.summary).substring(0, 120)}</div>` : ''}
            <div class="px-4 py-2 max-h-48 overflow-y-auto">
                <table class="w-full text-xs">
                    ${t.columns.map(c => `<tr class="border-b border-d-border/50">
                        <td class="py-1 pr-2">
                            ${c.is_primary_key ? '<span class="text-yellow-400" title="Primary Key">🔑</span> ' : ''}
                            <span class="text-d-text">${_esc(c.name)}</span>
                        </td>
                        <td class="py-1 text-d-muted">${_esc(c.data_type)}</td>
                        <td class="py-1 text-d-muted text-right">${c.is_nullable ? 'NULL' : 'NOT NULL'}</td>
                    </tr>`).join('')}
                </table>
            </div>
        </div>`;
    }
    html += `</div>`;
    container.innerHTML = html;
}

function askAboutTable(tableName) {
    switchTab('chat');
    const input = document.getElementById('queryInput');
    if (input) { input.value = `Show me the first 10 rows from ${tableName}`; sendMessage(); }
}

function filterSchema() {
    if (schemaData) renderSchemaExplorer(schemaData);
}

// ═══════ F3: Query Validation ═══════════════════════════

async function validateQuery(sql, connectionId) {
    if (!sql || !connectionId) return;
    const panel = document.getElementById('validationPanel');
    if (!panel) return;
    panel.style.display = '';
    panel.innerHTML = '<div class="p-3 text-xs text-d-muted">Validating…</div>';
    try {
        const r = await authFetch(`${chatUrl()}/api/validate/query`, {
            method: 'POST',
            body: JSON.stringify({ connection_id: connectionId, sql }),
        });
        if (!r.ok) throw new Error('Validation failed');
        const v = await r.json();
        renderValidation(v);
    } catch (e) {
        panel.innerHTML = `<div class="p-3 text-xs text-d-red">${e.message}</div>`;
    }
}

function renderValidation(v) {
    const panel = document.getElementById('validationPanel');
    if (!panel) return;
    const iconMap = { info: 'ℹ️', warning: '⚠️', danger: '🛑' };
    const colorMap = { info: 'text-blue-400', warning: 'text-yellow-400', danger: 'text-red-400' };
    let html = `<div class="p-3 border border-d-border rounded-lg bg-d-surface">
        <div class="flex items-center gap-2 mb-2">
            <span class="${v.is_safe ? 'text-d-green' : 'text-d-red'} font-semibold text-xs">
                ${v.is_safe ? '✓ Query looks safe' : '⚠ Issues detected'}
            </span>
            ${v.estimated_cost ? `<span class="text-[10px] text-d-muted">Cost: ${v.estimated_cost}</span>` : ''}
            ${v.estimated_rows != null ? `<span class="text-[10px] text-d-muted">Est. rows: ${v.estimated_rows.toLocaleString()}</span>` : ''}
        </div>`;
    if (v.warnings.length) {
        html += v.warnings.map(w => `
            <div class="flex items-start gap-2 text-xs mt-1">
                <span>${iconMap[w.level] || ''}</span>
                <div>
                    <span class="${colorMap[w.level] || ''}">${_esc(w.message)}</span>
                    ${w.suggestion ? `<span class="text-d-muted ml-1">— ${_esc(w.suggestion)}</span>` : ''}
                </div>
            </div>
        `).join('');
    }
    html += '</div>';
    panel.innerHTML = html;
}

// ═══════ F4: Smart Suggestions ══════════════════════════

async function loadSuggestions(prompt, sql) {
    if (!selectedConnId) return;
    const container = document.getElementById('suggestionsBar');
    if (!container) return;
    try {
        const params = new URLSearchParams({ connection_id: selectedConnId });
        if (prompt) params.set('prompt', prompt);
        if (sql) params.set('sql', sql);
        const r = await authFetch(`${chatUrl()}/api/suggestions?${params}`);
        if (!r.ok) return;
        const data = await r.json();
        renderSuggestions(data);
    } catch { /* silent */ }
}

function renderSuggestions(data) {
    const container = document.getElementById('suggestionsBar');
    if (!container) return;
    const all = [...(data.follow_ups || []), ...(data.related_tables || []).map(t => `Show me data from ${t}`)];
    if (!all.length) { container.innerHTML = ''; return; }
    container.innerHTML = `<div class="flex flex-wrap gap-1.5 px-4 py-2 border-t border-d-border bg-d-surface">
        <span class="text-[10px] text-d-muted uppercase font-semibold mr-1 self-center">Follow up:</span>
        ${all.slice(0, 5).map(s => `<button class="chip" onclick="askFollowUp(this)">${_esc(s)}</button>`).join('')}
    </div>`;
}

function askFollowUp(btn) {
    const input = document.getElementById('queryInput');
    if (input) { input.value = btn.textContent.trim(); sendMessage(); }
}

// ═══════ F5: Annotations ════════════════════════════════

async function addAnnotation(chatHistoryId, savedQueryId) {
    const note = prompt('Add a note to this result:');
    if (!note) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/annotations`, {
            method: 'POST',
            body: JSON.stringify({
                connection_id: selectedConnId,
                note,
                chat_history_id: chatHistoryId || null,
                saved_query_id: savedQueryId || null,
                is_shared: false,
            }),
        });
        if (!r.ok) throw new Error('Failed to save');
        showToast('Annotation saved');
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

async function loadAnnotations(container, chatHistoryId, savedQueryId) {
    if (!container) return;
    const params = new URLSearchParams({ include_shared: 'true' });
    if (selectedConnId) params.set('connection_id', selectedConnId);
    if (chatHistoryId) params.set('chat_history_id', chatHistoryId);
    if (savedQueryId) params.set('saved_query_id', savedQueryId);
    try {
        const r = await authFetch(`${chatUrl()}/api/annotations?${params}`);
        if (!r.ok) return;
        const anns = await r.json();
        if (!anns.length) { container.innerHTML = ''; return; }
        container.innerHTML = anns.map(a => `
            <div class="flex items-start gap-2 text-xs p-2 bg-d-surface rounded-lg mt-1">
                <span class="text-yellow-400">📝</span>
                <div class="flex-1">
                    <span class="text-d-text">${_esc(a.note)}</span>
                    ${a.tags.length ? `<div class="mt-0.5">${a.tags.map(t => `<span class="text-[10px] bg-d-accent/20 text-d-accent px-1.5 py-0.5 rounded mr-1">${_esc(t)}</span>`).join('')}</div>` : ''}
                    <div class="text-[10px] text-d-muted mt-0.5">${a.username || 'You'} · ${_timeAgo(a.created_at)}</div>
                </div>
                <button onclick="deleteAnnotation(${a.id}, this.parentElement.parentElement)" class="text-d-muted hover:text-d-red text-xs">✕</button>
            </div>
        `).join('');
    } catch { /* silent */ }
}

async function deleteAnnotation(id, el) {
    try {
        await authFetch(`${chatUrl()}/api/annotations/${id}`, { method: 'DELETE' });
        if (el) el.remove();
    } catch { /* silent */ }
}

// ═══════ F6: Scheduled Queries ══════════════════════════

async function loadSchedules() {
    const container = document.getElementById('scheduledQueriesContent');
    if (!container) return;
    try {
        const params = selectedConnId ? `?connection_id=${selectedConnId}` : '';
        const r = await authFetch(`${chatUrl()}/api/scheduled${params}`);
        if (!r.ok) throw new Error('Failed to load');
        const scheds = await r.json();
        renderSchedules(scheds);
    } catch (e) {
        container.innerHTML = `<p class="text-sm text-d-red p-4">${e.message}</p>`;
    }
}

function renderSchedules(scheds) {
    const container = document.getElementById('scheduledQueriesContent');
    if (!container) return;
    if (!scheds.length) {
        container.innerHTML = '<p class="text-sm text-d-muted p-4">No scheduled queries yet. Save a query first, then schedule it.</p>';
        return;
    }
    container.innerHTML = `<div class="grid gap-3" style="grid-template-columns:repeat(auto-fill,minmax(340px,1fr))">
        ${scheds.map(s => `
            <div class="bg-d-card border border-d-border rounded-xl p-4">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-sm font-semibold text-white">${_esc(s.name)}</span>
                    <span class="text-[10px] px-2 py-0.5 rounded ${s.is_active ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}">
                        ${s.is_active ? 'Active' : 'Paused'}
                    </span>
                </div>
                <div class="text-xs text-d-muted mb-2">
                    <span class="font-mono">${_esc(s.cron_expression)}</span>
                    · Runs: ${s.run_count}
                    ${s.last_run_at ? `· Last: ${_timeAgo(s.last_run_at)}` : ''}
                </div>
                ${s.alert_condition ? `<div class="text-xs text-yellow-400 mb-2">🔔 Alert: ${_esc(JSON.stringify(s.alert_condition))}</div>` : ''}
                <div class="flex gap-2">
                    <button class="chip" onclick="runScheduleNow(${s.id})">▶ Run Now</button>
                    <button class="chip" onclick="toggleSchedule(${s.id}, ${!s.is_active})">${s.is_active ? '⏸ Pause' : '▶ Resume'}</button>
                    <button class="chip" style="color:#f87171" onclick="deleteSchedule(${s.id})">🗑</button>
                </div>
            </div>
        `).join('')}
    </div>`;
}

async function openScheduleModal(savedQueryId, savedQueryName) {
    document.getElementById('schedSavedQueryId').value = savedQueryId;
    document.getElementById('schedName').value = savedQueryName + ' - Daily';
    document.getElementById('scheduleModal').classList.add('open');
}

function closeScheduleModal() {
    document.getElementById('scheduleModal').classList.remove('open');
}

async function submitSchedule() {
    const sqId = parseInt(document.getElementById('schedSavedQueryId').value);
    const name = document.getElementById('schedName').value.trim();
    const preset = document.getElementById('schedPreset').value;
    const customCron = document.getElementById('schedCustomCron').value.trim();
    const alertType = document.getElementById('schedAlertType').value;
    const alertValue = document.getElementById('schedAlertValue').value;

    if (!name) { showToast('Name required'); return; }

    const body = {
        saved_query_id: sqId,
        name,
        cron_preset: preset !== 'custom' ? preset : undefined,
        cron_expression: preset === 'custom' ? customCron : undefined,
    };
    if (alertType && alertType !== 'none') {
        body.alert_condition = { type: alertType, op: '>', value: parseInt(alertValue) || 0 };
    }

    try {
        const r = await authFetch(`${chatUrl()}/api/scheduled`, {
            method: 'POST',
            body: JSON.stringify(body),
        });
        if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Failed'); }
        closeScheduleModal();
        showToast('Schedule created');
        loadSchedules();
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

async function runScheduleNow(id) {
    try {
        const r = await authFetch(`${chatUrl()}/api/scheduled/${id}/run`, { method: 'POST' });
        const data = await r.json();
        if (data.alert_triggered) {
            showToast(`🔔 Alert! ${data.alert_message}`);
        } else {
            showToast(`Completed: ${data.row_count} rows`);
        }
        loadSchedules();
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

async function toggleSchedule(id, active) {
    try {
        await authFetch(`${chatUrl()}/api/scheduled/${id}`, {
            method: 'PUT',
            body: JSON.stringify({ is_active: active }),
        });
        loadSchedules();
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

async function deleteSchedule(id) {
    if (!confirm('Delete this schedule?')) return;
    try {
        await authFetch(`${chatUrl()}/api/scheduled/${id}`, { method: 'DELETE' });
        loadSchedules();
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

// ═══════ F7: Write-Back ═════════════════════════════════

async function loadWritebacks() {
    const container = document.getElementById('writebackContent');
    if (!container) return;
    try {
        const params = selectedConnId ? `?connection_id=${selectedConnId}` : '';
        const r = await authFetch(`${chatUrl()}/api/writeback${params}`);
        if (!r.ok) throw new Error('Failed');
        const wbs = await r.json();
        renderWritebacks(wbs);
    } catch (e) {
        container.innerHTML = `<p class="text-sm text-d-red p-4">${e.message}</p>`;
    }
}

function renderWritebacks(wbs) {
    const container = document.getElementById('writebackContent');
    if (!container) return;
    if (!wbs.length) {
        container.innerHTML = '<p class="text-sm text-d-muted p-4">No write-back requests yet.</p>';
        return;
    }
    const statusColors = { pending: 'text-yellow-400', approved: 'text-blue-400', rejected: 'text-red-400', executed: 'text-green-400', failed: 'text-red-400' };
    container.innerHTML = wbs.map(w => `
        <div class="bg-d-card border border-d-border rounded-xl p-4 mb-3">
            <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                    <span class="text-xs font-semibold px-2 py-0.5 rounded bg-d-input ${statusColors[w.status] || 'text-d-muted'}">${w.status.toUpperCase()}</span>
                    <span class="text-xs text-d-muted">${w.operation_type}</span>
                    <span class="text-xs text-d-accent">${_esc(w.target_table)}</span>
                </div>
                <span class="text-[10px] text-d-muted">${_timeAgo(w.created_at)}</span>
            </div>
            <div class="sql-block text-xs mb-2" style="max-height:80px;overflow:auto">${_esc(w.sql)}</div>
            ${w.reason ? `<div class="text-xs text-d-muted mb-2">Reason: ${_esc(w.reason)}</div>` : ''}
            ${w.rows_affected != null ? `<div class="text-xs text-d-green mb-2">Rows affected: ${w.rows_affected}</div>` : ''}
            <div class="flex gap-2">
                ${w.status === 'pending' && _isAnyAdmin() ? `
                    <button class="chip" style="color:#34d399" onclick="approveWriteback(${w.id})">✓ Approve</button>
                    <button class="chip" style="color:#f87171" onclick="rejectWriteback(${w.id})">✕ Reject</button>
                ` : ''}
                ${w.status === 'approved' && _isAnyAdmin() ? `
                    <button class="chip" onclick="executeWriteback(${w.id})">▶ Execute</button>
                ` : ''}
            </div>
        </div>
    `).join('');
}

function openWritebackModal() {
    document.getElementById('writebackModal').classList.add('open');
    document.getElementById('wbSql').value = '';
    document.getElementById('wbReason').value = '';
}

function closeWritebackModal() {
    document.getElementById('writebackModal').classList.remove('open');
}

async function submitWriteback() {
    const sql = document.getElementById('wbSql').value.trim();
    const reason = document.getElementById('wbReason').value.trim();
    if (!sql) { showToast('SQL required'); return; }
    try {
        const r = await authFetch(`${chatUrl()}/api/writeback`, {
            method: 'POST',
            body: JSON.stringify({ connection_id: selectedConnId, sql, reason: reason || null }),
        });
        if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Failed'); }
        closeWritebackModal();
        showToast('Write-back request submitted');
        loadWritebacks();
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

async function approveWriteback(id) {
    try {
        await authFetch(`${chatUrl()}/api/writeback/${id}/approve`, { method: 'POST' });
        showToast('Approved');
        loadWritebacks();
    } catch (e) { showToast('Error: ' + e.message); }
}
async function rejectWriteback(id) {
    try {
        await authFetch(`${chatUrl()}/api/writeback/${id}/reject`, { method: 'POST' });
        showToast('Rejected');
        loadWritebacks();
    } catch (e) { showToast('Error: ' + e.message); }
}
async function executeWriteback(id) {
    if (!confirm('Execute this write-back? This will modify data.')) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/writeback/${id}/execute`, { method: 'POST' });
        const data = await r.json();
        showToast(data.status === 'executed' ? `Executed: ${data.rows_affected} rows affected` : 'Execution failed');
        loadWritebacks();
    } catch (e) { showToast('Error: ' + e.message); }
}

// ═══════ F8: Multi-Query Workbench ══════════════════════

let workbenchPanes = [{ id: 'wb-1', sql: '', label: 'Query 1' }];
let workbenchResults = {};

function renderWorkbench() {
    const container = document.getElementById('workbenchContent');
    if (!container) return;
    container.innerHTML = `
        <div class="flex items-center gap-2 mb-3">
            <button class="chip" onclick="addWorkbenchPane()">＋ Add Query</button>
            <button class="chip" onclick="executeWorkbench()" style="background:rgba(124,110,255,.15);color:#a78bfa;border-color:rgba(124,110,255,.3)">▶ Run All</button>
            <button class="chip" onclick="diffWorkbench()">⇔ Diff First Two</button>
        </div>
        <div class="grid gap-4" style="grid-template-columns:repeat(auto-fill,minmax(480px,1fr))">
            ${workbenchPanes.map((p, i) => `
                <div class="bg-d-card border border-d-border rounded-xl overflow-hidden">
                    <div class="px-3 py-2 border-b border-d-border flex items-center justify-between bg-d-surface">
                        <input class="bg-transparent text-xs text-white font-semibold outline-none flex-1" 
                               value="${_esc(p.label)}" onchange="workbenchPanes[${i}].label=this.value">
                        ${i > 0 ? `<button class="text-d-muted hover:text-d-red text-xs ml-2" onclick="removeWorkbenchPane(${i})">✕</button>` : ''}
                    </div>
                    <textarea id="${p.id}-sql" class="w-full bg-d-input text-xs text-d-text font-mono p-3 outline-none resize-none"
                              rows="5" placeholder="Enter SQL…" oninput="workbenchPanes[${i}].sql=this.value">${_esc(p.sql)}</textarea>
                    <div id="${p.id}-result" class="p-2 max-h-64 overflow-auto text-xs">
                        ${workbenchResults[p.id] ? renderWorkbenchResult(workbenchResults[p.id]) : '<span class="text-d-muted">Results will appear here</span>'}
                    </div>
                </div>
            `).join('')}
        </div>
        <div id="workbenchDiffResult" class="mt-4"></div>
    `;
}

function addWorkbenchPane() {
    const n = workbenchPanes.length + 1;
    workbenchPanes.push({ id: `wb-${Date.now()}`, sql: '', label: `Query ${n}` });
    renderWorkbench();
}

function removeWorkbenchPane(idx) {
    workbenchPanes.splice(idx, 1);
    renderWorkbench();
}

async function executeWorkbench() {
    if (!selectedConnId) { showToast('Select a database first'); return; }
    const queries = workbenchPanes.map(p => ({
        id: p.id,
        connection_id: selectedConnId,
        sql: (cmEditors[p.id] ? cmEditors[p.id].getValue() : '') || p.sql || document.getElementById(`${p.id}-sql`)?.value || '',
        label: p.label,
    })).filter(q => q.sql.trim());

    if (!queries.length) { showToast('Enter at least one query'); return; }

    try {
        const r = await authFetch(`${chatUrl()}/api/workbench/execute`, {
            method: 'POST',
            body: JSON.stringify({ queries }),
        });
        if (!r.ok) throw new Error('Failed');
        const data = await r.json();
        data.results.forEach(res => { workbenchResults[res.id] = res; });
        renderWorkbench();
        showToast(`${data.results.length} queries completed in ${data.total_time_ms}ms`);
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

function renderWorkbenchResult(res) {
    if (!res.success) return `<span class="text-d-red">${_esc(res.error || 'Failed')}</span>`;
    if (!res.rows.length) return `<span class="text-d-muted">No rows returned (${res.execution_time_ms}ms)</span>`;
    let html = `<div class="text-d-muted mb-1">${res.row_count} rows · ${res.execution_time_ms}ms</div>`;
    html += `<div class="overflow-x-auto"><table class="dt"><thead><tr>${res.columns.map(c => `<th>${_esc(c)}</th>`).join('')}</tr></thead><tbody>`;
    for (const row of res.rows.slice(0, 50)) {
        html += `<tr>${res.columns.map(c => `<td>${_esc(String(row[c] ?? ''))}</td>`).join('')}</tr>`;
    }
    html += '</tbody></table></div>';
    return html;
}

async function diffWorkbench() {
    if (workbenchPanes.length < 2 || !selectedConnId) { showToast('Need at least 2 queries'); return; }
    const sqlA = (cmEditors[workbenchPanes[0].id] ? cmEditors[workbenchPanes[0].id].getValue() : '') || workbenchPanes[0].sql || '';
    const sqlB = (cmEditors[workbenchPanes[1].id] ? cmEditors[workbenchPanes[1].id].getValue() : '') || workbenchPanes[1].sql || '';
    if (!sqlA.trim() || !sqlB.trim()) { showToast('Both queries need SQL'); return; }

    try {
        const r = await authFetch(`${chatUrl()}/api/workbench/diff`, {
            method: 'POST',
            body: JSON.stringify({ connection_id: selectedConnId, sql_a: sqlA, sql_b: sqlB }),
        });
        if (!r.ok) throw new Error('Failed');
        const diff = await r.json();
        const el = document.getElementById('workbenchDiffResult');
        if (!el) return;
        el.innerHTML = `<div class="bg-d-card border border-d-border rounded-xl p-4">
            <h4 class="text-sm font-semibold text-white mb-2">Diff Results</h4>
            <div class="flex gap-4 text-xs mb-3">
                <span class="text-green-400">Only in Q1: ${diff.only_in_a}</span>
                <span class="text-blue-400">Only in Q2: ${diff.only_in_b}</span>
                <span class="text-d-muted">In both: ${diff.in_both}</span>
            </div>
            ${diff.differences.length ? `<div class="text-xs text-d-muted">${diff.differences.length} rows differ</div>` : '<div class="text-xs text-d-green">No differences in common rows</div>'}
        </div>`;
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

// ═══════ F9: Data Lineage ═══════════════════════════════

async function loadLineage() {
    const container = document.getElementById('lineageContent');
    if (!container || !selectedConnId) return;
    container.innerHTML = '<p class="text-sm text-d-muted p-4">Loading lineage…</p>';
    try {
        const r = await authFetch(`${chatUrl()}/api/lineage/${selectedConnId}`);
        if (!r.ok) throw new Error('Failed');
        const data = await r.json();
        renderLineage(data);
    } catch (e) {
        container.innerHTML = `<p class="text-sm text-d-red p-4">${e.message}</p>`;
    }
}

function renderLineage(data) {
    const container = document.getElementById('lineageContent');
    if (!container) return;

    // Build FK graph
    const fkDeps = data.dependencies.filter(d => d.dependency_type === 'fk_child');
    const coOccur = data.dependencies.filter(d => d.dependency_type === 'query_co_occurrence');

    let html = `<div class="grid gap-4" style="grid-template-columns:1fr 1fr">`;

    // FK dependency graph
    html += `<div class="bg-d-card border border-d-border rounded-xl p-4">
        <h4 class="text-sm font-semibold text-white mb-3">Foreign Key Dependencies</h4>
        ${fkDeps.length ? fkDeps.map(d => `
            <div class="flex items-center gap-2 text-xs py-1 border-b border-d-border/50">
                <span class="text-d-accent">${_esc(d.table_name)}</span>
                <span class="text-d-muted">→</span>
                <span class="text-d-accent">${_esc(d.related_table)}</span>
                <span class="text-[10px] text-d-muted ml-auto">${_esc(d.via_column || '')}</span>
            </div>
        `).join('') : '<p class="text-xs text-d-muted">No FK relationships found</p>'}
    </div>`;

    // Query co-occurrence
    html += `<div class="bg-d-card border border-d-border rounded-xl p-4">
        <h4 class="text-sm font-semibold text-white mb-3">Frequently Queried Together</h4>
        ${coOccur.length ? coOccur.slice(0, 15).map(d => `
            <div class="flex items-center gap-2 text-xs py-1 border-b border-d-border/50">
                <span class="text-d-text">${_esc(d.table_name)}</span>
                <span class="text-d-muted">↔</span>
                <span class="text-d-text">${_esc(d.related_table)}</span>
                <div class="ml-auto bg-d-accent/20 rounded-full h-1.5" style="width:${Math.round(d.strength * 60)}px"></div>
            </div>
        `).join('') : '<p class="text-xs text-d-muted">Not enough query history</p>'}
    </div>`;

    html += `</div>`;

    // Table usage ranking
    html += `<div class="bg-d-card border border-d-border rounded-xl p-4 mt-4">
        <h4 class="text-sm font-semibold text-white mb-3">Table Usage Ranking</h4>
        <div class="grid gap-2" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr))">
            ${data.table_usage.map(u => `
                <div class="flex items-center gap-2 p-2 bg-d-surface rounded-lg">
                    <span class="text-xs text-d-accent font-medium flex-1">${_esc(u.table_name)}</span>
                    <span class="text-[10px] text-d-muted">${u.query_count} queries</span>
                    <span class="text-[10px] text-d-muted">${u.unique_users} users</span>
                    <button class="text-[10px] text-d-accent" onclick="showImpact('${_esc(u.table_name)}')">Impact</button>
                </div>
            `).join('')}
        </div>
    </div>`;

    container.innerHTML = html;
}

async function showImpact(tableName) {
    if (!selectedConnId) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/lineage/impact/${selectedConnId}/${encodeURIComponent(tableName)}`);
        if (!r.ok) throw new Error('Failed');
        const data = await r.json();
        const msg = [
            `Impact Analysis: ${tableName}`,
            `Direct dependents: ${data.direct_dependents.join(', ') || 'none'}`,
            `Indirect dependents: ${data.indirect_dependents.join(', ') || 'none'}`,
            `Affected saved queries: ${data.affected_saved_queries}`,
            `Affected dashboards: ${data.affected_dashboards}`,
            `Impact score: ${data.total_impact_score}`,
        ].join('\n');
        alert(msg);
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

// ═══════ F10: Connection Intelligence ═══════════════════

async function loadIntelligence() {
    const container = document.getElementById('intelligenceContent');
    if (!container || !selectedConnId) return;
    container.innerHTML = '<p class="text-sm text-d-muted p-4">Loading database intelligence…</p>';
    try {
        const r = await authFetch(`${chatUrl()}/api/intelligence/${selectedConnId}`);
        if (!r.ok) throw new Error('Failed');
        const stats = await r.json();
        renderIntelligence(stats);
    } catch (e) {
        container.innerHTML = `<p class="text-sm text-d-red p-4">${e.message}</p>`;
    }
}

function renderIntelligence(stats) {
    const container = document.getElementById('intelligenceContent');
    if (!container) return;

    let html = `
    <!-- Stats cards -->
    <div class="flex flex-wrap gap-3 mb-4">
        <div class="stat-card"><div class="stat-val">${stats.total_tables}</div><div class="stat-lbl">Tables</div></div>
        <div class="stat-card"><div class="stat-val">${stats.total_columns}</div><div class="stat-lbl">Columns</div></div>
        <div class="stat-card"><div class="stat-val">${stats.total_queries_run}</div><div class="stat-lbl">Queries Run</div></div>
        <div class="stat-card"><div class="stat-val">${stats.avg_query_time_ms ? stats.avg_query_time_ms + 'ms' : '—'}</div><div class="stat-lbl">Avg Query Time</div></div>
        ${stats.db_size ? `<div class="stat-card"><div class="stat-val">${stats.db_size}</div><div class="stat-lbl">DB Size</div></div>` : ''}
        ${stats.connection_count != null ? `<div class="stat-card"><div class="stat-val">${stats.connection_count}</div><div class="stat-lbl">Connections</div></div>` : ''}
    </div>
    ${stats.db_version ? `<div class="text-xs text-d-muted mb-4">${_esc(stats.db_version)}</div>` : ''}`;

    // Table sizes
    if (stats.table_sizes.length) {
        html += `<div class="bg-d-card border border-d-border rounded-xl p-4 mb-4">
            <h4 class="text-sm font-semibold text-white mb-3">Table Sizes</h4>
            <table class="dt">
                <thead><tr><th>Table</th><th>Est. Rows</th><th>Total Size</th><th>Index Size</th></tr></thead>
                <tbody>
                    ${stats.table_sizes.map(t => `<tr>
                        <td class="text-d-accent">${_esc(t.table_name)}</td>
                        <td class="num">${t.estimated_rows != null ? t.estimated_rows.toLocaleString() : '—'}</td>
                        <td>${t.total_size || '—'}</td>
                        <td>${t.index_size || '—'}</td>
                    </tr>`).join('')}
                </tbody>
            </table>
        </div>`;
    }

    // Active queries
    if (stats.active_queries.length) {
        html += `<div class="bg-d-card border border-d-border rounded-xl p-4 mb-4">
            <h4 class="text-sm font-semibold text-white mb-3">Active Queries <span class="text-[10px] text-d-muted">(${stats.active_queries.length})</span></h4>
            ${stats.active_queries.map(q => `
                <div class="py-2 border-b border-d-border/50 text-xs">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-d-muted">PID ${q.pid}</span>
                        <span class="text-d-accent">${_esc(q.state || '')}</span>
                        <span class="text-d-muted ml-auto">${_esc(q.duration || '')}</span>
                    </div>
                    <div class="font-mono text-d-text truncate">${_esc((q.query || '').substring(0, 150))}</div>
                </div>
            `).join('')}
        </div>`;
    }

    // Index recommendations
    if (stats.index_recommendations.length) {
        html += `<div class="bg-d-card border border-d-border rounded-xl p-4 mb-4">
            <h4 class="text-sm font-semibold text-white mb-3">💡 Index Recommendations</h4>
            ${stats.index_recommendations.map(r => `
                <div class="flex items-start gap-2 py-2 border-b border-d-border/50 text-xs">
                    <span class="text-yellow-400 mt-0.5">⚡</span>
                    <div>
                        <span class="text-d-text font-medium">${_esc(r.column_name)}</span>
                        <span class="text-d-muted ml-1">(${_esc(r.table_name)})</span>
                        <div class="text-d-muted mt-0.5">${_esc(r.reason)}</div>
                    </div>
                </div>
            `).join('')}
        </div>`;
    }

    container.innerHTML = html;
}

// ═══════ LLM Provider Settings ══════════════════════════

async function loadLlmProviderSettings() {
    try {
        const r = await authFetch(`${chatUrl()}/api/llm/providers`);
        if (!r.ok) return;
        const d = await r.json();
        const sel = document.getElementById('llmProvider');
        if (sel) sel.value = d.active || 'ollama_local';
        const model = document.getElementById('llmModel');
        if (model) model.value = d.active_model || '';
        const url = document.getElementById('llmApiUrl');
        if (url) url.value = d.active_url || '';
        onLlmProviderSelect();
        checkLlmHealth();
    } catch { /* silent */ }
}

function onLlmProviderSelect() {
    const prov = document.getElementById('llmProvider')?.value;
    const keyWrap = document.getElementById('llmKeyWrap');
    const urlWrap = document.getElementById('llmUrlWrap');
    if (keyWrap) keyWrap.style.display = (prov === 'openai' || prov === 'anthropic') ? '' : 'none';
    if (urlWrap) urlWrap.style.display = (prov !== 'anthropic') ? '' : 'none';
}

async function saveLlmProvider() {
    const prov = document.getElementById('llmProvider')?.value;
    const model = document.getElementById('llmModel')?.value;
    const apiUrl = document.getElementById('llmApiUrl')?.value;
    const apiKey = document.getElementById('llmApiKey')?.value;
    const status = document.getElementById('llmSaveStatus');
    try {
        const r = await authFetch(`${chatUrl()}/api/llm/provider`, {
            method: 'POST',
            body: JSON.stringify({ provider: prov, model: model || undefined, api_url: apiUrl || undefined, api_key: apiKey || undefined }),
        });
        if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Failed'); }
        if (status) { status.textContent = '✓ Saved'; status.style.color = '#34d399'; setTimeout(() => { status.textContent = ''; }, 3000); }
        checkLlmHealth();
    } catch (e) {
        if (status) { status.textContent = 'Error: ' + e.message; status.style.color = '#f87171'; }
    }
}

async function checkLlmHealth() {
    const badge = document.getElementById('llmHealthBadge');
    if (!badge) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/llm/health`);
        if (!r.ok) throw new Error();
        const d = await r.json();
        badge.textContent = d.healthy ? '● Healthy' : '○ Unreachable';
        badge.style.color = d.healthy ? '#34d399' : '#f87171';
    } catch {
        badge.textContent = '○ Error';
        badge.style.color = '#f87171';
    }
}

// ═══════ Model Routing ═══════════════════════════════════

async function loadModelRouting() {
    const container = document.getElementById('modelRoutingContainer');
    if (!container) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/llm/model-routing`);
        if (!r.ok) { container.innerHTML = '<p class="text-xs text-red-400">Failed to load</p>'; return; }
        const d = await r.json();
        const roles = d.valid_roles || [];
        const roleCfgs = d.roles || {};
        const defaultCfg = d.default || {};
        const descs = d.role_descriptions || {};
        const providers = d.providers || [];

        let html = '';
        for (const role of roles) {
            const cfg = roleCfgs[role] || {};
            const hasOverride = !!cfg.provider;
            const providerVal = cfg.provider || '';
            const modelVal = cfg.model || '';
            const urlVal = cfg.api_url || '';
            const keyVal = cfg.api_key || '';
            const desc = descs[role] || '';
            const badge = hasOverride
                ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/40 text-emerald-400">Custom</span>`
                : `<span class="text-[10px] px-1.5 py-0.5 rounded bg-d-input text-d-muted">Default</span>`;

            html += `
            <div class="border border-d-border rounded-lg p-3" id="routeCard_${role}">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                        <span class="text-xs font-semibold text-white">${role}</span>
                        ${badge}
                    </div>
                    <div class="flex items-center gap-1">
                        <span id="routeHealth_${role}" class="text-[10px] text-d-muted"></span>
                        ${hasOverride ? `<button onclick="clearRoleProvider('${role}')" class="text-[10px] text-red-400 hover:text-red-300 px-1">✕ Clear</button>` : ''}
                    </div>
                </div>
                <p class="text-[10px] text-d-muted mb-2">${desc}</p>
                <div class="grid grid-cols-2 gap-2">
                    <div>
                        <label class="text-[10px] text-d-muted block mb-0.5">Provider</label>
                        <select id="routeProv_${role}" class="col-select text-xs" style="width:100%">
                            <option value="">— Use Default (${defaultCfg.provider || 'auto'}) —</option>
                            ${providers.map(p => `<option value="${p.id}" ${p.id === providerVal ? 'selected' : ''}>${p.name}</option>`).join('')}
                        </select>
                    </div>
                    <div>
                        <label class="text-[10px] text-d-muted block mb-0.5">Model</label>
                        <input id="routeModel_${role}" class="search-input text-xs" placeholder="e.g. mistral, gpt-4o" value="${modelVal}">
                    </div>
                    <div>
                        <label class="text-[10px] text-d-muted block mb-0.5">API URL</label>
                        <input id="routeUrl_${role}" class="search-input text-xs" placeholder="(optional)" value="${urlVal}">
                    </div>
                    <div>
                        <label class="text-[10px] text-d-muted block mb-0.5">API Key</label>
                        <input id="routeKey_${role}" type="password" class="search-input text-xs" placeholder="(optional)" value="${keyVal}">
                    </div>
                </div>
                <div class="mt-2 flex justify-end">
                    <button onclick="saveRoleProvider('${role}')" class="text-[10px] px-2 py-1 rounded bg-d-accent text-white hover:bg-d-accent/80">Save</button>
                </div>
            </div>`;
        }
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<p class="text-xs text-red-400">Error: ${e.message}</p>`;
    }
}

async function saveRoleProvider(role) {
    const prov = document.getElementById(`routeProv_${role}`)?.value;
    const model = document.getElementById(`routeModel_${role}`)?.value;
    const apiUrl = document.getElementById(`routeUrl_${role}`)?.value;
    const apiKey = document.getElementById(`routeKey_${role}`)?.value;
    const status = document.getElementById('routingSaveStatus');

    if (!prov) {
        await clearRoleProvider(role);
        return;
    }

    try {
        const r = await authFetch(`${chatUrl()}/api/llm/model-routing`, {
            method: 'POST',
            body: JSON.stringify({ role, provider: prov, model: model || undefined,
                                   api_url: apiUrl || undefined, api_key: apiKey || undefined }),
        });
        if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Failed'); }
        if (status) { status.textContent = `✓ ${role} saved`; status.style.color = '#34d399';
            setTimeout(() => { status.textContent = ''; }, 3000); }
        loadModelRouting();
    } catch (e) {
        if (status) { status.textContent = `Error: ${e.message}`; status.style.color = '#f87171'; }
    }
}

async function clearRoleProvider(role) {
    const status = document.getElementById('routingSaveStatus');
    try {
        const r = await authFetch(`${chatUrl()}/api/llm/model-routing`, {
            method: 'DELETE',
            body: JSON.stringify({ role }),
        });
        if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Failed'); }
        if (status) { status.textContent = `✓ ${role} cleared`; status.style.color = '#34d399';
            setTimeout(() => { status.textContent = ''; }, 3000); }
        loadModelRouting();
    } catch (e) {
        if (status) { status.textContent = `Error: ${e.message}`; status.style.color = '#f87171'; }
    }
}

// ═══════ DB Type Change (Admin) ═════════════════════════

function onDbTypeChange() {
    const dt = document.getElementById('adminRegType')?.value;
    const hostEl = document.getElementById('adminRegHost');
    const portEl = document.getElementById('adminRegPort');
    const userEl = document.getElementById('adminRegUser');
    const passEl = document.getElementById('adminRegPass');
    const isFile = (dt === 'sqlite' || dt === 'duckdb');
    if (hostEl) hostEl.placeholder = isFile ? '(not needed)' : 'e.g. localhost';
    if (portEl) portEl.value = isFile ? '' : (dt === 'mysql' ? '3306' : dt === 'sqlserver' ? '1433' : '5432');
    if (userEl) userEl.placeholder = isFile ? '(not needed)' : 'DB username';
    if (passEl) passEl.placeholder = isFile ? '(not needed)' : 'DB password';
    const dbEl = document.getElementById('adminRegDb');
    if (dbEl) dbEl.placeholder = isFile ? '/path/to/file.db' : 'Database name';
}

// ═══════ Query Templates ════════════════════════════════

let templateCategories = [];

async function loadTemplates() {
    const container = document.getElementById('templatesContent');
    if (!container) return;
    container.innerHTML = '<p class="text-sm text-d-muted p-4">Loading templates…</p>';
    try {
        // Load categories
        const catR = await authFetch(`${chatUrl()}/api/templates/categories`);
        if (catR.ok) {
            templateCategories = await catR.json();
            const sel = document.getElementById('templateCategoryFilter');
            if (sel) {
                const current = sel.value;
                sel.innerHTML = '<option value="">All categories</option>' +
                    templateCategories.map(c => `<option value="${_esc(c)}"${c === current ? ' selected' : ''}>${_esc(c)}</option>`).join('');
            }
        }

        const cat = document.getElementById('templateCategoryFilter')?.value || '';
        const params = cat ? `?category=${encodeURIComponent(cat)}` : '';
        const r = await authFetch(`${chatUrl()}/api/templates${params}`);
        if (!r.ok) throw new Error('Failed');
        const templates = await r.json();
        renderTemplates(templates);
    } catch (e) {
        container.innerHTML = `<p class="text-sm text-d-red p-4">${e.message}</p>`;
    }
}

function renderTemplates(templates) {
    const container = document.getElementById('templatesContent');
    if (!container) return;
    if (!templates.length) {
        container.innerHTML = '<p class="text-sm text-d-muted p-4">No templates found.</p>';
        return;
    }
    container.innerHTML = `<div class="grid gap-3" style="grid-template-columns:repeat(auto-fill,minmax(340px,1fr))">
        ${templates.map(t => {
            const vars = t.variables || [];
            return `<div class="bg-d-card border border-d-border rounded-xl p-4">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-sm font-semibold text-white">${_esc(t.name)}</span>
                    <span class="sq-folder-badge">${_esc(t.category)}</span>
                </div>
                ${t.description ? `<p class="text-xs text-d-muted mb-2">${_esc(t.description)}</p>` : ''}
                <div class="sql-block text-xs mb-3" style="max-height:60px;overflow:auto">${_esc(t.sql_template)}</div>
                ${vars.length ? `<div class="space-y-2 mb-3">
                    ${vars.map(v => `<div class="flex items-center gap-2">
                        <label class="text-[10px] text-d-muted w-20 shrink-0">${_esc(v.label)}</label>
                        <input class="search-input flex-1" style="font-size:11px;padding:4px 8px" id="tpl-${t.id}-${v.name}" value="${_esc(v.default || '')}" placeholder="${_esc(v.name)}">
                    </div>`).join('')}
                </div>` : ''}
                <div class="flex gap-2">
                    <button class="chip" onclick="useTemplate(${t.id}, ${JSON.stringify(vars.map(v=>v.name)).replace(/"/g,'&quot;')})">▶ Use in Workbench</button>
                    <span class="text-[10px] text-d-muted self-center">${t.use_count || 0} uses</span>
                </div>
            </div>`;
        }).join('')}
    </div>`;
}

async function useTemplate(templateId, varNames) {
    const variables = {};
    for (const name of varNames) {
        const el = document.getElementById(`tpl-${templateId}-${name}`);
        variables[name] = el ? el.value : '';
    }
    try {
        const r = await authFetch(`${chatUrl()}/api/templates/render`, {
            method: 'POST',
            body: JSON.stringify({ template_id: templateId, variables }),
        });
        if (!r.ok) throw new Error('Failed');
        const d = await r.json();
        // Add to workbench and switch
        workbenchPanes.push({ id: `wb-tpl-${Date.now()}`, sql: d.sql, label: d.template_name || 'Template' });
        switchTab('workbench');
        showToast('Template loaded into workbench');
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

// ═══════ Cross-Database Query ═══════════════════════════

async function loadCrossDbConnections() {
    const container = document.getElementById('crossDbConnectionList');
    if (!container) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/crossdb/connections`);
        if (!r.ok) return;
        const conns = await r.json();
        container.innerHTML = conns.map(c => `
            <label class="flex items-center gap-2 text-xs p-1.5 bg-d-surface rounded cursor-pointer hover:bg-d-hover">
                <input type="checkbox" class="crossdb-conn-cb" value="${c.id}" style="accent-color:#7c6eff">
                <span class="text-d-text">${_esc(c.name)}</span>
                <span class="text-[10px] text-d-muted">(${_esc(c.database_type)} · ${_esc(c.database)})</span>
            </label>
        `).join('');
    } catch { /* silent */ }
}

async function executeCrossDb() {
    const checkboxes = document.querySelectorAll('.crossdb-conn-cb:checked');
    const ids = Array.from(checkboxes).map(cb => parseInt(cb.value));
    const sql = document.getElementById('crossDbSql')?.value?.trim();
    const mode = document.getElementById('crossDbMergeMode')?.value || 'union';
    const status = document.getElementById('crossDbStatus');
    const results = document.getElementById('crossDbResults');

    if (!ids.length) { showToast('Select at least one database'); return; }
    if (!sql) { showToast('Enter a SQL query'); return; }

    if (status) status.textContent = 'Executing…';
    try {
        const r = await authFetch(`${chatUrl()}/api/crossdb/query`, {
            method: 'POST',
            body: JSON.stringify({ connection_ids: ids, sql, merge_mode: mode }),
        });
        if (!r.ok) throw new Error('Query failed');
        const data = await r.json();
        if (status) status.textContent = `Done in ${data.total_time_ms}ms`;
        renderCrossDbResults(data, results);
    } catch (e) {
        if (status) status.textContent = 'Error: ' + e.message;
    }
}

function renderCrossDbResults(data, container) {
    if (!container) return;
    if (data.merge_mode === 'union') {
        const cols = data.columns || [];
        let html = `<div class="bg-d-card border border-d-border rounded-xl p-4">
            <div class="text-xs text-d-muted mb-2">${data.total_rows} total rows across ${data.per_connection.length} databases</div>
            <div class="flex gap-2 mb-3">${data.per_connection.map(p => `
                <span class="text-[10px] px-2 py-0.5 rounded ${p.success ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}">
                    ${_esc(p.name)}: ${p.success ? p.row_count + ' rows' : p.error}
                </span>
            `).join('')}</div>
            <div class="overflow-x-auto max-h-96"><table class="dt"><thead><tr>${cols.map(c => `<th>${_esc(c)}</th>`).join('')}</tr></thead><tbody>
            ${data.rows.slice(0, 200).map(row => `<tr>${cols.map(c => `<td>${_esc(String(row[c] ?? ''))}</td>`).join('')}</tr>`).join('')}
            </tbody></table></div>
        </div>`;
        container.innerHTML = html;
    } else {
        let html = `<div class="grid gap-4" style="grid-template-columns:repeat(auto-fill,minmax(480px,1fr))">`;
        for (const res of data.results) {
            const cols = res.columns || [];
            const colNames = cols.map(c => typeof c === 'string' ? c : c.name);
            html += `<div class="bg-d-card border border-d-border rounded-xl p-4">
                <h4 class="text-sm font-semibold text-white mb-2">${_esc(res.connection_name)}</h4>
                <div class="text-xs text-d-muted mb-2">${res.success ? res.row_count + ' rows' : 'Error: ' + res.error}</div>
                ${res.success && res.rows.length ? `<div class="overflow-x-auto max-h-64"><table class="dt"><thead><tr>${colNames.map(c => `<th>${_esc(c)}</th>`).join('')}</tr></thead><tbody>
                    ${res.rows.slice(0, 100).map(row => `<tr>${colNames.map(c => `<td>${_esc(String(row[c] ?? ''))}</td>`).join('')}</tr>`).join('')}
                </tbody></table></div>` : ''}
            </div>`;
        }
        html += '</div>';
        container.innerHTML = html;
    }
}

// ═══════ AI Data Summarization (on-demand) ══════════════

async function requestSummary(prompt, columns, rows, rowCount) {
    if (!rows || !rows.length) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/summarize`, {
            method: 'POST',
            body: JSON.stringify({ prompt, columns, rows: rows.slice(0, 25), row_count: rowCount }),
        });
        if (!r.ok) return;
        const d = await r.json();
        if (d.summary) _appendSummaryCard(d.summary);
    } catch { /* silent */ }
}

// ═══════ CodeMirror Workbench Enhancement ═══════════════

let cmEditors = {};

function initWorkbenchEditor(paneId) {
    const el = document.getElementById(paneId + '-sql');
    if (!el || cmEditors[paneId]) return;
    const cm = CodeMirror.fromTextArea(el, {
        mode: 'text/x-pgsql',
        theme: 'material-darker',
        lineNumbers: true,
        lineWrapping: true,
        autofocus: false,
        extraKeys: { 'Ctrl-Space': 'autocomplete' },
        hintOptions: { tables: {} },
    });
    cm.setSize(null, 120);
    cm.on('change', () => {
        const idx = workbenchPanes.findIndex(p => p.id === paneId);
        if (idx >= 0) workbenchPanes[idx].sql = cm.getValue();
    });
    cmEditors[paneId] = cm;
    if (el.value) cm.setValue(el.value);
}

// Override renderWorkbench to use CodeMirror
const _origRenderWorkbench = typeof renderWorkbench === 'function' ? renderWorkbench : null;

function renderWorkbench() {
    cmEditors = {};
    const container = document.getElementById('workbenchContent');
    if (!container) return;
    container.innerHTML = `
        <div class="flex items-center gap-2 mb-3">
            <button class="chip" onclick="addWorkbenchPane()">＋ Add Query</button>
            <button class="chip" onclick="executeWorkbench()" style="background:rgba(124,110,255,.15);color:#a78bfa;border-color:rgba(124,110,255,.3)">▶ Run All</button>
            <button class="chip" onclick="diffWorkbench()">⇔ Diff First Two</button>
        </div>
        <div class="grid gap-4" style="grid-template-columns:repeat(auto-fill,minmax(480px,1fr))">
            ${workbenchPanes.map((p, i) => `
                <div class="bg-d-card border border-d-border rounded-xl overflow-hidden">
                    <div class="px-3 py-2 border-b border-d-border flex items-center justify-between bg-d-surface">
                        <input class="bg-transparent text-xs text-white font-semibold outline-none flex-1" 
                               value="${_esc(p.label)}" onchange="workbenchPanes[${i}].label=this.value">
                        ${i > 0 ? `<button class="text-d-muted hover:text-d-red text-xs ml-2" onclick="removeWorkbenchPane(${i})">✕</button>` : ''}
                    </div>
                    <textarea id="${p.id}-sql" class="w-full bg-d-input text-xs text-d-text font-mono p-3 outline-none resize-none"
                              rows="5" placeholder="Enter SQL…">${_esc(p.sql)}</textarea>
                    <div id="${p.id}-result" class="p-2 max-h-64 overflow-auto text-xs">
                        ${workbenchResults[p.id] ? renderWorkbenchResult(workbenchResults[p.id]) : '<span class="text-d-muted">Results will appear here</span>'}
                    </div>
                </div>
            `).join('')}
        </div>
        <div id="workbenchDiffResult" class="mt-4"></div>
    `;
    // Initialize CodeMirror on each pane after DOM render
    requestAnimationFrame(() => {
        workbenchPanes.forEach(p => initWorkbenchEditor(p.id));
    });
}

// ═══════ HELPERS ════════════════════════════════════════

function _esc(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}

function _timeAgo(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    const now = Date.now();
    const diff = now - d.getTime();
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
    return Math.floor(diff / 86400000) + 'd ago';
}


// ═══════════════════════════════════════════════════════════
//  NEW FEATURES – ERD, Quality, Optimizer, Training, Files,
//  Pipeline, API Generator, Migration, Embed
// ═══════════════════════════════════════════════════════════

// ── Helper: populate connection selects ───────────────────
async function _populateConnSelect(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/crossdb/connections`);
        if (!r.ok) return;
        const conns = await r.json();
        const current = sel.value;
        sel.innerHTML = '<option value="">— Select —</option>';
        conns.forEach(c => {
            sel.innerHTML += `<option value="${c.id}">${c.name} (${c.database_type})</option>`;
        });
        if (current) sel.value = current;
    } catch(e) { console.error(e); }
}

// ═══════ ERD Diagrams ══════════════════════════════════════
function initErdTab() { _populateConnSelect('erdConnectionSelect'); }

async function loadErd() {
    const connId = document.getElementById('erdConnectionSelect')?.value;
    const container = document.getElementById('erdDiagram');
    if (!connId || !container) return;
    container.innerHTML = '<p class="text-xs text-d-muted text-center">Generating ERD…</p>';
    try {
        const r = await authFetch(`${chatUrl()}/api/erd/${connId}`);
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        document.getElementById('erdMermaidText').value = data.mermaid;
        document.getElementById('erdMermaidSrc').style.display = '';
        container.innerHTML = `<div class="mermaid">${data.mermaid}</div>`;
        await mermaid.run({ nodes: container.querySelectorAll('.mermaid') });
    } catch(e) {
        container.innerHTML = `<p class="text-xs text-d-red">${e.message}</p>`;
    }
}

// ═══════ Data Quality ══════════════════════════════════════
function initQualityTab() { _populateConnSelect('qualityConnSelect'); }

async function loadQualityOverview() {
    const connId = document.getElementById('qualityConnSelect')?.value;
    const container = document.getElementById('qualityOverview');
    if (!connId || !container) return;
    container.innerHTML = '<p class="text-xs text-d-muted">Loading overview…</p>';
    try {
        const r = await authFetch(`${chatUrl()}/api/quality/score/${connId}`);
        if (!r.ok) throw new Error(await r.text());
        const tables = await r.json();
        let html = '<div class="grid gap-2" style="grid-template-columns:repeat(auto-fill,minmax(180px,1fr))">';
        tables.forEach(t => {
            const color = t.quality_score >= 90 ? '#34d399' : t.quality_score >= 70 ? '#fbbf24' : '#f87171';
            html += `<div class="stat-card cursor-pointer" onclick="document.getElementById('qualityTableInput').value='${t.table}';runQualityScan()">
                <div class="stat-val" style="color:${color}">${t.quality_score}%</div>
                <div class="stat-lbl">${t.table}</div>
                <div class="text-[10px] text-d-muted">${t.row_count?.toLocaleString()} rows</div>
            </div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch(e) { container.innerHTML = `<p class="text-xs text-d-red">${e.message}</p>`; }
}

async function runQualityScan() {
    const connId = document.getElementById('qualityConnSelect')?.value;
    const table = document.getElementById('qualityTableInput')?.value?.trim();
    const container = document.getElementById('qualityScanResult');
    if (!connId || !table || !container) return;
    container.innerHTML = '<p class="text-xs text-d-muted text-center">Scanning…</p>';
    try {
        const r = await authFetch(`${chatUrl()}/api/quality/scan`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({connection_id: parseInt(connId), table_name: table})
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        let html = `<div class="flex items-center gap-4 mb-3">
            <div class="stat-card"><div class="stat-val">${data.overall_score}%</div><div class="stat-lbl">Quality Score</div></div>
            <div class="stat-card"><div class="stat-val">${data.total_rows?.toLocaleString()}</div><div class="stat-lbl">Total Rows</div></div>
            <div class="stat-card"><div class="stat-val">${data.columns?.length || 0}</div><div class="stat-lbl">Columns</div></div>
        </div>`;
        if (data.issues?.length) {
            html += '<div class="mb-3">';
            data.issues.forEach(iss => {
                const color = iss.severity === 'warning' ? '#fbbf24' : '#6b7084';
                html += `<div class="text-xs mb-1" style="color:${color}">⚠ ${iss.message}</div>`;
            });
            html += '</div>';
        }
        if (data.columns?.length) {
            html += '<table class="dt"><thead><tr><th>Column</th><th>Type</th><th>Completeness</th><th>Nulls</th><th>Distinct</th><th>Uniqueness</th></tr></thead><tbody>';
            data.columns.forEach(c => {
                const compColor = c.completeness >= 95 ? '#34d399' : c.completeness >= 80 ? '#fbbf24' : '#f87171';
                html += `<tr><td>${c.name}</td><td class="text-d-muted">${c.type}</td>
                    <td><span style="color:${compColor}">${c.completeness}%</span></td>
                    <td class="num">${c.null_count?.toLocaleString()}</td>
                    <td class="num">${c.distinct_count?.toLocaleString() || '—'}</td>
                    <td class="num">${c.uniqueness != null ? c.uniqueness + '%' : '—'}</td></tr>`;
            });
            html += '</tbody></table>';
        }
        container.innerHTML = html;
    } catch(e) { container.innerHTML = `<p class="text-xs text-d-red">${e.message}</p>`; }
}

// ═══════ Query Optimizer ═══════════════════════════════════
function initOptimizerTab() { _populateConnSelect('optimizerConnSelect'); }

async function runOptimizer() {
    const connId = document.getElementById('optimizerConnSelect')?.value;
    const sql = document.getElementById('optimizerSqlInput')?.value?.trim();
    const container = document.getElementById('optimizerResult');
    const status = document.getElementById('optimizerStatus');
    if (!connId || !sql || !container) return;
    if (status) status.textContent = 'Analyzing…';
    container.innerHTML = '';
    try {
        const r = await authFetch(`${chatUrl()}/api/optimizer/analyze`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({connection_id: parseInt(connId), sql})
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        let html = '';
        if (data.issues?.length) {
            html += '<div class="bg-d-card border border-d-border rounded-xl p-4 mb-3"><h3 class="text-sm font-semibold text-white mb-2">Issues Found</h3>';
            data.issues.forEach(iss => {
                const color = iss.severity === 'high' ? '#f87171' : iss.severity === 'medium' ? '#fbbf24' : '#6b7084';
                html += `<div class="text-xs mb-1" style="color:${color}">● ${iss.message}</div>`;
            });
            html += '</div>';
        }
        if (data.suggestions?.length) {
            html += '<div class="bg-d-card border border-d-border rounded-xl p-4 mb-3"><h3 class="text-sm font-semibold text-d-green mb-2">Suggestions</h3>';
            data.suggestions.forEach(s => { html += `<div class="text-xs text-d-text mb-1">→ ${s}</div>`; });
            html += '</div>';
        }
        if (data.optimized_sql) {
            html += `<div class="bg-d-card border border-d-border rounded-xl p-4"><h3 class="text-sm font-semibold text-d-accent mb-2">Optimized SQL</h3>
                <div class="sql-block">${data.optimized_sql}</div>
                <button onclick="document.getElementById('optimizerSqlInput').value=\`${data.optimized_sql.replace(/`/g,'\\`')}\`" class="chip mt-2">Use This Query</button></div>`;
        }
        if (data.explain_plan) {
            html += `<details class="mt-3"><summary class="text-xs text-d-muted cursor-pointer">EXPLAIN Plan (JSON)</summary>
                <pre class="sql-block mt-1" style="font-size:11px">${JSON.stringify(data.explain_plan, null, 2)}</pre></details>`;
        }
        container.innerHTML = html || '<p class="text-xs text-d-green">No issues found.</p>';
        if (status) status.textContent = '';
    } catch(e) {
        container.innerHTML = `<p class="text-xs text-d-red">${e.message}</p>`;
        if (status) status.textContent = '';
    }
}

// ═══════ Training / RAG ════════════════════════════════════
function initTrainingTab() { _populateConnSelect('trainingConnSelect'); loadTrainingPairs(); }

async function loadTrainingPairs() {
    const connId = document.getElementById('trainingConnSelect')?.value;
    const container = document.getElementById('trainingPairsList');
    if (!container) return;
    try {
        let url = `${chatUrl()}/api/training?limit=50`;
        if (connId) url += `&connection_id=${connId}`;
        const r = await authFetch(url);
        if (!r.ok) return;
        const pairs = await r.json();
        if (!pairs.length) { container.innerHTML = '<p class="text-xs text-d-muted">No training pairs yet.</p>'; return; }
        let html = '<table class="dt"><thead><tr><th>Question</th><th>Query</th><th>Type</th><th>Verified</th><th>Votes</th><th></th></tr></thead><tbody>';
        pairs.forEach(p => {
            html += `<tr>
                <td class="text-xs">${p.question}</td>
                <td class="text-xs font-mono text-d-accent" style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.query}</td>
                <td class="text-xs text-d-muted">${p.query_type}</td>
                <td>${p.is_verified ? '✅' : '⏳'}</td>
                <td class="num">${p.upvotes || 0}</td>
                <td>
                    <button onclick="upvoteTrainingPair(${p.id})" class="chip" style="padding:2px 6px;font-size:10px">👍</button>
                    <button onclick="deleteTrainingPair(${p.id})" class="chip" style="padding:2px 6px;font-size:10px;color:#f87171">✕</button>
                </td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch(e) { container.innerHTML = `<p class="text-xs text-d-red">${e.message}</p>`; }
}

async function addTrainingPair() {
    const connId = document.getElementById('trainingConnSelect')?.value || selectedConnId;
    const question = document.getElementById('trainQuestion')?.value?.trim();
    const query = document.getElementById('trainQuery')?.value?.trim();
    if (!connId || !question || !query) return alert('Fill all fields');
    try {
        await authFetch(`${chatUrl()}/api/training`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({connection_id: parseInt(connId), question, query})
        });
        document.getElementById('trainQuestion').value = '';
        document.getElementById('trainQuery').value = '';
        loadTrainingPairs();
    } catch(e) { console.error(e); }
}

async function upvoteTrainingPair(id) {
    await authFetch(`${chatUrl()}/api/training/${id}/upvote`, {method:'POST'});
    loadTrainingPairs();
}

async function deleteTrainingPair(id) {
    if (!confirm('Delete this training pair?')) return;
    await authFetch(`${chatUrl()}/api/training/${id}`, {method:'DELETE'});
    loadTrainingPairs();
}

// ═══════ File Upload ═══════════════════════════════════════
function initFileUploadTab() { loadUploadedTables(); }

async function handleFileUpload() {
    const input = document.getElementById('fileUploadInput');
    const status = document.getElementById('fileUploadStatus');
    if (!input.files?.length) return;
    const file = input.files[0];
    if (status) status.textContent = `Uploading ${file.name}…`;
    const fd = new FormData();
    fd.append('file', file);
    try {
        const r = await authFetch(`${chatUrl()}/api/files/upload`, {method:'POST', body:fd});
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        if (status) status.textContent = data.message || 'Uploaded';
        loadUploadedTables();
        document.getElementById('fileQuerySection').style.display = '';
    } catch(e) { if (status) status.textContent = `Error: ${e.message}`; }
}

async function loadUploadedTables() {
    const container = document.getElementById('uploadedTables');
    if (!container) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/files/tables`);
        if (!r.ok) return;
        const tables = await r.json();
        if (!tables.length) { container.innerHTML = ''; return; }
        let html = '<div class="bg-d-card border border-d-border rounded-xl p-3"><h3 class="text-sm font-semibold text-white mb-2">Uploaded Tables</h3><div class="space-y-1">';
        tables.forEach(t => {
            html += `<div class="flex items-center justify-between bg-d-input border border-d-border rounded-lg px-3 py-2">
                <span class="text-xs font-mono text-d-accent">${t.name}</span>
                <span class="text-[10px] text-d-muted">${t.row_count?.toLocaleString()} rows · ${t.columns?.length} cols</span>
                <button onclick="dropUploadedTable('${t.name}')" class="text-xs text-d-red hover:underline">Delete</button>
            </div>`;
        });
        html += '</div></div>';
        container.innerHTML = html;
        document.getElementById('fileQuerySection').style.display = '';
    } catch(e) { console.error(e); }
}

async function queryUploadedFile() {
    const sql = document.getElementById('fileQuerySql')?.value?.trim();
    const container = document.getElementById('fileQueryResult');
    if (!sql || !container) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/files/query?sql=${encodeURIComponent(sql)}`, {method:'POST'});
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        if (!data.success) { container.innerHTML = `<p class="text-xs text-d-red">${data.error}</p>`; return; }
        let html = `<p class="text-xs text-d-muted mb-2">${data.row_count} rows</p>`;
        if (data.rows?.length) {
            html += '<div style="max-height:400px;overflow:auto"><table class="dt"><thead><tr>';
            data.columns.forEach(c => { html += `<th>${c}</th>`; });
            html += '</tr></thead><tbody>';
            data.rows.slice(0, 200).forEach(row => {
                html += '<tr>';
                data.columns.forEach(c => { html += `<td>${row[c] ?? ''}</td>`; });
                html += '</tr>';
            });
            html += '</tbody></table></div>';
        }
        container.innerHTML = html;
    } catch(e) { container.innerHTML = `<p class="text-xs text-d-red">${e.message}</p>`; }
}

async function dropUploadedTable(name) {
    if (!confirm(`Delete table "${name}"?`)) return;
    await authFetch(`${chatUrl()}/api/files/table/${name}`, {method:'DELETE'});
    loadUploadedTables();
}

// ═══════ Data Pipeline ═════════════════════════════════════
function initPipelineTab() {
    _populateConnSelect('pipelineSrcConn');
    _populateConnSelect('pipelineTgtConn');
}

async function executePipeline() {
    const src = document.getElementById('pipelineSrcConn')?.value;
    const tgt = document.getElementById('pipelineTgtConn')?.value;
    const sql = document.getElementById('pipelineExtractSql')?.value?.trim();
    const table = document.getElementById('pipelineTargetTable')?.value?.trim();
    const mode = document.getElementById('pipelineMode')?.value;
    const container = document.getElementById('pipelineResult');
    const status = document.getElementById('pipelineStatus');
    if (!src || !tgt || !sql || !table) return alert('Fill all fields');
    if (status) status.textContent = 'Running pipeline…';
    try {
        const r = await authFetch(`${chatUrl()}/api/pipeline/execute`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({name:'Manual', source_connection_id:parseInt(src), target_connection_id:parseInt(tgt), extract_sql:sql, target_table:table, mode})
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        container.innerHTML = `<div class="bg-d-card border border-d-border rounded-xl p-4">
            <p class="text-sm text-d-green font-semibold">Pipeline completed</p>
            <p class="text-xs text-d-muted mt-1">${data.rows_transferred} rows transferred to "${data.target_table}" in ${data.elapsed_ms}ms</p>
        </div>`;
        if (status) status.textContent = '';
    } catch(e) {
        container.innerHTML = `<p class="text-xs text-d-red">${e.message}</p>`;
        if (status) status.textContent = '';
    }
}

async function previewPipeline() {
    const src = document.getElementById('pipelineSrcConn')?.value;
    const sql = document.getElementById('pipelineExtractSql')?.value?.trim();
    const container = document.getElementById('pipelineResult');
    if (!src || !sql) return alert('Select source and enter SQL');
    try {
        const r = await authFetch(`${chatUrl()}/api/pipeline/preview?connection_id=${src}&sql=${encodeURIComponent(sql)}&limit=10`);
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        let html = `<p class="text-xs text-d-muted mb-2">Preview (${data.row_count} rows)</p>`;
        if (data.rows?.length) {
            html += '<div style="max-height:300px;overflow:auto"><table class="dt"><thead><tr>';
            data.columns.forEach(c => { html += `<th>${c}</th>`; });
            html += '</tr></thead><tbody>';
            data.rows.forEach(row => {
                html += '<tr>';
                data.columns.forEach(c => { html += `<td>${row[c] ?? ''}</td>`; });
                html += '</tr>';
            });
            html += '</tbody></table></div>';
        }
        container.innerHTML = html;
    } catch(e) { container.innerHTML = `<p class="text-xs text-d-red">${e.message}</p>`; }
}

// ═══════ API Generator ═════════════════════════════════════
async function initApiGenTab() {
    try {
        const r = await authFetch(`${chatUrl()}/api/saved-queries?limit=100`);
        if (!r.ok) return;
        const queries = await r.json();
        const sel = document.getElementById('apiGenQuerySelect');
        if (!sel) return;
        sel.innerHTML = '<option value="">— Select saved query —</option>';
        queries.forEach(q => { sel.innerHTML += `<option value="${q.id}">${q.name || q.sql?.substring(0,50)}</option>`; });
    } catch(e) { console.error(e); }
    loadApiEndpoints();
}

async function generateApiEndpoint() {
    const queryId = document.getElementById('apiGenQuerySelect')?.value;
    const slug = document.getElementById('apiGenSlug')?.value?.trim();
    if (!queryId || !slug) return alert('Select a query and enter a slug');
    try {
        const r = await authFetch(`${chatUrl()}/api/endpoints/generate`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({saved_query_id: parseInt(queryId), path_slug: slug})
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        alert(`Endpoint created! URL: ${data.url}\nAPI Key: ${data.api_key}`);
        loadApiEndpoints();
    } catch(e) { alert('Error: ' + e.message); }
}

async function loadApiEndpoints() {
    const container = document.getElementById('apiGenList');
    if (!container) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/endpoints`);
        if (!r.ok) return;
        const endpoints = await r.json();
        if (!endpoints.length) { container.innerHTML = '<p class="text-xs text-d-muted">No endpoints created yet.</p>'; return; }
        let html = '<table class="dt"><thead><tr><th>URL</th><th>Method</th><th>API Key</th><th>Calls</th><th>Created</th><th></th></tr></thead><tbody>';
        endpoints.forEach(ep => {
            html += `<tr>
                <td class="font-mono text-d-accent text-xs">${ep.url}</td>
                <td>${ep.method}</td>
                <td class="text-xs text-d-muted">${ep.api_key}</td>
                <td class="num">${ep.call_count}</td>
                <td class="text-xs text-d-muted">${ep.created_at ? new Date(ep.created_at).toLocaleDateString() : ''}</td>
                <td><button onclick="deleteApiEndpoint(${ep.id})" class="chip" style="padding:2px 6px;font-size:10px;color:#f87171">✕</button></td>
            </tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch(e) { console.error(e); }
}

async function deleteApiEndpoint(id) {
    if (!confirm('Delete this endpoint?')) return;
    await authFetch(`${chatUrl()}/api/endpoints/${id}`, {method:'DELETE'});
    loadApiEndpoints();
}

// ═══════ Schema Migration ══════════════════════════════════
function initMigrationTab() { _populateConnSelect('migrationConnSelect'); }

async function generateMigration(dryRun) {
    const connId = document.getElementById('migrationConnSelect')?.value;
    const desc = document.getElementById('migrationDescription')?.value?.trim();
    const container = document.getElementById('migrationResult');
    const status = document.getElementById('migrationStatus');
    if (!connId || !desc) return alert('Select connection and describe the change');
    if (status) status.textContent = dryRun ? 'Generating…' : 'Executing…';
    if (!dryRun && !confirm('This will execute the migration against your live database. Continue?')) {
        if (status) status.textContent = '';
        return;
    }
    try {
        const r = await authFetch(`${chatUrl()}/api/migration/generate`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({connection_id: parseInt(connId), description: desc, dry_run: dryRun})
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        let html = `<div class="bg-d-card border border-d-border rounded-xl p-4">
            <div class="flex items-center gap-2 mb-2">
                <span class="text-sm font-semibold ${data.executed ? 'text-d-green' : 'text-d-accent'}">${data.executed ? '✅ Migration Executed' : '📝 Migration Script (Dry Run)'}</span>
                <span class="text-[10px] text-d-muted">${data.dialect}</span>
            </div>
            <div class="sql-block">${data.migration_sql}</div>`;
        if (data.error) html += `<p class="text-xs text-d-red mt-2">Error: ${data.error}</p>`;
        if (data.message) html += `<p class="text-xs text-d-green mt-2">${data.message}</p>`;
        html += '</div>';
        container.innerHTML = html;
        if (status) status.textContent = '';
    } catch(e) {
        container.innerHTML = `<p class="text-xs text-d-red">${e.message}</p>`;
        if (status) status.textContent = '';
    }
}

// ═══════ Embeddable Widget ═════════════════════════════════
function initEmbedTab() { _populateConnSelect('embedConnSelect'); loadEmbedTokens(); }

async function createEmbedWidget() {
    const connId = document.getElementById('embedConnSelect')?.value;
    const title = document.getElementById('embedTitle')?.value || 'Database Chat';
    if (!connId) return alert('Select a connection');
    try {
        const r = await authFetch(`${chatUrl()}/api/embed/create`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({connection_id: parseInt(connId), title})
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        document.getElementById('embedCode').value = data.snippet;
        document.getElementById('embedSnippet').style.display = '';
        loadEmbedTokens();
    } catch(e) { alert('Error: ' + e.message); }
}

async function loadEmbedTokens() {
    const container = document.getElementById('embedTokensList');
    if (!container) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/embed/tokens`);
        if (!r.ok) return;
        const tokens = await r.json();
        if (!tokens.length) { container.innerHTML = ''; return; }
        let html = '<h3 class="text-sm font-semibold text-white mb-2">Active Widgets</h3>';
        tokens.forEach(t => {
            html += `<div class="flex items-center gap-3 bg-d-card border border-d-border rounded-lg px-3 py-2 mb-1">
                <span class="text-xs text-d-accent">${t.title}</span>
                <span class="text-[10px] text-d-muted">Token: ${t.token}</span>
                <span class="text-[10px] text-d-muted">Theme: ${t.theme}</span>
            </div>`;
        });
        container.innerHTML = html;
    } catch(e) { console.error(e); }
}

// ═══════════════════════════════════════════════════════════
// ═══════ KNOWLEDGE GRAPH ═════════════════════════════════
// ═══════════════════════════════════════════════════════════

async function loadKnowledgeTab() {
    loadConcepts();
    populateKnowledgeDropdowns();
}

async function populateKnowledgeDropdowns() {
    try {
        const r = await authFetch(`${chatUrl()}/api/admin/databases`);
        const dbs = await r.json();
        for (const sel of ['mappingConn','annotConn']) {
            const el = document.getElementById(sel);
            if (!el) continue;
            el.innerHTML = '<option value="">Connection</option>' +
                dbs.map(d => `<option value="${d.id}">${d.name}</option>`).join('');
        }
    } catch(e) {}
}

async function loadConcepts() {
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/concepts`);
        const concepts = await r.json();
        const el = document.getElementById('conceptsContent');
        if (!concepts.length) { el.innerHTML = '<p class="text-d-muted text-xs">No concepts yet. Create one above or run auto-discovery.</p>'; return; }

        const conceptSelect = document.getElementById('mappingConcept');
        if (conceptSelect) {
            conceptSelect.innerHTML = '<option value="">Concept</option>' +
                concepts.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
        }

        el.innerHTML = concepts.map(c => `
            <div class="bg-d-card border border-d-border rounded-lg p-3 mb-2 flex items-center justify-between">
                <div class="flex-1">
                    <span class="text-white font-semibold text-sm">${c.name}</span>
                    ${c.category ? `<span class="text-[10px] text-d-muted ml-2 bg-d-input px-2 py-0.5 rounded">${c.category}</span>` : ''}
                    ${c.description ? `<p class="text-xs text-d-muted mt-1">${c.description}</p>` : ''}
                    <span class="text-[10px] text-d-muted">${c.mapping_count} column mapping(s)</span>
                </div>
                <div class="flex gap-2">
                    <button onclick="viewConcept(${c.id})" class="chip text-[10px]">View</button>
                    <button onclick="deleteConcept(${c.id})" class="chip text-[10px]" style="color:#f87171">Delete</button>
                </div>
            </div>
        `).join('');
    } catch(e) { console.error('loadConcepts:', e); }
}

async function createConcept() {
    const name = document.getElementById('conceptName')?.value?.trim();
    const desc = document.getElementById('conceptDesc')?.value?.trim();
    const cat = document.getElementById('conceptCategory')?.value?.trim();
    if (!name) return alert('Concept name is required');
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/concepts`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({name, description: desc, category: cat})
        });
        if (!r.ok) { const e = await r.json(); return alert(e.detail || 'Error'); }
        document.getElementById('conceptName').value = '';
        document.getElementById('conceptDesc').value = '';
        document.getElementById('conceptCategory').value = '';
        loadConcepts();
    } catch(e) { alert('Error: ' + e.message); }
}

async function viewConcept(id) {
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/concepts/${id}`);
        const c = await r.json();
        let msg = `Concept: ${c.name}\n${c.description || ''}\n\nMappings:\n`;
        if (c.mappings.length === 0) msg += '  (none yet)';
        else c.mappings.forEach(m => { msg += `  conn=${m.connection_id} ${m.table_name}.${m.column_name} (${m.confidence}% via ${m.source})\n`; });
        alert(msg);
    } catch(e) { alert('Error: ' + e.message); }
}

async function deleteConcept(id) {
    if (!confirm('Delete this concept and all its mappings?')) return;
    try {
        await authFetch(`${chatUrl()}/api/knowledge/concepts/${id}`, {method:'DELETE'});
        loadConcepts();
    } catch(e) { alert('Error: ' + e.message); }
}

async function createMapping() {
    const conceptId = document.getElementById('mappingConcept')?.value;
    const connId = document.getElementById('mappingConn')?.value;
    const table = document.getElementById('mappingTable')?.value?.trim();
    const column = document.getElementById('mappingColumn')?.value?.trim();
    if (!conceptId || !connId || !table || !column) return alert('All fields required');
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/mappings`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({concept_id: parseInt(conceptId), connection_id: parseInt(connId), table_name: table, column_name: column})
        });
        if (!r.ok) { const e = await r.json(); return alert(e.detail || 'Error'); }
        document.getElementById('mappingTable').value = '';
        document.getElementById('mappingColumn').value = '';
        alert('Mapping created!');
        loadConcepts();
    } catch(e) { alert('Error: ' + e.message); }
}

async function fingerprintConnection() {
    const connId = typeof currentConnectionId !== 'undefined' ? currentConnectionId : null;
    if (!connId) return alert('Select a database connection first');
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/fingerprint/${connId}`, {method:'POST'});
        const data = await r.json();
        alert(`Fingerprinted ${data.columns_fingerprinted} columns`);
    } catch(e) { alert('Error: ' + e.message); }
}

async function discoverMatches() {
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/discover`);
        const matches = await r.json();
        const container = document.getElementById('discoveryResults');
        const list = document.getElementById('discoveryList');
        if (!matches.length) { container.style.display = 'none'; return alert('No cross-database matches found. Fingerprint your databases first.'); }
        container.style.display = 'block';
        list.innerHTML = matches.map((m, i) => `
            <div class="bg-d-card border border-d-border rounded-lg p-3 mb-2">
                <div class="flex items-center justify-between">
                    <div class="flex-1">
                        <span class="text-white text-xs font-mono">conn=${m.column_a.connection_id} ${m.column_a.table}.${m.column_a.column}</span>
                        <span class="text-d-accent mx-2">↔</span>
                        <span class="text-white text-xs font-mono">conn=${m.column_b.connection_id} ${m.column_b.table}.${m.column_b.column}</span>
                        <span class="ml-2 text-[10px] px-2 py-0.5 rounded ${m.confidence >= 80 ? 'bg-green-900/30 text-green-400' : 'bg-yellow-900/30 text-yellow-400'}">${m.confidence}% match</span>
                        ${m.column_a.pattern ? `<span class="text-[10px] text-d-muted ml-2">${m.column_a.pattern}</span>` : ''}
                    </div>
                </div>
            </div>
        `).join('');
    } catch(e) { alert('Error: ' + e.message); }
}

async function createAnnotation() {
    const connId = document.getElementById('annotConn')?.value;
    const table = document.getElementById('annotTable')?.value?.trim();
    const column = document.getElementById('annotColumn')?.value?.trim();
    const text = document.getElementById('annotText')?.value?.trim();
    if (!connId || !table || !column || !text) return alert('All fields required');
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/annotations`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({connection_id: parseInt(connId), table_name: table, column_name: column, annotation: text})
        });
        if (!r.ok) { const e = await r.json(); return alert(e.detail || 'Error'); }
        document.getElementById('annotText').value = '';
        alert('Annotation saved! The AI will use this context in future queries.');
    } catch(e) { alert('Error: ' + e.message); }
}


// ═══════════════════════════════════════════════════════════
// ═══════ BUSINESS GLOSSARY ═══════════════════════════════
// ═══════════════════════════════════════════════════════════

async function loadGlossaryTab() {
    loadGlossaryTerms();
    loadCorrections();
}

async function loadGlossaryTerms() {
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/glossary`);
        const terms = await r.json();
        const el = document.getElementById('glossaryContent');
        if (!terms.length) { el.innerHTML = '<p class="text-d-muted text-xs">No business terms defined yet. Add one above to teach the AI your vocabulary.</p>'; return; }
        el.innerHTML = terms.map(t => `
            <div class="bg-d-card border border-d-border rounded-lg p-3 mb-2 flex items-center justify-between">
                <div class="flex-1">
                    <span class="text-white font-semibold text-sm">${t.term}</span>
                    ${t.category ? `<span class="text-[10px] text-d-muted ml-2 bg-d-input px-2 py-0.5 rounded">${t.category}</span>` : ''}
                    <p class="text-xs text-d-muted mt-1">${t.definition}</p>
                    ${t.sql_expression ? `<p class="text-[10px] font-mono text-d-accent mt-1">SQL: ${t.sql_expression}</p>` : ''}
                    ${t.synonyms ? `<p class="text-[10px] text-d-muted mt-0.5">Also: ${t.synonyms}</p>` : ''}
                </div>
                <div class="flex gap-2 items-center">
                    <button onclick="upvoteGlossary(${t.id})" class="chip text-[10px]">👍 ${t.upvotes || 0}</button>
                    <button onclick="deleteGlossary(${t.id})" class="chip text-[10px]" style="color:#f87171">Delete</button>
                </div>
            </div>
        `).join('');
    } catch(e) { console.error('loadGlossaryTerms:', e); }
}

async function createGlossaryTerm() {
    const term = document.getElementById('glossTerm')?.value?.trim();
    const def = document.getElementById('glossDef')?.value?.trim();
    const sql = document.getElementById('glossSQL')?.value?.trim();
    const cat = document.getElementById('glossCategory')?.value?.trim();
    const syn = document.getElementById('glossSynonyms')?.value?.trim();
    if (!term || !def) return alert('Term and definition are required');
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/glossary`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({term, definition: def, sql_expression: sql, category: cat, synonyms: syn})
        });
        if (!r.ok) { const e = await r.json(); return alert(e.detail || 'Error'); }
        document.getElementById('glossTerm').value = '';
        document.getElementById('glossDef').value = '';
        document.getElementById('glossSQL').value = '';
        document.getElementById('glossCategory').value = '';
        document.getElementById('glossSynonyms').value = '';
        loadGlossaryTerms();
    } catch(e) { alert('Error: ' + e.message); }
}

async function upvoteGlossary(id) {
    try {
        await authFetch(`${chatUrl()}/api/knowledge/glossary/${id}/upvote`, {method:'POST'});
        loadGlossaryTerms();
    } catch(e) {}
}

async function deleteGlossary(id) {
    if (!confirm('Delete this glossary term?')) return;
    try {
        await authFetch(`${chatUrl()}/api/knowledge/glossary/${id}`, {method:'DELETE'});
        loadGlossaryTerms();
    } catch(e) { alert('Error: ' + e.message); }
}

async function createCorrection() {
    const connId = typeof currentConnectionId !== 'undefined' ? currentConnectionId : null;
    if (!connId) return alert('Select a database connection first');
    const prompt = document.getElementById('corrPrompt')?.value?.trim();
    const sql = document.getElementById('corrSQL')?.value?.trim();
    const text = document.getElementById('corrText')?.value?.trim();
    const fixedSql = document.getElementById('corrFixedSQL')?.value?.trim();
    if (!prompt || !text) return alert('Original prompt and correction are required');
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/corrections`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({connection_id: connId, original_prompt: prompt, original_sql: sql, correction_text: text, corrected_sql: fixedSql})
        });
        if (!r.ok) { const e = await r.json(); return alert(e.detail || 'Error'); }
        document.getElementById('corrPrompt').value = '';
        document.getElementById('corrSQL').value = '';
        document.getElementById('corrText').value = '';
        document.getElementById('corrFixedSQL').value = '';
        alert('Correction recorded! The AI will learn from this.');
        loadCorrections();
    } catch(e) { alert('Error: ' + e.message); }
}

async function loadCorrections() {
    const connId = typeof currentConnectionId !== 'undefined' ? currentConnectionId : null;
    if (!connId) return;
    try {
        const r = await authFetch(`${chatUrl()}/api/knowledge/corrections/${connId}?limit=20`);
        const corrections = await r.json();
        const el = document.getElementById('correctionsList');
        if (!el) return;
        if (!corrections.length) { el.innerHTML = ''; return; }
        el.innerHTML = '<h4 class="text-xs text-d-muted mb-2 mt-2">Recent Corrections</h4>' +
            corrections.map(c => `
                <div class="bg-d-input border border-d-border rounded-lg p-2 mb-1 text-[11px]">
                    <div class="text-d-muted">Q: ${c.original_prompt}</div>
                    <div class="text-white mt-0.5">Fix: ${c.correction_text}</div>
                    ${c.corrected_sql ? `<div class="text-d-accent font-mono mt-0.5">${c.corrected_sql}</div>` : ''}
                    <div class="text-[9px] text-d-muted mt-0.5">Applied ${c.applied_count}x</div>
                </div>
            `).join('');
    } catch(e) {}
}


// ═══════ Connection Test Button ════════════════════════════
async function testConnection() {
    const dbType = document.getElementById('adminRegType')?.value;
    const host = document.getElementById('adminRegHost')?.value;
    const port = document.getElementById('adminRegPort')?.value;
    const user = document.getElementById('adminRegUser')?.value;
    const pass = document.getElementById('adminRegPass')?.value;
    const database = document.getElementById('adminRegDb')?.value;
    if (!dbType || !host) return alert('Fill in connection details first');
    try {
        const r = await authFetch(`${chatUrl()}/api/connection/test`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({database_type:dbType, host, port:parseInt(port)||5432, username:user, password:pass, database})
        });
        const data = await r.json();
        alert(data.success ? '✅ Connection successful!' : `❌ Connection failed: ${data.message}`);
    } catch(e) { alert('Error: ' + e.message); }
}
