import asyncio
import aiohttp
from typing import List, Dict, Optional
import os
import re

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeSearcher:
    """
    YouTube searcher using YouTube Data API with intelligent title matching.
    """

    def __init__(self):
        pass

    def _clean_topic(self, topic: str) -> str:
        """Clean topic for better search - remove code formatting and tech jargon."""
        cleaned = topic
        
        # Remove backticks and code formatting
        cleaned = re.sub(r'`([^`]+)`', r'\1', cleaned)
        
        # Replace technical terms with readable versions
        replacements = {
            'virtualenv': 'virtual environment',
            'venv': 'virtual environment',
            'pip install': 'installing',
            'pip': 'package manager',
            'flask run': 'running Flask',
            'django-admin': 'Django admin',
            'python -m': 'Python module',
            'requirements.txt': 'requirements file',
            '__init__.py': 'init file',
            '.py': 'Python file',
            'def ': 'function',
            'class ': 'class',
            'import ': 'importing',
            'from ': 'from',
            'return ': 'returning',
            'self.': '',
            '():': '',
            '()': '',
        }
        
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
        
        # Remove parentheses with content (often contains code)
        cleaned = re.sub(r'\([^)]*\)', '', cleaned)
        
        # Clean up extra spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        return cleaned

    def _calculate_title_match_score(self, video_title: str, topic: str) -> int:
        """
        Calculate how well a video title matches the topic.
        Higher score = better match.
        """
        title_lower = video_title.lower()
        topic_lower = topic.lower()
        
        # Extract key terms from topic (remove common words)
        common_words = {'the', 'and', 'for', 'are', 'with', 'they', 'this', 'that', 
                       'you', 'how', 'what', 'why', 'when', 'where', 'from', 'into',
                       'over', 'than', 'only', 'some', 'time', 'very', 'after',
                       'before', 'being', 'having', 'each', 'more', 'most', 'other',
                       'such', 'make', 'made', 'well', 'work', 'first', 'last',
                       'long', 'great', 'little', 'just', 'also', 'back', 'know',
                       'take', 'year', 'good', 'come', 'these', 'them', 'were',
                       'said', 'which', 'using', 'use', 'create', 'creating',
                       'implement', 'implementing', 'build', 'building', 'learn',
                       'learning', 'tutorial', 'guide', 'beginner', 'complete'}
        
        topic_words = set(w for w in re.findall(r'\b[a-zA-Z]+\b', topic_lower) 
                         if len(w) > 2 and w not in common_words)
        
        score = 0
        
        # Exact or near-exact match is best
        if topic_lower in title_lower:
            score += 100
        
        # Check for key topic words in title
        title_words = set(re.findall(r'\b[a-zA-Z]+\b', title_lower))
        matching_words = topic_words & title_words
        
        if topic_words:
            # Percentage of topic words found in title
            coverage = len(matching_words) / len(topic_words)
            score += int(coverage * 50)
        
        # Bonus for exact word matches
        score += len(matching_words) * 10
        
        # Bonus if important technical terms appear
        tech_terms = {'python', 'pytorch', 'tensorflow', 'keras', 'django', 'flask',
                     'cnn', 'rnn', 'lstm', 'gan', 'neural', 'network', 'machine',
                     'learning', 'deep', 'scikit', 'numpy', 'pandas', 'matplotlib',
                     'opencv', 'nltk', 'transformer', 'bert', 'gpt', 'api', 'sql',
                     'database', 'docker', 'kubernetes', 'aws', 'azure'}
        
        for term in tech_terms:
            if term in topic_lower and term in title_lower:
                score += 15
        
        # Penalize generic titles
        generic_terms = ['full course', 'complete course', 'learn programming',
                        'programming tutorial', 'coding for beginners', 
                        'introduction to programming', 'software development']
        for generic in generic_terms:
            if generic in title_lower and generic not in topic_lower:
                score -= 30
        
        return max(0, score)

    async def _search_youtube_api(self, query: str, topic: str) -> List[Dict]:
        """Search for videos using YouTube Data API with intelligent ranking."""
        if not YOUTUBE_API_KEY:
            return []
        try:
            # Use a more specific query
            search_query = self._clean_topic(topic)
            
            # First, search for video IDs
            search_params = {
                "part": "snippet",
                "q": search_query,
                "type": "video",
                "maxResults": 15,  # Get more to filter
                "key": YOUTUBE_API_KEY,
                "relevanceLanguage": "en",
                "videoDuration": "medium",  # 4-20 minutes, good for tutorials
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    YOUTUBE_SEARCH_URL, params=search_params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        return []
                    search_data = await response.json()
                    
                    video_ids = []
                    video_info = {}  # Store title for scoring
                    
                    for item in search_data.get("items", []):
                        vid_id = item.get("id", {}).get("videoId", "")
                        if vid_id:
                            video_ids.append(vid_id)
                            video_info[vid_id] = {
                                "title": item.get("snippet", {}).get("title", ""),
                                "channel": item.get("snippet", {}).get("channelTitle", ""),
                            }
                    
                    if not video_ids:
                        return []
                    
                    # Get video details (duration, views, etc.)
                    videos_params = {
                        "part": "snippet,contentDetails,statistics",
                        "id": ",".join(video_ids[:10]),  # Limit to avoid quota issues
                        "key": YOUTUBE_API_KEY,
                    }
                    
                    async with session.get(
                        YOUTUBE_VIDEOS_URL, params=videos_params,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as videos_response:
                        if videos_response.status != 200:
                            return []
                        
                        videos_data = await videos_response.json()
                        
                        videos = []
                        for item in videos_data.get("items", []):
                            vid_id = item.get("id", "")
                            snippet = item.get("snippet", {})
                            content_details = item.get("contentDetails", {})
                            statistics = item.get("statistics", {})
                            
                            title = snippet.get("title", "Unknown")
                            
                            # Parse duration (ISO 8601 format: PT4M26S)
                            duration_str = content_details.get("duration", "PT0S")
                            duration_seconds = self._parse_duration(duration_str)
                            
                            # Skip shorts (< 3 minutes) and very long videos (> 30 min)
                            if duration_seconds and (duration_seconds < 180 or duration_seconds > 1800):
                                continue
                            
                            # Calculate match score
                            match_score = self._calculate_title_match_score(title, topic)
                            
                            videos.append({
                                "video_id": vid_id,
                                "title": title,
                                "channel": snippet.get("channelTitle", "Unknown"),
                                "url": f"https://www.youtube.com/watch?v={vid_id}",
                                "duration": self._fmt_duration(duration_seconds),
                                "views": self._fmt_views(int(statistics.get("viewCount", 0))),
                                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"),
                                "match_score": match_score,
                            })
                        
                        # Sort by match score (highest first)
                        videos.sort(key=lambda x: x["match_score"], reverse=True)
                        
                        return videos
                        
        except Exception as e:
            print(f"[YouTube Search] Error: {e}")
            return []

    def _parse_duration(self, duration_str: str) -> int:
        """Parse ISO 8601 duration (PT4M26S) to seconds."""
        import re
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
        if not match:
            return 0
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds

    async def _verify_video_api(self, video_id: str) -> bool:
        """Verify video availability using YouTube Data API."""
        if not YOUTUBE_API_KEY:
            return True  # Be optimistic if no key
        try:
            params = {
                "part": "status",
                "id": video_id,
                "key": YOUTUBE_API_KEY,
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    YOUTUBE_VIDEOS_URL, params=params,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = data.get("items", [])
                        if not items:
                            return False
                        status = items[0].get("status", {})
                        return status.get("privacyStatus") == "public"
        except Exception:
            pass
        return True  # Be optimistic on error

    async def verify_video(self, video_id: str) -> bool:
        """Verify that a YouTube video is available."""
        return await self._verify_video_api(video_id)

    async def find_single_video(self, topic: str) -> Optional[Dict]:
        """
        Find exactly one verified video that best matches the topic.
        Always returns at least a fallback search link.
        """
        search_results = await self._search_youtube_api(topic, topic)
        
        # Try videos in order of match score
        for video in search_results:
            vid_id = video.get("video_id", "").strip()
            if vid_id:
                # Accept videos with reasonable match (lowered threshold)
                if video.get("match_score", 0) >= 10:
                    if await self.verify_video(vid_id):
                        return {
                            "video_id": video["video_id"],
                            "title": video["title"],
                            "channel": video["channel"],
                            "url": video["url"],
                            "duration": video["duration"],
                            "views": video["views"],
                            "thumbnail": video["thumbnail"],
                        }
        
        # Fallback 1: Try with a simpler query (just key terms)
        simple_query = ' '.join(self._extract_keywords(topic)[:3])
        if simple_query and simple_query != topic:
            print(f"[YouTube] Trying simplified query: {simple_query}")
            simple_results = await self._search_youtube_api(simple_query, topic)
            for video in simple_results:
                vid_id = video.get("video_id", "").strip()
                if vid_id and await self.verify_video(vid_id):
                    return {
                        "video_id": video["video_id"],
                        "title": video["title"],
                        "channel": video["channel"],
                        "url": video["url"],
                        "duration": video["duration"],
                        "views": video["views"],
                        "thumbnail": video["thumbnail"],
                    }
        
        # Fallback 2: Try to get first result from YouTube search API
        print(f"[YouTube] Trying to fetch first search result for: {topic[:50]}...")
        first_video = await self._get_first_search_result(topic)
        if first_video:
            return first_video
        
        # Fallback 3: SerpAPI YouTube search for first real video
        print(f"[YouTube] Trying SerpAPI for: {topic[:50]}...")
        serp_video = await self._serpapi_first_video(topic)
        if serp_video:
            return serp_video

        # Ultimate fallback: search link (should rarely be reached)
        search_url = f"https://www.youtube.com/results?search_query={topic.replace(' ', '+')}"
        print(f"[YouTube] Using search fallback for: {topic[:50]}...")
        return {
            "video_id": "search",
            "title": f"Search YouTube: {topic[:60]}",
            "channel": "YouTube Search",
            "url": search_url,
            "duration": "Varies",
            "views": "Search results",
            "thumbnail": "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        }

    async def _serpapi_first_video(self, topic: str) -> Optional[Dict]:
        """Get first YouTube video via SerpAPI as last resort before search URL."""
        api_key = os.getenv("SERPAPI_KEY", "")
        if not api_key:
            return None
        try:
            params = {
                "engine": "youtube",
                "search_query": topic,
                "api_key": api_key,
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://serpapi.com/search.json",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("video_results", [])
                        if results:
                            v = results[0]
                            vid_url = v.get("link", "")
                            vid_id = v.get("id", "search")
                            views_raw = v.get("views", 0)
                            views_fmt = self._fmt_views(int(views_raw)) if isinstance(views_raw, (int, float)) else str(views_raw)
                            return {
                                "video_id": vid_id,
                                "title": v.get("title", topic),
                                "channel": v.get("channel", {}).get("name", "YouTube"),
                                "url": vid_url,
                                "duration": v.get("length", "Unknown"),
                                "views": views_fmt,
                                "thumbnail": v.get("thumbnail", {}).get("static", f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"),
                            }
        except Exception as e:
            print(f"[YouTube SerpAPI] Error: {e}")
        return None

    async def _get_first_search_result(self, topic: str) -> Optional[Dict]:
        """Fetch the first video result from YouTube search API."""
        api_key = os.getenv("YOUTUBE_API_KEY", "")
        if not api_key:
            return None
        
        try:
            search_url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "part": "snippet",
                "q": topic,
                "type": "video",
                "maxResults": 1,
                "key": api_key,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("items", [])
                        if items:
                            item = items[0]
                            vid_id = item["id"]["videoId"]
                            snippet = item["snippet"]
                            
                            # Get video details for duration
                            details = await self._get_video_details(vid_id, api_key)
                            
                            return {
                                "video_id": vid_id,
                                "title": snippet.get("title", topic),
                                "channel": snippet.get("channelTitle", "YouTube"),
                                "url": f"https://youtube.com/watch?v={vid_id}",
                                "duration": details.get("duration", "10:00") if details else "10:00",
                                "views": details.get("views", "N/A") if details else "N/A",
                                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", 
                                                   snippet.get("thumbnails", {}).get("default", {}).get("url", "")),
                            }
        except Exception as e:
            print(f"[YouTube] Error fetching first result: {e}")
        
        return None
    
    async def _get_video_details(self, video_id: str, api_key: str) -> Optional[Dict]:
        """Get video details (duration, views) from YouTube API."""
        try:
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "contentDetails,statistics",
                "id": video_id,
                "key": api_key,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("items", [])
                        if items:
                            details = items[0]
                            content = details.get("contentDetails", {})
                            stats = details.get("statistics", {})
                            
                            duration_iso = content.get("duration", "PT10M")
                            duration_sec = self._parse_duration(duration_iso)
                            
                            return {
                                "duration": self._fmt_duration(duration_sec),
                                "views": self._fmt_views(int(stats.get("viewCount", 0))),
                            }
        except Exception as e:
            print(f"[YouTube] Error getting video details: {e}")
        
        return None
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        import re
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        common = {'the', 'and', 'for', 'are', 'with', 'they', 'this', 'that', 'you', 'how', 
                  'what', 'why', 'when', 'where', 'from', 'into', 'over', 'than', 'only', 
                  'some', 'time', 'very', 'after', 'before', 'being', 'having', 'each', 
                  'more', 'most', 'other', 'such', 'make', 'made', 'well', 'work', 'first',
                  'last', 'long', 'great', 'little', 'just', 'also', 'back', 'know', 'take'}
        return [w for w in words if w not in common]

    @staticmethod
    def _fmt_duration(seconds: int) -> str:
        """Format seconds into human-readable duration."""
        if not seconds:
            return "0:00"
        h, remainder = divmod(seconds, 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _fmt_views(views: int) -> str:
        """Format view count into human-readable string."""
        if views >= 1_000_000:
            return f"{views / 1_000_000:.1f}M views"
        if views >= 1_000:
            return f"{views / 1_000:.0f}K views"
        return f"{views} views"
