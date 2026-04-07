if (localStorage.getItem('token')) {
    window.location.href = '/home.html';
}

document.getElementById('resetForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const code = document.getElementById('resetCode').value.trim();
    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;

    if (newPassword !== confirmPassword) {
        showMessage('Passwords do not match.', 'error');
        return;
    }

    if (newPassword.length < 6) {
        showMessage('Password must be at least 6 characters.', 'error');
        return;
    }

    setLoading(true);
    hideMessage();

    try {
        const response = await fetch('/api/auth/reset-password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                code,
                new_password: newPassword,
                confirm_password: confirmPassword
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Reset failed');
        }

        showMessage('Password reset successfully! Redirecting to login...', 'success');

        setTimeout(() => {
            window.location.href = '/login.html';
        }, 2000);

    } catch (error) {
        showMessage(error.message || 'Reset failed. Please try again.', 'error');
        setLoading(false);
    }
});

function showMessage(text, type) {
    const msgDiv = document.getElementById('message');
    const msgIcon = document.getElementById('messageIcon');
    const msgText = document.getElementById('messageText');

    msgDiv.className = `message-box ${type}`;
    msgIcon.className = type === 'success' ? 'fas fa-check-circle' : 'fas fa-exclamation-circle';
    msgText.textContent = text;
    msgDiv.style.display = 'flex';
}

function hideMessage() {
    document.getElementById('message').style.display = 'none';
}

function setLoading(loading) {
    const btn = document.getElementById('resetBtn');
    const btnText = document.getElementById('resetBtnText');
    const spinner = document.getElementById('resetSpinner');

    if (loading) {
        btn.disabled = true;
        btnText.style.display = 'none';
        spinner.style.display = 'inline-block';
    } else {
        btn.disabled = false;
        btnText.style.display = 'inline';
        spinner.style.display = 'none';
    }
}
