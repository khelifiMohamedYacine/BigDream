from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from typing import Optional
import uvicorn
import uuid
import asyncio
from datetime import datetime

from backend.app.GoalProcessingSystem import GoalProcessingSystem
from backend.database_manager import DatabaseManager
from backend.auth_middleware import AuthMiddleware
from backend.auth_routes import create_auth_router
from backend.admin_routes import create_admin_router

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "frontend" / "static"
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
DATA_DIR = Path(__file__).resolve().parent / "data"

db_manager = DatabaseManager(data_dir=str(DATA_DIR))
auth_middleware = AuthMiddleware(db_manager)

processing_system = None
_cleanup_task = None


async def _expired_goal_cleanup_task():
    """Background task that periodically deletes expired goals."""
    while True:
        try:
            await asyncio.sleep(60)
            if db_manager:
                db_manager.delete_expired_goals()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global processing_system, _cleanup_task
    processing_system = GoalProcessingSystem(data_dir=str(DATA_DIR))
    await processing_system.start()
    _cleanup_task = asyncio.create_task(_expired_goal_cleanup_task())
    host = "http://localhost:8000"
    divider  = "-" * 44
    routes = [
        ("Dashboard", "/home.html"),
        ("Admin",     "/admin.html"),
        ("API Docs",  "/docs"),
    ]
    print(f"\n{divider}")
    print(f"  App running at {host}")
    print(divider)
    for name, path in routes:
        print(f"  {name:<12}->  {host}{path}")
    print(f"{divider}\n")
    yield
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
    if processing_system:
        await processing_system.stop()


app = FastAPI(title="BigDream API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

auth_router = create_auth_router(db_manager, auth_middleware)
admin_router = create_admin_router(db_manager, auth_middleware)

app.include_router(auth_router)
app.include_router(admin_router)


class ChatMessage(BaseModel):
    message: str
    user_id: str = "default"
    goal_id: Optional[str] = None


class GoalCreate(BaseModel):
    description: str
    user_id: str
    timeline: str = "3 months"
    why_important: Optional[str] = None
    success_metric: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def index():
    with open(TEMPLATES_DIR / "index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/home.html", response_class=HTMLResponse)
async def home():
    with open(TEMPLATES_DIR / "home.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/login.html", response_class=HTMLResponse)
async def login():
    with open(TEMPLATES_DIR / "login.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/register.html", response_class=HTMLResponse)
async def register():
    with open(TEMPLATES_DIR / "register.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/forgot-password.html", response_class=HTMLResponse)
async def forgot_password():
    with open(TEMPLATES_DIR / "forgot-password.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/reset-password.html", response_class=HTMLResponse)
async def reset_password():
    with open(TEMPLATES_DIR / "reset-password.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/goals.html", response_class=HTMLResponse)
async def goals():
    with open(TEMPLATES_DIR / "goals.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/videos.html", response_class=HTMLResponse)
async def videos():
    with open(TEMPLATES_DIR / "videos.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/articles.html", response_class=HTMLResponse)
async def articles():
    with open(TEMPLATES_DIR / "articles.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/account.html", response_class=HTMLResponse)
async def account():
    with open(TEMPLATES_DIR / "account.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/admin.html", response_class=HTMLResponse)
async def admin():
    with open(TEMPLATES_DIR / "admin.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/chat")
async def chat(message: ChatMessage):
    """Send message to chatbot and get immediate response (non-blocking)."""
    try:
        if not processing_system:
            return JSONResponse(status_code=500, content={
                "error": "Service is starting up. Please try again in a moment.",
                "chat_response": "The service is starting up. Please wait a moment and try again."
            })

        response = await processing_system.chatbot.send_message(
            message.message,
            message.user_id,
            message.goal_id
        )

        if response.get("action_required") == "goal_created":
            if response.get("new_goal"):
                goal_id = response["new_goal"]["id"]
                response["goal_id"] = goal_id
                response["progress_url"] = f"/api/progress/{goal_id}"
            else:
                # Goal creation failed
                response["chat_response"] = "Sorry, there was an error creating your goal. Please try again."
                response["action_required"] = None

        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "chat_response": f"Error: {str(e)}"
        })


@app.get("/api/progress/{goal_id}")
async def get_progress(goal_id: str):
    """Get real-time progress for goal generation."""
    try:
        if not processing_system or not processing_system.shared_data:
            return {"status": "unknown", "progress": 0}

        task = None
        with processing_system.shared_data.lock:
            if goal_id in processing_system.shared_data.tasks:
                task = processing_system.shared_data.tasks[goal_id]

        if not task:
            goal = processing_system.db_manager.get_goal_by_id(goal_id)

            if goal:
                has_plan = bool(goal.get("plan"))
                # Check if videos and articles actually exist in DB
                videos = processing_system.db_manager.get_videos_by_goal(goal_id) if has_plan else []
                articles = processing_system.db_manager.get_articles_by_goal(goal_id) if has_plan else []
                has_videos = len(videos) > 0
                has_articles = len(articles) > 0

                if has_plan and has_videos and has_articles:
                    return {
                        "status": "completed",
                        "progress": 100,
                        "plan_ready": True,
                        "videos_ready": True,
                        "articles_ready": True,
                        "message": "Your learning plan is ready!"
                    }
                else:
                    return {
                        "status": "processing",
                        "progress": (has_plan * 33) + (has_videos * 33) + (has_articles * 34),
                        "plan_ready": has_plan,
                        "videos_ready": has_videos,
                        "articles_ready": has_articles,
                        "message": "Generating your content..."
                    }
            else:
                return {"status": "not_found", "progress": 0}

        results = task.results if hasattr(task, 'results') else {}

        has_plan = "plan" in results
        has_videos = "_video_map" in results or "youtube_videos" in results
        has_articles = "_article_map" in results or "articles" in results

        progress = 0
        if has_plan:
            progress += 33
        if has_videos:
            progress += 33
        if has_articles:
            progress += 34

        status = "processing"
        message = "Generating your learning plan..."

        if progress == 0:
            message = "Starting plan generation..."
        elif progress < 50:
            message = "Generating curriculum and finding content..."
        elif progress < 100:
            message = "Almost done! Finalizing your plan..."
        else:
            status = "completed"
            message = "Your learning plan is ready!"

        return {
            "status": status,
            "progress": progress,
            "plan_ready": has_plan,
            "videos_ready": has_videos,
            "articles_ready": has_articles,
            "message": message
        }

    except Exception as e:
        return {"status": "error", "progress": 0, "error": str(e)}


@app.get("/api/chat/history")
async def get_chat_history(user_id: str = "default", goal_id: Optional[str] = None):
    """Get chat history for a user/goal."""
    try:
        messages = db_manager.get_chat_history(user_id, goal_id)
        return {
            "messages": messages,
            "user_id": user_id,
            "goal_id": goal_id
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/chat/history")
async def delete_chat_history(user_id: str = "default", goal_id: Optional[str] = None):
    """Delete chat history for a user/goal."""
    try:
        success = db_manager.delete_chat_history(user_id, goal_id)
        if processing_system:
            processing_system.chatbot._delete_session(user_id, goal_id)
        return {"deleted": success}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/goals")
async def get_goals(user_id: str = "default"):
    """Get all goals for a user (returns immediately with current state)."""
    try:
        if not processing_system:
            return JSONResponse(status_code=500, content={"error": "Service is starting up. Please try again in a moment."})

        # Eagerly clean up any expired goals for this user before returning
        db_manager.delete_expired_goals(user_id=user_id)

        goals = processing_system.chatbot.get_goals(user_id)

        goals_dict = {}
        for goal in goals:
            goal_id = goal.get('id', str(uuid.uuid4())[:8])
            videos = processing_system.db_manager.get_videos_by_goal(goal_id)
            articles = processing_system.db_manager.get_articles_by_goal(goal_id)
            time_meta = _compute_goal_time_meta(goal)
            goals_dict[goal_id] = {
                "goal": goal,
                "results": {
                    "plan": goal.get("plan", {}),
                    "videos_generated": bool(videos),
                    "articles_generated": bool(articles)
                },
                "status": goal.get("status", "pending"),
                **time_meta,
            }

        return goals_dict
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/videos/{goal_id}")
async def get_videos(goal_id: str):
    """Get all videos for a specific goal (returns empty if not ready yet)."""
    try:
        videos = processing_system.db_manager.get_videos_by_goal(goal_id)
        return videos if videos else []
    except Exception:
        return []


@app.get("/api/articles/{goal_id}")
async def get_articles(goal_id: str):
    """Get all articles for a specific goal (returns empty if not ready yet)."""
    try:
        articles = processing_system.db_manager.get_articles_by_goal(goal_id)
        return articles if articles else []
    except Exception:
        return []


@app.get("/api/stats")
async def get_stats(user_id: str = "default"):
    """Get dashboard statistics."""
    try:
        goals = processing_system.chatbot.get_goals(user_id)

        return {
            "active_goals": len(goals),
            "completed_tasks": len([g for g in goals if g.get('status') == 'completed']),
            "progress": f"{sum(g.get('progress', 0) for g in goals) // max(len(goals), 1)}%",
            "streak": "0 days"
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


def _compute_goal_time_meta(goal: dict) -> dict:
    """Compute time-based progress and remaining time for a goal."""
    deadline_str = goal.get("deadline")
    created_str = goal.get("created_at")
    now = datetime.now()

    meta = {
        "time_progress_pct": 0.0,
        "time_remaining_text": "No deadline",
        "is_expired": False,
    }

    if not deadline_str:
        return meta

    try:
        deadline = datetime.strptime(deadline_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return meta

    created = now
    if created_str:
        try:
            if "T" in created_str:
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            else:
                created = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            created = now

    total_duration = (deadline - created).total_seconds()
    elapsed = (now - created).total_seconds()

    if total_duration > 0:
        meta["time_progress_pct"] = round(min(100.0, max(0.0, (elapsed / total_duration) * 100)), 1)
    else:
        meta["time_progress_pct"] = 100.0

    remaining_seconds = (deadline - now).total_seconds()

    if remaining_seconds < 0:
        meta["is_expired"] = True
        meta["time_remaining_text"] = "Expired"
    elif remaining_seconds < 86400:
        meta["time_remaining_text"] = "Due today"
    elif remaining_seconds < 86400 * 30:
        days = int(remaining_seconds // 86400)
        meta["time_remaining_text"] = f"{days} day{'s' if days != 1 else ''} left"
    else:
        months = int(remaining_seconds // (86400 * 30))
        meta["time_remaining_text"] = f"{months} month{'s' if months != 1 else ''} left"

    return meta


class TaskStatusUpdate(BaseModel):
    status: str   # pending | in_progress | completed | skipped
    notes: Optional[str] = ""


@app.get("/api/goals/{goal_id}/tasks")
async def get_goal_tasks(goal_id: str):
    """
    List all plan tasks for a goal with their current completion status.
    Tasks are derived from the weekly_breakdown of the stored learning plan.
    """
    try:
        tasks = db_manager.get_all_tasks_for_goal(goal_id)
        if not tasks:
            goal = db_manager.get_goal_by_id(goal_id)
            if not goal:
                return JSONResponse(status_code=404, content={"error": "Goal not found"})
            if not goal.get("plan"):
                return JSONResponse(status_code=202, content={
                    "message": "Plan not yet generated. Check /api/progress/{goal_id}",
                    "tasks": []
                })
        return {"goal_id": goal_id, "tasks": tasks, "total": len(tasks)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.put("/api/goals/{goal_id}/tasks/{task_id}")
async def update_task_status(goal_id: str, task_id: str, update: TaskStatusUpdate):
    """
    Update the status of a specific plan task.

    Allowed statuses: pending | in_progress | completed | skipped
    Status transitions are validated by plan_task_validator.py.
    Goal progress is automatically recomputed after each update.
    """
    try:
        result = db_manager.update_task_status(
            goal_id=goal_id,
            task_id=task_id,
            new_status=update.status,
            notes=update.notes or "",
        )
        goal = db_manager.get_goal_by_id(goal_id)
        return {
            "task_id": task_id,
            "updated": result,
            "goal_progress": goal.get("progress", 0) if goal else 0,
            "task_progress_detail": goal.get("task_progress_detail", {}) if goal else {},
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/goals/{goal_id}/tasks/summary")
async def get_task_summary(goal_id: str):
    """
    Return a full validation report for a goal's plan tasks:
      - Plan health (excellent / on_track / needs_attention / at_risk)
      - Progress by week
      - Overdue task count
      - Current recommended week
      - Recommendations for the user
    """
    try:
        from backend.app.plan_task_validator import generate_validation_report

        goal = db_manager.get_goal_by_id(goal_id)
        if not goal:
            return JSONResponse(status_code=404, content={"error": "Goal not found"})

        tasks = db_manager.get_all_tasks_for_goal(goal_id)
        report = generate_validation_report(goal, tasks)
        return report
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/goals/{goal_id}/tasks/week/{week_num}")
async def get_tasks_for_week(goal_id: str, week_num: int):
    """Return tasks filtered to a specific week number."""
    try:
        from backend.app.plan_task_validator import get_tasks_for_week

        all_tasks = db_manager.get_all_tasks_for_goal(goal_id)
        week_tasks = get_tasks_for_week(all_tasks, week_num)
        return {
            "goal_id": goal_id,
            "week": week_num,
            "tasks": week_tasks,
            "total": len(week_tasks),
            "completed": sum(1 for t in week_tasks if t.get("status") == "completed"),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/goals/{goal_id}")
async def delete_goal(goal_id: str, user_id: str = "default"):
    """Manually delete a goal and all associated resources."""
    try:
        deleted = db_manager.delete_goal(goal_id, user_id=user_id)
        if deleted:
            if processing_system and processing_system.chatbot:
                processing_system.chatbot._delete_session(user_id, goal_id)
            return {"deleted": True, "goal_id": goal_id}
        return JSONResponse(status_code=404, content={"error": "Goal not found or access denied"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


class QuizSubmitRequest(BaseModel):
    answers: dict


@app.get("/api/goals/{goal_id}/quiz")
async def get_goal_quiz(goal_id: str, user_id: str = "default"):
    """Get or generate the validation quiz for a goal."""
    try:
        quiz = await db_manager.get_or_create_quiz(goal_id, user_id)
        if not quiz:
            return JSONResponse(status_code=404, content={"error": "Goal not found or quiz could not be generated"})
        eligibility = db_manager.can_take_quiz(goal_id, user_id)
        return {
            "quiz": quiz,
            "can_take": eligibility.get("can_take", False),
            "reason": eligibility.get("reason"),
            "next_attempt_at": eligibility.get("next_attempt_at"),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/goals/{goal_id}/quiz/submit")
async def submit_quiz(goal_id: str, req: QuizSubmitRequest, user_id: str = "default"):
    """Submit quiz answers for validation."""
    try:
        eligibility = db_manager.can_take_quiz(goal_id, user_id)
        if not eligibility.get("can_take"):
            return JSONResponse(status_code=403, content={"error": eligibility.get("reason", "Cannot take quiz now")})
        # Normalize answers keys to ints
        answers = {}
        for k, v in req.answers.items():
            try:
                answers[int(k)] = str(v).upper()
            except (ValueError, TypeError):
                continue
        result = db_manager.submit_quiz_attempt(goal_id, user_id, answers)
        if result.get("error"):
            return JSONResponse(status_code=400, content={"error": result["error"]})
        if result.get("passed") and result.get("deleted"):
            if processing_system and processing_system.chatbot:
                processing_system.chatbot._delete_session(user_id, goal_id)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


class VideoWatchRequest(BaseModel):
    video_url: str


class ArticleReadRequest(BaseModel):
    article_url: str


@app.post("/api/goals/{goal_id}/videos/watch")
async def watch_video(goal_id: str, req: VideoWatchRequest, user_id: str = "default"):
    """Mark a specific video as watched for a goal."""
    try:
        success = db_manager.mark_video_watched(goal_id, user_id, req.video_url)
        if success:
            goal = db_manager.get_goal_by_id(goal_id)
            return {
                "watched": True,
                "goal_progress": goal.get("progress", 0) if goal else 0,
            }
        return JSONResponse(status_code=404, content={"error": "Goal not found or access denied"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/goals/{goal_id}/videos/unwatch")
async def unwatch_video(goal_id: str, req: VideoWatchRequest, user_id: str = "default"):
    """Unmark a specific video as watched for a goal."""
    try:
        success = db_manager.unmark_video_watched(goal_id, user_id, req.video_url)
        if success:
            goal = db_manager.get_goal_by_id(goal_id)
            return {
                "watched": False,
                "goal_progress": goal.get("progress", 0) if goal else 0,
            }
        return JSONResponse(status_code=404, content={"error": "Goal not found or access denied"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/goals/{goal_id}/articles/read")
async def read_article(goal_id: str, req: ArticleReadRequest, user_id: str = "default"):
    """Mark a specific article as read for a goal."""
    try:
        success = db_manager.mark_article_read(goal_id, user_id, req.article_url)
        if success:
            goal = db_manager.get_goal_by_id(goal_id)
            return {
                "read": True,
                "goal_progress": goal.get("progress", 0) if goal else 0,
            }
        return JSONResponse(status_code=404, content={"error": "Goal not found or access denied"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/goals/{goal_id}/articles/unread")
async def unread_article(goal_id: str, req: ArticleReadRequest, user_id: str = "default"):
    """Unmark a specific article as read for a goal."""
    try:
        success = db_manager.unmark_article_read(goal_id, user_id, req.article_url)
        if success:
            goal = db_manager.get_goal_by_id(goal_id)
            return {
                "read": False,
                "goal_progress": goal.get("progress", 0) if goal else 0,
            }
        return JSONResponse(status_code=404, content={"error": "Goal not found or access denied"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/health")
async def health_check():
    """Check if API is running."""
    return {
        "status": "healthy",
        "system_running": processing_system.running if processing_system else False
    }


if __name__ == "__main__":
    uvicorn.run(
        "backend.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
