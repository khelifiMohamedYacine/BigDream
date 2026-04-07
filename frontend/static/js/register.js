if (localStorage.getItem('token')) {
    window.location.href = '/home.html';
}

function checkPasswordStrength() {
    const password = document.getElementById('password').value;
    let strength = 0;

    for (let i = 1; i <= 4; i++) {
        const bar = document.getElementById(`str${i}`);
        bar.className = 'strength-bar';
    }

    const hasLength = password.length >= 8;
    const hasUpper = /[A-Z]/.test(password);
    const hasLower = /[a-z]/.test(password);
    const hasNumber = /[0-9]/.test(password);
    const hasSpecial = /[^A-Za-z0-9]/.test(password);

    updateReq('req1', hasLength);
    updateReq('req2', hasUpper);
    updateReq('req3', hasNumber);

    if (hasLength) strength++;
    if (hasUpper && hasLower) strength++;
    if (hasNumber) strength++;
    if (hasSpecial) strength++;

    const strengthClasses = ['', 'weak', 'fair', 'strong', 'excellent'];
    const strengthTexts = ['None', 'Weak', 'Fair', 'Strong', 'Excellent'];

    for (let i = 1; i <= strength; i++) {
        const bar = document.getElementById(`str${i}`);
        bar.classList.add('active', strengthClasses[strength]);
    }

    document.getElementById('strengthLevel').textContent = strengthTexts[strength];
}

function updateReq(id, met) {
    const elem = document.getElementById(id);
    const icon = elem.querySelector('.material-symbols-outlined');
    if (met) {
        icon.textContent = 'check_circle';
        elem.classList.add('met');
    } else {
        icon.textContent = 'radio_button_unchecked';
        elem.classList.remove('met');
    }
}

document.getElementById('registerForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const name = document.getElementById('name').value;
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirmPassword').value;

    if (password !== confirmPassword) {
        showMessage('error', 'Passwords do not match');
        return;
    }

    if (password.length < 8) {
        showMessage('error', 'Password must be at least 8 characters');
        return;
    }

    if (!/[A-Z]/.test(password)) {
        showMessage('error', 'Password must contain at least one uppercase letter');
        return;
    }

    if (!/[0-9]/.test(password)) {
        showMessage('error', 'Password must contain at least one number');
        return;
    }

    setLoading(true);
    hideMessage();

    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name, email, password, confirm_password: confirmPassword })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Registration failed');
        }

        localStorage.setItem('token', data.access_token);
        if (data.user) {
            localStorage.setItem('user_id', data.user.user_id);
            localStorage.setItem('user_name', data.user.name);
            localStorage.setItem('user_email', data.user.email);
        }

        showMessage('success', 'Account created successfully. Redirecting...');

        setTimeout(() => {
            window.location.href = '/home.html';
        }, 1500);

    } catch (error) {
        showMessage('error', error.message || 'Registration failed');
        setLoading(false);
    }
});

function showMessage(type, text) {
    const msgDiv = document.getElementById('message');
    const msgIcon = document.getElementById('messageIcon');
    const msgText = document.getElementById('messageText');

    msgDiv.className = 'message-box';

    if (type === 'error') {
        msgDiv.classList.add('error');
        msgIcon.textContent = 'error';
        msgText.textContent = `[ERROR] ${text}`;
    } else {
        msgDiv.classList.add('success');
        msgIcon.textContent = 'check_circle';
        msgText.textContent = `[SUCCESS] ${text}`;
    }

    msgDiv.style.display = 'flex';
}

function hideMessage() {
    document.getElementById('message').style.display = 'none';
}

function setLoading(loading) {
    const btn = document.getElementById('registerBtn');
    const btnText = document.getElementById('registerBtnText');
    const spinner = document.getElementById('registerSpinner');

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
