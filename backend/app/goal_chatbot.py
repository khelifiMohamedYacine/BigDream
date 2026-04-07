import json
import logging
import os
import re
import uuid
import aiohttp
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# HuggingFace Serverless Inference API – Free tier models
# Router endpoint for chat completions (model passed in body)
HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
HF_CODE_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
HF_PLAN_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"  # Free, supports chat completions

# Signals that a message is code-related → route to HF code model
CODE_SIGNALS = [
    "```", "def ", "class ", "import ", "print(", "syntax error", "traceback",
    "write a function", "write code", "write a class", "write me a", "write me",
    "make me a", "make me", "create a", "build a", "code a", "program a",
    "explain this code", "explain this function", "debug", "fix this code",
    "what does this do", "how to implement", "give me an example",
    "code for", "help me code", "show me how to code", "example of",
    "not working", "error:", "exception:", "indentationerror", "typeerror",
    "nameerror", "attributeerror", "valueerror", "how do i write",
    "calculator", "to-do list", "todo list", "todo app", "weather app",
    "chatbot", "web scraper", "api", "flask app", "django app",
]

SYSTEM_PROMPT = (
    "You are BigDream — a Python programming mentor. "
    "Your personality: calm, encouraging, honest, growth-mindset focused.\n\n"

    "PYTHON MENTORING: You help users learn Python, debug code, set learning goals, "
    "and build real projects. Use encouraging, growth-mindset language. "
    "For code questions, always use ```python code blocks.\n"
    "CODE FORMATTING — always follow exactly:\n"
    "- Put a newline immediately after ```python and before the first line of code\n"
    "- Each statement on its OWN line with proper indentation — never squash onto one line\n"
    "- Put a newline before the closing ``` fence\n\n"

    "CONTENT POLICY — politely decline and do NOT engage with:\n"
    "- Hate speech, slurs, racial/ethnic/religious insults\n"
    "- Sexual or explicit content\n"
    "- Instructions for violence, weapons, or illegal activities\n"
    "- Self-harm methods\n"
    "- Harassment or threats toward others\n"
    "For policy violations: one firm, brief decline — then offer to help with Python instead. "
    "Never lecture, never repeat the violation back, never apologise excessively.\n\n"

    "TONE: Be real. Don't be a corporate robot. Speak like a knowledgeable friend.\n\n"
    
    "Focus your responses on Python programming and learning. Be direct and professional."
)

CODE_SYSTEM_PROMPT = (
    "You are an expert Python developer and educator. "
    "CRITICAL FORMATTING RULES:\n"
    "- Always wrap ALL code in ```python ... ``` fenced blocks, never inline\n"
    "- Put a newline immediately after ```python and before the first line of code\n"
    "- Put a newline before the closing ``` and never omit it\n"
    "- Each statement on its OWN line — proper indentation, never squash onto one line\n"
    "- Add a blank line between logical sections inside the code\n"
    "- Put a short comment on each non-obvious line\n"
    "- Double-check that all operators (*, +, -, /, etc.) are present and syntax is valid\n\n"
    "CONVERSATION RULES:\n"
    "- When asked to 'improve', 'elaborate', or 'make a better version', you MUST build on "
    "the EXACT code from the previous response — do not switch topics\n"
    "- Read the conversation history carefully before responding\n"
    "- After the code block, give a 2-3 sentence explanation of what was added/changed\n"
    "- NEVER truncate code mid-function — you have UNLIMITED token budget (8192 tokens max) so always provide the COMPLETE runnable example\n"
    "- If a function is long, finish it completely rather than stopping early\n\n"
    "Follow PEP 8. Show runnable examples. Be concise but complete."
)

# ─────────────────────────────────────────────────────────
# CONTENT MODERATION
# Loaded from restrictions/content_policy.json
# Hard blocks only: hate, abuse, nsfw, dangerous instructions
# Only hard content blocks (hate, abuse, etc.) - general chat handled by main model with direct tone
# ─────────────────────────────────────────────────────────

def _load_content_policy() -> Dict:
    """Load content policy from restrictions folder."""
    policy_path = Path(__file__).parent.parent / "restrictions" / "content_policy.json"
    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Fallback if file missing
        return {
            "categories": {},
            "escalation": {"max_strikes_before_silent": 3, "silent_mode_response": "I can only help with Python."}
        }

_CONTENT_POLICY = _load_content_policy()


def _policy_violation(message: str) -> Optional[str]:
    """
    Check for hard content policy violations from JSON config.
    Returns a violation category string if found, else None.
    """
    low = message.lower()
    categories = _CONTENT_POLICY.get("categories", {})
    
    for category, config in categories.items():
        blocked = config.get("blocked_terms", []) + config.get("blocked_patterns", [])
        if any(t in low for t in blocked):
            return category
    
    return None


def _get_policy_reply(violation: str, strike_count: int) -> str:
    """Get reply for violation from policy config."""
    categories = _CONTENT_POLICY.get("categories", {})
    config = categories.get(violation, {})
    response = config.get("response", "I can't help with that. What Python topic can I assist with?")
    return response


def _is_code_question(message: str) -> bool:
    """Detect if the message is code-related → route to HuggingFace code model."""
    msg_lower = message.lower()
    return any(signal in msg_lower for signal in CODE_SIGNALS)


_CODE_FOLLOWUP_SIGNALS: List[str] = [
    "elaborate", "more elaborate", "very elaborate", "make it better",
    "improve it", "improve this", "better version", "more advanced",
    "advanced version", "more complex", "upgrade it", "upgrade this",
    "extend it", "extend this", "add more", "add to it", "build on",
    "make it more", "make a better", "can you make", "make it bigger",
    "now make", "now do", "do a better", "do an advanced",
    "more features", "add features", "refactor", "clean it up",
    "optimise", "optimize", "another version", "different version",
    "show me more", "show more", "go deeper", "in more detail",
]


def _is_code_followup(message: str, session: dict) -> bool:
    """
    Return True when the user is asking to improve/extend code from a
    previous bot response — even if the message has no explicit code signals.
    """
    msg_lower = message.lower()

    if not any(sig in msg_lower for sig in _CODE_FOLLOWUP_SIGNALS):
        return False

    recent_bot = [
        h for h in session.get("history", [])[-6:]
        if h.startswith("Bot:") and "```" in h
    ]
    return len(recent_bot) > 0


def _fix_code_formatting(content: str) -> str:
    """Fix code formatting issues - ensure proper newlines in code blocks."""
    import re
    
    # Find code blocks and fix formatting inside them
    def fix_block(match):
        block = match.group(0)
        # Check if code is all on one line (indicates formatting issue)
        lines = block.split('\n')
        if len(lines) <= 2:
            # Code is squashed - try to fix by adding newlines after colons and semicolons
            code = block
            # Fix common patterns where newlines are missing
            code = re.sub(r'(def\s+\w+\([^)]*\):)\s*([^\n])', r'\1\n    \2', code)
            code = re.sub(r'(class\s+\w+[^:]*:)\s*([^\n])', r'\1\n    \2', code)
            code = re.sub(r'(:)(\s*)(?=[a-zA-Z_])', r'\1\n    ', code)
            return code
        return block
    
    # Apply fix to code blocks
    content = re.sub(r'```python[\s\S]*?```', fix_block, content)
    return content


async def hf_code_chat(message: str, history: list) -> str:
    """Call HuggingFace Qwen2.5-Coder for code generation and explanation."""
    hf_key = os.getenv("HUGGINGFACE_API_KEY", "")
    if not hf_key:
        return await groq_general_chat(message, history, use_code_prompt=True)

    messages = [{"role": "system", "content": CODE_SYSTEM_PROMPT}]
    for entry in history[-6:]:
        if entry.startswith("User: "):
            messages.append({"role": "user", "content": entry[6:]})
        elif entry.startswith("Bot: "):
            messages.append({"role": "assistant", "content": entry[5:]})
    messages.append({"role": "user", "content": message})

    try:
        headers = {
            "Authorization": f"Bearer {hf_key}",
            "Content-Type": "application/json",
        }
        
        body = {
            "model": HF_CODE_MODEL,
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0.3,
            "stream": False,
        }
        
        async with aiohttp.ClientSession() as http:
            async with http.post(
                HF_ROUTER_URL, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    content = result["choices"][0]["message"]["content"].strip()
                    return _fix_code_formatting(content)
                else:
                    error_text = await resp.text()
                    print(f"[HF Code] API error: {resp.status} - {error_text[:200]}")
    except Exception as e:
        print(f"[HF Code] Exception: {e}")

    return await groq_general_chat(message, history, use_code_prompt=True)


def _validate_plan_content(content: str, expected_weeks: int) -> bool:
    """Validate that the plan contains all expected weeks."""
    if not content or len(content) < 200:
        return False
    # Count how many "Week X" patterns appear
    import re
    week_matches = re.findall(r'Week\s+\d+', content, re.IGNORECASE)
    unique_weeks = len(set([m.lower() for m in week_matches]))
    return unique_weeks >= expected_weeks


async def generate_learning_plan_with_hf(goal: str, weeks: int, why_important: str = "", goal_type: str = "project") -> str:
    """Generate structured learning plan using HF model with validation and retries."""
    hf_key = os.getenv("HUGGINGFACE_API_KEY", "")
    if not hf_key:
        print("[HF] No API key found, falling back to Groq")
        return await _generate_plan_with_groq(goal, weeks, why_important, goal_type)
    
    print(f"[HF] Generating plan for: {goal[:50]}... weeks: {weeks}, mode: {goal_type}")
    
    # Calculate phase distribution (30/50/20 split)
    phase1_weeks = max(1, round(0.3 * weeks))
    phase2_weeks = max(1, round(0.5 * weeks))
    phase3_weeks = max(1, weeks - phase1_weeks - phase2_weeks)
    
    # Adjust if rounding caused issues
    while phase1_weeks + phase2_weeks + phase3_weeks < weeks:
        phase2_weeks += 1
    while phase1_weeks + phase2_weeks + phase3_weeks > weeks:
        phase3_weeks = max(1, phase3_weeks - 1)
    
    user_context = f"""
LEARNER GOAL: {goal}
TIMELINE: {weeks} weeks
MOTIVATION: {why_important or 'To learn Python programming'}

Create a personalized, adaptive learning plan that directly addresses this specific goal and motivation."""
    
    prompt = f"""{user_context}

🎯 SELECTED MODE: {goal_type.upper()}

The user has selected **{goal_type.upper()} MODE**. Generate content specifically for this mode.

🎯 STEP 2: GENERATE MODE-SPECIFIC CONTENT

MODE DEFINITIONS - CRITICAL:

THEORETICAL MODE:
- Focus: Theory, concepts, algorithms, exam preparation
- Subtopics: 
  * Concepts and definitions (NOT implementation)
  * Algorithm theory and analysis
  * Complexity analysis (Big O)
  * Comparisons (pros/cons of approaches)
  * Mathematical foundations
  * Exam-style practice problems
  * Theory review and key concepts
- Style: Theoretical, conceptual, analytical
- AVOID: "Implementing", "Building", "Creating", "Training", "Using [tool]"
- USE: "Understanding", "Analyzing", "Comparing", "Theory of", "Mathematics of"

PRACTICAL MODE:
- Focus: Hands-on building, tools, implementation
- Subtopics: Framework setup, coding, architecture, deployment, projects
- Style: Practical, step-by-step implementation
- AVOID: "Theory of", "Analyzing", "Comparing concepts"
- USE: "Implementing", "Building", "Creating", "Using", "Training", "Deploying"

EXAMPLES:

THEORETICAL - Deep Learning (4 weeks):
- Phase 1: Neural network theory, perceptron mathematics, activation function comparisons
- Phase 2: Backpropagation algorithm analysis, gradient descent theory, loss function comparisons
- Phase 3: CNN architecture theory, RNN theory and LSTM comparisons, regularization techniques
- Phase 4: Practice exam problems, theory review, key concept summaries

PRACTICAL - Deep Learning (4 weeks):
- Phase 1: Installing PyTorch, creating virtual environment, loading datasets
- Phase 2: Implementing neural networks, training models on MNIST, visualizing results
- Phase 3: Building CNNs for image classification, training RNNs for text, data augmentation
- Phase 4: Deploying trained model, building web app, fine-tuning for production
- Phase 2: Backpropagation algorithm analysis, gradient descent theory, loss function comparisons
- Phase 3: CNN architecture analysis, filter theory, pooling strategies
- Phase 4: RNN theory, LSTM/GRU comparisons, vanishing gradient problem analysis
- Phase 5: Regularization techniques theory, dropout analysis, batch normalization mathematics
- Phase 6: Optimization algorithms comparison, hyperparameter tuning theory, convergence analysis
- Phase 7: Practice exam problems, theory review, key concept summaries

SPECIALIZATION - Deep Learning (5 weeks):
- Phase 1: Neural network basics, frameworks
- Phase 2: CNNs, RNNs, backpropagation
- Phase 3: Transfer learning, deployment

CRITICAL - WEEK TITLE GUIDELINES:
BAD: "Setup & First Steps", "Core Concepts", "Advanced Features"
GOOD: "Building User Authentication with Django", "Training CNNs on CIFAR-10 with PyTorch"

CRITICAL - SUBTOPIC GUIDELINES:
Each subtopic MUST be SPECIFIC and SEARCHABLE on YouTube.

BAD (too vague):
- "Reviewing Key Concepts" → YouTube returns random videos
- "Understanding Fundamentals" → Too broad

GOOD (specific & searchable):
- "Implementing User Login with Django Authentication System"
- "Training a ResNet-18 on ImageNet using PyTorch Lightning"

EACH subtopic MUST include:
1. Specific technology/library name
2. Specific technique, algorithm, or feature
3. Concrete application when applicable

CRITICAL - FORMATTING RULES FOR SUBTOPICS:
- NEVER use backticks (`) or code formatting in subtopics
- NEVER write `virtualenv` - instead write "virtual environment"
- NEVER write `pip install` - instead write "installing with pip"
- NEVER write `flask run` - instead write "running Flask server"
- Use plain English descriptions, not code syntax
- BAD: "Using `pandas.DataFrame`"
- GOOD: "Creating DataFrames with pandas"
- BAD: "Creating `requirements.txt`"
- GOOD: "Creating requirements file"

EXACT FORMAT (use em-dash "—" after week number):

Week 1 — [Mode-Specific Title for Phase 1]
- [Specific task] using [specific tool/library]
- [Specific task] using [specific tool/library]
- [Specific task] using [specific tool/library]
- [Specific task] using [specific tool/library]

[Continue for ALL {weeks} weeks following the 3-phase structure]

Week {weeks} — [Mode-Specific Title for Final Phase]
- [Specific task] using [specific tool/library]
- [Specific task] using [specific tool/library]
- [Specific task] using [specific tool/library]
- [Specific task] using [specific tool/library]

REQUIREMENTS:
- MUST generate ALL {weeks} weeks - incomplete plans rejected
- Adapt structure to SELECTED mode: {goal_type.upper()}

FOR THEORETICAL MODE - CRITICAL:
- Subtopics must be THEORETICAL (concepts, analysis, comparisons)
- AVOID implementation words: "Implementing", "Building", "Creating", "Using", "Training"
- USE theory words: "Understanding", "Analyzing", "Comparing", "Theory of", "Mathematics of"
- Focus on: algorithm theory, complexity analysis, mathematical foundations, concept comparisons
- Include exam preparation: practice problems, theory review, key concepts
- Example BAD: "Training CNNs on MNIST with PyTorch"
- Example GOOD: "CNN architecture theory and filter analysis"

FOR PRACTICAL MODE - CRITICAL:
- Subtopics must be PRACTICAL (implementation, coding, building)
- AVOID theory words: "Theory of", "Analyzing concepts", "Comparing approaches"
- USE implementation words: "Implementing", "Building", "Creating", "Using", "Training"
- Focus on: hands-on coding, framework usage, project building, deployment
- Include real projects and working code
- Example BAD: "CNN architecture theory and filter analysis"
- Example GOOD: "Training CNNs on MNIST with PyTorch"

FOR ALL MODES:
- NEVER use generic titles like "Basics", "Core Concepts", "Advanced"
- NEVER use vague subtopics like "Reviewing Concepts", "Understanding Fundamentals"
- Each subtopic MUST be specific and searchable
- Max 4-6 subtopics per week
- Logical progression within each phase
- NO explanations, NO intros, NO conclusions, ONLY the week structure"""

    headers = {
        "Authorization": f"Bearer {hf_key}",
        "Content-Type": "application/json",
    }
    
    # Try multiple times with increasing max_tokens
    max_tokens_options = [2500, 3500, 4096]
    
    for attempt, max_tokens in enumerate(max_tokens_options, 1):
        try:
            print(f"[HF] Attempt {attempt}: Calling router API with max_tokens={max_tokens}")
            
            body = {
                "model": HF_PLAN_MODEL,
                "messages": [
                    {"role": "system", "content": "You are an adaptive Python curriculum designer. First detect the goal type (Fundamentals/Project/Exam/Specialization), then generate a customized plan using the 3-phase structure. Each subtopic must name specific tools and techniques. Never use generic content—adapt everything to the specific goal type."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": 0.4,
                "stream": False,
            }
            
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    HF_ROUTER_URL, json=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    print(f"[HF] Response status: {resp.status}")
                    if resp.status == 200:
                        result = await resp.json()
                        content = result["choices"][0]["message"]["content"].strip()
                        print(f"[HF] Generated plan length: {len(content)}")
                        
                        # Validate the content
                        if _validate_plan_content(content, weeks):
                            print(f"[HF] Plan validation passed: contains all {weeks} weeks")
                            return content
                        else:
                            print(f"[HF] Plan validation failed: insufficient weeks detected")
                            if attempt < len(max_tokens_options):
                                print(f"[HF] Retrying with higher max_tokens...")
                                continue
                            else:
                                print(f"[HF] All attempts failed, returning best effort")
                                return content
                    else:
                        error_text = await resp.text()
                        print(f"[HF] API error: {resp.status} - {error_text[:200]}")
        except Exception as e:
            print(f"[HF] Exception on attempt {attempt}: {e}")
            import traceback
            traceback.print_exc()
    
    return ""


async def _generate_plan_with_groq(goal: str, weeks: int, why_important: str = "", goal_type: str = "project") -> str:
    """Fallback plan generation using Groq when HF is not available."""
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        print("[Groq Plan] No Groq API key found")
        return ""
    
    print(f"[Groq Plan] Generating plan for: {goal[:50]}... weeks: {weeks}, mode: {goal_type}")
    
    mode_instructions = {
        "theoretical": """
THEORETICAL MODE - Focus on concepts and theory:
- Subtopics must be THEORETICAL (concepts, analysis, comparisons)
- AVOID: "Implementing", "Building", "Creating", "Using", "Training"
- USE: "Understanding", "Analyzing", "Comparing", "Theory of", "Mathematics of"
- Focus on: algorithm theory, complexity analysis, mathematical foundations
""",
        "practical": """
PRACTICAL MODE - Focus on hands-on implementation:
- Subtopics must be PRACTICAL (implementation, coding, building)
- AVOID: "Theory of", "Analyzing concepts", "Comparing approaches"
- USE: "Implementing", "Building", "Creating", "Using", "Training"
- Focus on: hands-on coding, framework usage, project building
"""
    }
    
    mode_instruction = mode_instructions.get(goal_type.lower(), mode_instructions["practical"])
    
    prompt = f"""Create a {weeks}-week learning plan for: {goal}

Mode: {goal_type.upper()}
{mode_instruction}

FORMAT (use em-dash "—" after week number):
Week 1 — [Specific Title]
- [Specific subtopic] using [tool/library]
- [Specific subtopic] using [tool/library]
- [Specific subtopic] using [tool/library]

[Continue for ALL {weeks} weeks]

Week {weeks} — [Final Week Title]
- [Specific subtopic] using [tool/library]
- [Specific subtopic] using [tool/library]

RULES:
- Each subtopic MUST include specific tool/library name
- Each subtopic MUST be searchable on YouTube
- Max 4-6 subtopics per week
- NO generic titles like "Basics" or "Core Concepts"
- NO explanations, ONLY the week structure"""

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "You are a Python curriculum designer. Create specific, actionable learning plans with concrete tools and technologies."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 4000,
            "temperature": 0.4,
        }
        
        async with aiohttp.ClientSession() as http:
            async with http.post(
                GROQ_API_URL, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                print(f"[Groq Plan] Response status: {resp.status}")
                if resp.status == 200:
                    result = await resp.json()
                    content = result["choices"][0]["message"]["content"].strip()
                    print(f"[Groq Plan] Generated plan length: {len(content)}")
                    
                    # Validate
                    if _validate_plan_content(content, weeks):
                        print(f"[Groq Plan] Plan validation passed")
                        return content
                    else:
                        print(f"[Groq Plan] Plan validation failed, returning best effort")
                        return content
                else:
                    error_text = await resp.text()
                    print(f"[Groq Plan] API error: {resp.status} - {error_text[:200]}")
    except Exception as e:
        print(f"[Groq Plan] Exception: {e}")
        import traceback
        traceback.print_exc()
    
    return ""


async def groq_general_chat(message: str, history: list, use_code_prompt: bool = False) -> str:
    """Call Groq for general Python chat responses."""
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return "Hey there! I'm BigDream, your Python learning companion. I'm having a bit of trouble connecting right now, but I'm here to listen. How are you feeling today?"

    system = CODE_SYSTEM_PROMPT if use_code_prompt else SYSTEM_PROMPT
    messages = [{"role": "system", "content": system}]
    for entry in history[-8:]:
        if entry.startswith("User: "):
            messages.append({"role": "user", "content": entry[6:]})
        elif entry.startswith("Bot: "):
            messages.append({"role": "assistant", "content": entry[5:]})
    messages.append({"role": "user", "content": message})

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": GROQ_MODEL,
            "messages": messages,
            "max_tokens": 8192 if use_code_prompt else 4096,
            "temperature": 0.4 if use_code_prompt else 0.7,
        }
        async with aiohttp.ClientSession() as http:
            async with http.post(
                GROQ_API_URL, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result["choices"][0]["message"]["content"].strip()
    except Exception:
        pass

    # Minimal fallback - direct professional responses
    message_lower = message.lower()
    
    if any(word in message_lower for word in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]):
        return "Hey there! How can I help you with Python today?"
    elif any(word in message_lower for word in ["python", "code", "programming", "debug", "error", "function", "class", "learn", "project"]):
        return "I'd love to help with your Python journey! What are you working on or hoping to learn?"
    else:
        # Default response for non-Python topics
        return "I'm BigDream, your Python learning companion. I'm designed to help with Python programming - learning, debugging, projects, and more. What would you like to work on?"


def parse_timeline_to_weeks(timeline_text: str) -> int:
    """Parse timeline text and convert to number of weeks. Max is 8 weeks."""
    timeline_lower = timeline_text.lower().strip()

    numbers = re.findall(r'\d+', timeline_lower)
    if not numbers:
        return 8

    num = int(numbers[0])

    if 'week' in timeline_lower:
        weeks = num
    elif 'month' in timeline_lower:
        weeks = num * 4
    elif 'day' in timeline_lower:
        weeks = max(1, num // 7)
    elif 'year' in timeline_lower:
        weeks = num * 52
    else:
        weeks = num

    return min(weeks, 8)


def create_clean_goal_title(raw_goal: str, answers: Dict) -> str:
    """
    Create a clean, professional goal title from raw user input.

    Examples:
    - "i need to learn python" → "Learn Python"
    - "i need to get fit" → "Get Fit"
    - "want to speak spanish" → "Learn Spanish"
    """
    main_goal = raw_goal.split('|')[0].strip()

    prefixes_to_remove = [
        r'^i\s+want\s+to\s+',
        r'^i\s+need\s+to\s+',
        r'^i\s+wish\s+to\s+',
        r'^i\s+would\s+like\s+to\s+',
        r'^help\s+me\s+to\s+',
        r'^help\s+me\s+',
        r'^i\s+wanna\s+',
    ]

    for prefix in prefixes_to_remove:
        main_goal = re.sub(prefix, '', main_goal, flags=re.IGNORECASE)

    main_goal = main_goal.strip().capitalize()

    typo_corrections = {
        'sttracting': 'attracting',
        'progaming': 'programming',
        'javasript': 'javascript',
        'phyton': 'python',
    }

    for typo, correction in typo_corrections.items():
        main_goal = re.sub(r'\b' + typo + r'\b', correction, main_goal, flags=re.IGNORECASE)

    timeline = answers.get(1, "")
    if timeline:
        weeks = parse_timeline_to_weeks(timeline)
        main_goal = f"{main_goal} in {weeks} Week{'s' if weeks > 1 else ''}"

    return main_goal


def detect_goal_type(goal_description: str) -> str:
    """
    Detect the CS sub-type of a programming goal.

    Returns a CS-specific type string.
    All non-CS goals are mapped to 'coding' as the default
    (domain restriction is enforced separately by is_python_goal).
    """
    goal_lower = goal_description.lower()

    if any(k in goal_lower for k in ['machine learning', 'deep learning', 'tensorflow', 'pytorch', 'neural', 'ai ', ' ai', 'data science', 'nlp']):
        return 'coding'
    if any(k in goal_lower for k in ['python', 'flask', 'django', 'pandas', 'numpy']):
        return 'coding'
    if any(k in goal_lower for k in ['javascript', 'typescript', 'react', 'vue', 'angular', 'node', 'next']):
        return 'coding'
    if any(k in goal_lower for k in ['java', 'kotlin', 'spring', 'android']):
        return 'coding'
    if any(k in goal_lower for k in ['c++', 'c#', 'rust', 'go ', ' go', 'swift']):
        return 'coding'
    if any(k in goal_lower for k in ['sql', 'database', 'postgres', 'mongo', 'redis']):
        return 'coding'
    if any(k in goal_lower for k in ['docker', 'kubernetes', 'devops', 'cloud', 'aws', 'azure']):
        return 'coding'
    if any(k in goal_lower for k in ['security', 'cyber', 'cryptograph', 'hacking', 'penetration']):
        return 'coding'
    if any(k in goal_lower for k in ['algorithm', 'data structure', 'leetcode', 'competitive']):
        return 'coding'
    if any(k in goal_lower for k in ['code', 'programming', 'software', 'developer', 'web', 'app', 'computer science']):
        return 'coding'

    return 'coding'


def is_python_goal(goal_description: str) -> bool:
    """Validate that a goal is Python-related."""
    python_keywords = [
        'python', 'django', 'flask', 'fastapi', 'pandas', 'numpy',
        'pytorch', 'tensorflow', 'scikit', 'matplotlib', 'jupyter',
        'pip', 'virtualenv', 'pytest', 'asyncio', 'pydantic', 'sqlalchemy',
        'data science', 'machine learning', 'deep learning', 'automation', 'scripting',
        'web scraping', 'api', 'backend', 'algorithm', 'data structure',
        'programming', 'coding', 'code', 'software', 'developer', 'programmer',
        'script', 'module', 'package', 'library', 'framework',
        'oop', 'class', 'function', 'decorator', 'generator', 'lambda',
        'debugging', 'testing', 'deployment', 'data analysis', 'celery',
        'neural network', 'nlp', 'computer vision', 'ai', 'artificial intelligence',
        'keras', 'opencv', 'seaborn', 'plotly', 'bokeh', 'streamlit', 'gradio',
        'huggingface', 'transformers', 'llm', 'langchain', 'vector database',
    ]
    desc_lower = goal_description.lower()
    return any(kw in desc_lower for kw in python_keywords)


class GoalChatInterface:
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.goals = {}
        self.db_manager = None
        self.shared_data = None
        self.processing_callback = None

    def set_db_manager(self, db_manager):
        self.db_manager = db_manager
        return self

    def set_shared_data(self, shared_data):
        self.shared_data = shared_data
        return self

    def set_processing_callback(self, callback):
        self.processing_callback = callback
        return self

    def _session_key(self, user_id: str, goal_id: Optional[str] = None) -> str:
        if goal_id:
            return f"{user_id}:{goal_id}"
        return user_id

    def _get_session(self, user_id: str, goal_id: Optional[str] = None) -> Dict:
        key = self._session_key(user_id, goal_id)
        if key not in self.sessions:
            # Load chat history from disk if available
            history = []
            if self.db_manager:
                saved_messages = self.db_manager.get_chat_history(user_id, goal_id)
                # Convert saved messages back to history format
                for msg in saved_messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "user":
                        history.append(f"User: {content}")
                    else:
                        history.append(f"Bot: {content}")
            
            self.sessions[key] = {
                "history": history,
                "goal_detected": False,
                "clarifying_questions": [],
                "question_index": 0,
                "goal_context": {},
                "awaiting_goal_confirm": False,
                "current_goal": None,
                "strike_count": 0,
            }
        return self.sessions[key]

    def _save_session_chat(self, user_id: str, goal_id: Optional[str] = None):
        """Save chat history to disk."""
        if not self.db_manager:
            return
        
        key = self._session_key(user_id, goal_id)
        if key not in self.sessions:
            return
        
        session = self.sessions[key]
        messages = []
        
        for entry in session.get("history", []):
            if entry.startswith("User: "):
                messages.append({"role": "user", "content": entry[6:]})
            elif entry.startswith("Bot: "):
                messages.append({"role": "assistant", "content": entry[5:]})
        
        self.db_manager.save_chat_history(user_id, goal_id, messages)

    def _delete_session(self, user_id: str, goal_id: Optional[str] = None):
        key = self._session_key(user_id, goal_id)
        self.sessions.pop(key, None)

    async def send_message(self, message: str, user_id: str = "default", goal_id: Optional[str] = None) -> Dict:
        """Process user message and return structured response."""
        session = self._get_session(user_id, goal_id)
        message = message.strip()
        result = None

        # Hard content policy check (pure Python — no LLM call).
        # Emotional/personal messages are NOT blocked — the LLM handles them
        # with empathy. Only hate speech, NSFW, abuse, and dangerous content
        # are intercepted here.
        violation = _policy_violation(message)
        if violation:
            strikes = session.get("strike_count", 0)
            reply = _get_policy_reply(violation, strikes)
            session["strike_count"] = strikes + 1
            session["history"].append(f"Bot: {reply}")
            result = {
                "chat_response": reply,
                "new_goal": None,
                "goal_detected": False,
                "action_required": "policy_violation",
                "violation_type": violation,
            }
        else:
            session["history"].append(f"User: {message}")

            # Route code questions to HF code model.
            # Also detect follow-up messages when the conversation already involved code.
            if not session["awaiting_goal_confirm"] and (
                _is_code_question(message) or _is_code_followup(message, session)
            ):
                code_response = await hf_code_chat(message, session["history"])
                session["history"].append(f"Bot: {code_response}")
                result = {
                    "chat_response": code_response,
                    "new_goal": None,
                    "goal_detected": False,
                    "action_required": "code_response",
                    "model_used": "hf_code_model",
                }
            else:
                response_text = await groq_general_chat(message, session["history"])

                if session["awaiting_goal_confirm"]:
                    result = await self._handle_goal_mode(message, user_id, session, response_text)
                elif self._detect_goal_signal(message) and not session["goal_detected"]:
                    if not is_python_goal(message):
                        result = {
                            "chat_response": (
                                "BigDream is a Python learning assistant. "
                                "I can help you learn Python, build Python projects, "
                                "understand Python concepts, or work with Python libraries. "
                                "What Python goal would you like to work on?"
                            ),
                            "new_goal": None,
                            "goal_detected": False,
                            "action_required": "domain_restriction"
                        }
                    else:
                        session["goal_detected"] = True
                        session["goal_context"] = {
                            "initial_goal": message,
                            "answers": {},
                            "step": 0
                        }
                        session["awaiting_goal_confirm"] = True
                        session["current_goal"] = message

                        questions = self._get_goal_questions()
                        session["clarifying_questions"] = questions

                        result = {
                            "chat_response": f"I'd love to help you with that!\n\n{questions[0]}",
                            "new_goal": None,
                            "goal_detected": True,
                            "action_required": "clarification"
                        }
                else:
                    session["history"].append(f"Bot: {response_text}")
                    result = {
                        "chat_response": response_text,
                        "new_goal": None,
                        "goal_detected": False,
                        "action_required": None
                    }
        
        # Save chat history to disk after each message
        self._save_session_chat(user_id, goal_id)
        
        return result
    def _is_python_topic(self, message: str) -> bool:
        """Check if the message is a direct Python topic request."""
        low = message.lower().strip()
        python_keywords = [
            "python", "flask", "django", "fastapi", "pandas", "numpy", 
            "matplotlib", "seaborn", "scikit", "sklearn", "tensorflow", 
            "pytorch", "keras", "machine learning", "data science", 
            "web scraping", "automation", "scripting", "api", "database",
            "sql", "sqlite", "postgresql", "mongodb", "docker", "git",
            "algorithm", "data structure", "oop", "object oriented",
            "testing", "pytest", "unittest", "jupyter", "notebook",
            "opencv", "pillow", "requests", "beautifulsoup", "selenium",
            "pygame", "tkinter", "streamlit", "dash", "plotly", "bokeh"
        ]
        return any(kw in low for kw in python_keywords)

    def _detect_mode_from_topic(self, message: str) -> str:
        """Infer mode from topic keywords."""
        low = message.lower()
        practical_keywords = ["build", "project", "app", "application", "website", 
                              "create", "make", "develop", "deploy", "flask", "django", 
                              "fastapi", "web", "api", "script", "automation"]
        theoretical_keywords = ["exam", "certification", "theory", "concept", 
                                "algorithm", "data structure", "understand", "learn",
                                "analysis", "mathematics", "statistics", "compare"]
        
        practical_score = sum(1 for kw in practical_keywords if kw in low)
        theoretical_score = sum(1 for kw in theoretical_keywords if kw in low)
        
        if theoretical_score > practical_score:
            return "theoretical"
        return "practical"

    def _validate_clarifying_answer(self, step: int, message: str):
        low = message.lower().strip()
        if len(low) < 1:
            return False, "Please provide an answer."
        if step == 0:
            # Step 0: Mode selection OR direct Python topic
            valid_modes = ["1", "2", "theoretical", "practical", "theory", "practice"]
            if low in valid_modes:
                return True, "mode_selected"
            # Accept direct Python topic
            if self._is_python_topic(message):
                return True, "topic_provided"
            return False, "Please select: **1** (Theoretical) or **2** (Practical)"
        elif step == 1:
            # Timeline - needs a number and time unit
            has_number = any(c.isdigit() for c in message)
            has_unit = any(u in low for u in ["week", "month", "day", "year"])
            if not (has_number and has_unit):
                return False, "Please give a timeframe like **4 weeks** or **2 months** (max 2 months)."
            weeks = parse_timeline_to_weeks(message)
            if weeks >= 8:
                return True, "capped"
        return True, ""

    async def _handle_goal_mode(self, message: str, user_id: str, session: Dict, base_response: str) -> Dict:
        goal_context = session["goal_context"]
        questions = session["clarifying_questions"]
        step = goal_context.get("step", 0)
        result = None

        if step < len(questions):
            if self._is_stop(message):
                self._reset_session(session)
                result = {
                    "chat_response": "No problem! Let's start over when you're ready.",
                    "new_goal": None,
                    "goal_detected": False,
                    "action_required": "cancelled"
                }
            elif self._looks_like_correction(message):
                correction_step = self._detect_correction_step(message)
                if correction_step is not None and correction_step < step:
                    goal_context["step"] = correction_step
                    reply = f"Sure! Let's fix that.\n\n{questions[correction_step]}"
                    session["history"].append(f"Bot: {reply}")
                    result = {
                        "chat_response": reply,
                        "new_goal": None,
                        "goal_detected": True,
                        "action_required": "clarification"
                    }
                else:
                    # No specific step detected — step back one if possible
                    goal_context["step"] = max(0, step - 1)
                    reply = f"No problem, let's go back.\n\n{questions[max(0, step - 1)]}"
                    session["history"].append(f"Bot: {reply}")
                    result = {
                        "chat_response": reply,
                        "new_goal": None,
                        "goal_detected": True,
                        "action_required": "clarification"
                    }
            else:
                valid, hint = self._validate_clarifying_answer(step, message)
                if not valid:
                    reply = f"{hint}\n\n{questions[step]}"
                    session["history"].append(f"Bot: {reply}")
                    result = {
                        "chat_response": reply,
                        "new_goal": None,
                        "goal_detected": True,
                        "action_required": "clarification"
                    }
                else:
                    # Handle topic-provided case (user gave a Python topic instead of mode)
                    if hint == "topic_provided" and step == 0:
                        # Update the goal with the new topic
                        goal_context["initial_goal"] = message
                        # Auto-detect mode from topic
                        detected_mode = self._detect_mode_from_topic(message)
                        goal_context["answers"][step] = detected_mode
                        goal_context["step"] = step + 1
                        
                        reply = f"Great! I understood you want to learn about **{message}**. I'll create a **{detected_mode}** plan for that.\n\n{questions[goal_context['step']] if goal_context['step'] < len(questions) else ''}"
                        session["history"].append(f"Bot: {reply}")
                        result = {
                            "chat_response": reply,
                            "new_goal": None,
                            "goal_detected": True,
                            "action_required": "clarification"
                        }
                    elif hint == "capped":
                        goal_context["answers"][step] = message
                        goal_context["step"] = step + 1

                        if goal_context["step"] < len(questions):
                            next_question = questions[goal_context["step"]]
                            reply = f"Got it! Plan capped at 8 weeks (max).\n\n{next_question}"
                            session["history"].append(f"Bot: {reply}")
                            result = {
                                "chat_response": reply,
                                "new_goal": None,
                                "goal_detected": True,
                                "action_required": "clarification"
                            }
                        else:
                            clean_title = create_clean_goal_title(
                                goal_context.get("initial_goal", ""),
                                goal_context.get("answers", {})
                            )
                            goal_context["clean_title"] = clean_title
                            reply = f"Got it! Plan capped at 8 weeks (max).\n\nPerfect! Here's what I understand:\n\n**{clean_title}**\n\nIs this correct? (yes/no)"
                            session["history"].append(f"Bot: {reply}")
                            result = {
                                "chat_response": reply,
                                "new_goal": None,
                                "goal_detected": True,
                                "action_required": "confirmation"
                            }
                    else:
                        # Standard mode selection
                        goal_context["answers"][step] = message
                        goal_context["step"] = step + 1

                        if goal_context["step"] < len(questions):
                            next_question = questions[goal_context["step"]]
                            reply = f"Got it!\n\n{next_question}"
                            session["history"].append(f"Bot: {reply}")
                            result = {
                                "chat_response": reply,
                                "new_goal": None,
                                "goal_detected": True,
                                "action_required": "clarification"
                            }
                        else:
                            clean_title = create_clean_goal_title(
                                goal_context.get("initial_goal", ""),
                                goal_context.get("answers", {})
                            )
                            goal_context["clean_title"] = clean_title
                            goal_context["summary"] = clean_title

                            reply = f"Perfect! Here's what I understand:\n\n**{clean_title}**\n\nIs this correct? (yes/no)"
                            session["history"].append(f"Bot: {reply}")
                            result = {
                                "chat_response": reply,
                                "new_goal": None,
                                "goal_detected": True,
                                "action_required": "confirmation"
                            }

        elif self._is_yes(message):
            clean_title = goal_context.get("clean_title", goal_context.get("initial_goal", "Goal"))
            try:
                new_goal = await self._create_goal(clean_title, user_id, goal_context)
                if not new_goal:
                    reply = "Sorry, there was an error creating your goal. Please try again."
                    session["history"].append(f"Bot: {reply}")
                    result = {
                        "chat_response": reply,
                        "new_goal": None,
                        "goal_detected": False,
                        "action_required": None,
                    }
                else:
                    self._reset_session(session)
                    reply = "Goal locked in! Creating your learning plan now..."
                    session["history"].append(f"Bot: {reply}")
                    result = {
                        "chat_response": reply,
                        "new_goal": new_goal,
                        "goal_detected": True,
                        "action_required": "goal_created",
                    }
            except Exception as e:
                import traceback
                traceback.print_exc()
                reply = f"Sorry, there was an error: {str(e)}"
                session["history"].append(f"Bot: {reply}")
                result = {
                    "chat_response": reply,
                    "new_goal": None,
                    "goal_detected": False,
                    "action_required": None,
                }

        elif self._is_stop(message):
            self._reset_session(session)
            reply = "No problem! Let's start over when you're ready."
            session["history"].append(f"Bot: {reply}")
            result = {
                "chat_response": reply,
                "new_goal": None,
                "goal_detected": False,
                "action_required": "cancelled"
            }

        elif self._looks_like_correction(message):
            step = self._detect_correction_step(message)
            if step is not None:
                goal_context["step"] = step
                reply = f"Sure! Let's fix that. {questions[step]}"
                session["history"].append(f"Bot: {reply}")
                result = {
                    "chat_response": reply,
                    "new_goal": None,
                    "goal_detected": True,
                    "action_required": "clarification"
                }
            else:
                reply = (
                    "Got it — you want to change something. Which part? "
                    "Reply with **why** or **timeline**."
                )
                session["history"].append(f"Bot: {reply}")
                result = {
                    "chat_response": reply,
                    "new_goal": None,
                    "goal_detected": True,
                    "action_required": "confirmation"
                }

        else:
            reply = (
                "I didn't quite catch that. Please reply **yes** to confirm, "
                "or tell me what you'd like to change (e.g., **why** or **timeline**). "
                "Say **stop** to cancel goal creation."
            )
            session["history"].append(f"Bot: {reply}")
            result = {
                "chat_response": reply,
                "new_goal": None,
                "goal_detected": True,
                "action_required": "confirmation"
            }
        
        return result

    def _get_goal_questions(self) -> List[str]:
        """Goal clarification questions with mode selection."""
        return [
            "Select a plan type:\n\n"
            "1 - Theoretical - For exams, certifications, understanding concepts\n\n"
            "2 - Practical - For building projects, hands-on coding\n\n"
            "Reply with 1 or 2",
            "**How many weeks** do you have? (e.g., 4 weeks, 2 months — max 2 months)",
        ]

    async def _create_goal(self, clean_title: str, user_id: str, goal_context: Dict) -> Dict:
        goal_id = str(uuid.uuid4())[:8]

        answers = goal_context.get("answers", {})
        initial_goal = goal_context.get("initial_goal", clean_title)

        # Answers: 0 = mode selection, 1 = timeline
        mode_answer = answers.get(0, "").lower().strip()
        timeline_text = answers.get(1, "8 weeks")
        total_weeks = parse_timeline_to_weeks(timeline_text)
        
        # Map mode selection to goal_type (only 2 modes now)
        mode_mapping = {
            "1": "theoretical",
            "2": "practical",
            "theoretical": "theoretical",
            "practical": "practical",
            "theory": "theoretical",
            "practice": "practical",
        }
        goal_type = mode_mapping.get(mode_answer, "practical")
        
        # Set why_important based on mode for the prompt context
        why_important_map = {
            "theoretical": "To understand theory and prepare for exams",
            "practical": "To build real Python projects and applications",
        }
        why_important = why_important_map.get(goal_type, "")

        deadline_date = datetime.now() + timedelta(weeks=total_weeks)
        
        # Plan generation is handled asynchronously by the background workers.
        # Do NOT generate the plan here — it would block the HTTP response for minutes.
        generated_plan_text = ""
        weekly_breakdown = []

        goal = {
            "id": goal_id,
            "title": clean_title,
            "description": clean_title,
            "user_id": user_id,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "deadline": deadline_date.strftime("%Y-%m-%d"),
            "status": "pending",
            "progress": 0.0,
            "skill_level": "",
            "why_important": why_important,
            "timeline": timeline_text,
            "hours_per_week": "",
            "success_metric": why_important,
            "total_weeks": total_weeks,
            "videos_per_week": 2,
            "articles_per_week": 2,
            "goal_type": goal_type,
            "generated_plan": generated_plan_text,  # Store the raw generated plan
            "weekly_breakdown": weekly_breakdown  # Store parsed structure
        }

        if self.db_manager:
            self.db_manager.save_goal(goal)

        if self.shared_data:
            from backend.app.shared_data import GoalData
            goal_obj = GoalData(
                id=goal_id,
                description=clean_title,
                user_id=user_id,
                created_at=goal["created_at"],
                deadline=goal["deadline"],
                status="pending"
            )
            goal_obj.total_weeks = total_weeks
            goal_obj.timeline = timeline_text
            goal_obj.why_important = goal["why_important"]
            goal_obj.skill_level = goal["skill_level"]
            goal_obj.hours_per_week = ""
            goal_obj.success_metric = goal["success_metric"]
            goal_obj.goal_type = goal_type
            goal_obj.weekly_breakdown = weekly_breakdown  # Store HF-generated plan
            
            print(f"[GoalChat] Created goal {goal_id} with {len(weekly_breakdown)} weeks in weekly_breakdown")
            if weekly_breakdown:
                print(f"[GoalChat] Week 1 theme: {weekly_breakdown[0].get('theme', 'N/A')}")
                print(f"[GoalChat] Week 1 subtopics: {weekly_breakdown[0].get('subtopics', [])}")

            self.shared_data.add_task(goal_obj)
            logger.info(f"Goal {goal_id} added to shared_data for processing")

        if self.processing_callback:
            self.processing_callback(goal)

        return goal

    def _reset_session(self, session: Dict):
        session["goal_detected"] = False
        session["clarifying_questions"] = []
        session["question_index"] = 0
        session["goal_context"] = {}
        session["awaiting_goal_confirm"] = False
        session["current_goal"] = None

    def _parse_generated_plan(self, plan_text: str, total_weeks: int) -> List[Dict]:
        """Parse the generated plan text into structured weekly breakdown."""
        weekly_breakdown = []
        if not plan_text:
            return weekly_breakdown
        
        try:
            lines = plan_text.strip().split('\n')
            current_week = None
            current_theme = ""
            current_subtopics = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Skip separator lines like "---" and phase headers
                if line.replace('-', '').replace('=', '').replace('*', '') == '':
                    continue
                
                # Skip markdown headers and phase descriptions
                if line.startswith('#') or line.startswith('**Phase'):
                    continue
                
                # Remove markdown bold formatting: **text** → text
                clean_line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
                
                # Check if this is a week line - support multiple formats:
                # "Week 1: Title", "Week 1 — Title", "Week 1 - Title", "Week 1 – Title"
                # Also: "- Week 1 — Title" with bullet
                week_match = re.match(r'(?:[-•*]\s+)?Week\s+(\d+)[:\-–—\s]+(.+)', clean_line, re.IGNORECASE)
                if week_match:
                    # Save previous week if exists
                    if current_week and (current_subtopics or current_theme):
                        weekly_breakdown.append({
                            "week": current_week,
                            "theme": current_theme,
                            "subtopics": current_subtopics if current_subtopics else [current_theme],
                            "video_query": f"python {current_theme}",
                            "article_query": f"python {current_theme} tutorial",
                            "videos_needed": 2,
                            "articles_needed": 2
                        })
                    # Start new week
                    current_week = int(week_match.group(1))
                    current_theme = week_match.group(2).strip()
                    current_subtopics = []
                elif clean_line.startswith('-') or clean_line.startswith('•') or clean_line.startswith('*'):
                    # This is a subtopic with bullet
                    subtopic = clean_line[1:].strip()
                    # Remove any leading dash or bullet artifacts
                    subtopic = re.sub(r'^[-•*]\s*', '', subtopic)
                    if subtopic and len(subtopic) > 3:
                        current_subtopics.append(subtopic)
                elif current_week and clean_line and not clean_line.lower().startswith('week') and not clean_line.startswith('**'):
                    # This might be a subtopic without bullet
                    if len(clean_line) > 3:
                        current_subtopics.append(clean_line)
            
            # Don't forget the last week
            if current_week and (current_subtopics or current_theme):
                weekly_breakdown.append({
                    "week": current_week,
                    "theme": current_theme,
                    "subtopics": current_subtopics if current_subtopics else [current_theme],
                    "video_query": f"python {current_theme}",
                    "article_query": f"python {current_theme} tutorial",
                    "videos_needed": 2,
                    "articles_needed": 2
                })
        except Exception as e:
            logger.error(f"Failed to parse generated plan: {e}")
        
        return weekly_breakdown

    def _detect_goal_signal(self, message: str) -> bool:
        keywords = [
            "i want to", "i need to", "i'd like to", "i wish to",
            "learn", "study", "master", "improve", "build", "create",
            "goal", "achieve", "accomplish", "work on", "help me"
        ]
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in keywords)

    def _is_yes(self, message: str) -> bool:
        return message.lower().strip() in [
            "yes", "yeah", "yep", "y", "ok", "okay", "sure",
            "correct", "right", "accurate", "true"
        ]

    def _is_stop(self, message: str) -> bool:
        stop_phrases = [
            "stop", "cancel", "drop", "quit", "abort", "give up",
            "never mind", "nevermind", "forget it", "leave it",
            "i drop the goal", "drop the goal", "end this", "exit"
        ]
        low = message.lower().strip()
        return any(phrase in low for phrase in stop_phrases)

    def _looks_like_correction(self, message: str) -> bool:
        correction_signals = [
            "change", "edit", "modify", "wrong", "incorrect",
            "fix", "update", "not right", "mistake", "typo",
            "meant", "actually", "no", "nope", "nah", "not correct"
        ]
        low = message.lower()
        return any(sig in low for sig in correction_signals)

    def _detect_correction_step(self, message: str) -> Optional[int]:
        low = message.lower()
        if any(k in low for k in ["mode", "type", "fundamentals", "project", "exam", "specialization", "learning style"]):
            return 0
        if any(k in low for k in ["week", "month", "timeline", "timeframe", "duration", "how long", "time"]):
            return 1
        return None

    def get_goals(self, user_id: str = "default") -> List[Dict]:
        if self.db_manager:
            return self.db_manager.get_user_goals(user_id)
        else:
            return self.goals.get(user_id, [])
