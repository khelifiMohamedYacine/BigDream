if (localStorage.getItem('token')) {
    window.location.href = '/home.html';
}

document.getElementById('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;

    setLoading(true);
    hideError();

    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Login failed');
        }

        localStorage.setItem('token', data.access_token);
        if (data.user) {
            localStorage.setItem('user_id', data.user.user_id);
            localStorage.setItem('user_name', data.user.name);
            localStorage.setItem('user_email', data.user.email);
        }

        showSuccess();
        setTimeout(() => {
            window.location.href = '/home.html';
        }, 1000);

    } catch (error) {
        showError(error.message || 'Sign in failed. Please check your email and password.');
        setLoading(false);
    }
});

function showError(message) {
    const errorDiv = document.getElementById('errorMessage');
    const errorText = document.getElementById('errorText');
    errorText.textContent = message;
    errorDiv.style.display = 'flex';
}

function hideError() {
    document.getElementById('errorMessage').style.display = 'none';
}

function showSuccess() {
    const errorDiv = document.getElementById('errorMessage');
    errorDiv.className = 'message-box success';
    document.getElementById('errorText').textContent = 'Signed in successfully. Redirecting...';
    errorDiv.style.display = 'flex';
}

function setLoading(loading) {
    const btn = document.getElementById('loginBtn');
    const btnText = document.getElementById('loginBtnText');
    const spinner = document.getElementById('loginSpinner');

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

function guestAccess() {
    localStorage.setItem('user_id', 'guest_' + Math.random().toString(36).substr(2, 9));
    localStorage.setItem('user_name', 'Guest');
    window.location.href = '/home.html';
}
