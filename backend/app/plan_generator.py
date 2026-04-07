import os
import re
from typing import Dict, List, Tuple
import aiohttp


class PlanGenerator:
    """
    Minimal plan generator using Together AI (Llama 3.3 70B).
    Generates week titles and subtopics only - no hardcoded templates.
    """

    def __init__(self, shared_data):
        self.shared_data = shared_data
        self.db_manager = None
        self.together_api_key = os.getenv("TOGETHER_API_KEY", "")
        self.together_url = "https://api.together.xyz/v1/chat/completions"
        self.model = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    def set_db_manager(self, db_manager):
        self.db_manager = db_manager

    async def _together_generate(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call Together AI API for plan generation."""
        if not self.together_api_key:
            return ""
        try:
            headers = {
                "Authorization": f"Bearer {self.together_api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.5,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.together_url, json=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data["choices"][0]["message"]["content"].strip()
        except Exception:
            pass
        return ""

    async def generate_plan(self, goal) -> Dict:
        """
        Generate a learning plan with week titles and subtopics.
        Uses Together AI only - no fallbacks.
        """
        weeks = getattr(goal, "total_weeks", None)
        topic = getattr(goal, "description", None)
        
        if not weeks or not topic:
            return {"error": "Missing required parameters", "weekly_breakdown": []}
        
        # Use existing weekly_breakdown from chatbot if available
        existing_breakdown = getattr(goal, "weekly_breakdown", None)
        if existing_breakdown and len(existing_breakdown) > 0:
            weekly_breakdown = []
            for week in existing_breakdown:
                subtopics = week.get("subtopics", [])
                subtopic_titles = []
                for st in subtopics:
                    if isinstance(st, str):
                        subtopic_titles.append(st)
                    elif isinstance(st, dict):
                        subtopic_titles.append(st.get("title", ""))
                
                weekly_breakdown.append({
                    "week": week.get("week", len(weekly_breakdown) + 1),
                    "theme": week.get("theme", ""),
                    "subtopics": [{"title": t} for t in subtopic_titles if t]
                })
            
            return {
                "goal": topic,
                "total_weeks": len(weekly_breakdown),
                "weekly_breakdown": weekly_breakdown,
            }
        
        # Generate with Together AI
        week_structure = await self._generate_week_structure(topic, weeks)
        
        if not week_structure:
            return {"error": "Failed to generate plan", "weekly_breakdown": []}
        
        weekly_breakdown = []
        for week_num, (theme, subtopics) in enumerate(week_structure, 1):
            weekly_breakdown.append({
                "week": week_num,
                "theme": theme,
                "subtopics": [{"title": st} for st in subtopics]
            })
        
        return {
            "goal": topic,
            "total_weeks": len(weekly_breakdown),
            "weekly_breakdown": weekly_breakdown,
        }

    async def _generate_week_structure(self, topic: str, weeks: int) -> List[Tuple[str, List[str]]]:
        """Generate week titles and subtopics using Together AI."""
        prompt = f"""Generate a structured {weeks}-week learning plan for {topic}.

Output format (exact):
Week 1: [Title]
Subtopic 1
Subtopic 2
Subtopic 3
Subtopic 4

Week 2: [Title]
Subtopic 1
Subtopic 2
...

Continue for all {weeks} weeks.

Requirements:
- Content must be fully tailored to {topic}
- No generic titles like "Basics" or "Fundamentals" - be specific
- Ensure logical progression from beginner to advanced
- No introductions, conclusions, or explanations
- No placeholders or template variables"""

        raw = await self._together_generate(prompt, max_tokens=2000)
        return self._parse_week_structure(raw, weeks)

    def _parse_week_structure(self, raw: str, expected_weeks: int) -> List[Tuple[str, List[str]]]:
        """Parse AI response into list of (theme, subtopics)."""
        result = []
        
        # Split by "Week X:" pattern
        week_blocks = re.split(r'Week\s+\d+:\s*', raw, flags=re.IGNORECASE)
        
        for block in week_blocks[1:]:  # Skip first empty split
            lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
            if not lines:
                continue
            
            # First line is the title
            theme = lines[0].strip()
            
            # Remaining lines are subtopics
            subtopics = []
            for line in lines[1:]:
                # Clean up bullet points if present
                clean = re.sub(r'^[\-\•\*\d\.\)\]]+\s*', '', line).strip()
                if clean and len(clean) > 3:
                    subtopics.append(clean)
            
            if theme and len(theme) > 3 and subtopics:
                result.append((theme, subtopics[:6]))
        
        return result[:expected_weeks]
