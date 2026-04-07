class BigDreamApp {
    constructor() {
        this.apiBase = '/api';
        this.userId = this.getUserId();
        this.currentPage = window.location.pathname;
        this.init();
    }

    getUserId() {
        return localStorage.getItem('user_id') ||
               localStorage.getItem('bigdream_user_id') ||
               'default';
    }

    getToken() {
        return localStorage.getItem('token');
    }

    init() {
        this.setupNavigation();
        this.setupAvatar();
        this.initPageSpecificFeatures();
    }

    setupNavigation() {
        const currentPath = window.location.pathname;
        document.querySelectorAll('.nav-tabs a').forEach(link => {
            const href = link.getAttribute('href');
            if (href === currentPath ||
                (currentPath.includes('/goals') && href === '/goals') ||
                (currentPath.includes('/videos') && href === '/videos') ||
                (currentPath.includes('/articles') && href === '/articles')) {
                link.classList.add('active');
            }
        });

        const hamburger = document.getElementById('navHamburger');
        const navTabs = document.querySelector('.nav-tabs');

        const overlay = document.createElement('div');
        overlay.className = 'nav-overlay';
        document.body.appendChild(overlay);

        if (hamburger && navTabs) {
            const closeNav = () => {
                navTabs.classList.remove('open');
                overlay.classList.remove('open');
                const icon = hamburger.querySelector('i');
                if (icon) icon.className = 'fas fa-bars';
            };

            hamburger.addEventListener('click', (e) => {
                e.stopPropagation();
                const isOpen = navTabs.classList.toggle('open');
                overlay.classList.toggle('open', isOpen);
                const icon = hamburger.querySelector('i');
                icon.className = isOpen ? 'fas fa-times' : 'fas fa-bars';
            });

            navTabs.querySelectorAll('a').forEach(link => {
                link.addEventListener('click', closeNav);
            });
            overlay.addEventListener('click', closeNav);
        }
    }

    setupAvatar() {
        const userName = localStorage.getItem('user_name') || 'BD';
        const avatar = document.getElementById('userAvatar');
        if (avatar) {
            avatar.textContent = userName.substring(0, 2).toUpperCase();
        }
    }

    initPageSpecificFeatures() {
        const path = this.currentPage;

        if (path === '/' || path === '/home.html' || path.includes('home')) {
            this.initDashboard();
        } else if (path.includes('/goals')) {
            this.initGoals();
        } else if (path.includes('/videos')) {
            this.initVideos();
        } else if (path.includes('/articles')) {
            this.initArticles();
        } else if (path.includes('/account')) {
            this.initAccount();
        }
    }

    async apiCall(endpoint, options = {}) {
        try {
            const headers = {
                'Content-Type': 'application/json',
                ...options.headers
            };

            const token = this.getToken();
            if (token) {
                headers['Authorization'] = `Bearer ${token}`;
            }

            const response = await fetch(endpoint, {
                headers,
                ...options
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({
                    detail: `HTTP ${response.status}`
                }));
                throw new Error(error.detail || `API error: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            this.showNotification(`Error: ${error.message}`, 'error');
            throw error;
        }
    }

    initDashboard() {
        if (!this.getToken() && !localStorage.getItem('user_id')) {
            window.location.href = '/login.html';
            return;
        }
        this.loadDashboardStats();
        this.initChatbot();
    }

    async loadDashboardStats() {
        try {
            const response = await this.apiCall(`${this.apiBase}/goals?user_id=${this.userId}`);
            const goalsData = response || {};
            const goals = Object.values(goalsData);

            const activeEl = document.getElementById('stat-active-goals');
            if (activeEl) activeEl.textContent = goals.length;

            const completedEl = document.getElementById('stat-completed');
            if (completedEl) completedEl.textContent =
                goals.filter(g => g.status === 'completed').length;
        } catch (error) {
            // stats load failure is non-critical
        }
    }

    initChatbot() {
        const chatWindow  = document.getElementById('chatMessages');
        const chatInput   = document.getElementById('chatInput');
        const sendButton  = document.getElementById('chatSend');
        const stopButton  = document.getElementById('chatStop');

        if (!chatWindow || !chatInput || !sendButton) return;

        let isProcessing = false;
        let abortController = null;
        let progressInterval = null;

        // Load chat history on startup
        this.loadChatHistory();

        // Auto-resize textarea to fit content
        const resizeTextarea = () => {
            const style   = window.getComputedStyle(chatInput);
            const lh      = parseFloat(style.lineHeight) || 22;
            const pt      = parseFloat(style.paddingTop)    || 0;
            const pb      = parseFloat(style.paddingBottom) || 0;
            const minH    = lh * 1 + pt + pb;
            chatInput.style.height = '0px';
            chatInput.style.height = Math.max(chatInput.scrollHeight, minH) + 2 + 'px';
        };

        const syncSendBtn = () => {
            const empty = chatInput.value.trim().length === 0;
            sendButton.disabled = empty || isProcessing;
        };

        const setLoading = (loading) => {
            isProcessing = loading;
            if (loading) {
                sendButton.style.display = 'none';
                if (stopButton) stopButton.style.display = 'flex';
                chatInput.style.opacity = '0.6';
            } else {
                if (stopButton) stopButton.style.display = 'none';
                sendButton.style.display = 'flex';
                chatInput.style.opacity = '1';
                syncSendBtn();
                chatInput.focus();
            }
        };

        chatInput.addEventListener('input', () => {
            resizeTextarea();
            syncSendBtn();
        });

        // Enter to send, Shift+Enter for newline
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey && !isProcessing) {
                if (chatInput.value.trim().length === 0) return;
                e.preventDefault();
                sendMessage();
            }
        });

        if (stopButton) {
            stopButton.addEventListener('click', () => {
                if (abortController) abortController.abort();
                setLoading(false);
                this.removeTypingIndicator();
                this.addChatMessage('_Response stopped._', 'bot');
            });
        }

        sendButton.addEventListener('click', (e) => {
            e.preventDefault();
            sendMessage();
        });

        const sendMessage = async () => {
            const text = chatInput.value.trim();
            if (!text || isProcessing) return;

            this.addChatMessage(text, 'user');
            chatInput.value = '';
            resizeTextarea();
            setLoading(true);
            this.showTypingIndicator();

            abortController = new AbortController();

            try {
                const headers = { 'Content-Type': 'application/json' };
                const token = this.getToken();
                if (token) headers['Authorization'] = `Bearer ${token}`;

                const goalId = this.getCurrentGoalIdForChat();
                const res = await fetch(`${this.apiBase}/chat`, {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ message: text, user_id: this.userId, goal_id: goalId }),
                    signal: abortController.signal
                });

                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();

                if (data.chat_response) {
                    this.addChatMessage(data.chat_response, 'bot');
                }

                if (data.new_goal && data.action_required === 'goal_created') {
                    const goalId = data.goal_id || data.new_goal.id;
                    console.log('Goal created:', goalId, data.new_goal);
                    
                    // Start progress tracking - the completion message
                    // will be shown AFTER progress reaches 100%
                    this.startProgressTracking(goalId);
                    
                    // Update stats
                    this.loadDashboardStats();
                } else if (data.action_required === 'goal_created' && !data.new_goal) {
                    console.error('Goal creation failed - no new_goal in response', data);
                    this.addChatMessage('Sorry, there was an error creating your goal. Please try again.', 'bot');
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    this.removeTypingIndicator();
                    this.addChatMessage('Something went wrong. Please try again.', 'bot');
                }
            } finally {
                setLoading(false);
            }
        };

        resizeTextarea();
        syncSendBtn();

        // Clear chat card handler (4th stat card)
        const clearChatCard = document.getElementById('clearChatCard');
        if (clearChatCard) {
            clearChatCard.addEventListener('click', async () => {
                if (confirm('Clear this conversation? This cannot be undone.')) {
                    await this.deleteChatHistory();
                    chatWindow.innerHTML = '';
                    this.addChatMessage(
                        "Hi! I am **BigDream**, your Python mentor and learning companion.\n\nTell me what you want to build or learn and I will create a personalised plan.",
                        'bot'
                    );
                }
            });
        }

        // Only show welcome message if no history loaded
        if (chatWindow.children.length === 0) {
            this.addChatMessage(
                "Hi! I am **BigDream**, your Python mentor and learning companion.\n\nTell me what you want to build or learn and I will create a personalised plan.",
                'bot'
            );
        }
    }

    async deleteChatHistory() {
        try {
            const goalId = this.getCurrentGoalIdForChat();
            const res = await fetch(`${this.apiBase}/chat/history?user_id=${this.userId}${goalId ? '&goal_id=' + goalId : ''}`, {
                method: 'DELETE'
            });
            return res.ok;
        } catch (e) {
            console.error('Failed to delete chat history:', e);
            return false;
        }
    }

    async loadChatHistory() {
        try {
            const goalId = this.getCurrentGoalIdForChat();
            const res = await fetch(`${this.apiBase}/chat/history?user_id=${this.userId}${goalId ? '&goal_id=' + goalId : ''}`);
            if (!res.ok) return;
            
            const data = await res.json();
            if (data.messages && data.messages.length > 0) {
                const chatWindow = document.getElementById('chatMessages');
                if (chatWindow) {
                    // Clear welcome message if exists
                    chatWindow.innerHTML = '';
                    
                    // Add each message
                    data.messages.forEach(msg => {
                        const role = msg.role === 'user' ? 'user' : 'bot';
                        this.addChatMessage(msg.content, role);
                    });
                }
            }
        } catch (e) {
            console.error('Failed to load chat history:', e);
        }
    }

    startProgressTracking(goalId) {
        if (!goalId) return;
        
        // Add progress bar message
        this.addProgressMessage(goalId);
        
        // Poll for progress every 2 seconds
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`${this.apiBase}/progress/${goalId}`);
                if (!res.ok) return;
                
                const data = await res.json();
                this.updateProgressMessage(goalId, data.progress, data.message, data.status);
                
                if (data.status === 'completed' || data.status === 'error' || data.status === 'not_found') {
                    clearInterval(interval);
                    if (data.status === 'completed') {
                        // Show completion message with View Goals button AFTER progress reaches 100%
                        this.addChatMessage(
                            `<strong>Your learning plan is ready!</strong><br><a href="/goals.html" style="color:var(--accent);text-decoration:underline;">View your goal →</a>`,
                            'bot',
                            true
                        );
                    }
                }
            } catch (e) {
                console.error('Progress polling error:', e);
            }
        }, 2000);
        
        // Store interval to clear later if needed
        this._progressIntervals = this._progressIntervals || {};
        this._progressIntervals[goalId] = interval;
    }

    addProgressMessage(goalId) {
        const chatWindow = document.getElementById('chatMessages');
        if (!chatWindow) return;
        
        const msgDiv = document.createElement('div');
        msgDiv.className = 'chat-msg chat-bot';
        msgDiv.id = 'progress_msg_' + goalId;
        msgDiv.innerHTML = `
            <div class="progress-container" style="margin-top:0.5rem;">
                <div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.3rem;">
                    Generating your learning plan...
                </div>
                <div class="progress-bar-bg" style="background:rgba(255,255,255,0.1);border-radius:4px;height:8px;overflow:hidden;">
                    <div class="progress-bar-fill" id="progress_fill_${goalId}" style="background:var(--accent);height:100%;width:0%;transition:width 0.5s ease;"></div>
                </div>
                <div class="progress-text" id="progress_text_${goalId}" style="font-size:0.75rem;color:var(--text-secondary);margin-top:0.3rem;">
                    Starting plan generation...
                </div>
            </div>
        `;
        chatWindow.appendChild(msgDiv);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    updateProgressMessage(goalId, progress, message, status) {
        const fill = document.getElementById(`progress_fill_${goalId}`);
        const text = document.getElementById(`progress_text_${goalId}`);
        
        if (fill) fill.style.width = `${progress}%`;
        if (text) text.textContent = message || `${progress}% complete`;
        
        if (status === 'completed') {
            const msgDiv = document.getElementById(`progress_msg_${goalId}`);
            if (msgDiv) {
                msgDiv.innerHTML = '<div style="color:var(--success);">Plan generation complete!</div>';
            }
        }
    }

    /** Escape HTML to prevent XSS inside code blocks. */
    escapeHTML(str) {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    /**
     * Build a single code card HTML string.
     * Code content is HTML-escaped but newlines are kept as real \n —
     * never converted to <br> — so Prism.js can read them via textContent.
     */
    buildCodeCard(language, code) {
        const codeId = 'cc_' + Math.random().toString(36).slice(2, 10);
        const lang = language || 'python';
        const escaped = this.escapeHTML(code.trim());
        return {
            id: codeId,
            html: `<div class="code-card" id="${codeId}">` +
                    `<div class="code-card-header">` +
                      `<span class="code-lang-badge"><i class="fas fa-code"></i> ${lang}</span>` +
                      `<button class="code-copy-btn" onclick="bigDreamApp.copyCode('${codeId}')" title="Copy code">` +
                        `<i class="fas fa-copy"></i><span>Copy</span>` +
                      `</button>` +
                    `</div>` +
                    `<pre class="code-card-body"><code class="language-${lang}">${escaped}</code></pre>` +
                  `</div>`
        };
    }

    /**
     * Render bot message text to HTML.
     *
     * Code blocks are extracted FIRST to preserve their formatting,
     * then markdown is processed on the remaining text.
     */
    renderBotText(text) {
        if (!text || typeof text !== 'string') return { html: '', cardIds: [] };
        
        // Remove model artifacts
        text = text
            .replace(/^user\s+/gim, '')
            .replace(/^model\s+/gim, '')
            .replace(/user\s+[^\n]+\s+model\s+/gi, '');

        // Heal malformed code fences: if there's an unmatched opening ```, close it
        const fenceMatches = text.match(/```/g) || [];
        if (fenceMatches.length % 2 !== 0) {
            text += '\n```';
        }

        // Extract code blocks FIRST (before any text processing) to preserve their formatting
        const cards = {};
        let placeholderCounter = 0;
        const codePlaceholders = {};
        
        // Replace code blocks with placeholders
        text = text.replace(/```(\w*)\s*\r?\n?([\s\S]*?)```/g, (match, lang, code) => {
            const placeholder = `__CODE_BLOCK_${placeholderCounter++}__`;
            codePlaceholders[placeholder] = { lang, code };
            return placeholder;
        });

        // Now clean up the non-code text (remove artifacts)
        text = text
            // Remove em/en dashes, but keep regular hyphens
            .replace(/[—–]/g, ' ')
            // Clean up multiple spaces (but preserve newlines)
            .replace(/[^\S\n]{2,}/g, ' ')
            .trim();

        // Build code cards from placeholders
        for (const [placeholder, { lang, code }] of Object.entries(codePlaceholders)) {
            const card = this.buildCodeCard(lang, code);
            const key = `\x00CODE_${card.id}\x00`;
            cards[key] = card;
            text = text.replace(placeholder, key);
        }

        // Process markdown on non-code text
        let rendered = text
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')
            .replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>')
            .replace(/^[•\-] (.+)/gm, '<li>$1</li>')
            .replace(/(<li>.*<\/li>(\n|$))+/g, m => `<ul>${m}</ul>`)
            .replace(/\n/g, '<br>');

        // Replace code placeholders with actual card HTML
        for (const [key, card] of Object.entries(cards)) {
            rendered = rendered.replace(key, card.html);
        }

        return { html: rendered, cardIds: Object.values(cards).map(c => c.id) };
    }

    /**
     * Clean up text for display by removing visible punctuation artifacts.
     * Only used for non-code text (week themes, explanations, etc.)
     */
    cleanDisplayText(text) {
        if (!text || typeof text !== 'string') return text;
        return text
            // Remove em/en dashes only (not regular hyphens or underscores)
            .replace(/[—–]/g, ' ')
            // Clean up multiple spaces but preserve newlines
            .replace(/[^\S\n]{2,}/g, ' ')
            .trim();
    }

    /** Copy code inside a card to clipboard with visual feedback. */
    copyCode(codeId) {
        const card = document.getElementById(codeId);
        if (!card) return;
        const code = card.querySelector('code').textContent;
        navigator.clipboard.writeText(code).then(() => {
            const btn = card.querySelector('.code-copy-btn');
            const span = btn.querySelector('span');
            const icon = btn.querySelector('i');
            span.textContent = 'Copied!';
            icon.className = 'fas fa-check';
            btn.classList.add('code-copy-btn--copied');
            setTimeout(() => {
                span.textContent = 'Copy';
                icon.className = 'fas fa-copy';
                btn.classList.remove('code-copy-btn--copied');
            }, 2000);
        }).catch(() => {
            const ta = document.createElement('textarea');
            ta.value = code;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            ta.remove();
        });
    }

    addChatMessage(text, sender = 'bot', isHTML = false) {
        const chatWindow = document.getElementById('chatMessages');
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-msg chat-${sender}`;

        this.removeTypingIndicator();

        // Clean up text for better display
        if (typeof text === 'string' && !isHTML) {
            text = this.cleanDisplayText(text);
        }

        if (sender === 'bot') {
            const { html, cardIds } = this.renderBotText(text);
            messageDiv.innerHTML = html;

            cardIds.forEach((id, i) => {
                const card = messageDiv.querySelector(`#${id}`);
                if (card) card.style.animationDelay = `${i * 80}ms`;
            });

            if (window.Prism) {
                messageDiv.querySelectorAll('pre code').forEach(block => {
                    Prism.highlightElement(block);
                });
            }
        } else if (isHTML) {
            messageDiv.innerHTML = text;
        } else {
            messageDiv.textContent = text;
        }

        chatWindow.appendChild(messageDiv);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    showTypingIndicator() {
        const chatWindow = document.getElementById('chatMessages');
        if (!chatWindow || chatWindow.querySelector('.chat-typing')) return;

        const typing = document.createElement('div');
        typing.className = 'chat-typing';
        typing.innerHTML = '<span></span><span></span><span></span>';
        chatWindow.appendChild(typing);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    removeTypingIndicator() {
        const chatWindow = document.getElementById('chatMessages');
        if (!chatWindow) return;
        const typing = chatWindow.querySelector('.chat-typing');
        if (typing) typing.remove();
    }

    async initGoals() {
        const container = document.getElementById('goals-container');
        const goalId = this.getGoalIdFromUrl();

        const listView = document.getElementById('goals-list-view');
        const detailView = document.getElementById('goal-detail-view');
        if (listView && detailView) {
            if (goalId) {
                listView.style.display = 'none';
                detailView.style.display = 'block';
            } else {
                listView.style.display = 'block';
                detailView.style.display = 'none';
            }
        }

        if (goalId) {
            await this.showGoalDetails(goalId);
        } else {
            await this.loadGoalsList(container);
        }
    }

    getGoalTimeProgress(goalData) {
        if (goalData.time_progress_pct !== undefined) {
            return {
                timePct: goalData.time_progress_pct,
                remainingText: goalData.time_remaining_text,
                isExpired: goalData.is_expired
            };
        }
        const goal = goalData.goal || goalData;
        const created = new Date(goal.created_at);
        const deadline = goal.deadline ? new Date(goal.deadline + 'T23:59:59') : null;
        if (!deadline || isNaN(deadline)) {
            return { timePct: 0, remainingText: 'No deadline', isExpired: false };
        }
        const now = new Date();
        const total = deadline - created;
        const elapsed = now - created;
        const timePct = total > 0 ? Math.min(100, Math.max(0, (elapsed / total) * 100)) : 100;
        const msRemaining = deadline - now;
        const isExpired = msRemaining < 0;
        let remainingText = '';
        if (isExpired) remainingText = 'Expired';
        else if (msRemaining < 86400000) remainingText = 'Due today';
        else if (msRemaining < 86400000 * 30) {
            const days = Math.ceil(msRemaining / 86400000);
            remainingText = `${days} day${days !== 1 ? 's' : ''} left`;
        } else {
            const months = Math.floor(msRemaining / (86400000 * 30));
            remainingText = `${months} month${months !== 1 ? 's' : ''} left`;
        }
        return { timePct: Math.round(timePct * 10) / 10, remainingText, isExpired };
    }

    async deleteGoal(goalId) {
        if (!confirm('Are you sure you want to delete this goal? All videos and articles will be removed.')) return;
        try {
            await this.apiCall(`${this.apiBase}/goals/${goalId}?user_id=${this.userId}`, { method: 'DELETE' });
            this.showNotification('Goal deleted successfully', 'success');
            if (window.location.pathname.includes('/goals.html') && new URLSearchParams(window.location.search).get('id')) {
                window.location.href = '/goals.html';
            } else {
                this.initGoals();
            }
        } catch (e) {
            // handled by apiCall
        }
    }

    getCurrentGoalIdForChat() {
        const params = new URLSearchParams(window.location.search);
        return params.get('id') || params.get('goal') || null;
    }

    async startQuiz(goalId) {
        try {
            const container = document.querySelector('.goal-detail-content');
            if (!container) return;
            container.innerHTML = this.createSpinner('Loading quiz...');
            const data = await this.apiCall(`${this.apiBase}/goals/${goalId}/quiz?user_id=${this.userId}`);
            if (!data.can_take) {
                this.showNotification(data.reason || 'You cannot take the quiz right now', 'error');
                await this.showGoalDetails(goalId);
                return;
            }
            this.renderQuiz(goalId, data.quiz.questions);
        } catch (e) {
            this.showNotification('Failed to load quiz', 'error');
        }
    }

    renderQuiz(goalId, questions) {
        const container = document.querySelector('.goal-detail-content');
        if (!container) return;
        const html = `
            <div class="quiz-panel" style="background:rgba(0,0,0,0.35);border:1px solid rgba(255,255,255,0.08);border-radius:14px;padding:1.5rem;margin-top:1rem;">
                <h2 style="margin:0 0 1rem;font-size:1.2rem;"><i class="fas fa-clipboard-check"></i> Final Validation Quiz</h2>
                <p style="color:var(--text-muted);margin-bottom:1.25rem;">Answer all 10 questions. You need more than 5 correct answers to validate your goal.</p>
                <form id="quiz-form" style="display:flex;flex-direction:column;gap:1.25rem;">
                    ${questions.map((q, idx) => `
                        <div class="quiz-question" style="background:rgba(255,255,255,0.03);border-radius:10px;padding:1rem;">
                            <div style="font-weight:600;margin-bottom:0.5rem;">${idx + 1}. ${q.question}</div>
                            <div style="display:flex;flex-direction:column;gap:0.35rem;">
                                ${['A','B','C','D'].map(opt => `
                                    <label style="cursor:pointer;display:flex;align-items:center;gap:0.5rem;font-size:0.9rem;">
                                        <input type="radio" name="q${idx + 1}" value="${opt}" required>
                                        <span><strong>${opt}.</strong> ${q.options[opt] || ''}</span>
                                    </label>
                                `).join('')}
                            </div>
                        </div>
                    `).join('')}
                    <div style="display:flex;gap:0.75rem;justify-content:flex-end;margin-top:0.5rem;">
                        <button type="button" class="btn" onclick="bigDreamApp.showGoalDetails('${goalId}')">Cancel</button>
                        <button type="submit" class="btn btn-accent"><i class="fas fa-paper-plane"></i> Submit Quiz</button>
                    </div>
                </form>
                <div id="quiz-result" style="margin-top:1rem;"></div>
            </div>
        `;
        container.innerHTML = html;
        document.getElementById('quiz-form').addEventListener('submit', (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const answers = {};
            for (let i = 1; i <= questions.length; i++) {
                answers[i] = formData.get(`q${i}`) || '';
            }
            this.submitQuiz(goalId, answers);
        });
    }

    async submitQuiz(goalId, answers) {
        try {
            const resultDiv = document.getElementById('quiz-result');
            if (resultDiv) resultDiv.innerHTML = '<p>Checking answers...</p>';
            const data = await this.apiCall(`${this.apiBase}/goals/${goalId}/quiz/submit?user_id=${this.userId}`, {
                method: 'POST',
                body: JSON.stringify({ answers })
            });
            if (data.error) {
                this.showNotification(data.error, 'error');
                if (resultDiv) resultDiv.innerHTML = `<p style="color:#ff7777;">${data.error}</p>`;
                return;
            }
            if (data.passed) {
                this.showNotification(`You passed! Score ${data.score}/10. Goal validated.`, 'success');
                setTimeout(() => {
                    window.location.href = '/goals.html';
                }, 1200);
            } else if (data.permanently_failed) {
                this.showNotification(`You scored ${data.score}/10. Quiz permanently failed.`, 'error');
                setTimeout(() => {
                    window.location.href = '/goals.html';
                }, 1200);
            } else {
                this.showNotification(`You scored ${data.score}/10. Retake available tomorrow.`, 'error');
                if (resultDiv) {
                    resultDiv.innerHTML = `<p style="color:#ff7777;">You scored <strong>${data.score}/10</strong>. You can retake the quiz tomorrow after reviewing the material.</p>`;
                }
            }
        } catch (e) {
            this.showNotification('Failed to submit quiz', 'error');
        }
    }

    async loadGoalsList(container) {
        container.innerHTML = this.createSpinner('Loading your goals...');

        try {
            const response = await this.apiCall(`${this.apiBase}/goals?user_id=${this.userId}`);
            const goalsData = response || {};
            const goals = Object.values(goalsData);

            if (goals.length === 0) {
                container.innerHTML = this.createEmptyState(
                    'fas fa-bullseye',
                    'No Goals Yet',
                    'Start by creating your first goal in the Dashboard!'
                );
                return;
            }

            container.innerHTML = goals.map(goalData => {
                const goal = goalData.goal || goalData;
                const results = goalData.results || {};
                const plan = results.plan || {};
                const progress = Math.min(100, Math.round(goal.progress || 0));
                const timeMeta = this.getGoalTimeProgress(goalData);
                const isFailed = !!(goal.quiz && goal.quiz.permanently_failed);
                const statusClass = isFailed ? 'failed' : (timeMeta.isExpired ? 'expired' : (goalData.status || 'processing'));
                const timeClass = timeMeta.isExpired ? 'expired' : timeMeta.timePct >= 90 ? 'urgent' : timeMeta.timePct >= 60 ? 'warning' : 'ok';

                return `
                    <div class="card goal-card" onclick="bigDreamApp.openGoal('${goal.id}')">
                        <h3>
                            <i class="fas fa-bullseye"></i>
                            ${goal.description}
                        </h3>

                        <div class="goal-meta">
                            <span>
                                <i class="far fa-calendar"></i>
                                ${this.formatDate(goal.deadline)}
                            </span>
                        </div>

                        <div class="goal-time-remaining ${timeClass}">
                            <i class="fas fa-clock"></i> ${timeMeta.remainingText}
                        </div>

                        <div class="goal-progress-section">
                            <div class="progress-row">
                                <span class="progress-label">Completion</span>
                                <div class="progress-bar-bg">
                                    <div class="progress-bar-fill completion" style="width: ${progress}%"></div>
                                </div>
                                <span class="progress-value">${progress}%</span>
                            </div>
                            <div class="progress-row">
                                <span class="progress-label">Time elapsed</span>
                                <div class="progress-bar-bg">
                                    <div class="progress-bar-fill time" style="width: ${timeMeta.timePct}%"></div>
                                </div>
                                <span class="progress-value">${timeMeta.timePct}%</span>
                            </div>
                        </div>


                        <div class="goal-card-actions">
                            ${(() => {
                                const progress = goal.progress || 0;
                                const isFailed = !!(goal.quiz && goal.quiz.permanently_failed);
                                const quizPassed = !!(goal.quiz && goal.quiz.passed);
                                if (progress >= 100 && !quizPassed && !isFailed) {
                                    return `<button class="btn btn-accent" onclick="event.stopPropagation(); bigDreamApp.openGoal('${goal.id}')"><i class="fas fa-clipboard-check"></i> Take Quiz</button>`;
                                } else if (isFailed) {
                                    return `<span class="btn" style="background:rgba(255,0,0,0.12);color:#ff5555;border-color:rgba(255,0,0,0.3);cursor:default;"><i class="fas fa-times-circle"></i> Failed</span>`;
                                }
                                return '';
                            })()}
                            <button class="btn btn-danger" onclick="event.stopPropagation(); bigDreamApp.deleteGoal('${goal.id}')">
                                <i class="fas fa-trash"></i> Delete
                            </button>
                        </div>
                    </div>
                `;
            }).join('');
        } catch (error) {
            container.innerHTML = this.createError('Failed to load goals');
        }
    }

    async showGoalDetails(goalId) {
        const container = document.querySelector('.goal-detail-content');
        if (!container) return;

        container.innerHTML = this.createSpinner('Loading your plan...');

        try {
            const response = await this.apiCall(`${this.apiBase}/goals?user_id=${this.userId}`);
            const goalsData = response || {};
            const goalData = Object.values(goalsData).find(g =>
                (g.goal && g.goal.id === goalId) || g.id === goalId
            );

            if (!goalData) {
                container.innerHTML = this.createError('Goal not found');
                return;
            }

            const goal = goalData.goal || goalData;
            const results = goalData.results || {};
            const plan = results.plan || goal.plan || {};
            const weeks = plan.weekly_breakdown || [];
            
            // DEBUG: Log data structure
            console.log('[DEBUG] Goal ID:', goalId);
            console.log('[DEBUG] Plan keys:', Object.keys(plan));
            console.log('[DEBUG] Weeks count:', weeks.length);
            console.log('[DEBUG] First week:', weeks[0] ? {
                week: weeks[0].week,
                theme: weeks[0].theme,
                subtopicsCount: weeks[0].subtopics?.length,
                firstSubtopic: weeks[0].subtopics?.[0]
            } : 'no weeks');
            const timeMeta = this.getGoalTimeProgress(goalData);
            const isCompleted = goalData.status === 'completed';
            const isFailed = !!(goal.quiz && goal.quiz.permanently_failed);
            const goalTag = isCompleted ? 'COMPLETED GOAL' : (isFailed ? 'FAILED GOAL' : (timeMeta.isExpired ? 'EXPIRED GOAL' : 'ACTIVE GOAL'));

            document.title = `${goal.description} - BigDream`;

            const headerEl = document.getElementById('goal-detail-header');
            if (headerEl) {
                headerEl.innerHTML = `
                    <a href="/goals.html" class="goal-detail-back">
                        <i class="fas fa-arrow-left"></i> All Goals
                    </a>
                    ${isFailed ? `<span class="quiz-failed-badge"><i class="fas fa-times-circle"></i> Validation Failed</span>` : ''}
                `;
            }


            const deadlineDate = goal.deadline ? new Date(goal.deadline) : null;
            const daysLeft = deadlineDate
                ? Math.ceil((deadlineDate - new Date()) / (1000 * 60 * 60 * 24))
                : null;
            const daysLeftText = daysLeft === null ? '—'
                : daysLeft > 0  ? `${daysLeft} days remaining`
                : daysLeft === 0 ? 'Due today'
                : `${Math.abs(daysLeft)} days overdue`;
            const urgencyClass = daysLeft !== null && daysLeft <= 7  ? 'urgent'
                               : daysLeft !== null && daysLeft <= 30 ? 'warning' : 'ok';
            const deadlineFmt = deadlineDate
                ? deadlineDate.toLocaleDateString('en-US', {year:'numeric', month:'long', day:'numeric'})
                : 'Not set';

            // DEBUG: Check weeks data before rendering
            console.log('[DEBUG] Rendering timeline with weeks:', weeks.length);
            weeks.forEach((w, i) => {
                console.log(`[DEBUG] Week ${i}: subtopics = ${w.subtopics?.length}, first =`, w.subtopics?.[0]);
            });
            
            const timelineHTML = weeks.length > 0 ? `
                <div class="gid-timeline">
                    <div class="gid-timeline-line"></div>
                    ${weeks.map((week, idx) => `
                        <div class="gid-week-item" style="animation-delay:${idx * 0.06}s">
                            <div class="gid-week-node">
                                <div class="gid-week-num">${week.week}</div>
                            </div>
                            <div class="gid-week-card">
                                <div class="gid-week-tag">WEEK ${week.week}</div>
                                <div class="gid-week-theme">${this.cleanDisplayText(week.theme || 'Learning Week')}</div>
                                ${week.explanation ? `<div class="gid-week-explanation">${this.cleanDisplayText(week.explanation)}</div>` : ''}
                                ${(console.log(`[DEBUG] Week ${week.week}: subtopics=${week.subtopics?.length}, type=${typeof week.subtopics}`), week.subtopics && week.subtopics.length > 0) ? `
                                    <div class="gid-week-subtopics">
                                        ${week.subtopics.map(st => `
                                            <div class="gid-subtopic">
                                                <div class="gid-subtopic-title">
                                                    <i class="fas fa-chevron-right"></i>
                                                    <span>${this.cleanDisplayText(st.title)}</span>
                                                </div>
                                                ${st.video || st.article ? `
                                                    <div class="gid-subtopic-resources">
                                                        ${st.video ? `
                                                            <a href="${st.video.url}" target="_blank" class="gid-resource-link gid-video-link" title="Watch Video">
                                                                <i class="fas fa-play-circle"></i>
                                                            </a>
                                                        ` : ''}
                                                        ${st.article ? `
                                                            <a href="${st.article.url}" target="_blank" class="gid-resource-link gid-article-link" title="Read Article">
                                                                <i class="fas fa-book-open"></i>
                                                            </a>
                                                        ` : ''}
                                                    </div>
                                                ` : ''}
                                            </div>
                                        `).join('')}
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    `).join('')}
                </div>
            ` : `
                <div class="gid-plan-pending">
                    <i class="fas fa-spinner fa-spin"></i>
                    <p>Your learning plan is being generated — check back in a moment.</p>
                </div>
            `;

            const principlesHTML = plan.core_principles && plan.core_principles.length > 0 ? `
                <div class="gid-principles">
                    <div class="gid-section-label">Core Principles</div>
                    <div class="gid-principles-list">
                        ${plan.core_principles.map(p => `<span class="gid-principle">${this.cleanDisplayText(p)}</span>`).join('')}
                    </div>
                </div>
            ` : '';

            const totalWeeks = goal.total_weeks || 0;
            const totalContent = totalWeeks * 2;
            const watchedCount = (goal.watched_video_urls || []).length;
            const readCount = (goal.read_article_urls || []).length;
            const contentProgressHTML = totalContent > 0 ? `
                <div class="gid-divider"></div>
                <div>
                    <div class="gid-section-label">Content Progress</div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 0.3rem;">
                        <span style="color: var(--cyber-cyan);"><i class="fas fa-video"></i> ${watchedCount}/${totalContent} videos watched</span>
                        <span style="color: var(--primary);"><i class="fas fa-book-open"></i> ${readCount}/${totalContent} articles read</span>
                    </div>
                </div>
            ` : '';

            container.innerHTML = `
                <div class="goal-split-view">

                    <!-- LEFT: Goal Info Card -->
                    <div class="goal-info-card">
                        <div class="gid-tag">${goalTag}</div>
                        <h2 class="gid-title">${goal.description}</h2>

                        <div class="gid-divider"></div>

                        <!-- Deadline -->
                        <div class="gid-deadline-block">
                            <div class="gid-deadline-icon"><i class="fas fa-calendar-alt"></i></div>
                            <div>
                                <div class="gid-section-label">Deadline</div>
                                <div class="gid-deadline-date">${deadlineFmt}</div>
                                <div class="gid-deadline-remaining gid-remaining-${timeMeta.isExpired ? 'urgent' : urgencyClass}">${timeMeta.isExpired ? 'Expired — ' + timeMeta.remainingText : daysLeftText}</div>
                            </div>
                        </div>

                        <div class="gid-progress-block">
                            <div class="progress-row">
                                <span class="progress-label">Completion</span>
                                <div class="progress-bar-bg">
                                    <div class="progress-bar-fill completion" style="width: ${Math.min(100, Math.round(goal.progress || 0))}%"></div>
                                </div>
                                <span class="progress-value">${Math.min(100, Math.round(goal.progress || 0))}%</span>
                            </div>
                            <div class="progress-row">
                                <span class="progress-label">Time elapsed</span>
                                <div class="progress-bar-bg">
                                    <div class="progress-bar-fill time" style="width: ${timeMeta.timePct}%"></div>
                                </div>
                                <span class="progress-value">${timeMeta.timePct}%</span>
                            </div>
                        </div>

                        ${contentProgressHTML}

                        <div class="gid-divider"></div>

                        <div class="gid-validation-block">
                            <div class="gid-validation-instructions">
                                <div class="gid-section-label">To validate your goal</div>
                                <ul class="gid-checklist">
                                    <li><i class="fas fa-video"></i> Watch all assigned videos</li>
                                    <li><i class="fas fa-book-open"></i> Read all assigned articles</li>
                                    <li><i class="fas fa-tasks"></i> Complete all weekly topics</li>
                                    <li><i class="fas fa-chart-line"></i> Reach 100% completion</li>
                                </ul>
                            </div>
                            <div class="gid-validated-row">
                                <input type="checkbox" class="gid-validated-checkbox" ${Math.round(goal.progress || 0) >= 100 ? 'checked' : ''} disabled>
                                <span class="gid-validated-label">Goal Validated</span>
                            </div>
                        </div>

                    </div>

                    <!-- RIGHT: Timeline Card -->
                    <div class="goal-timeline-card">
                        <div class="gtc-header">
                            <div class="gid-tag">LEARNING PLAN</div>
                            <h2 class="gtc-title">${plan.total_weeks ? `${plan.total_weeks}-Week Roadmap` : 'Your Roadmap'}</h2>
                            ${principlesHTML}
                        </div>
                        <div class="gtc-body">
                            ${timelineHTML}
                        </div>
                    </div>

                </div>
            `;
        } catch (error) {
            container.innerHTML = this.createError('Failed to load goal details');
        }
    }

    openGoal(goalId) {
        window.location.href = `/goals.html?id=${goalId}`;
    }

    getGoalIdFromUrl() {
        const params = new URLSearchParams(window.location.search);
        return params.get('id') || params.get('goal') || null;
    }

    async toggleVideoWatch(goalId, videoUrl, isWatched) {
        try {
            const endpoint = isWatched ? 'unwatch' : 'watch';
            const res = await this.apiCall(`${this.apiBase}/goals/${goalId}/videos/${endpoint}?user_id=${this.userId}`, {
                method: 'POST',
                body: JSON.stringify({ video_url: videoUrl })
            });
            this.showNotification(isWatched ? 'Video unwatched' : 'Video marked as watched!', 'success');
            if (res && res.goal_progress >= 100) {
                this.showNotification('All content completed! Take the Final Validation Quiz on the goal page.', 'success');
            }
            this.initVideos();
            this.loadDashboardStats();
            if (window.location.pathname.includes('goals.html') && window.location.search.includes(goalId)) {
                this.showGoalDetails(goalId);
            }
        } catch (e) {
            // handled by apiCall
        }
    }

    async toggleArticleRead(goalId, articleUrl, isRead) {
        try {
            const endpoint = isRead ? 'unread' : 'read';
            const res = await this.apiCall(`${this.apiBase}/goals/${goalId}/articles/${endpoint}?user_id=${this.userId}`, {
                method: 'POST',
                body: JSON.stringify({ article_url: articleUrl })
            });
            this.showNotification(isRead ? 'Article unread' : 'Article marked as read!', 'success');
            if (res && res.goal_progress >= 100) {
                this.showNotification('All content completed! Take the Final Validation Quiz on the goal page.', 'success');
            }
            this.initArticles();
            this.loadDashboardStats();
            if (window.location.pathname.includes('goals.html') && window.location.search.includes(goalId)) {
                this.showGoalDetails(goalId);
            }
        } catch (e) {
            // handled by apiCall
        }
    }

    async initVideos() {
        const container = document.getElementById('videos-container');
        const goalId = this.getGoalIdFromUrl();

        container.innerHTML = this.createSpinner('Loading videos...');

        try {
            let videos = [];
            let watchedUrls = [];

            if (goalId) {
                const [videosResp, goalsResp] = await Promise.all([
                    this.apiCall(`${this.apiBase}/videos/${goalId}`),
                    this.apiCall(`${this.apiBase}/goals?user_id=${this.userId}`)
                ]);
                videos = videosResp || [];
                const goalData = Object.values(goalsResp || {}).find(g =>
                    (g.goal && g.goal.id === goalId) || g.id === goalId
                );
                const goal = goalData ? (goalData.goal || goalData) : null;
                watchedUrls = goal ? (goal.watched_video_urls || []) : [];
            } else {
                const goalsResponse = await this.apiCall(`${this.apiBase}/goals?user_id=${this.userId}`);
                const goals = Object.values(goalsResponse || {});
                const goalsMap = {};
                goals.forEach(gd => {
                    const g = gd.goal || gd;
                    goalsMap[g.id] = g;
                });

                for (const goalData of goals) {
                    const goal = goalData.goal || goalData;
                    try {
                        const goalVideos = await this.apiCall(`${this.apiBase}/videos/${goal.id}`);
                        if (Array.isArray(goalVideos)) {
                            const w = goal.watched_video_urls || [];
                            videos.push(...goalVideos.map(v => ({ ...v, goal_title: goal.description, _watched: w.includes(v.url) })));
                        }
                    } catch (e) {
                        // continue loading other goals
                    }
                }
            }

            if (videos.length === 0) {
                container.innerHTML = this.createEmptyState(
                    'fas fa-video',
                    'No Videos Yet',
                    'Create a goal and we\'ll curate videos for you!'
                );
                return;
            }

            container.innerHTML = videos.map(video => {
                const thumb = video.thumbnail ||
                    (video.url && video.url.includes('youtube.com/watch?v=')
                        ? `https://img.youtube.com/vi/${new URL(video.url).searchParams.get('v')}/hqdefault.jpg`
                        : 'https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg');
                const desc = (video.description || '').substring(0, 90).trim();
                const urlJs = JSON.stringify(video.url || '');
                const isWatched = goalId
                    ? watchedUrls.includes(video.url)
                    : !!video._watched;
                const cardGoalId = goalId || video.goal_id || '';
                const watchCheckbox = cardGoalId ? `
                    <button type="button" class="content-check${isWatched ? ' checked' : ''}" onclick='bigDreamApp.toggleVideoWatch("${cardGoalId}", ${urlJs}, ${isWatched})'>
                        <span class="content-check-box"><i class="fas fa-check"></i></span>
                        <span class="content-check-label">${isWatched ? 'Done' : 'Mark as done'}</span>
                    </button>
                ` : (
                    isWatched
                        ? `<span class="content-check checked" style="cursor:default;"><span class="content-check-box"><i class="fas fa-check"></i></span><span class="content-check-label">Done</span></span>`
                        : `<span class="content-check" style="cursor:default;opacity:0.6;"><span class="content-check-box"></span><span class="content-check-label">No goal linked</span></span>`
                );
                return `
                <div class="video-card-new">
                    <div class="video-thumb-wrap">
                        <a href="${video.url || '#'}" target="_blank" class="video-thumb-link">
                            <img src="${thumb}"
                                 alt="${video.title}"
                                 onerror="this.src='https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg'">
                            <div class="video-play-overlay">
                                <div class="video-play-btn">
                                    <i class="fas fa-play"></i>
                                </div>
                            </div>
                        </a>
                        ${video.duration ? `<div class="video-duration-badge">${video.duration}</div>` : ''}
                        ${video.week ? `<div class="video-week-badge">Week ${video.week}</div>` : ''}
                        ${video.goal_title ? `<div class="video-goal-badge">${video.goal_title}</div>` : ''}
                        ${isWatched ? `<div class="video-watched-badge"><i class="fas fa-check"></i></div>` : ''}
                    </div>
                    <div class="video-card-body">
                        <div class="video-channel">${video.channel || 'YouTube'}</div>
                        <a href="${video.url || '#'}" target="_blank" class="video-title-link"><div class="video-title">${video.title}</div></a>
                        ${desc ? `<div class="video-desc">${desc}…</div>` : ''}
                        <div class="video-card-actions">
                            ${watchCheckbox}
                        </div>
                    </div>
                </div>
            `}).join('');
        } catch (error) {
            container.innerHTML = this.createError('Failed to load videos');
        }
    }

    async initArticles() {
        const container = document.getElementById('articles-container');
        const goalId = this.getGoalIdFromUrl();

        container.innerHTML = this.createSpinner('Loading articles...');

        try {
            let articles = [];
            let readUrls = [];

            if (goalId) {
                const [articlesResp, goalsResp] = await Promise.all([
                    this.apiCall(`${this.apiBase}/articles/${goalId}`),
                    this.apiCall(`${this.apiBase}/goals?user_id=${this.userId}`)
                ]);
                articles = articlesResp || [];
                const goalData = Object.values(goalsResp || {}).find(g =>
                    (g.goal && g.goal.id === goalId) || g.id === goalId
                );
                const goal = goalData ? (goalData.goal || goalData) : null;
                readUrls = goal ? (goal.read_article_urls || []) : [];
            } else {
                const goalsResponse = await this.apiCall(`${this.apiBase}/goals?user_id=${this.userId}`);
                const goals = Object.values(goalsResponse || {});

                for (const goalData of goals) {
                    const goal = goalData.goal || goalData;
                    try {
                        const goalArticles = await this.apiCall(`${this.apiBase}/articles/${goal.id}`);
                        if (Array.isArray(goalArticles)) {
                            const r = goal.read_article_urls || [];
                            articles.push(...goalArticles.map(a => ({ ...a, goal_title: goal.description, _read: r.includes(a.url) })));
                        }
                    } catch (e) {
                        // continue loading other goals
                    }
                }
            }

            if (articles.length === 0) {
                container.innerHTML = this.createEmptyState(
                    'fas fa-newspaper',
                    'No Articles Yet',
                    'Create a goal and we\'ll curate articles for you!'
                );
                return;
            }

            container.innerHTML = articles.map(article => {
                const urlJs = JSON.stringify(article.url || '');
                const isRead = goalId
                    ? readUrls.includes(article.url)
                    : !!article._read;
                const cardGoalId = goalId || article.goal_id || '';
                const readCheckbox = cardGoalId ? `
                    <button type="button" class="content-check${isRead ? ' checked' : ''}" onclick='bigDreamApp.toggleArticleRead("${cardGoalId}", ${urlJs}, ${isRead})'>
                        <span class="content-check-box"><i class="fas fa-check"></i></span>
                        <span class="content-check-label">${isRead ? 'Done' : 'Mark as done'}</span>
                    </button>
                ` : (
                    isRead
                        ? `<span class="content-check checked" style="cursor:default;"><span class="content-check-box"><i class="fas fa-check"></i></span><span class="content-check-label">Done</span></span>`
                        : `<span class="content-check" style="cursor:default;opacity:0.6;"><span class="content-check-box"></span><span class="content-check-label">No goal linked</span></span>`
                );
                return `
                <div class="card article-card${isRead ? ' article-read' : ''}">
                    ${article.image ? `
                        <a href="${article.url || '#'}" target="_blank">
                            <img src="${article.image}" alt="${article.title}" class="article-image"
                                 onerror="this.style.display='none'">
                        </a>
                    ` : ''}

                    <div class="article-content">
                        <a href="${article.url || '#'}" target="_blank" class="article-title-link"><h3 style="margin-bottom: 10px; font-size: 16px;">${article.title}</h3></a>

                        <p style="color: var(--text-sub); font-size: 14px; margin-bottom: 15px; flex-grow: 1;">
                            ${(article.description || 'Read this article to learn more.').substring(0, 120)}...
                        </p>

                        ${article.goal_title ? `
                            <div class="article-tags">
                                <span class="article-tag">${article.goal_title}</span>
                            </div>
                        ` : ''}

                        <div class="article-meta">
                            <span><i class="far fa-clock"></i> ${article.read_time || '5 min'}</span>
                            ${article.week ? `<span style="color: var(--neon-cyan);">Week ${article.week}</span>` : ''}
                        </div>

                        <div class="article-card-actions">
                            ${readCheckbox}
                        </div>
                    </div>
                </div>
            `;
            }).join('');
        } catch (error) {
            container.innerHTML = this.createError('Failed to load articles');
        }
    }

    initAccount() {
        if (!this.getToken()) {
            window.location.href = '/login.html';
            return;
        }
    }

    formatDate(dateString) {
        if (!dateString) return 'No deadline';
        try {
            const date = new Date(dateString);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
        } catch {
            return dateString;
        }
    }

    createSpinner(text = 'Loading...') {
        return `
            <div class="loading-state">
                <i class="fas fa-spinner fa-spin"></i>
                <p>${text}</p>
            </div>
        `;
    }

    createEmptyState(icon, title, message) {
        return `
            <div class="empty-state">
                <i class="${icon}"></i>
                <h3>${title}</h3>
                <p>${message}</p>
            </div>
        `;
    }

    createError(message) {
        return `
            <div class="empty-state">
                <i class="fas fa-exclamation-triangle"></i>
                <h3>Error</h3>
                <p>${message}</p>
                <button class="btn" onclick="location.reload()">
                    <i class="fas fa-sync-alt"></i> Retry
                </button>
            </div>
        `;
    }

    showNotification(message, type = 'info') {
        document.querySelectorAll('.bd-notification').forEach(el => el.remove());

        const notification = document.createElement('div');
        notification.className = `bd-notification ${type}`;
        notification.style.animation = 'slideInRight 0.3s ease';
        notification.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check-circle' :
                              type === 'error' ? 'exclamation-circle' :
                              'info-circle'}"></i>
            <span>${message}</span>
            <button onclick="this.parentElement.remove()">
                <i class="fas fa-times"></i>
            </button>
        `;

        document.body.appendChild(notification);

        setTimeout(() => {
            if (notification.parentElement) {
                notification.style.animation = 'slideOutRight 0.3s ease';
                setTimeout(() => notification.remove(), 300);
            }
        }, 5000);
    }
}

let bigDreamApp;
document.addEventListener('DOMContentLoaded', () => {
    bigDreamApp = new BigDreamApp();
});
