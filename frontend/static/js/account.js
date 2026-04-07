const API_URL = '';
let currentUser = null;

const token = localStorage.getItem('token');
if (!token) {
    window.location.href = '/login.html';
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function updatePassport(user) {
    setText('passport-name', user.name || '—');
    setText('passport-email', user.email || '—');
    setText('passport-handle', user.handle ? `@${user.handle}` : '—');
    setText('passport-bio', user.bio || '—');
    setText('passport-uid', user.user_id || '—');
    setText('avatar-display-name', user.name || 'Operator');
    setText('avatar-display-handle', user.handle ? `@${user.handle}` : '@handle');
}

async function loadUserProfile() {
    try {
        const response = await fetch(`${API_URL}/api/auth/me`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            throw new Error('Failed to load profile');
        }

        const data = await response.json();
        currentUser = data.user;

        document.getElementById('user-name').value = currentUser.name || '';
        document.getElementById('user-email').value = currentUser.email || '';
        document.getElementById('user-handle').value = currentUser.handle || '';
        document.getElementById('user-bio').value = currentUser.bio || '';
        document.getElementById('user-id').value = currentUser.user_id || '';

        const avatarUrl = currentUser.avatar_url || '';
        if (avatarUrl) {
            document.getElementById('profile-picture-display').src = avatarUrl;
            document.getElementById('userAvatar').textContent = currentUser.name?.substring(0, 2).toUpperCase() || 'BD';
        }

        updatePassport(currentUser);

        document.getElementById('email-notifications').checked = currentUser.email_notifications !== false;
        document.getElementById('weekly-summary').checked = currentUser.weekly_summary !== false;
        document.getElementById('content-updates').checked = currentUser.content_updates !== false;

    } catch (error) {
        showNotification('Failed to load profile', 'error');
    }
}

document.getElementById('profile-photo-trigger').addEventListener('click', () => {
    document.getElementById('avatar-upload').click();
});

document.getElementById('avatar-upload').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_URL}/api/auth/profile/avatar`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Upload failed');
        }

        document.getElementById('profile-picture-display').src = data.avatar_url;
        showNotification('Avatar uploaded successfully!', 'success');

    } catch (error) {
        showNotification(error.message || 'Failed to upload avatar', 'error');
    }
});

document.getElementById('save-profile').addEventListener('click', async () => {
    try {
        const updates = {
            name: document.getElementById('user-name').value,
            handle: document.getElementById('user-handle').value,
            bio: document.getElementById('user-bio').value
        };

        const response = await fetch(`${API_URL}/api/auth/profile`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(updates)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Update failed');
        }

        showNotification('Profile updated successfully!', 'success');
        currentUser = data.user;
        updatePassport(currentUser);

    } catch (error) {
        showNotification(error.message || 'Failed to update profile', 'error');
    }
});

document.getElementById('save-preferences').addEventListener('click', async () => {
    try {
        const preferences = {
            email_notifications: document.getElementById('email-notifications').checked,
            weekly_summary: document.getElementById('weekly-summary').checked,
            content_updates: document.getElementById('content-updates').checked
        };

        const response = await fetch(`${API_URL}/api/auth/preferences`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(preferences)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Update failed');
        }

        showNotification('Preferences saved!', 'success');

    } catch (error) {
        showNotification(error.message || 'Failed to save preferences', 'error');
    }
});

document.getElementById('export-data').addEventListener('click', () => {
    const data = {
        user: currentUser,
        exportedAt: new Date().toISOString()
    };

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `bigdream-data-${Date.now()}.json`;
    a.click();

    showNotification('Data exported successfully!', 'success');
});

document.getElementById('delete-account').addEventListener('click', async () => {
    if (confirm('Are you sure you want to delete your account? This action cannot be undone!')) {
        if (confirm('This will permanently delete all your data. Are you absolutely sure?')) {
            try {
                const response = await fetch(`${API_URL}/api/auth/account`, {
                    method: 'DELETE',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });

                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.detail || 'Deletion failed');
                }

                localStorage.clear();
                showNotification('Account deleted successfully. Redirecting...', 'success');
                setTimeout(() => { window.location.href = '/login.html'; }, 1500);
            } catch (error) {
                showNotification(error.message || 'Failed to delete account', 'error');
            }
        }
    }
});

document.getElementById('logout-btn').addEventListener('click', async () => {
    try {
        await fetch(`${API_URL}/api/auth/logout`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
    } catch (error) {
        // ignore logout errors
    }
    localStorage.removeItem('token');
    localStorage.removeItem('user_id');
    localStorage.removeItem('user_name');
    localStorage.removeItem('user_email');
    window.location.href = '/login.html';
});

// Notification function — uses CSS classes from style.css
function showNotification(message, type = 'info') {
    document.querySelectorAll('.bd-notification').forEach(el => el.remove());

    const notification = document.createElement('div');
    notification.className = `bd-notification ${type}`;
    notification.style.animation = 'slideInRight 0.3s ease';
    notification.innerHTML = `<span>${message}</span><button onclick="this.parentElement.remove()">&times;</button>`;

    document.body.appendChild(notification);
    setTimeout(() => {
        if (notification.parentElement) {
            notification.style.animation = 'slideOutRight 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }
    }, 5000);
}

loadUserProfile();
