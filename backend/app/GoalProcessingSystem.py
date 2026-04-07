import asyncio
import logging
import os
import sys
from typing import Dict, List
import time

logger = logging.getLogger(__name__)

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from backend.app.goal_chatbot import GoalChatInterface, generate_learning_plan_with_hf
from backend.app.plan_generator import PlanGenerator
from backend.app.youtube_searcher import YouTubeSearcher
from backend.app.article_searcher import ArticleSearcher
from backend.app.shared_data import SharedData
from backend.database_manager import DatabaseManager


class SmartCache:
    """Time-bounded in-memory cache."""

    def __init__(self, max_age_seconds: int = 1800):
        self.cache = {}
        self.max_age = max_age_seconds

    def get(self, key: str):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.max_age:
                return value
            del self.cache[key]
        return None

    def set(self, key: str, value):
        self.cache[key] = (value, time.time())

    def clear(self):
        self.cache.clear()


class GoalProcessingSystem:

    def __init__(self, data_dir: str = None):
        self.running = False
        self.worker_tasks = []

        self.cache = SmartCache(max_age_seconds=1800)
        if data_dir is None:
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(backend_dir, "data")
        self.db_manager = DatabaseManager(data_dir=data_dir)
        self.shared_data = SharedData()

        self.chatbot = GoalChatInterface()
        self.plan_generator = PlanGenerator(self.shared_data)
        self.youtube_searcher = YouTubeSearcher()
        self.article_searcher = ArticleSearcher()

        self.chatbot.set_db_manager(self.db_manager)
        self.chatbot.set_shared_data(self.shared_data)
        self.chatbot.set_processing_callback(self._on_goal_created)
        self.plan_generator.set_db_manager(self.db_manager)

    async def start(self):
        self.running = True
        self.worker_tasks = [
            asyncio.create_task(self._plan_worker()),
            asyncio.create_task(self._video_worker()),
            asyncio.create_task(self._article_worker()),
            asyncio.create_task(self._assembly_worker()),
        ]

    async def stop(self):
        self.running = False
        for task in self.worker_tasks:
            task.cancel()
        await asyncio.gather(*self.worker_tasks, return_exceptions=True)

    async def _plan_worker(self):
        """Generate week structure (titles + subtopics only)."""
        await asyncio.sleep(0.5)
        logger.info("Plan worker started")

        while self.running:
            try:
                pending_goals = []
                with self.shared_data.lock:
                    for task_id, task in self.shared_data.tasks.items():
                        status_val = task.status.value if hasattr(task.status, 'value') else str(task.status)
                        has_plan = "plan" in task.results
                        if status_val == "pending" and not has_plan:
                            pending_goals.append((task_id, task))

                if pending_goals:
                    print(f"[GPS] Processing {len(pending_goals)} pending goal(s)")
                    tasks = [self._generate_plan_for_task(tid, t) for tid, t in pending_goals]
                    await asyncio.gather(*tasks, return_exceptions=True)

                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Plan worker error: {e}")
                await asyncio.sleep(1)

    async def _generate_plan_for_task(self, task_id: str, task):
        try:
            print(f"[GPS] Generating plan for {task_id}: {task.goal.description[:50]}...")
            self.shared_data.mark_task_processing(task_id)

            plan = await self.plan_generator.generate_plan(task.goal)
            week_count = len(plan.get('weekly_breakdown', []))

            # If Together AI returned an empty plan, fall back to HF
            if not week_count:
                print(f"[GPS] Together AI returned empty plan, trying HF fallback for {task_id}")
                goal = task.goal
                why_map = {
                    "theoretical": "To understand theory and prepare for exams",
                    "practical": "To build real Python projects and applications",
                }
                why = why_map.get(getattr(goal, "goal_type", ""), "")
                hf_text = await generate_learning_plan_with_hf(
                    goal=goal.description,
                    weeks=goal.total_weeks,
                    why_important=why,
                    goal_type=getattr(goal, "goal_type", "practical"),
                )
                if hf_text:
                    weekly_breakdown = self.chatbot._parse_generated_plan(hf_text, goal.total_weeks)
                    if weekly_breakdown:
                        goal.weekly_breakdown = weekly_breakdown
                        plan = await self.plan_generator.generate_plan(goal)
                        week_count = len(plan.get('weekly_breakdown', []))
                        print(f"[GPS] HF fallback produced {week_count} weeks for {task_id}")

            # Save plan to database FIRST before videos/articles start
            if self.db_manager:
                self.db_manager.save_learning_plan(task_id, plan)

            # Mark plan as saved so video/article workers can start
            self.shared_data.update_task(task_id, {"plan": plan, "_plan_saved": True})
            print(f"[GPS] Plan ready for {task_id}: {week_count} weeks")
        except Exception as e:
            print(f"[GPS] ERROR generating plan for {task_id}: {e}")
            logger.error("Plan generation failed for task %s: %s", task_id, e)
            # Reset to pending so the worker can retry
            with self.shared_data.lock:
                if task_id in self.shared_data.tasks:
                    from backend.app.shared_data import ProcessingStatus
                    self.shared_data.tasks[task_id].status = ProcessingStatus.PENDING

    async def _video_worker(self):
        """Fetch videos for all subtopics in parallel."""
        await asyncio.sleep(0.5)
        logger.info("Video worker started")

        while self.running:
            try:
                tasks_needing_videos = []
                with self.shared_data.lock:
                    for task_id, task in self.shared_data.tasks.items():
                        status_val = task.status.value if hasattr(task.status, 'value') else str(task.status)
                        has_plan_saved = "_plan_saved" in task.results
                        has_video_map = "_video_map" in task.results
                        
                        if (status_val in ["processing", "completed"] and
                                has_plan_saved and
                                not has_video_map):
                            tasks_needing_videos.append((task_id, task))

                for task_id, task in tasks_needing_videos:
                    print(f"[GPS] Fetching videos for {task_id}")
                    await self._find_videos_for_task(task_id, task)

                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Video worker error: {e}")
                await asyncio.sleep(1)

    async def _find_videos_for_task(self, task_id: str, task):
        """Fetch videos for all subtopics in parallel with concurrency limit."""
        try:
            plan = task.results.get("plan", {})
            weekly_breakdown = plan.get("weekly_breakdown", [])
            
            if not weekly_breakdown:
                # No weeks - create empty video map
                with self.shared_data.lock:
                    if task_id in self.shared_data.tasks:
                        self.shared_data.tasks[task_id].results["_video_map"] = {}
                print(f"[GPS] No weekly breakdown, created empty _video_map for {task_id}")
                return

            # Collect all subtopics
            all_subtopics = []
            for week in weekly_breakdown:
                for subtopic in week.get("subtopics", []):
                    title = subtopic.get("title", "")
                    if title:
                        all_subtopics.append(title)

            if not all_subtopics:
                # No subtopics - create empty video map
                with self.shared_data.lock:
                    if task_id in self.shared_data.tasks:
                        self.shared_data.tasks[task_id].results["_video_map"] = {}
                print(f"[GPS] No subtopics found, created empty _video_map for {task_id}")
                return

            print(f"[GPS] Fetching videos for {len(all_subtopics)} subtopics")

            # Fetch videos with concurrency limit (5 at a time)
            semaphore = asyncio.Semaphore(5)
            
            async def fetch_with_limit(subtopic_title):
                async with semaphore:
                    video = await self.youtube_searcher.find_single_video(subtopic_title)
                    return (subtopic_title, video)

            tasks = [fetch_with_limit(st) for st in all_subtopics]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Store in _video_map keyed by subtopic title
            video_map = {}
            for r in results:
                if isinstance(r, tuple):
                    subtopic_title, video = r
                    video_map[subtopic_title] = video

            with self.shared_data.lock:
                if task_id in self.shared_data.tasks:
                    self.shared_data.tasks[task_id].results["_video_map"] = video_map

            print(f"[GPS] Found {sum(1 for v in video_map.values() if v is not None)} videos")

        except Exception as e:
            logger.error("Video search failed for task %s: %s", task_id, e)

    async def _article_worker(self):
        """Fetch articles for all subtopics in parallel."""
        await asyncio.sleep(0.5)
        logger.info("Article worker started")

        while self.running:
            try:
                tasks_needing_articles = []
                with self.shared_data.lock:
                    for task_id, task in self.shared_data.tasks.items():
                        status_val = task.status.value if hasattr(task.status, 'value') else str(task.status)
                        has_plan_saved = "_plan_saved" in task.results
                        has_article_map = "_article_map" in task.results
                        
                        if (status_val in ["processing", "completed"] and
                                has_plan_saved and
                                not has_article_map):
                            tasks_needing_articles.append((task_id, task))

                for task_id, task in tasks_needing_articles:
                    print(f"[GPS] Fetching articles for {task_id}")
                    await self._find_articles_for_task(task_id, task)

                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Article worker error: {e}")
                await asyncio.sleep(1)

    async def _find_articles_for_task(self, task_id: str, task):
        """Fetch articles for all subtopics in parallel with concurrency limit."""
        try:
            plan = task.results.get("plan", {})
            weekly_breakdown = plan.get("weekly_breakdown", [])
            
            if not weekly_breakdown:
                # No weeks - create empty article map
                with self.shared_data.lock:
                    if task_id in self.shared_data.tasks:
                        self.shared_data.tasks[task_id].results["_article_map"] = {}
                print(f"[GPS] No weekly breakdown, created empty _article_map for {task_id}")
                return

            # Collect all subtopics
            all_subtopics = []
            for week in weekly_breakdown:
                for subtopic in week.get("subtopics", []):
                    title = subtopic.get("title", "")
                    if title:
                        all_subtopics.append(title)

            if not all_subtopics:
                # No subtopics - create empty article map
                with self.shared_data.lock:
                    if task_id in self.shared_data.tasks:
                        self.shared_data.tasks[task_id].results["_article_map"] = {}
                print(f"[GPS] No subtopics found, created empty _article_map for {task_id}")
                return

            # Get goal type for mode-specific article selection
            goal_type = getattr(task.goal, 'goal_type', '').lower()
            print(f"[GPS] Fetching articles for {len(all_subtopics)} subtopics (mode: {goal_type or 'auto'})")

            # Fetch articles with concurrency limit (5 at a time)
            semaphore = asyncio.Semaphore(5)
            
            async def fetch_with_limit(subtopic_title):
                async with semaphore:
                    article = await self.article_searcher.find_single_article(subtopic_title, goal_type=goal_type)
                    return (subtopic_title, article)

            tasks = [fetch_with_limit(st) for st in all_subtopics]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Store in _article_map keyed by subtopic title
            article_map = {}
            for r in results:
                if isinstance(r, tuple):
                    subtopic_title, article = r
                    article_map[subtopic_title] = article

            with self.shared_data.lock:
                if task_id in self.shared_data.tasks:
                    self.shared_data.tasks[task_id].results["_article_map"] = article_map

            print(f"[GPS] Found {sum(1 for a in article_map.values() if a is not None)} articles")

        except Exception as e:
            logger.error("Article search failed for task %s: %s", task_id, e)

    async def _assembly_worker(self):
        """Merge videos/articles with plan. Keep ALL subtopics."""
        await asyncio.sleep(1)
        logger.info("Assembly worker started")

        while self.running:
            try:
                tasks_ready_for_assembly = []
                with self.shared_data.lock:
                    for task_id, task in self.shared_data.tasks.items():
                        has_plan = "plan" in task.results
                        has_videos = "_video_map" in task.results
                        has_articles = "_article_map" in task.results
                        already_assembled = "_assembled" in task.results
                        
                        if has_plan and has_videos and has_articles and not already_assembled:
                            tasks_ready_for_assembly.append((task_id, task))

                for task_id, task in tasks_ready_for_assembly:
                    print(f"[GPS] Assembling final plan for {task_id}")
                    await self._assemble_task(task_id, task)

                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Assembly worker error: {e}")
                await asyncio.sleep(1)

    async def _assemble_task(self, task_id: str, task):
        """Merge plan with videos/articles. Keep ALL subtopics, attach resources (can be null)."""
        try:
            print(f"[GPS] Assembling final plan for task {task_id}")
            
            plan = task.results.get("plan", {})
            video_map = task.results.get("_video_map", {})
            article_map = task.results.get("_article_map", {})
            
            # Build final plan with resources attached to each subtopic
            final_weeks = []
            total_videos = 0
            total_articles = 0
            
            for week in plan.get("weekly_breakdown", []):
                subtopics_with_resources = []
                
                for subtopic in week.get("subtopics", []):
                    title = subtopic.get("title", "")
                    video = video_map.get(title)
                    article = article_map.get(title)
                    
                    if video:
                        total_videos += 1
                    if article:
                        total_articles += 1
                    
                    # Keep ALL subtopics - attach video/article (can be null)
                    subtopics_with_resources.append({
                        "title": title,
                        "video": video,
                        "article": article,
                    })
                
                final_weeks.append({
                    "week": week.get("week", 1),
                    "theme": week.get("theme", ""),
                    "subtopics": subtopics_with_resources,
                })
            
            # Update plan
            final_plan = {
                "goal": plan.get("goal", ""),
                "total_weeks": len(final_weeks),
                "weekly_breakdown": final_weeks,
            }
            
            # Extract resources for DB storage
            videos = [st["video"] for w in final_weeks for st in w["subtopics"] if st["video"]]
            articles = [st["article"] for w in final_weeks for st in w["subtopics"] if st["article"]]
            
            with self.shared_data.lock:
                if task_id in self.shared_data.tasks:
                    self.shared_data.tasks[task_id].results["plan"] = final_plan
                    self.shared_data.tasks[task_id].results["_assembled"] = True
            
            # Save to database
            if self.db_manager:
                self.db_manager.save_learning_plan(task_id, final_plan)
                if videos:
                    self.db_manager.save_youtube_videos_for_goal(task_id, videos)
                if articles:
                    self.db_manager.save_articles_for_goal(task_id, articles)
            
            print(f"[GPS] Final plan assembled: {len(final_weeks)} weeks, {total_videos} videos, {total_articles} articles")

        except Exception as e:
            logger.error("Assembly failed for task %s: %s", task_id, e)

    def _on_goal_created(self, goal: dict):
        """Called when a new goal is created. Add it to the processing queue."""
        try:
            goal_id = goal.get('id')
            if not goal_id:
                return
            
            # Check if task already exists
            with self.shared_data.lock:
                if goal_id in self.shared_data.tasks:
                    return
            
            # Create a new task for processing
            from backend.app.shared_data import ProcessingTask, ProcessingStatus, GoalData
            
            # Create GoalData object from the dict
            goal_data = GoalData(
                id=goal_id,
                description=goal.get('title', ''),
                user_id=goal.get('user_id', ''),
                created_at=goal.get('created_at', ''),
                deadline=goal.get('deadline', ''),
                status=goal.get('status', 'pending'),
                total_weeks=goal.get('total_weeks', 0),
                why_important=goal.get('why_important', ''),
                skill_level=goal.get('skill_level', ''),
                hours_per_week=goal.get('hours_per_week', ''),
                success_metric=goal.get('success_metric', ''),
                goal_type=goal.get('goal_type', ''),
                weekly_breakdown=goal.get('weekly_breakdown', [])
            )
            
            task = ProcessingTask(
                goal=goal_data,
                status=ProcessingStatus.PENDING
            )
            
            with self.shared_data.lock:
                self.shared_data.tasks[goal_id] = task
            
            print(f"[GPS] New goal queued: {goal_id}")
            
        except Exception as e:
            logger.error(f"Failed to queue goal: {e}")

    def get_user_goals(self, user_id: str) -> Dict:
        cache_key = f"user_goals_{user_id}"
        cached = self.cache.get(cache_key)

        if cached is not None:
            return cached

        goals = self.chatbot.get_goals(user_id)

        goals_dict = {}
        for goal in goals:
            goal_id = goal.get('id', '')
            videos = self.db_manager.get_videos_by_goal(goal_id)
            articles = self.db_manager.get_articles_by_goal(goal_id)
            goals_dict[goal_id] = {
                "goal": goal,
                "results": {
                    "plan": goal.get("plan", {}),
                    "videos_generated": bool(videos),
                    "articles_generated": bool(articles)
                },
                "status": goal.get("status", "pending")
            }

        self.cache.set(cache_key, goals_dict)
        return goals_dict
