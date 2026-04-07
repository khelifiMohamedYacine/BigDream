const token = localStorage.getItem('token');

if (!token) {
    window.location.href = '/login.html';
}

const headers = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
};

async function loadDashboard() {
    try {
        const resp = await fetch('/api/admin/dashboard', { headers });

        if (resp.status === 403) {
            alert('Admin access required.');
            window.location.href = '/home.html';
            return;
        }

        if (!resp.ok) throw new Error('Failed to load dashboard');

        const data = await resp.json();
        const d = data.dashboard;

        document.getElementById('stat-total-users').textContent = d.users.total;
        document.getElementById('stat-active-users').textContent = d.users.active;
        document.getElementById('stat-total-goals').textContent = d.system.goals.total;
        document.getElementById('stat-total-content').textContent =
            d.system.content.videos + d.system.content.articles;

        renderAuditLog(d.recent_activity);

    } catch (error) {
        console.error('Dashboard error:', error);
    }
}

async function loadUsers(search = '') {
    try {
        const url = search
            ? `/api/admin/users?search=${encodeURIComponent(search)}`
            : '/api/admin/users';

        const resp = await fetch(url, { headers });
        if (!resp.ok) throw new Error('Failed to load users');

        const data = await resp.json();
        renderUsers(data.users);

    } catch (error) {
        console.error('Load users error:', error);
    }
}

function renderUsers(users) {
    const tbody = document.getElementById('users-tbody');

    if (!users || users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="table-empty-cell">No users found</td></tr>';
        return;
    }

    tbody.innerHTML = users.map(user => `
        <tr>
            <td>
                <strong>${user.name || 'Unknown'}</strong>
                <div class="user-handle-sub">${user.handle || ''}</div>
            </td>
            <td>${user.email}</td>
            <td><span class="role-badge ${user.role}">${user.role}</span></td>
            <td>
                <span class="${user.is_active !== false ? 'status-active' : 'status-inactive'}">
                    <i class="fas fa-circle status-icon-sm"></i>
                    ${user.is_active !== false ? 'Active' : 'Inactive'}
                </span>
            </td>
            <td class="user-date">
                ${user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}
            </td>
            <td>
                ${user.is_active !== false
                    ? `<button class="action-btn danger" onclick="deactivateUser('${user.user_id}')">Deactivate</button>`
                    : `<button class="action-btn" onclick="reactivateUser('${user.user_id}')">Reactivate</button>`
                }
                <button class="action-btn danger" onclick="deleteUser('${user.user_id}', '${user.name}')">Delete</button>
            </td>
        </tr>
    `).join('');
}

function renderAuditLog(entries) {
    const container = document.getElementById('audit-log');

    if (!entries || entries.length === 0) {
        container.innerHTML = '<p class="text-muted">No recent activity</p>';
        return;
    }

    container.innerHTML = entries.reverse().map(entry => `
        <div class="audit-entry">
            <span class="audit-action">${entry.action.replace(/_/g, ' ')}</span>
            <span class="audit-time">${new Date(entry.timestamp).toLocaleString()}</span>
            ${entry.details ? `<div class="audit-details">${JSON.stringify(entry.details)}</div>` : ''}
        </div>
    `).join('');
}

async function deactivateUser(userId) {
    if (!confirm('Deactivate this user?')) return;
    try {
        const resp = await fetch(`/api/admin/users/${userId}/deactivate`, { method: 'POST', headers });
        if (resp.ok) { loadUsers(); loadDashboard(); }
    } catch (e) { console.error(e); }
}

async function reactivateUser(userId) {
    try {
        const resp = await fetch(`/api/admin/users/${userId}/reactivate`, { method: 'POST', headers });
        if (resp.ok) { loadUsers(); loadDashboard(); }
    } catch (e) { console.error(e); }
}

async function deleteUser(userId, name) {
    if (!confirm(`Delete user "${name}"? This cannot be undone!`)) return;
    try {
        const resp = await fetch(`/api/admin/users/${userId}`, { method: 'DELETE', headers });
        if (resp.ok) { loadUsers(); loadDashboard(); }
    } catch (e) { console.error(e); }
}

let searchTimeout;
document.getElementById('user-search').addEventListener('input', (e) => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => loadUsers(e.target.value), 300);
});

loadDashboard();
loadUsers();
