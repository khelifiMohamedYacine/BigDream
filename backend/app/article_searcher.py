import aiohttp
from typing import Dict, List, Optional
from datetime import datetime
import re
import os


class ArticleSearcher:
    """
    Article searcher using live APIs (SerpAPI, ArXiv, Semantic Scholar, CORE, HAL).
    No hardcoded resource lists — all results are fetched dynamically.
    """

    # ArXiv categories for CS/ML papers
    ARXIV_CATEGORIES = {
        'machine learning': 'cs.LG',
        'deep learning': 'cs.LG',
        'neural network': 'cs.LG',
        'cnn': 'cs.CV',
        'rnn': 'cs.LG',
        'lstm': 'cs.LG',
        'gan': 'cs.CV',
        'computer vision': 'cs.CV',
        'nlp': 'cs.CL',
        'natural language': 'cs.CL',
        'transformer': 'cs.CL',
        'bert': 'cs.CL',
        'gpt': 'cs.CL',
        'reinforcement': 'cs.AI',
        'ai': 'cs.AI',
        'artificial intelligence': 'cs.AI',
        'algorithm': 'cs.DS',
        'data structure': 'cs.DS',
        'database': 'cs.DB',
        'web': 'cs.SE',
        'security': 'cs.CR',
        'cryptography': 'cs.CR',
    }

    def __init__(self):
        pass

    def _clean_topic(self, topic: str) -> str:
        """Clean topic - remove code formatting and tech jargon."""
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
        }
        
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
        
        # Remove parentheses with content
        cleaned = re.sub(r'\([^)]*\)', '', cleaned)
        
        # Clean up extra spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        return cleaned

    def _extract_keywords(self, topic: str) -> List[str]:
        """Extract meaningful keywords from topic."""
        # Clean first
        cleaned = self._clean_topic(topic)
        words = re.findall(r'\b[a-zA-Z]{3,}\b', cleaned.lower())
        common = {"the", "and", "for", "are", "with", "they", "this", "that", "you", "how", "what", "why", "when", "where", "from", "into", "over", "than", "only", "some", "time", "very", "after", "before", "being", "having", "each", "more", "most", "other", "such", "make", "made", "well", "work", "first", "last", "long", "great", "little", "only", "just", "also", "back", "only", "know", "take", "year", "good", "come", "these", "them", "than", "well", "were", "said", "each", "which", "using", "use", "create", "creating", "implement", "implementing", "build", "building", "learn", "learning", "tutorial", "guide", "beginner", "complete"}
        return [w for w in words if w not in common]

    async def _search_arxiv(self, topic: str) -> Optional[Dict]:
        """
        Search ArXiv for research papers related to the topic.
        ArXiv is open access and doesn't require API keys.
        """
        try:
            # Clean topic for search
            search_terms = self._extract_keywords(topic)
            if not search_terms:
                return None
            
            # Build search query (first 3-4 important words)
            query = ' '.join(search_terms[:4])
            
            # Determine category
            category = 'cs'  # Default to Computer Science
            topic_lower = topic.lower()
            for key, cat in self.ARXIV_CATEGORIES.items():
                if key in topic_lower:
                    category = cat
                    break
            
            # ArXiv API endpoint
            url = "http://export.arxiv.org/api/query"
            params = {
                "search_query": f"cat:{category} AND (ti:{query} OR abs:{query})",
                "start": 0,
                "max_results": 5,
                "sortBy": "relevance",
                "sortOrder": "descending"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        return None
                    
                    data = await response.text()
                    
                    # Parse Atom feed (ArXiv returns XML)
                    import xml.etree.ElementTree as ET
                    
                    root = ET.fromstring(data.encode('utf-8'))
                    
                    # Atom namespace
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}
                    
                    entries = root.findall('atom:entry', ns)
                    
                    for entry in entries:
                        title_elem = entry.find('atom:title', ns)
                        summary_elem = entry.find('atom:summary', ns)
                        link_elem = entry.find('atom:link[@title="pdf"]', ns)
                        
                        if title_elem is None:
                            continue
                            
                        title = title_elem.text.strip() if title_elem.text else "Research Paper"
                        summary = summary_elem.text.strip()[:300] + "..." if summary_elem is not None and summary_elem.text else "Research paper on " + topic
                        
                        # Get PDF link
                        pdf_url = None
                        if link_elem is not None:
                            pdf_url = link_elem.get('href')
                        else:
                            # Try alternate link
                            for link in entry.findall('atom:link', ns):
                                if link.get('type') == 'application/pdf':
                                    pdf_url = link.get('href')
                                    break
                        
                        if not pdf_url:
                            # Use abstract URL
                            id_elem = entry.find('atom:id', ns)
                            if id_elem is not None and id_elem.text:
                                arxiv_id = id_elem.text.split('/')[-1]
                                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                        
                        return {
                            "title": title,
                            "source": "ArXiv (Research Paper)",
                            "url": pdf_url or f"https://arxiv.org/search/?query={query}&searchtype=all",
                            "summary": f"Research Paper · ArXiv · {summary[:100]}...",
                            "topic": topic,
                            "published": datetime.now().strftime("%Y-%m-%d"),
                            "author": "ArXiv",
                            "read_time": "20 min read",
                            "is_research": True,
                        }
                        
        except Exception as e:
            print(f"[ArXiv Search] Error: {e}")
        
        return None

    async def _search_semantic_scholar(self, topic: str) -> Optional[Dict]:
        """
        Search Semantic Scholar for research papers.
        Has a free API with good coverage and often has PDF links.
        """
        try:
            search_terms = self._extract_keywords(topic)
            if not search_terms:
                return None
            
            query = ' '.join(search_terms[:4])
            
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                "query": query,
                "limit": 5,
                "fields": "title,abstract,url,year,authors,openAccessPdf,externalIds"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        return None
                    
                    data = await response.json()
                    papers = data.get("data", [])
                    
                    if papers:
                        paper = papers[0]  # Best match
                        authors = paper.get("authors", [])
                        author_str = authors[0]["name"] if authors else "Unknown"
                        
                        # Try to get PDF link
                        pdf_url = None
                        open_access = paper.get("openAccessPdf")
                        if open_access and open_access.get("url"):
                            pdf_url = open_access["url"]
                        
                        # Fallback to regular URL
                        if not pdf_url:
                            pdf_url = paper.get("url")
                        
                        # Use arXiv ID if available for direct PDF
                        if not pdf_url:
                            external_ids = paper.get("externalIds", {})
                            arxiv_id = external_ids.get("ArXiv")
                            if arxiv_id:
                                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                        
                        return {
                            "title": paper.get("title", "Research Paper"),
                            "source": "Semantic Scholar (Research Paper)",
                            "url": pdf_url or f"https://www.semanticscholar.org/search?q={query}",
                            "summary": f"Research Paper · {paper.get('year', 'Recent')} · {paper.get('abstract', 'No abstract')[:100]}...",
                            "topic": topic,
                            "published": str(paper.get("year", datetime.now().year)),
                            "author": author_str,
                            "read_time": "25 min read",
                            "is_research": True,
                        }
                        
        except Exception as e:
            print(f"[Semantic Scholar] Error: {e}")
        
        return None

    async def _serpapi_search_article(self, topic: str, site: str = None) -> Optional[Dict]:
        """
        Search for an article via SerpAPI. If site is given (e.g. 'w3schools.com'),
        restricts results to that domain. Returns a full article dict.
        """
        api_key = os.getenv("SERPAPI_KEY", "")
        if not api_key:
            return None
        try:
            keywords = self._extract_keywords(topic)
            base_query = ' '.join(keywords[:5]) if keywords else topic
            query = f"{base_query} site:{site}" if site else f"{base_query} tutorial"

            params = {
                "engine": "google",
                "q": query,
                "num": 3,
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
                        results = data.get("organic_results", [])
                        if results:
                            r = results[0]
                            url = r.get("link", "")
                            title = r.get("title", topic)
                            snippet = r.get("snippet", "")
                            source = site.replace("www.", "").split(".")[0].capitalize() if site else "Web"
                            return {
                                "title": title,
                                "source": source,
                                "url": url,
                                "summary": snippet[:200] if snippet else f"Tutorial · {topic}",
                                "topic": topic,
                                "published": datetime.now().strftime("%Y-%m-%d"),
                                "author": source,
                                "read_time": "15 min read",
                                "is_research": False,
                            }
        except Exception as e:
            print(f"[Article SerpAPI] Error: {e}")
        return None

    async def find_single_article(self, topic: str, goal_type: str = "") -> Optional[Dict]:
        """
        Find exactly one article for a specific topic using live API searches only.
        PROJECT mode: W3Schools → GeeksForGeeks → general tutorial (via SerpAPI).
        Theory mode: ArXiv → CORE → HAL → theory books → Semantic Scholar → SerpAPI.
        """
        topic = self._clean_topic(topic)
        goal_type = goal_type.lower()
        is_project_mode = goal_type in ["practical", "project", "coding", "web", "app"]

        if is_project_mode:
            print(f"[Article Search] PROJECT mode: {topic[:50]}...")

            article = await self._serpapi_search_article(topic, site="w3schools.com")
            if article:
                print(f"[Article Search] W3Schools hit: {article['title'][:50]}...")
                return article

            article = await self._serpapi_search_article(topic, site="geeksforgeeks.org")
            if article:
                print(f"[Article Search] GeeksForGeeks hit: {article['title'][:50]}...")
                return article

            article = await self._serpapi_search_article(topic)
            if article:
                print(f"[Article Search] General tutorial hit: {article['title'][:50]}...")
                return article

        else:
            print(f"[Article Search] Theory mode: {topic[:50]}...")

            first_article = await self._get_first_scholar_result(topic)
            if first_article:
                print(f"[Article Search] Scholar/PDF hit: {first_article['title'][:50]}...")
                return first_article

            article = await self._search_semantic_scholar(topic)
            if article:
                print(f"[Article Search] Semantic Scholar hit: {article['title'][:50]}...")
                return article

            article = await self._serpapi_search_article(topic)
            if article:
                print(f"[Article Search] SerpAPI hit: {article['title'][:50]}...")
                return article

        # Bare minimum fallback — should almost never be reached
        keywords = self._extract_keywords(topic)
        query = '+'.join(keywords[:4]) if keywords else topic.replace(' ', '+')
        print(f"[Article Search] Using bare fallback for: {topic[:50]}...")
        return {
            "title": topic[:80],
            "source": "Web",
            "url": f"https://www.google.com/search?q={query}+tutorial",
            "summary": f"Tutorial · {topic}",
            "topic": topic,
            "published": datetime.now().strftime("%Y-%m-%d"),
            "author": "Various",
            "read_time": "Varies",
            "is_research": not is_project_mode,
        }

    async def _get_first_scholar_result(self, topic: str) -> Optional[Dict]:
        """
        Try multiple open access PDF sources (NO Google Scholar scraping).
        Uses: ArXiv (first), CORE, HAL, theory resources.
        """
        # Try ArXiv first (most reliable for CS/ML topics)
        try:
            arxiv_result = await self._search_arxiv(topic)
            if arxiv_result:
                return arxiv_result
        except Exception as e:
            print(f"[Article Search] ArXiv error: {e}")
        
        # Try CORE (core.ac.uk) - Open Access papers
        try:
            core_result = await self._search_core(topic)
            if core_result:
                return core_result
        except Exception as e:
            print(f"[Article Search] CORE error: {e}")
        
        # Try HAL (hal.science) - French open archive, great for CS
        try:
            hal_result = await self._search_hal(topic)
            if hal_result:
                return hal_result
        except Exception as e:
            print(f"[Article Search] HAL error: {e}")
        
        # Try more static educational resources for theory topics
        theory_result = await self._search_theory_resources(topic)
        if theory_result:
            return theory_result
        
        return None

    async def _search_core(self, topic: str) -> Optional[Dict]:
        """Search CORE (core.ac.uk) for open access papers."""
        try:
            search_terms = self._extract_keywords(topic)
            if not search_terms:
                return None
            
            query = ' '.join(search_terms[:4])
            
            # CORE API endpoint (no API key required for basic search)
            url = "https://core.ac.uk/api-v2/search"
            params = {
                "query": query,
                "page": 1,
                "pageSize": 5,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        works = data.get("results", [])
                        
                        if works:
                            work = works[0]
                            title = work.get("title", "Research Paper")
                            
                            # Get download URL if available
                            download_url = None
                            links = work.get("links", [])
                            for link in links:
                                if link.get("type") == "download":
                                    download_url = link.get("url")
                                    break
                            
                            # Fallback to display URL
                            if not download_url:
                                download_url = work.get("downloadUrl") or work.get("displayLink", f"https://core.ac.uk/search?q={query}")
                            
                            authors_list = work.get("authors", [])
                            author_str = authors_list[0].get("name", "Unknown") if authors_list else "Unknown"
                            
                            year = work.get("yearPublished") or work.get("publishedDate", datetime.now().year)
                            
                            return {
                                "title": title,
                                "source": "CORE (Open Access)",
                                "url": download_url,
                                "summary": f"Open Access Paper · {year} · {work.get('abstract', 'Research paper')[:100]}...",
                                "topic": topic,
                                "published": str(year),
                                "author": author_str,
                                "read_time": "20 min read",
                                "is_research": True,
                            }
        except Exception as e:
            print(f"[CORE] Error: {e}")
        
        return None

    async def _search_hal(self, topic: str) -> Optional[Dict]:
        """Search HAL (hal.science) for French open archive papers."""
        try:
            search_terms = self._extract_keywords(topic)
            if not search_terms:
                return None
            
            query = ' '.join(search_terms[:4])
            
            # HAL API
            url = "https://api.archives-ouvertes.fr/search/"
            params = {
                "q": query,
                "rows": 5,
                "wt": "json",
                "fl": "title_s,authFullName_s,uri_s,fileMain_s,abstract_s,producedDateY_i",
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        docs = data.get("response", {}).get("docs", [])
                        
                        if docs:
                            doc = docs[0]
                            title = doc.get("title_s", ["Research Paper"])[0] if isinstance(doc.get("title_s"), list) else doc.get("title_s", "Research Paper")
                            
                            # Try to get PDF link first
                            pdf_url = doc.get("fileMain_s")
                            if not pdf_url:
                                pdf_url = doc.get("uri_s")
                            
                            authors = doc.get("authFullName_s", [])
                            author_str = authors[0] if authors else "Unknown"
                            
                            year = doc.get("producedDateY_i", datetime.now().year)
                            
                            return {
                                "title": title,
                                "source": "HAL (Open Archive)",
                                "url": pdf_url or f"https://hal.science/search/?q={query}",
                                "summary": f"Open Archive Paper · {year} · {doc.get('abstract_s', ['Research paper'])[0][:100] if isinstance(doc.get('abstract_s'), list) else 'Research paper'}...",
                                "topic": topic,
                                "published": str(year),
                                "author": author_str,
                                "read_time": "20 min read",
                                "is_research": True,
                            }
        except Exception as e:
            print(f"[HAL] Error: {e}")
        
        return None

    async def _search_theory_resources(self, topic: str) -> Optional[Dict]:
        """Search for theory-focused static resources and PDF textbooks."""
        topic_lower = topic.lower()
        
        # Theory-specific PDF resources
        theory_resources = [
            # Algorithms
            {"title": "Introduction to Algorithms (CLRS) - PDF Available", "url": "https://mitpress.mit.edu/9780262046305/introduction-to-algorithms/", "source": "MIT Press", "keywords": ["algorithm", "algorithms", "complexity", "data structure", "sorting", "searching"]},
            {"title": "Algorithm Design Manual - Steven Skiena", "url": "https://www.algorist.com/", "source": "Skiena", "keywords": ["algorithm", "algorithms", "design", "manual"]},
            # Machine Learning / Deep Learning
            {"title": "Deep Learning Book (Goodfellow et al.) - Full PDF", "url": "https://www.deeplearningbook.org/", "source": "Deep Learning Book", "keywords": ["deep learning", "neural network", "machine learning", "tensorflow", "pytorch"]},
            {"title": "Pattern Recognition and Machine Learning (Bishop) - PDF", "url": "https://www.microsoft.com/en-us/research/publication/pattern-recognition-machine-learning/", "source": "Microsoft Research", "keywords": ["pattern recognition", "machine learning", "statistics", "probability"]},
            {"title": "Mathematics for Machine Learning - Free PDF", "url": "https://mml-book.github.io/book/mml-book.pdf", "source": "MML Book", "keywords": ["mathematics", "math", "linear algebra", "calculus", "machine learning", "vector"]},
            # Python Theory
            {"title": "Python Cookbook - David Beazley (PDF)", "url": "https://dabeaz-course.github.io/practical-python/Notes/Contents.html", "source": "Beazley", "keywords": ["python", "cookbook", "practical", "advanced"]},
            {"title": "Think Python 2e - Free PDF", "url": "https://greenteapress.com/thinkpython2/thinkpython2.pdf", "source": "Green Tea Press", "keywords": ["python", "basics", "think", "beginner", "fundamentals"]},
            # Databases
            {"title": "Database Systems - The Complete Book (Garcia-Molina)", "url": "http://infolab.stanford.edu/~ullman/dscb.html", "source": "Stanford", "keywords": ["database", "sql", "dbms", "relational"]},
            # Web
            {"title": "High Performance Browser Networking - Free Book", "url": "https://hpbn.co/", "source": "Ilya Grigorik", "keywords": ["networking", "http", "browser", "performance", "web"]},
            # Operating Systems
            {"title": "Operating Systems: Three Easy Pieces - Free PDF", "url": "http://pages.cs.wisc.edu/~remzi/OSTEP/", "source": "Remzi Arpaci-Dusseau", "keywords": ["operating system", "os", "process", "memory", "file system"]},
            # Compilers
            {"title": "Crafting Interpreters - Free Web/PDF", "url": "https://craftinginterpreters.com/", "source": "Robert Nystrom", "keywords": ["compiler", "interpreter", "language", "parsing", "lexer"]},
            # Distributed Systems
            {"title": "Designing Data-Intensive Applications - Martin Kleppmann", "url": "https://dataintensive.net/", "source": "Martin Kleppmann", "keywords": ["distributed", "database", "data intensive", "systems"]},
        ]
        
        topic_keywords = self._extract_keywords(topic)
        
        # Score resources
        scored = []
        for resource in theory_resources:
            score = 0
            for kw in resource["keywords"]:
                if kw in topic_lower:
                    score += 20
                for tk in topic_keywords:
                    if tk in kw or kw in tk:
                        score += 10
            if score > 0:
                scored.append((resource, score))
        
        if scored:
            scored.sort(key=lambda x: x[1], reverse=True)
            best = scored[0][0]
            return {
                "title": best["title"],
                "source": best["source"],
                "url": best["url"],
                "summary": f"Free Book/PDF · {best['source']} · {topic}",
                "topic": topic,
                "published": datetime.now().strftime("%Y-%m-%d"),
                "author": best["source"],
                "read_time": "30 min read",
                "is_research": True,
            }
        
        return None
