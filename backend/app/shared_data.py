# shared_data.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import threading
from enum import Enum


class ProcessingStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class GoalData:
    id: str
    description: str
    user_id: str
    created_at: str
    deadline: str
    status: str
    total_weeks: int = 0
    why_important: str = ""
    skill_level: str = ""
    hours_per_week: str = ""
    success_metric: str = ""
    goal_type: str = ""
    weekly_breakdown: List = None
    
    def __post_init__(self):
        if self.weekly_breakdown is None:
            self.weekly_breakdown = []


@dataclass
class ProcessingTask:
    goal: GoalData
    status: ProcessingStatus
    results: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


class SharedData:
    """Thread-safe shared data between workers"""

    def __init__(self):
        self.lock = threading.Lock()
        self.tasks: Dict[str, ProcessingTask] = {}  # goal_id -> task
        self.user_tasks: Dict[str, List[str]] = {}  # user_id -> [goal_ids]

    def add_task(self, goal: GoalData) -> str:
        """Add new goal for processing"""
        with self.lock:
            task = ProcessingTask(
                goal=goal,
                status=ProcessingStatus.PENDING
            )
            self.tasks[goal.id] = task

            if goal.user_id not in self.user_tasks:
                self.user_tasks[goal.user_id] = []
            self.user_tasks[goal.user_id].append(goal.id)

            return goal.id

    def get_task(self, goal_id: str) -> Optional[ProcessingTask]:
        """Get task by ID"""
        with self.lock:
            return self.tasks.get(goal_id)

    def update_task(self, goal_id: str, results: Dict):
        """Update task results and mark as completed"""
        with self.lock:
            if goal_id in self.tasks:
                self.tasks[goal_id].results.update(results)
                self.tasks[goal_id].status = ProcessingStatus.COMPLETED

    def get_user_results(self, user_id: str) -> Dict:
        """Get all results for a user"""
        with self.lock:
            results = {}
            if user_id in self.user_tasks:
                for goal_id in self.user_tasks[user_id]:
                    if goal_id in self.tasks:
                        task = self.tasks[goal_id]
                        results[goal_id] = {
                            "goal": task.goal,
                            "results": task.results,
                            "status": task.status.value
                        }
            return results

    def get_pending_tasks(self) -> List[ProcessingTask]:
        """Get all pending tasks for workers"""
        with self.lock:
            return [task for task in self.tasks.values()
                    if task.status == ProcessingStatus.PENDING]

    def get_completed_tasks(self) -> List[ProcessingTask]:
        """Get all completed tasks"""
        with self.lock:
            return [task for task in self.tasks.values()
                    if task.status == ProcessingStatus.COMPLETED]

    def get_tasks_needing_videos(self) -> List[ProcessingTask]:
        """Get completed tasks that don't have videos"""
        with self.lock:
            return [task for task in self.tasks.values()
                    if task.status == ProcessingStatus.COMPLETED
                    and "youtube_videos" not in task.results]

    def get_tasks_needing_articles(self) -> List[ProcessingTask]:
        """Get completed tasks that don't have articles"""
        with self.lock:
            return [task for task in self.tasks.values()
                    if task.status == ProcessingStatus.COMPLETED
                    and "articles" not in task.results]

    def mark_task_processing(self, goal_id: str):
        """Mark task as being processed"""
        with self.lock:
            if goal_id in self.tasks:
                self.tasks[goal_id].status = ProcessingStatus.PROCESSING