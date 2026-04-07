if (localStorage.getItem('token')) {
    window.location.href = '/home.html';
}

document.getElementById('forgotForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const email = document.getElementById('email').value;

    setLoading(true);
    hideMessage();

    try {
        const response = await fetch('/api/auth/forgot-password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Request failed');
        }

        showMessage(
            'If an account with that email exists, a reset code has been sent to your inbox. Check your email and enter the code on the next page.',
            'success'
        );
        setTimeout(() => {
            window.location.href = '/reset-password.html';
        }, 3500);

    } catch (error) {
        showMessage(error.message || 'Request failed. Please try again.', 'error');
    } finally {
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
    const btn = document.getElementById('submitBtn');
    const btnText = document.getElementById('submitBtnText');
    const spinner = document.getElementById('submitSpinner');

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
