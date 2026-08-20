import random
from typing import Optional, Dict
from pathlib import Path
import json

class ImageFetcher:
    """Fetch random high-quality images from Lorem Picsum for IGCSE picture tasks."""
    
    # Lorem Picsum API (reliable, free, no API key needed)
    BASE_URL = "https://picsum.photos"
    
    # Image themes and keywords for each topic (used as seed for random images)
    THEMES = {
        "homes": {
            "seeds": ["home", "house", "apartment", "family", "living room", "kitchen", "bedroom"],
        },
        "tourism": {
            "seeds": ["travel", "vacation", "beach", "mountain", "city", "landmark", "sightseeing"],
        },
        "school": {
            "seeds": ["school", "classroom", "students", "education", "teacher", "library", "university"],
        },
        "work": {
            "seeds": ["office", "work", "business", "meeting", "coworker", "professional", "desk"],
        }
    }
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path(__file__).parent.parent / "static" / "images" / "pictures"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "image_cache.json"
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict:
        """Load cached image URLs."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_cache(self):
        """Save cache to file."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except:
            pass
    
    def get_random_image_url(self, topic: str, width: int = 1920, height: int = 1080) -> str:
        """
        Get a random image URL for a topic from Lorem Picsum.
        
        Args:
            topic: One of 'homes', 'tourism', 'school', 'work'
            width: Image width in pixels
            height: Image height in pixels
            
        Returns:
            URL to a random image
        """
        if topic not in self.THEMES:
            raise ValueError(f"Unknown topic: {topic}. Must be one of {list(self.THEMES.keys())}")
        
        theme = self.THEMES[topic]
        seed = random.choice(theme["seeds"])
        
        # Add random number to ensure different images even with same seed
        random_suffix = random.randint(1, 1000)
        
        # Construct Lorem Picsum URL
        # Format: https://picsum.photos/{width}/{height}?random={seed}-{random_suffix}
        url = f"{self.BASE_URL}/{width}/{height}?random={seed}-{random_suffix}"
        
        return url
    
    def get_cached_image_url(self, topic: str) -> Optional[str]:
        """Get a cached image URL for a topic."""
        return self.cache.get(topic)
    
    def cache_image_url(self, topic: str, url: str):
        """Cache an image URL for a topic."""
        self.cache[topic] = url
        self._save_cache()
    
    def refresh_all_images(self) -> Dict[str, str]:
        """
        Generate new random image URLs for all topics.
        
        Returns:
            Dictionary mapping topic names to image URLs
        """
        new_urls = {}
        for topic in self.THEMES.keys():
            new_urls[topic] = self.get_random_image_url(topic)
            self.cache_image_url(topic, new_urls[topic])
        
        return new_urls
    
    def get_image_for_topic(self, topic: str, force_refresh: bool = False) -> str:
        """
        Get an image URL for a topic, using cache if available.
        
        Args:
            topic: Topic name
            force_refresh: If True, generate a new URL even if cached
            
        Returns:
            Image URL
        """
        if force_refresh or topic not in self.cache:
            url = self.get_random_image_url(topic)
            self.cache_image_url(topic, url)
            return url
        
        return self.cache[topic]

# Singleton instance
_image_fetcher = None

def get_image_fetcher() -> ImageFetcher:
    """Get the singleton ImageFetcher instance."""
    global _image_fetcher
    if _image_fetcher is None:
        _image_fetcher = ImageFetcher()
    return _image_fetcher

if __name__ == "__main__":
    # Test the image fetcher
    fetcher = get_image_fetcher()
    
    print("Fetching random images for all topics...")
    urls = fetcher.refresh_all_images()
    
    for topic, url in urls.items():
        print(f"{topic}: {url}")
    
    print("\nFetching with cache...")
    cached_url = fetcher.get_image_for_topic("homes")
    print(f"Cached homes URL: {cached_url}")
