const $ = (selector, root = document) => root.querySelector(selector);
const app = $('#app');
let me = null;
let page = 'home';
let timer = null;
let toastTimer = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const type = response.headers.get('content-type') || '';
  const body = type.includes('json') ? await response.json() : null;
  if (!response.ok) throw new Error(body?.error || `Request failed (${response.status})`);
  return body;
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function initials(name = '') { return name.split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase(); }
function formatDate(iso, options = { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) {
  return iso ? new Intl.DateTimeFormat(undefined, options).format(new Date(iso)) : '—';
}
function showToast(message, error = false) {
  const el = $('#toast'); el.textContent = message; el.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.className = 'toast', 2600);
}
function icon(name) { return ({ home: '⌂', sessions: '◷', history: '▤', devices: '⌁' })[name] || '•'; }

async function start() {
  try {
    const state = await api('/api/me'); me = state.user;
    me ? await renderDashboard() : renderLogin();
  } catch { renderLogin(); }
}

function renderLogin() {
  clearInterval(timer);
  app.innerHTML = `<section class="login-page">
    <div class="login-story">
      <div class="wordmark"><span class="brand-mark">P</span> ProxyProof</div>
      <h1>Here.<br><span>In person.</span></h1>
      <p class="story-copy">Attendance that starts with being in the room. A nearby Bluetooth signal verifies presence while rotating tokens help stop shared codes and replays.</p>
      <div class="signal-art"><i></i> Presence, verified nearby</div>
    </div>
    <section class="login-card">
      <div class="eyebrow">Welcome back</div><h2>Sign in to ProxyProof</h2>
      <p class="login-sub">Your attendance workspace is ready.</p>
      <form id="login-form">
        <div class="field"><label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="username" placeholder="you@school.edu" required></div>
        <div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" placeholder="Enter your password" required></div>
        <button class="btn btn-primary login-submit" type="submit">Sign in <span aria-hidden="true">→</span></button>
      </form>
      <div class="demo-box"><div class="demo-label">Try a demo account</div>
        <div class="demo-actions"><button class="btn btn-light" data-demo="organizer">Organiser demo</button><button class="btn btn-light" data-demo="student">Student demo</button></div>
      </div>
      <p class="login-note">Demo mode uses a proximity simulator. Real BLE advertising and scanning require a companion native app; see the project README.</p>
    </section>
  </section>`;
  $('#login-form').addEventListener('submit', async e => {
    e.preventDefault(); const form = new FormData(e.currentTarget);
    try { me = (await api('/api/login', { method: 'POST', body: JSON.stringify({ email: form.get('email'), password: form.get('password') }) })).user; page = 'home'; await renderDashboard(); }
    catch (err) { showToast(err.message, true); }
  });
  document.querySelectorAll('[data-demo]').forEach(button => button.addEventListener('click', () => {
    $('#email').value = button.dataset.demo === 'organizer' ? 'organizer@proxyproof.app' : 'maya@proxyproof.app';
    $('#password').value = button.dataset.demo === 'organizer' ? 'organizer123' : 'student123';
    $('#login-form').requestSubmit();
  }));
}

function shell(content) {
  const organizer = me.role === 'organizer';
  const nav = organizer ? [['home', 'Overview'], ['sessions', 'Sessions'], ['devices', 'Devices']] : [['home', 'Overview'], ['history', 'My attendance'], ['devices', 'My device']];
  app.innerHTML = `<div class="dashboard">
    <aside class="sidebar"><div class="side-brand"><div class="wordmark"><span class="brand-mark">P</span> ProxyProof</div></div>
      <nav class="side-nav" aria-label="Main navigation">${nav.map(([key, label]) => `<button class="nav-item ${page === key ? 'active' : ''}" data-page="${key}"><span class="nav-icon">${icon(key)}</span>${label}</button>`).join('')}</nav>
      <div class="side-bottom"><div class="profile-mini"><div class="avatar">${escapeHtml(initials(me.name))}</div><div class="profile-info"><div class="profile-name">${escapeHtml(me.name)}</div><div class="profile-role">${organizer ? 'Organiser' : 'Student'}</div></div><button class="logout" aria-label="Sign out" title="Sign out">↗</button></div></div>
    </aside><section class="main">${content}</section>
  </div>`;
  document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => { page = button.dataset.page; renderDashboard(); }));
  $('.logout').addEventListener('click', async () => { await api('/api/logout', { method: 'POST', body: '{}' }); me = null; renderLogin(); });
}

function heading(title, sub, action = '') {
  return `<header class="topline"><div><div class="eyebrow">${me.role === 'organizer' ? 'Organiser workspace' : 'Student workspace'}</div><h1>${title}</h1><p>${sub}</p></div><div class="date-pill">${new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date())}</div>${action}</header>`;
}
function stat(title, value, note, dot = true) {
  return `<article class="stat-card"><div class="stat-head">${title}${dot ? '<span class="stat-dot"></span>' : ''}</div><div class="stat-value">${value}</div><div class="stat-note">${note}</div></article>`;
}

async function renderDashboard() {
  clearInterval(timer);
  if (!me) return renderLogin();
  try {
    const data = await api('/api/dashboard');
    if (me.role === 'organizer') renderOrganizer(data);
    else renderStudent(data);
    timer = setInterval(() => { if (!['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) refreshQuietly(); }, 3000);
  } catch (err) { showToast(err.message, true); }
}
async function refreshQuietly() {
  try {
    const data = await api('/api/dashboard');
    if (me.role === 'organizer') renderOrganizer(data); else renderStudent(data);
  } catch { /* Refresh resumes on the next interval. */ }
}

function renderOrganizer(data) {
  if (page === 'devices') return renderDevices();
  const active = data.active;
  const title = page === 'sessions' ? 'Sessions' : `Good ${new Date().getHours() < 12 ? 'morning' : 'afternoon'}, ${escapeHtml(me.name.split(' ')[0])}`;
  let content = heading(title, page === 'sessions' ? 'Open a timed attendance window and follow marks as they come in.' : 'Here’s the attendance picture for your classes today.');
  content += `<section class="stats">${stat('Students enrolled', data.students, 'Ready to check in')}${stat('Sessions created', data.session_count, 'Across your workspace', false)}${stat('Session status', active ? 'Live' : 'Idle', active ? `${active.present} marked present` : 'No active window', !!active)}</section>`;
  if (active) content += renderActiveSession(active);
  else content += `<section class="panel"><div class="panel-head"><div><h2>Start a session</h2><p>Attendance window closes automatically when the timer ends.</p></div></div><form id="session-form" class="session-form"><div class="field"><label for="class-name">Class or session name</label><input id="class-name" name="class_name" placeholder="e.g. Biology · Period 2" maxlength="80" required></div><div class="field duration-field"><label for="duration">Duration</label><select id="duration" name="duration"><option value="5">5 minutes</option><option value="10">10 minutes</option><option value="15">15 minutes</option><option value="30">30 minutes</option><option value="60">60 minutes</option></select></div><button class="btn btn-primary" type="submit">Start session <span>→</span></button></form></section>`;
  const sessions = data.recent || [];
  content += `<section class="panel"><div class="panel-head"><div><h2>Recent sessions</h2><p>Your latest attendance windows.</p></div><a class="btn btn-light btn-small" href="/api/export.csv">Export CSV ↓</a></div>${sessions.length ? `<div class="table-wrap"><table><thead><tr><th>Session</th><th>Date</th><th>Attendance</th><th>Status</th></tr></thead><tbody>${sessions.slice(0, 8).map(s => `<tr><td><strong>${escapeHtml(s.class_name)}</strong></td><td>${formatDate(s.started_at)}</td><td>${s.present} ${Number(s.present) === 1 ? 'student' : 'students'}</td><td><span class="badge ${s.closed_at || new Date(s.ends_at) <= new Date() ? 'badge-absent' : 'badge-present'}">${s.closed_at || new Date(s.ends_at) <= new Date() ? 'Closed' : 'Live'}</span></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty-state"><div class="empty-symbol">◷</div><strong>No sessions yet</strong><p>Start your first attendance window above.</p></div>'}</section>`;
  shell(content);
  $('#session-form')?.addEventListener('submit', async e => { e.preventDefault(); const form = new FormData(e.currentTarget); try { await api('/api/sessions', { method: 'POST', body: JSON.stringify({ class_name: form.get('class_name'), duration: form.get('duration') }) }); page = 'home'; showToast('Attendance session is live.'); await renderDashboard(); } catch (err) { showToast(err.message, true); } });
  $('#close-session')?.addEventListener('click', async e => { try { await api(`/api/sessions/${e.currentTarget.dataset.id}/close`, { method: 'POST', body: '{}' }); showToast('Session closed.'); await renderDashboard(); } catch (err) { showToast(err.message, true); } });
  document.querySelectorAll('[data-mark]').forEach(button => button.addEventListener('click', async () => { try { await api(`/api/sessions/${active.id}/attendance`, { method: 'POST', body: JSON.stringify({ student_id: button.dataset.student, present: button.dataset.mark === 'yes' }) }); showToast(button.dataset.mark === 'yes' ? 'Student marked present.' : 'Attendance mark removed.'); await renderDashboard(); } catch (err) { showToast(err.message, true); } }));
}

function renderActiveSession(active) {
  const left = Math.max(0, Math.ceil((new Date(active.ends_at) - Date.now()) / 1000));
  const roster = active.roster || [];
  return `<section class="panel"><div class="panel-head"><div><h2>Live attendance</h2><p>Updates automatically · proximity marks are checked by the server</p></div><span class="live-tag">Session live</span></div>
    <div class="session-row"><div><div class="session-title">${escapeHtml(active.class_name)}</div><div class="session-meta">Started ${formatDate(active.started_at)} · ${active.present} of ${roster.length} students present</div></div><div class="toolbar"><div class="timer">${String(Math.floor(left / 60)).padStart(2, '0')}:${String(left % 60).padStart(2, '0')} left</div><button class="btn btn-danger btn-small" id="close-session" data-id="${escapeHtml(active.id)}">Close session</button></div></div>
    ${active.beacon ? `<div class="beacon-box"><div class="beacon-copy"><strong>Rotating beacon payload <span class="muted small">· demo/native adapter</span></strong><span>${escapeHtml(active.beacon.id)} · ${escapeHtml(active.beacon.token)}</span></div><div class="beacon-refresh">Rotates in ${active.beacon.rotates_in}s</div></div>` : ''}
    <div class="panel-head" style="margin:23px 0 10px"><div><h2>Class roster</h2><p>Manually add or remove a mark if needed.</p></div><a class="btn btn-light btn-small" href="/api/export.csv">Export CSV</a></div>
    ${roster.length ? `<div class="table-wrap"><table><thead><tr><th>Student</th><th>Attendance</th><th>Method / signal</th><th>Correction</th></tr></thead><tbody>${roster.map(s => `<tr><td><div class="person"><span class="avatar">${escapeHtml(initials(s.name))}</span><span>${escapeHtml(s.name)}</span></div></td><td><span class="badge ${s.marked_at ? 'badge-present' : 'badge-absent'}">${s.marked_at ? 'Present' : 'Not marked'}</span></td><td>${s.marked_at ? `${s.method === 'ble' ? 'Nearby' : 'Manual'}${s.rssi != null ? ` · ${s.rssi} dBm` : ''}` : '—'}</td><td><div class="mark-actions">${s.marked_at ? `<button data-mark="no" data-student="${escapeHtml(s.student_id)}">Remove</button>` : `<button data-mark="yes" data-student="${escapeHtml(s.student_id)}">Add mark</button>`}</div></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty-state">No students have been enrolled yet.</div>'}</section>`;
}

function renderStudent(data) {
  if (page === 'devices') return renderStudentDevice();
  if (page === 'history') return renderHistory(data.history);
  const history = data.history;
  let content = heading(`Welcome, ${escapeHtml(me.name.split(' ')[0])}`, 'Your attendance is recorded when your approved device is nearby during class.');
  content += `<section class="stats">${stat('Attendance rate', `${history.percentage}%`, `${history.attended} of ${history.total} sessions attended`)}${stat('Sessions attended', history.attended, 'Your completed classes', false)}${stat('Sessions missed', Math.max(0, history.total - history.attended), 'Keep building your streak', false)}</section>`;
  if (data.active) {
    const active = data.active;
    content += `<section class="student-hero"><div><div class="hero-kicker">Class session is live</div><h2>${escapeHtml(active.class_name)}</h2><p>${active.marked_at ? `You're marked present · recorded ${formatDate(active.marked_at)}` : 'Checking for a nearby beacon…'}</p></div><div class="hero-icon">⌁</div></section>`;
    if (!active.marked_at) content += `<section class="panel"><div class="panel-head"><div><h2>Proximity check</h2><p>Demo interaction uses the same rotating-token, approved-device, and signal-strength server checks.</p></div><span class="live-tag">Listening</span></div><button class="btn btn-primary" id="simulate-mark">Simulate nearby device</button><div class="small muted" style="margin-top:12px">In production, your companion app submits beacon scans automatically when you enter the room.</div></section>`;
  } else content += `<section class="student-hero"><div><div class="hero-kicker">You're all caught up</div><h2>No active attendance window</h2><p>Your attendance will update automatically when your organiser starts a session.</p></div><div class="hero-icon">✓</div></section>`;
  content += `<section class="panel"><div class="panel-head"><div><h2>Recent attendance</h2><p>Your latest completed sessions.</p></div><button class="btn btn-light btn-small" data-page="history">View history</button></div>${history.sessions.length ? history.sessions.slice(0, 4).map(historyRow).join('') : '<div class="empty-state"><div class="empty-symbol">▤</div><strong>Your history starts here</strong><p>Completed sessions will appear in this list.</p></div>'}</section>`;
  shell(content);
  $('[data-page="history"]')?.addEventListener('click', () => { page = 'history'; renderDashboard(); });
  $('#simulate-mark')?.addEventListener('click', async e => {
    e.currentTarget.disabled = true; e.currentTarget.textContent = 'Checking nearby signal…';
    try {
      const fresh = await api('/api/dashboard');
      if (!fresh.active?.beacon) throw new Error('The session ended before a nearby signal could be checked.');
      await api('/api/proximity', { method: 'POST', body: JSON.stringify({ session_id: fresh.active.id, token: fresh.active.beacon.token, device_id: me.device_id, rssi: -54 }) });
      showToast('You’re marked present.'); await renderDashboard();
    } catch (err) { showToast(err.message, true); e.currentTarget.disabled = false; e.currentTarget.textContent = 'Try proximity check again'; }
  });
}

function historyRow(s) {
  return `<div class="history-row"><div><div class="history-name">${escapeHtml(s.class_name)}</div><div class="history-date">${formatDate(s.started_at)}</div></div><div class="muted small">${s.method === 'manual' ? 'Manual' : s.present ? 'Nearby' : ''}</div><span class="badge ${s.present ? 'badge-present' : 'badge-absent'}">${s.present ? 'Present' : 'Absent'}</span></div>`;
}
function renderHistory(history) {
  const content = heading('My attendance', 'A clear record of the sessions you’ve attended.') + `<section class="panel"><div class="panel-head"><div><h2>Attendance history</h2><p>${history.attended} of ${history.total} completed sessions</p></div><div class="percentage">${history.percentage}%</div></div>${history.sessions.length ? history.sessions.map(historyRow).join('') : '<div class="empty-state"><div class="empty-symbol">▤</div><strong>No completed sessions yet</strong><p>Your history will show here after a class attendance window closes.</p></div>'}</section>`;
  shell(content);
}

async function renderDevices() {
  if (me.role === 'student') return renderStudentDevice();
  let data;
  try { data = await api('/api/devices'); } catch (err) { showToast(err.message, true); return; }
  const content = heading('Device approvals', 'One registered device per student helps reduce shared and replayed check-ins.') + `<section class="panel"><div class="panel-head"><div><h2>Student devices</h2><p>Review device changes before they can be used for attendance.</p></div></div>${data.devices.map(d => `<div class="device-card" style="margin-bottom:9px"><div><strong>${escapeHtml(d.name)}</strong><div class="device-label">${escapeHtml(d.email)} · registered: <span class="device-value">${escapeHtml(d.device_id || 'None')}</span>${d.pending_device_id ? `<br>Requested: <span class="device-value">${escapeHtml(d.pending_device_id)}</span>` : ''}</div></div>${d.pending_device_id ? `<div class="toolbar"><button class="btn btn-primary btn-small" data-review="yes" data-student="${escapeHtml(d.id)}">Approve</button><button class="btn btn-light btn-small" data-review="no" data-student="${escapeHtml(d.id)}">Reject</button></div>` : '<span class="badge badge-present">Approved</span>'}</div>`).join('')}</section>`;
  shell(content);
  document.querySelectorAll('[data-review]').forEach(button => button.addEventListener('click', async () => { try { await api(`/api/devices/${button.dataset.student}`, { method: 'POST', body: JSON.stringify({ approve: button.dataset.review === 'yes' }) }); showToast('Device request updated.'); await renderDevices(); } catch (err) { showToast(err.message, true); } }));
}

function renderStudentDevice() {
  const pending = me.pending_device_id;
  const content = heading('My device', 'Attendance can only be recorded from the device approved for your account.') + `<section class="panel"><div class="panel-head"><div><h2>Registered device</h2><p>Changing phones requires organiser approval.</p></div><span class="badge ${pending ? 'badge-absent' : 'badge-present'}">${pending ? 'Approval pending' : 'Approved'}</span></div><div class="device-card"><div><div class="device-label">Current device</div><div class="device-value">${escapeHtml(me.device_id || 'No device registered')}</div></div><span class="hero-icon">⌁</span></div>${pending ? `<div class="device-card" style="margin-top:10px"><div><div class="device-label">Requested device · waiting for approval</div><div class="device-value">${escapeHtml(pending)}</div></div></div>` : ''}<hr class="divider"><form id="device-form" class="session-form"><div class="field"><label for="device-id">Request a device change</label><input id="device-id" name="device_id" placeholder="New device identifier" required></div><button class="btn btn-primary" type="submit">Request approval</button></form><p class="small muted" style="margin:13px 0 0">Demo device ID is assigned to your account. A native app should generate and protect a stable device identity.</p></section>`;
  shell(content);
  $('#device-form').addEventListener('submit', async e => { e.preventDefault(); const id = new FormData(e.currentTarget).get('device_id'); try { await api('/api/device/request', { method: 'POST', body: JSON.stringify({ device_id: id }) }); me = (await api('/api/me')).user; showToast('Device change sent for organiser approval.'); await renderDashboard(); } catch (err) { showToast(err.message, true); } });
}

start();
