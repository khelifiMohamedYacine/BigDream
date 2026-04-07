import json
import os
import aiohttp
from typing import Dict, List

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


async def _call_groq(prompt: str, max_tokens: int = 1200) -> str:
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return ""
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GROQ_API_URL,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return ""


async def generate_quiz_for_goal(
    goal: Dict, videos: List[Dict], articles: List[Dict]
) -> List[Dict]:
    """Generate a 10-question MCQ quiz based on the goal's plan and resources."""
    title = goal.get("title", "Python")
    total_weeks = goal.get("total_weeks", 8)
    plan = goal.get("plan", {})

    weekly = plan.get("weekly_breakdown", []) if isinstance(plan, dict) else []
    themes = []
    objectives = []
    for w in weekly[:total_weeks]:
        if w.get("theme"):
            themes.append(w["theme"])
        for obj in w.get("learning_objectives", []):
            objectives.append(obj)

    video_titles = [v.get("title", "") for v in videos if v.get("title")]
    article_titles = [a.get("title", "") for a in articles if a.get("title")]

    themes_text = "\n".join(f"- {t}" for t in themes) or "- General Python learning"
    objectives_text = "\n".join(f"- {o}" for o in objectives[:10]) or "- Understand core Python concepts"
    videos_text = "\n".join(f"- {t}" for t in video_titles[:8]) or "- Python tutorial videos"
    articles_text = "\n".join(f"- {t}" for t in article_titles[:8]) or "- Python reading articles"

    prompt = f"""You are a Python educator. Create a final validation quiz for this learning goal. The quiz MUST be based on the actual learning plan themes, learning objectives, and curated resources provided below.

Goal: "{title}"
Duration: {total_weeks} weeks

LEARNING PLAN THEMES:
{themes_text}

LEARNING OBJECTIVES:
{objectives_text}

CURATED VIDEOS:
{videos_text}

CURATED ARTICLES:
{articles_text}

INSTRUCTIONS:
- Generate exactly 10 multiple-choice questions.
- Questions must test understanding of the specific themes, objectives, videos, and articles above.
- Each question must have 4 options labeled A, B, C, D with exactly one correct answer.
- Make questions practical and conceptually grounded in the provided materials.

Return ONLY a valid JSON array. Each object must have:
- "question": string
- "options": object with keys "A", "B", "C", "D"
- "correct": one of "A", "B", "C", "D"

No markdown, no explanation.

JSON array:"""

    raw = await _call_groq(prompt, max_tokens=1200)
    try:
        if "[" in raw:
            questions = json.loads(raw[raw.find("["): raw.rfind("]") + 1])
            if isinstance(questions, list) and len(questions) == 10:
                valid = True
                for q in questions:
                    if not all(k in q for k in ("question", "options", "correct")):
                        valid = False
                        break
                    opts = q.get("options", {})
                    if not all(k in opts for k in ("A", "B", "C", "D")):
                        valid = False
                        break
                    if q["correct"] not in ("A", "B", "C", "D"):
                        valid = False
                        break
                if valid:
                    return questions
    except Exception:
        pass
    return []
