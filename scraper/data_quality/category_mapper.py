from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path

from .models import (
    MappedCategory,
    ProductCategory,
    BaseProduct,
    BaseArticle,
    BaseListing,
)


@dataclass
class CategoryConfig:
    default_category: ProductCategory = ProductCategory.OTHER
    confidence_threshold: float = 0.5
    use_fuzzy_matching: bool = True
    fuzzy_threshold: float = 0.8
    custom_taxonomy: Optional[Dict[str, List[str]]] = None
    taxonomy_file: Optional[str] = None


class CategoryMapper:
    def __init__(self, config: Optional[CategoryConfig] = None):
        self.config = config or CategoryConfig()
        self._category_keywords: Dict[ProductCategory, List[str]] = self._build_keywords()
        self._category_patterns: Dict[ProductCategory, List[re.Pattern]] = self._build_patterns()
        self._custom_taxonomy: Dict[str, List[str]] = self.config.custom_taxonomy or {}
        
        if self.config.taxonomy_file:
            self._load_taxonomy(self.config.taxonomy_file)
    
    def _build_keywords(self) -> Dict[ProductCategory, List[str]]:
        """Build keyword mapping for each category."""
        return {
            ProductCategory.ELECTRONICS: [
                "electronic", "electronic", "gadget", "device", "tech", "digital",
                "smart", "wireless", "bluetooth", "wifi", "usb", "hdmi",
            ],
            ProductCategory.COMPUTERS: [
                "laptop", "notebook", "desktop", "pc", "computer", "macbook",
                "chromebook", "ultrabook", "workstation", "server", "motherboard",
                "cpu", "processor", "gpu", "graphics card", "ram", "memory",
                "ssd", "hdd", "storage", "monitor", "display", "keyboard",
                "mouse", "trackpad", "webcam", "microphone",
            ],
            ProductCategory.PHONES: [
                "phone", "smartphone", "iphone", "android", "mobile", "cellphone",
                "handset", "5g", "dual sim", "unlocked", "carrier",
            ],
            ProductCategory.AUDIO: [
                "headphone", "headset", "earphone", "earbud", "speaker", "soundbar",
                "microphone", "mic", "audio", "sound", "music", "bluetooth speaker",
                "wireless earbuds", "noise cancelling", "anc",
            ],
            ProductCategory.CAMERAS: [
                "camera", "dslr", "mirrorless", "point and shoot", "action camera",
                "lens", "zoom", "megapixel", "4k", "video camera", "camcorder",
                "gopro", "drone camera", "webcam",
            ],
            ProductCategory.HOME_APPLIANCES: [
                "refrigerator", "fridge", "freezer", "oven", "stove", "range",
                "microwave", "dishwasher", "washer", "dryer", "laundry",
                "vacuum", "roomba", "air conditioner", "heater", "fan",
                "humidifier", "dehumidifier", "purifier",
            ],
            ProductCategory.KITCHEN: [
                "blender", "mixer", "food processor", "toaster", "coffee maker",
                "espresso", "kettle", "cookware", "pan", "pot", "knife",
                "cutting board", "utensil", "bakeware", "slow cooker",
                "pressure cooker", "air fryer", "instant pot",
            ],
            ProductCategory.FURNITURE: [
                "sofa", "couch", "chair", "table", "desk", "bed", "mattress",
                "dresser", "wardrobe", "bookshelf", "shelf", "cabinet",
                "ottoman", "recliner", "sectional", "loveseat", "bench",
            ],
            ProductCategory.CLOTHING: [
                "shirt", "t-shirt", "top", "blouse", "sweater", "hoodie", "jacket",
                "coat", "pants", "jeans", "shorts", "skirt", "dress", "suit",
                "sweatshirt", "cardigan", "vest", "leggings", "underwear",
                "socks", "swimwear", "activewear", "outerwear",
            ],
            ProductCategory.SHOES: [
                "shoe", "sneaker", "boot", "sandal", "loafer", "heel", "flat",
                "running shoe", "athletic", "trainer", "cleat", "slipper",
                "clog", "moccasin", "oxford", "derby", "brogue",
            ],
            ProductCategory.ACCESSORIES: [
                "watch", "watch band", "strap", "bracelet", "necklace", "ring",
                "earring", "jewelry", "bag", "backpack", "purse", "wallet",
                "belt", "hat", "cap", "scarf", "glove", "sunglasses",
                "glasses", "phone case", "screen protector",
            ],
            ProductCategory.BEAUTY: [
                "makeup", "cosmetic", "lipstick", "foundation", "concealer",
                "mascara", "eyeliner", "eyeshadow", "blush", "bronzer",
                "highlighter", "powder", "primer", "setting spray",
                "skincare", "moisturizer", "serum", "cleanser", "toner",
                "sunscreen", "spf", "anti-aging", "retinol", "vitamin c",
                "haircare", "shampoo", "conditioner", "styling", "hair oil",
                "perfume", "fragrance", "cologne", "body wash", "lotion",
            ],
            ProductCategory.HEALTH: [
                "vitamin", "supplement", "protein", "probiotic", "omega",
                "multivitamin", "calcium", "magnesium", "zinc", "iron",
                "cbd", "hemp", "essential oil", "diffuser", "first aid",
                "bandage", "thermometer", "blood pressure", "glucose",
                "fitness tracker", "scale", "massager",
            ],
            ProductCategory.SPORTS: [
                "fitness", "exercise", "workout", "gym", "weight", "dumbbell",
                "kettlebell", "resistance band", "yoga mat", "treadmill",
                "elliptical", "bike", "cycle", "running", "swimming",
                "tennis", "golf", "basketball", "football", "soccer",
                "baseball", "hockey", "ski", "snowboard", "climbing",
            ],
            ProductCategory.OUTDOORS: [
                "camping", "tent", "sleeping bag", "backpack", "hiking",
                "trekking", "outdoor", "lantern", "flashlight", "cooler",
                "grill", "bbq", "fishing", "kayak", "canoe", "binoculars",
                "compass", "gps", "survival", "first aid",
            ],
            ProductCategory.TOYS: [
                "toy", "game", "puzzle", "lego", "building block", "action figure",
                "doll", "plush", "stuffed animal", "board game", "card game",
                "rc car", "drone", "robot", "educational", "stem", "craft",
            ],
            ProductCategory.GAMES: [
                "video game", "console", "playstation", "xbox", "nintendo",
                "switch", "pc game", "steam", "dlc", "controller", "headset",
                "gaming chair", "gaming mouse", "gaming keyboard", "monitor",
            ],
            ProductCategory.BOOKS: [
                "book", "novel", "textbook", "ebook", "audiobook", "kindle",
                "paperback", "hardcover", "magazine", "comic", "manga",
                "guide", "manual", "reference", "dictionary", "encyclopedia",
            ],
            ProductCategory.AUTOMOTIVE: [
                "car", "auto", "vehicle", "truck", "suv", "motorcycle",
                "tire", "wheel", "brake", "battery", "oil", "filter",
                "spark plug", "windshield", "mirror", "seat cover",
                "floor mat", "gps", "dash cam", "car charger",
            ],
            ProductCategory.INDUSTRIAL: [
                "industrial", "manufacturing", "machinery", "tool", "power tool",
                "drill", "saw", "sander", "welder", "compressor", "generator",
                "hydraulic", "pneumatic", "bearing", "motor", "pump",
                "valve", "pipe", "fitting", "fastener", "safety equipment",
            ],
        }
    
    def _build_patterns(self) -> Dict[ProductCategory, List[re.Pattern]]:
        """Build regex patterns for each category."""
        patterns = {}
        for category, keywords in self._category_keywords.items():
            patterns[category] = [
                re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                for kw in keywords
            ]
        return patterns
    
    def _load_taxonomy(self, filepath: str):
        """Load custom taxonomy from JSON file."""
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                self._custom_taxonomy = data.get("taxonomy", {})
        except Exception:
            pass
    
    def map_category(
        self,
        text: str,
        source_category: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MappedCategory:
        """Map text to a product category."""
        scores: Dict[ProductCategory, float] = {}
        
        # Score based on keyword matches
        for category, patterns in self._category_patterns.items():
            score = 0
            matched = []
            for pattern in patterns:
                matches = pattern.findall(text.lower())
                if matches:
                    score += len(matches) * 0.1
                    matched.extend(matches)
            if score > 0:
                scores[category] = min(score, 1.0)
        
        # Boost from source category
        if source_category:
            source_lower = source_category.lower()
            for category in ProductCategory:
                if category.value in source_lower or source_lower in category.value:
                    scores[category] = scores.get(category, 0) + 0.3
        
        # Boost from metadata
        if metadata:
            for key, value in metadata.items():
                if isinstance(value, str):
                    text_with_meta = text + " " + value
                    # Re-score with metadata
                    for category, patterns in self._category_patterns.items():
                        for pattern in patterns:
                            if pattern.search(value.lower()):
                                scores[category] = scores.get(category, 0) + 0.15
        
        # Find best match
        if scores:
            best_category = max(scores, key=scores.get)
            confidence = min(scores[best_category], 1.0)
        else:
            best_category = self.config.default_category
            confidence = 0.1
        
        # Get matched keywords
        matched_keywords = []
        if scores:
            best_patterns = self._category_patterns.get(best_category, [])
            for pattern in best_patterns:
                matches = pattern.findall(text.lower())
                matched_keywords.extend(matches)
        
        # Build taxonomy path
        taxonomy_path = [best_category.value]
        if best_category in self._custom_taxonomy:
            taxonomy_path = self._custom_taxonomy[best_category] + taxonomy_path
        
        return MappedCategory(
            original=source_category or "",
            mapped=best_category,
            confidence=confidence,
            matched_keywords=list(set(matched_keywords)),
            taxonomy_path=taxonomy_path,
        )
    
    def map_product(self, product: BaseProduct) -> MappedCategory:
        """Map a product to a category using all available fields."""
        # Combine all text fields
        text_parts = [
            product.name,
            product.brand,
            product.model,
            product.description,
            product.category.value,
            " ".join(product.tags),
        ]
        text = " ".join(filter(None, text_parts))
        
        metadata = {
            "brand": product.brand,
            "category": product.category.value,
        }
        
        return self.map_category(text, product.category.value, metadata)
    
    def map_article(self, article: BaseArticle) -> MappedCategory:
        """Map an article to a category."""
        text_parts = [
            article.title,
            article.subtitle,
            article.content,
            article.category,
            " ".join(article.tags),
        ]
        text = " ".join(filter(None, text_parts))
        
        return self.map_category(text, article.category)
    
    def map_listing(self, listing: BaseListing) -> MappedCategory:
        """Map a listing to a category."""
        text_parts = [
            listing.title,
            listing.description,
            listing.category,
            listing.subcategory,
        ]
        text = " ".join(filter(None, text_parts))
        
        return self.map_category(text, listing.category)
    
    def get_taxonomy_tree(self) -> Dict[str, List[str]]:
        """Get the full category taxonomy."""
        return {cat.value: [] for cat in ProductCategory}
    
    def add_custom_mapping(self, category: ProductCategory, keywords: List[str]):
        """Add custom keywords for a category."""
        self._category_keywords[category].extend(keywords)
        self._category_patterns[category] = [
            re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
            for kw in self._category_keywords[category]
        ]
    
    def get_category_stats(self) -> Dict[str, int]:
        """Get statistics about keyword coverage."""
        return {
            cat.value: len(keywords)
            for cat, keywords in self._category_keywords.items()
        }


def map_category(text: str, config: Optional[CategoryConfig] = None) -> MappedCategory:
    """Convenience function to map text to category."""
    mapper = CategoryMapper(config)
    return mapper.map_category(text)