import json
import os
import uuid
import bcrypt
import jwt
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path


class DatabaseManager:

    def __init__(self, data_dir="data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        self.goals_file = self.data_dir / "goals.json"
        self.users_file = self.data_dir / "users.json"
        self.tokens_blacklist_file = self.data_dir / "tokens_blacklist.json"
        self.audit_log_file = self.data_dir / "audit_log.json"
        self.user_stats_file = self.data_dir / "user_stats.json"
        self.videos_file = self.data_dir / "videos.json"
        self.articles_file = self.data_dir / "articles.json"
        self.reset_tokens_file = self.data_dir / "reset_tokens.json"
        self.chat_file = self.data_dir / "chat_history.json"

        self._initialize_database_files()

    def _initialize_database_files(self):
        if not self.goals_file.exists():
            self._write_json(self.goals_file, [])

        if not self.users_file.exists():
            self._write_json(self.users_file, {})

        if not self.tokens_blacklist_file.exists():
            self._write_json(self.tokens_blacklist_file, [])

        if not self.audit_log_file.exists():
            self._write_json(self.audit_log_file, [])

        if not self.user_stats_file.exists():
            self._write_json(self.user_stats_file, {})

        if not self.videos_file.exists():
            self._write_json(self.videos_file, [])

        if not self.articles_file.exists():
            self._write_json(self.articles_file, [])

        if not self.reset_tokens_file.exists():
            self._write_json(self.reset_tokens_file, {})

        if not self.chat_file.exists():
            self._write_json(self.chat_file, {})

    # File names that store lists (everything else defaults to {})
    _LIST_FILES = {"goals.json", "videos.json", "articles.json"}

    def _read_json(self, filepath: Path):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return [] if filepath.name in self._LIST_FILES else {}

    def _write_json(self, filepath: Path, data):
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def hash_password(self, password: str) -> str:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def verify_password(self, password: str, hashed_password: str) -> bool:
        return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))

    def is_token_blacklisted(self, token: str) -> bool:
        blacklist = self._read_json(self.tokens_blacklist_file)
        return token in blacklist

    def blacklist_token(self, token: str):
        blacklist = self._read_json(self.tokens_blacklist_file)
        if token not in blacklist:
            blacklist.append(token)
            self._write_json(self.tokens_blacklist_file, blacklist)

    def create_user(self, name: str, email: str, password: str, role: str = "user") -> Dict:
        users = self._read_json(self.users_file)

        if any(user_record['email'].lower() == email.lower() for user_record in users.values()):
            raise ValueError("Email already registered")

        user_id = str(uuid.uuid4())
        handle = self._generate_handle(name)

        user = {
            "user_id": user_id,
            "name": name,
            "email": email.lower(),
            "password_hash": self.hash_password(password),
            "role": role,
            "handle": handle,
            "avatar_url": "",
            "bio": "",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "is_active": True,
            "last_login": None,

            "region": self._generate_region(),
            "activity_score": 0.0,
            "reputation": 1,
            "credits": 0,
            "account_tier": "BASIC",
            "profile_status": "ACTIVE",
            "tagline": "New user in the system...",

            "total_goals": 0,
            "completed_goals": 0,
            "total_videos_watched": 0,
            "total_articles_read": 0
        }

        users[user_id] = user
        self._write_json(self.users_file, users)

        self._initialize_user_stats(user_id)
        self._log_action(user_id, "user_created", {"email": email, "role": role})

        return self._sanitize_user(user)

    def authenticate_user(self, email: str, password: str) -> Optional[Dict]:
        users = self._read_json(self.users_file)

        user = None
        for user_record in users.values():
            if user_record['email'].lower() == email.lower():
                user = user_record
                break

        if not user:
            return None

        if not user.get('is_active', True):
            raise ValueError("Account is deactivated")

        if not self.verify_password(password, user['password_hash']):
            return None

        user['last_login'] = datetime.now().isoformat()
        users[user['user_id']] = user
        self._write_json(self.users_file, users)

        self._log_action(user['user_id'], "user_login", {"email": email})

        return self._sanitize_user(user)

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        users = self._read_json(self.users_file)
        user = users.get(user_id)
        return self._sanitize_user(user) if user else None

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        users = self._read_json(self.users_file)
        for user in users.values():
            if user['email'].lower() == email.lower():
                return self._sanitize_user(user)
        return None

    def update_user_profile(self, user_id: str, updates: Dict) -> Dict:
        users = self._read_json(self.users_file)

        if user_id not in users:
            raise ValueError("User not found")

        user = users[user_id]

        allowed_fields = ['name', 'bio', 'avatar_url', 'tagline', 'handle']

        for field in allowed_fields:
            if field in updates:
                user[field] = updates[field]

        user['updated_at'] = datetime.now().isoformat()
        users[user_id] = user
        self._write_json(self.users_file, users)

        self._log_action(user_id, "profile_updated", {"fields": list(updates.keys())})

        return self._sanitize_user(user)

    def change_password(self, user_id: str, old_password: str, new_password: str) -> bool:
        users = self._read_json(self.users_file)

        if user_id not in users:
            raise ValueError("User not found")

        user = users[user_id]

        if not self.verify_password(old_password, user['password_hash']):
            raise ValueError("Current password is incorrect")

        user['password_hash'] = self.hash_password(new_password)
        user['updated_at'] = datetime.now().isoformat()
        users[user_id] = user
        self._write_json(self.users_file, users)

        self._log_action(user_id, "password_changed", {})

        return True

    def create_reset_token(self, email: str) -> Optional[str]:
        users = self._read_json(self.users_file)

        user_id = None
        for uid, user in users.items():
            if user['email'].lower() == email.lower():
                user_id = uid
                break

        if not user_id:
            return None

        import random
        code = str(random.randint(100000, 999999))

        tokens = self._read_json(self.reset_tokens_file)
        tokens[code] = {
            "user_id": user_id,
            "email": email.lower(),
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(minutes=15)).isoformat()
        }
        self._write_json(self.reset_tokens_file, tokens)

        self._log_action(user_id, "password_reset_requested", {"email": email})

        return code

    def reset_password_with_token(self, code: str, new_password: str) -> bool:
        tokens = self._read_json(self.reset_tokens_file)

        if code not in tokens:
            return False

        token_data = tokens[code]

        expires_at = datetime.fromisoformat(token_data['expires_at'])
        if datetime.now() > expires_at:
            del tokens[code]
            self._write_json(self.reset_tokens_file, tokens)
            return False

        user_id = token_data['user_id']
        users = self._read_json(self.users_file)

        if user_id not in users:
            return False

        users[user_id]['password_hash'] = self.hash_password(new_password)
        users[user_id]['updated_at'] = datetime.now().isoformat()
        self._write_json(self.users_file, users)

        del tokens[code]
        self._write_json(self.reset_tokens_file, tokens)

        self._log_action(user_id, "password_reset_completed", {})

        return True

    def logout_user(self, token: str):
        self.blacklist_token(token)

    def get_all_users(self) -> List[Dict]:
        users = self._read_json(self.users_file)
        return [self._sanitize_user(user_record) for user_record in users.values()]

    def update_user_role(self, user_id: str, new_role: str) -> Dict:
        users = self._read_json(self.users_file)

        if user_id not in users:
            raise ValueError("User not found")

        user = users[user_id]
        old_role = user['role']
        user['role'] = new_role
        user['updated_at'] = datetime.now().isoformat()
        users[user_id] = user
        self._write_json(self.users_file, users)

        self._log_action(user_id, "role_changed", {"old_role": old_role, "new_role": new_role})

        return self._sanitize_user(user)

    def deactivate_user(self, user_id: str) -> Dict:
        users = self._read_json(self.users_file)

        if user_id not in users:
            raise ValueError("User not found")

        user = users[user_id]
        user['is_active'] = False
        user['updated_at'] = datetime.now().isoformat()
        users[user_id] = user
        self._write_json(self.users_file, users)

        self._log_action(user_id, "user_deactivated", {})

        return self._sanitize_user(user)

    def reactivate_user(self, user_id: str) -> Dict:
        users = self._read_json(self.users_file)

        if user_id not in users:
            raise ValueError("User not found")

        user = users[user_id]
        user['is_active'] = True
        user['updated_at'] = datetime.now().isoformat()
        users[user_id] = user
        self._write_json(self.users_file, users)

        self._log_action(user_id, "user_reactivated", {})

        return self._sanitize_user(user)

    def _initialize_user_stats(self, user_id: str):
        stats = self._read_json(self.user_stats_file)
        stats[user_id] = {
            "goals_created": 0,
            "goals_completed": 0,
            "videos_watched": 0,
            "articles_read": 0,
            "total_learning_time": 0,
            "last_activity": datetime.now().isoformat()
        }
        self._write_json(self.user_stats_file, stats)

    def update_user_stats(self, user_id: str, stat_name: str, increment: int = 1):
        users = self._read_json(self.users_file)
        stats = self._read_json(self.user_stats_file)

        if user_id not in users:
            return

        if user_id not in stats:
            self._initialize_user_stats(user_id)

        stats[user_id][stat_name] = stats[user_id].get(stat_name, 0) + increment
        stats[user_id]['last_activity'] = datetime.now().isoformat()
        self._write_json(self.user_stats_file, stats)

        user = users[user_id]
        if stat_name == "goals_created":
            user['total_goals'] = user.get('total_goals', 0) + increment
        elif stat_name == "goals_completed":
            user['completed_goals'] = user.get('completed_goals', 0) + increment
            user['reputation'] = user.get('reputation', 1) + (increment * 5)
            user['credits'] = user.get('credits', 0) + (increment * 100)
        elif stat_name == "videos_watched":
            user['total_videos_watched'] = user.get('total_videos_watched', 0) + increment
        elif stat_name == "articles_read":
            user['total_articles_read'] = user.get('total_articles_read', 0) + increment

        total_activity = (user.get('total_goals', 0) +
                          user.get('total_videos_watched', 0) +
                          user.get('total_articles_read', 0))
        user['activity_score'] = min(100.0, total_activity * 0.5)

        users[user_id] = user
        self._write_json(self.users_file, users)

    def get_user_stats(self, user_id: str) -> Dict:
        stats = self._read_json(self.user_stats_file)
        return stats.get(user_id, {})

    def _log_action(self, user_id: str, action: str, details: Dict):
        log = self._read_json(self.audit_log_file)

        log.append({
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "action": action,
            "details": details
        })

        if len(log) > 1000:
            log = log[-1000:]

        self._write_json(self.audit_log_file, log)

    def get_audit_log(self, limit: int = 100) -> List[Dict]:
        log = self._read_json(self.audit_log_file)
        return log[-limit:]

    def _sanitize_user(self, user: Dict) -> Dict:
        """Remove sensitive data from user object."""
        if not user:
            return None

        sanitized = user.copy()
        sanitized.pop('password_hash', None)
        return sanitized

    def _generate_handle(self, name: str) -> str:
        base_handle = name.upper().replace(' ', '-')
        return f"{base_handle}"

    def _generate_region(self) -> str:
        import random
        regions = ["SECTOR_7G", "SECTOR_42", "SECTOR_9", "SECTOR_13", "SECTOR_X"]
        return random.choice(regions)

    def save_goal(self, goal_data: Dict):
        goals = self._read_json(self.goals_file)

        if 'created_at' not in goal_data:
            goal_data['created_at'] = datetime.now().isoformat()

        goals.append(goal_data)
        self._write_json(self.goals_file, goals)

        user_id = goal_data.get('user_id', 'default')
        self.update_user_stats(user_id, 'goals_created')

        return goal_data.get('id')

    def save_learning_plan(self, goal_id: str, plan: Dict):
        goals = self._read_json(self.goals_file)

        for goal in goals:
            if goal.get('id') == goal_id:
                goal['plan'] = plan
                goal['plan_generated_at'] = datetime.now().isoformat()
                break

        self._write_json(self.goals_file, goals)

    def get_user_goals(self, user_id: str) -> List[Dict]:
        goals = self._read_json(self.goals_file)
        return [g for g in goals if g.get('user_id') == user_id]

    def mark_goal_complete(self, user_id: str, goal_id: str):
        goals = self._read_json(self.goals_file)

        for goal in goals:
            if goal.get('id') == goal_id and goal.get('user_id') == user_id:
                goal['completed'] = True
                goal['completed_at'] = datetime.now().isoformat()
                break

        self._write_json(self.goals_file, goals)
        self.update_user_stats(user_id, 'goals_completed')

    def get_goal_by_id(self, goal_id: str) -> Optional[Dict]:
        goals = self._read_json(self.goals_file)
        for goal in goals:
            if goal.get('id') == goal_id:
                return goal
        return None

    def get_task_completions(self, goal_id: str) -> Dict:
        """
        Return stored task completion data for a goal.
        Stored inside the goal record as 'task_completions':
          { task_id: {status, completed_at, notes} }
        """
        goal = self.get_goal_by_id(goal_id)
        if not goal:
            return {}
        return goal.get('task_completions', {})

    def _recompute_goal_content_progress(self, goal: dict) -> float:
        """Recompute goal progress based on watched videos and read articles."""
        total_weeks = goal.get('total_weeks', 0)
        total_items = total_weeks * 4
        if total_items <= 0:
            goal['progress'] = 0.0
            return 0.0

        watched = len(goal.get('watched_video_urls', []))
        read = len(goal.get('read_article_urls', []))
        progress = min(100.0, round((watched + read) / total_items * 100, 1))
        goal['progress'] = progress

        return progress

    def mark_video_watched(self, goal_id: str, user_id: str, video_url: str) -> bool:
        goals = self._read_json(self.goals_file)
        for goal in goals:
            if goal.get('id') == goal_id:
                if goal.get('user_id') != user_id:
                    return False
                watched = goal.setdefault('watched_video_urls', [])
                if video_url not in watched:
                    watched.append(video_url)
                    self._recompute_goal_content_progress(goal)
                    self._write_json(self.goals_file, goals)
                    self.update_user_stats(user_id, 'videos_watched')
                    self._log_action(user_id, 'video_watched', {'goal_id': goal_id, 'url': video_url})
                return True
        return False

    def unmark_video_watched(self, goal_id: str, user_id: str, video_url: str) -> bool:
        goals = self._read_json(self.goals_file)
        for goal in goals:
            if goal.get('id') == goal_id:
                if goal.get('user_id') != user_id:
                    return False
                watched = goal.get('watched_video_urls', [])
                if video_url in watched:
                    watched.remove(video_url)
                    self._recompute_goal_content_progress(goal)
                    self._write_json(self.goals_file, goals)
                    self.update_user_stats(user_id, 'videos_watched', -1)
                    self._log_action(user_id, 'video_unwatched', {'goal_id': goal_id, 'url': video_url})
                return True
        return False

    def mark_article_read(self, goal_id: str, user_id: str, article_url: str) -> bool:
        goals = self._read_json(self.goals_file)
        for goal in goals:
            if goal.get('id') == goal_id:
                if goal.get('user_id') != user_id:
                    return False
                read = goal.setdefault('read_article_urls', [])
                if article_url not in read:
                    read.append(article_url)
                    self._recompute_goal_content_progress(goal)
                    self._write_json(self.goals_file, goals)
                    self.update_user_stats(user_id, 'articles_read')
                    self._log_action(user_id, 'article_read', {'goal_id': goal_id, 'url': article_url})
                return True
        return False

    def unmark_article_read(self, goal_id: str, user_id: str, article_url: str) -> bool:
        goals = self._read_json(self.goals_file)
        for goal in goals:
            if goal.get('id') == goal_id:
                if goal.get('user_id') != user_id:
                    return False
                read = goal.get('read_article_urls', [])
                if article_url in read:
                    read.remove(article_url)
                    self._recompute_goal_content_progress(goal)
                    self._write_json(self.goals_file, goals)
                    self.update_user_stats(user_id, 'articles_read', -1)
                    self._log_action(user_id, 'article_unread', {'goal_id': goal_id, 'url': article_url})
                return True
        return False

    def update_task_status(
        self,
        goal_id: str,
        task_id: str,
        new_status: str,
        notes: str = ""
    ) -> Dict:
        """
        Update the status of a single plan task and recompute goal progress.

        Returns the updated task completion record.
        Raises ValueError on invalid transitions (enforced by plan_task_validator).
        """
        from backend.app.plan_task_validator import (
            validate_status_transition,
            compute_task_progress,
            extract_tasks_from_plan,
            merge_existing_completions,
        )

        goals = self._read_json(self.goals_file)
        target_goal = None
        target_idx = None

        for idx, goal in enumerate(goals):
            if goal.get('id') == goal_id:
                target_goal = goal
                target_idx = idx
                break

        if target_goal is None:
            raise ValueError(f"Goal '{goal_id}' not found")

        completions = target_goal.setdefault('task_completions', {})
        current = completions.get(task_id, {})
        current_status = current.get('status', 'pending')

        valid, error = validate_status_transition(current_status, new_status)
        if not valid:
            raise ValueError(error)

        now = datetime.now().isoformat()
        completions[task_id] = {
            'status': new_status,
            'completed_at': now if new_status == 'completed' else current.get('completed_at'),
            'updated_at': now,
            'notes': notes or current.get('notes', ''),
        }

        plan = target_goal.get('plan', {})
        if plan:
            extracted = extract_tasks_from_plan(goal_id, plan)
            merged = merge_existing_completions(extracted, completions)
            progress_data = compute_task_progress(merged)
            target_goal['task_progress_detail'] = {
                'total': progress_data['total_tasks'],
                'completed': progress_data['completed_tasks'],
                'in_progress': progress_data['in_progress_tasks'],
                'completion_rate': progress_data['completion_rate'],
            }

        # Goal progress is now driven by content consumption (videos + articles)
        self._recompute_goal_content_progress(target_goal)

        goals[target_idx] = target_goal
        self._write_json(self.goals_file, goals)

        self._log_action(
            target_goal.get('user_id', 'unknown'),
            'task_status_updated',
            {'goal_id': goal_id, 'task_id': task_id, 'new_status': new_status}
        )

        return completions[task_id]

    def get_all_tasks_for_goal(self, goal_id: str) -> List[Dict]:
        """
        Return all tasks for a goal with their current completion status.
        Extracts from the stored plan and merges stored completion data.
        """
        from backend.app.plan_task_validator import (
            extract_tasks_from_plan,
            merge_existing_completions,
        )

        goal = self.get_goal_by_id(goal_id)
        if not goal:
            return []

        plan = goal.get('plan', {})
        if not plan:
            return []

        extracted = extract_tasks_from_plan(goal_id, plan)
        completions = goal.get('task_completions', {})
        return merge_existing_completions(extracted, completions)

    def save_youtube_videos_for_goal(self, goal_id: str, videos: List[Dict]):
        all_videos = self._read_json(self.videos_file)

        all_videos = [v for v in all_videos if v.get('goal_id') != goal_id]

        for video in videos:
            video['goal_id'] = goal_id
            video['saved_at'] = datetime.now().isoformat()
            all_videos.append(video)

        self._write_json(self.videos_file, all_videos)

    def get_videos_by_goal(self, goal_id: str) -> List[Dict]:
        all_videos = self._read_json(self.videos_file)
        return [v for v in all_videos if v.get('goal_id') == goal_id]

    def get_all_videos(self) -> List[Dict]:
        return self._read_json(self.videos_file)

    def save_articles_for_goal(self, goal_id: str, articles: List[Dict]):
        all_articles = self._read_json(self.articles_file)

        all_articles = [a for a in all_articles if a.get('goal_id') != goal_id]

        for article in articles:
            article['goal_id'] = goal_id
            article['saved_at'] = datetime.now().isoformat()
            all_articles.append(article)

        self._write_json(self.articles_file, all_articles)

    def get_articles_by_goal(self, goal_id: str) -> List[Dict]:
        all_articles = self._read_json(self.articles_file)
        return [a for a in all_articles if a.get('goal_id') == goal_id]

    def get_all_articles(self) -> List[Dict]:
        return self._read_json(self.articles_file)

    # ------------------------------------------------------------------
    # Goal deletion (with cascade to videos + articles)
    # ------------------------------------------------------------------

    def delete_goal(self, goal_id: str, user_id: Optional[str] = None) -> bool:
        """
        Delete a goal and cascade-remove all associated videos and articles.

        Args:
            goal_id: ID of the goal to delete.
            user_id: When provided, the goal must belong to this user or
                     the call is rejected (returns False).

        Returns:
            True  — goal found and deleted.
            False — goal not found (or ownership mismatch).
        """
        goals = self._read_json(self.goals_file)

        target = next((g for g in goals if g.get('id') == goal_id), None)
        if target is None:
            return False

        if user_id is not None and target.get('user_id') != user_id:
            return False

        # Remove goal record
        goals = [g for g in goals if g.get('id') != goal_id]
        self._write_json(self.goals_file, goals)

        # Cascade: remove associated videos
        all_videos = self._read_json(self.videos_file)
        all_videos = [v for v in all_videos if v.get('goal_id') != goal_id]
        self._write_json(self.videos_file, all_videos)

        # Cascade: remove associated articles
        all_articles = self._read_json(self.articles_file)
        all_articles = [a for a in all_articles if a.get('goal_id') != goal_id]
        self._write_json(self.articles_file, all_articles)

        # Cascade: remove associated chat history
        owner = target.get('user_id', 'unknown')
        self.delete_chat_history(owner, goal_id)
        
        self._log_action(owner, 'goal_deleted', {'goal_id': goal_id, 'title': target.get('title', '')})
        return True

    # ------------------------------------------------------------------
    # Deadline / expiry helpers
    # ------------------------------------------------------------------

    def is_goal_expired(self, goal: Dict) -> bool:
        """
        Return True when the goal's deadline is in the past AND the goal
        has not been marked as completed.

        A goal without a 'deadline' field is never considered expired.
        """
        if goal.get('completed') or goal.get('status') == 'completed':
            return False

        deadline_str = goal.get('deadline')
        if not deadline_str:
            return False

        try:
            deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
        except ValueError:
            return False

        return deadline < datetime.now().date()

    def get_expired_goals(self, user_id: Optional[str] = None) -> List[Dict]:
        """
        Return all goals whose deadline has passed and that are not completed.

        Args:
            user_id: When provided, only return goals belonging to this user.
        """
        goals = self._read_json(self.goals_file)
        if user_id is not None:
            goals = [g for g in goals if g.get('user_id') == user_id]
        return [g for g in goals if self.is_goal_expired(g)]

    def delete_expired_goals(self, user_id: Optional[str] = None) -> int:
        """
        Delete all expired goals (and their associated content).

        Args:
            user_id: When provided, only delete expired goals for this user.

        Returns:
            Number of goals deleted.
        """
        expired = self.get_expired_goals(user_id=user_id)
        count = 0
        for goal in expired:
            if self.delete_goal(goal['id']):
                count += 1
        return count

    def complete_goal(self, goal_id: str, user_id: str) -> bool:
        """
        Mark a goal as completed.

        Returns True if the goal was found and updated, False otherwise
        (including ownership mismatch).
        """
        goals = self._read_json(self.goals_file)

        for goal in goals:
            if goal.get('id') == goal_id:
                if goal.get('user_id') != user_id:
                    return False

                now = datetime.now().isoformat()
                goal['status'] = 'completed'
                goal['completed'] = True
                goal['completed_at'] = now
                self._write_json(self.goals_file, goals)

                self.update_user_stats(user_id, 'goals_completed')
                self._log_action(user_id, 'goal_completed', {'goal_id': goal_id})
                return True

        return False

    def save_goal_quiz(self, goal_id: str, user_id: str, questions: List[Dict]) -> bool:
        goals = self._read_json(self.goals_file)
        for goal in goals:
            if goal.get('id') == goal_id:
                if goal.get('user_id') != user_id:
                    return False
                goal['quiz'] = {
                    'questions': questions,
                    'submitted_at': None,
                    'score': None,
                    'passed': False,
                    'attempts': 0,
                    'next_attempt_at': None,
                    'permanently_failed': False,
                }
                self._write_json(self.goals_file, goals)
                return True
        return False

    def get_goal_quiz(self, goal_id: str, user_id: str) -> Optional[Dict]:
        goal = self.get_goal_by_id(goal_id)
        if not goal or goal.get('user_id') != user_id:
            return None
        return goal.get('quiz')

    async def get_or_create_quiz(self, goal_id: str, user_id: str) -> Optional[Dict]:
        quiz = self.get_goal_quiz(goal_id, user_id)
        if quiz and quiz.get('questions'):
            return quiz
        goal = self.get_goal_by_id(goal_id)
        if not goal or goal.get('user_id') != user_id:
            return None
        from backend.app.quiz_generator import generate_quiz_for_goal
        videos = self.get_videos_by_goal(goal_id)
        articles = self.get_articles_by_goal(goal_id)
        questions = await generate_quiz_for_goal(goal, videos, articles)
        if not questions:
            return None
        self.save_goal_quiz(goal_id, user_id, questions)
        return self.get_goal_quiz(goal_id, user_id)

    def can_take_quiz(self, goal_id: str, user_id: str) -> Dict:
        goal = self.get_goal_by_id(goal_id)
        if not goal or goal.get('user_id') != user_id:
            return {'can_take': False, 'reason': 'Goal not found or access denied', 'next_attempt_at': None}
        if goal.get('progress', 0) < 100:
            return {'can_take': False, 'reason': 'Progress not complete', 'next_attempt_at': None}
        quiz = goal.get('quiz', {})
        if quiz.get('passed'):
            return {'can_take': False, 'reason': 'Quiz already passed', 'next_attempt_at': None}
        if quiz.get('permanently_failed'):
            return {'can_take': False, 'reason': 'Quiz permanently failed', 'next_attempt_at': None}
        attempts = quiz.get('attempts', 0) if quiz else 0
        next_attempt_at = quiz.get('next_attempt_at') if quiz else None
        if attempts >= 1 and next_attempt_at:
            if datetime.now() < datetime.fromisoformat(next_attempt_at):
                return {'can_take': False, 'reason': 'Retake not yet available', 'next_attempt_at': next_attempt_at}
        return {'can_take': True, 'reason': None, 'next_attempt_at': next_attempt_at}

    def submit_quiz_attempt(self, goal_id: str, user_id: str, answers: Dict[int, str]) -> Dict:
        goals = self._read_json(self.goals_file)
        for goal in goals:
            if goal.get('id') == goal_id:
                if goal.get('user_id') != user_id:
                    return {'error': 'Access denied'}
                quiz = goal.get('quiz')
                if not quiz or not quiz.get('questions'):
                    return {'error': 'No quiz available'}
                questions = quiz['questions']
                correct = 0
                for i, q in enumerate(questions, 1):
                    if answers.get(i) == q.get('correct'):
                        correct += 1
                passed = correct > (len(questions) / 2)
                attempts = quiz.get('attempts', 0) + 1
                quiz['score'] = correct
                quiz['attempts'] = attempts
                quiz['submitted_at'] = datetime.now().isoformat()

                if passed:
                    quiz['passed'] = True
                    self._write_json(self.goals_file, goals)
                    result = self.validate_and_complete_goal(goal_id, user_id)
                    return {
                        'passed': True,
                        'score': correct,
                        'attempts': attempts,
                        'completed': result.get('completed', False),
                        'deleted': result.get('deleted', False),
                    }
                else:
                    if attempts >= 2:
                        quiz['permanently_failed'] = True
                        quiz['next_attempt_at'] = None
                    else:
                        quiz['next_attempt_at'] = (datetime.now() + timedelta(days=1)).isoformat()
                    self._write_json(self.goals_file, goals)
                    return {
                        'passed': False,
                        'score': correct,
                        'attempts': attempts,
                        'permanently_failed': quiz.get('permanently_failed', False),
                        'next_attempt_at': quiz.get('next_attempt_at'),
                    }
        return {'error': 'Goal not found'}

    def validate_and_complete_goal(self, goal_id: str, user_id: str) -> Dict:
        goal = self.get_goal_by_id(goal_id)
        if not goal:
            return {'success': False, 'error': 'Goal not found'}
        if goal.get('user_id') != user_id:
            return {'success': False, 'error': 'Access denied'}
        if goal.get('progress', 0) < 100:
            return {'success': False, 'error': 'Progress not complete'}
        if not goal.get('quiz', {}).get('passed'):
            return {'success': False, 'error': 'Quiz not passed'}

        completed = self.complete_goal(goal_id, user_id)
        if not completed:
            return {'success': False, 'error': 'Could not complete goal'}

        deleted = self.delete_goal(goal_id, user_id=user_id)
        return {'success': True, 'completed': True, 'deleted': deleted}

    def delete_user(self, user_id: str) -> bool:
        users = self._read_json(self.users_file)

        if user_id not in users:
            return False

        user = users[user_id]
        email = user['email']

        del users[user_id]
        self._write_json(self.users_file, users)

        stats = self._read_json(self.user_stats_file)
        if user_id in stats:
            del stats[user_id]
            self._write_json(self.user_stats_file, stats)

        self._log_action(user_id, "user_deleted", {"email": email})

        return True

    def get_system_stats(self) -> Dict:
        users = self._read_json(self.users_file)
        goals = self._read_json(self.goals_file)
        videos = self._read_json(self.videos_file)
        articles = self._read_json(self.articles_file)

        total_users = len(users)
        active_users = len([u for u in users.values() if u.get('is_active', True)])
        total_goals = len(goals)
        completed_goals = len([g for g in goals if g.get('completed', False)])
        total_videos = len(videos)
        total_articles = len(articles)

        return {
            "users": {
                "total": total_users,
                "active": active_users,
                "inactive": total_users - active_users
            },
            "goals": {
                "total": total_goals,
                "completed": completed_goals,
                "active": total_goals - completed_goals
            },
            "content": {
                "videos": total_videos,
                "articles": total_articles
            }
        }

    def update_user_preferences(self, user_id: str, preferences: Dict) -> Dict:
        users = self._read_json(self.users_file)

        if user_id not in users:
            raise ValueError("User not found")

        user = users[user_id]

        if 'email_notifications' in preferences:
            user['email_notifications'] = preferences['email_notifications']
        if 'weekly_summary' in preferences:
            user['weekly_summary'] = preferences['weekly_summary']
        if 'content_updates' in preferences:
            user['content_updates'] = preferences['content_updates']

        user['updated_at'] = datetime.now().isoformat()
        users[user_id] = user
        self._write_json(self.users_file, users)

        self._log_action(user_id, "preferences_updated", preferences)

        return self._sanitize_user(user)


    # Chat persistence methods
    def save_chat_history(self, user_id: str, goal_id: Optional[str], messages: List[Dict]) -> bool:
        """Save chat messages for a user/goal combination."""
        try:
            chat_data = self._read_json(self.chat_file)
            session_key = f"{user_id}:{goal_id}" if goal_id else user_id
            
            chat_data[session_key] = {
                "user_id": user_id,
                "goal_id": goal_id,
                "messages": messages,
                "updated_at": datetime.now().isoformat()
            }
            
            self._write_json(self.chat_file, chat_data)
            return True
        except Exception:
            return False

    def get_chat_history(self, user_id: str, goal_id: Optional[str] = None) -> List[Dict]:
        """Retrieve chat messages for a user/goal combination."""
        try:
            chat_data = self._read_json(self.chat_file)
            session_key = f"{user_id}:{goal_id}" if goal_id else user_id
            
            if session_key in chat_data:
                return chat_data[session_key].get("messages", [])
            return []
        except Exception:
            return []

    def delete_chat_history(self, user_id: str, goal_id: Optional[str] = None) -> bool:
        """Delete chat history for a user/goal combination."""
        try:
            chat_data = self._read_json(self.chat_file)
            session_key = f"{user_id}:{goal_id}" if goal_id else user_id
            
            if session_key in chat_data:
                del chat_data[session_key]
                self._write_json(self.chat_file, chat_data)
                return True
            return False
        except Exception:
            return False

