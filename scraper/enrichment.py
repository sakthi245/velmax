from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set
from datetime import datetime
from collections import defaultdict

from .utils.observability import get_logger

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


@dataclass
class EnrichmentConfig:
    steps: List[str] = field(default_factory=list)
    geo_api_key: Optional[str] = None
    entity_patterns: Dict[str, str] = field(default_factory=dict)
    
    # Category mapping settings
    category_confidence_threshold: float = 0.7
    category_ambiguous_threshold: float = 0.4
    use_ml_classifier: bool = True
    category_model_path: Optional[str] = None
    category_confidence_boost: float = 0.1


class EnrichmentPipeline:
    """Apply enrichment steps to scraped data."""

    def __init__(self, config: EnrichmentConfig):
        self.config = config
        self.logger = get_logger("enrichment")

        # Compile regex patterns
        self._email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        self._phone_pattern = re.compile(r'\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b')
        self._url_pattern = re.compile(r'https?://[^\s]+')
        self._price_pattern = re.compile(r'[\$\£\€]\s*[\d,]+\.?\d*')

        # Simple sentiment lexicon
        self._positive_words = {"good", "great", "excellent", "amazing", "love", "best", "awesome", "fantastic", "perfect", "wonderful"}
        self._negative_words = {"bad", "terrible", "awful", "hate", "worst", "poor", "disappointing", "horrible", "useless", "broken"}

        # Category keywords (rule-based)
        self._categories = {
            "electronics": ["phone", "laptop", "computer", "tablet", "camera", "headphone", "tv", "monitor", "smartphone", "gadget", "device", "electronic", "gaming", "console", "headset", "speaker", "charger", "cable", "battery", "power bank"],
            "clothing": ["shirt", "pants", "dress", "shoe", "jacket", "sweater", "jeans", "sneaker", "boot", "t-shirt", "hoodie", "coat", "blazer", "skirt", "shorts", "sock", "underwear", "swimwear", "activewear"],
            "home": ["furniture", "decor", "kitchen", "bedding", "lamp", "chair", "table", "sofa", "mattress", "pillow", "curtain", "rug", "mirror", "wall art", "vase", "candle", "storage", "organizer", "appliance"],
            "beauty": ["makeup", "skincare", "perfume", "cosmetic", "cream", "serum", "lipstick", "foundation", "mascara", "eyeliner", "moisturizer", "cleanser", "toner", "sunscreen", "hair care", "nail polish"],
            "sports": ["fitness", "exercise", "yoga", "running", "gym", "weight", "protein", "supplement", "dumbbell", "treadmill", "bike", "swim", "tennis", "basketball", "soccer", "golf", "outdoor", "camping", "hiking"],
            "books": ["book", "novel", "ebook", "author", "chapter", "page", "read", "library", "magazine", "comic", "manga", "textbook", "guide", "manual", "dictionary", "encyclopedia"],
            "automotive": ["car", "auto", "vehicle", "tire", "wheel", "brake", "engine", "oil", "filter", "battery", "spark plug", "headlight", "mirror", "seat", "dashboard", "gps", "carplay"],
            "health": ["vitamin", "supplement", "medicine", "pill", "tablet", "capsule", "syrup", "ointment", "cream", "bandage", "first aid", "thermometer", "monitor", "device"],
            "toys": ["toy", "game", "puzzle", "lego", "doll", "action figure", "board game", "card game", "video game", "console", "controller", "remote control", "drone", "robot"],
            "food": ["food", "snack", "drink", "beverage", "coffee", "tea", "wine", "beer", "chocolate", "candy", "cookie", "chip", "nut", "fruit", "vegetable", "meal", "recipe", "ingredient"],
            "jewelry": ["jewelry", "ring", "necklace", "bracelet", "earring", "watch", "pendant", "chain", "gold", "silver", "diamond", "gemstone", "pearl", "cufflink", "brooch"],
            "pet": ["pet", "dog", "cat", "food", "toy", "bed", "collar", "leash", "carrier", "grooming", "litter", "treat", "vitamin", "medicine"],
            "office": ["office", "desk", "chair", "monitor", "keyboard", "mouse", "printer", "paper", "pen", "notebook", "folder", "binder", "stapler", "scissors", "tape", "envelope"],
        }

        # ML-based category classifier
        self._ml_classifier = None
        self._category_vectorizer = None
        self._category_labels = list(self._categories.keys())
        self._init_ml_classifier()
    
    def _init_ml_classifier(self):
        """Initialize ML-based category classifier."""
        if not self.config.use_ml_classifier or not HAS_SKLEARN:
            self._ml_classifier = None
            return
        
        try:
            # Create training data from category keywords
            train_texts = []
            train_labels = []
            for category, keywords in self._categories.items():
                for kw in keywords:
                    train_texts.append(kw)
                    train_labels.append(category)
            
            # Create pipeline: TF-IDF + Logistic Regression
            self._category_vectorizer = TfidfVectorizer(
                ngram_range=(1, 2),
                max_features=5000,
                min_df=1,
                sublinear_tf=True
            )
            self._ml_classifier = Pipeline([
                ('tfidf', self._category_vectorizer),
                ('clf', LogisticRegression(
                    max_iter=1000,
                    class_weight='balanced',
                    random_state=42,
                    multi_class='multinomial',
                    solver='lbfgs'
                ))
            ])
            
            # Train the classifier
            X = self._category_vectorizer.fit_transform(train_texts)
            self._ml_classifier.fit(X, train_labels)
            
            self.logger.info(f"ML category classifier trained on {len(train_texts)} samples")
        except Exception as e:
            self.logger.warning(f"Failed to initialize ML classifier: {e}")
            self._ml_classifier = None

    def enrich(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Apply all enabled enrichment steps."""
        enriched = item.copy()

        for step in self.config.steps:
            try:
                if step == "entity":
                    enriched = self._enrich_entities(enriched)
                elif step == "category":
                    enriched = self._enrich_category(enriched)
                elif step == "sentiment":
                    enriched = self._enrich_sentiment(enriched)
                elif step == "geo":
                    enriched = self._enrich_geo(enriched)
                elif step == "price":
                    enriched = self._enrich_price(enriched)
                elif step == "timestamp":
                    enriched["_enriched_at"] = datetime.utcnow().isoformat()
            except Exception as e:
                self.logger.warning(f"Enrichment step '{step}' failed", error=str(e))

        return enriched

    def _enrich_entities(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Extract entities (emails, phones, URLs) from text fields."""
        entities = {
            "emails": [],
            "phones": [],
            "urls": [],
        }

        text_parts = []
        for v in item.values():
            if isinstance(v, str):
                text_parts.append(v)
            elif isinstance(v, list):
                for item_v in v:
                    if isinstance(item_v, str):
                        text_parts.append(item_v)

        full_text = " ".join(text_parts)

        entities["emails"] = self._email_pattern.findall(full_text)
        entities["phones"] = ["-".join(m) for m in self._phone_pattern.findall(full_text)]
        entities["urls"] = self._url_pattern.findall(full_text)

        # Deduplicate
        for key in entities:
            entities[key] = list(set(entities[key]))

        enriched = item.copy()
        enriched["_entities"] = entities
        return enriched

    def _enrich_category(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Categorize item based on text content using hybrid approach (rules + ML)."""
        text_parts = []
        for v in item.values():
            if isinstance(v, str):
                text_parts.append(v.lower())
            elif isinstance(v, list):
                for item_v in v:
                    if isinstance(item_v, str):
                        text_parts.append(item_v.lower())

        full_text = " ".join(text_parts)
        if not full_text.strip():
            return item.copy()

        # Step 1: Rule-based matching (fast, high precision)
        rule_matches = self._rule_based_category(full_text)

        # Step 2: ML-based classification for ambiguous cases
        ml_predictions = {}
        if self._ml_classifier is not None and self.config.use_ml_classifier:
            ml_predictions = self._ml_classify(full_text)

        # Step 3: Combine results with confidence scoring
        final_categories = self._combine_predictions(rule_matches, ml_predictions)

        enriched = item.copy()
        enriched["_categories"] = final_categories
        enriched["_category_confidence"] = self._get_confidence_scores(rule_matches, ml_predictions)
        return enriched

    def _rule_based_category(self, text: str) -> Dict[str, float]:
        """Rule-based category matching with confidence scores."""
        matches = {}
        text_lower = text.lower()

        for category, keywords in self._categories.items():
            score = 0.0
            matched_keywords = []
            for kw in keywords:
                if kw in text_lower:
                    # Weight by keyword length (longer = more specific)
                    score = len(kw) / 10.0
                    score = min(score, 1.0)
                    score += 0.1  # Base match score
                    score = min(score, 1.0)
                    if score > matches.get(category, 0):
                        matches[category] = score

        return matches

    def _ml_classify(self, text: str) -> Dict[str, float]:
        """ML-based category classification with confidence scores."""
        if self._ml_classifier is None or self._category_vectorizer is None:
            return {}

        try:
            X = self._category_vectorizer.transform([text])
            probabilities = self._ml_classifier.predict_proba(X)[0]

            predictions = {}
            for i, label in enumerate(self._category_labels):
                prob = float(probabilities[i])
                if prob >= self.config.category_ambiguous_threshold:
                    predictions[label] = prob

            return predictions
        except Exception as e:
            self.logger.warning(f"ML classification failed: {e}")
            return {}

    def _combine_predictions(self, rule_matches: Dict[str, float], ml_predictions: Dict[str, float]) -> List[str]:
        """Combine rule-based and ML predictions with confidence weighting."""
        combined = {}

        # Add rule-based matches with base confidence
        for cat, score in rule_matches.items():
            combined[cat] = score

        # Add ML predictions with confidence boost
        for cat, prob in ml_predictions.items():
            if cat in combined:
                # Combine scores: rule + ML with boost
                combined[cat] = min(1.0, combined[cat] + prob * self.config.category_confidence_boost)
            else:
                # Only add ML predictions above ambiguous threshold
                if prob >= self.config.category_ambiguous_threshold:
                    combined[cat] = prob

        # Filter by confidence threshold
        final_categories = [
            cat for cat, score in combined.items()
            if score >= self.config.category_confidence_threshold
        ]

        return final_categories

    def _get_confidence_scores(self, rule_matches: Dict[str, float], ml_predictions: Dict[str, float]) -> Dict[str, float]:
        """Get confidence scores for each predicted category."""
        scores = {}

        for cat, score in rule_matches.items():
            scores[cat] = {"rule": score, "ml": ml_predictions.get(cat, 0.0)}
            if cat in ml_predictions:
                scores[cat]["combined"] = min(1.0, score + ml_predictions[cat] * self.config.category_confidence_boost)
            else:
                scores[cat]["combined"] = score

        for cat, prob in ml_predictions.items():
            if cat not in scores:
                scores[cat] = {"rule": 0.0, "ml": prob, "combined": prob}

        return scores

    def _enrich_sentiment(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Basic sentiment analysis on text fields."""
        text_parts = []
        for v in item.values():
            if isinstance(v, str):
                text_parts.append(v.lower())

        full_text = " ".join(text_parts)
        words = set(re.findall(r'\b\w+\b', full_text))

        pos_count = len(words & self._positive_words)
        neg_count = len(words & self._negative_words)

        if pos_count > neg_count:
            sentiment = "positive"
        elif neg_count > pos_count:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        score = (pos_count - neg_count) / max(1, pos_count + neg_count)

        enriched = item.copy()
        enriched["_sentiment"] = {
            "label": sentiment,
            "score": round(score, 3),
            "positive_words": pos_count,
            "negative_words": neg_count,
        }
        return enriched

    def _enrich_price(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and normalize prices."""
        prices = []

        for v in item.values():
            if isinstance(v, str):
                matches = self._price_pattern.findall(v)
                for match in matches:
                    # Clean and convert
                    cleaned = re.sub(r'[\$\£\€,\s]', '', match)
                    try:
                        prices.append(float(cleaned))
                    except ValueError:
                        pass
            elif isinstance(v, (int, float)) and v > 0:
                # Heuristic: if field name suggests price
                prices.append(float(v))

        enriched = item.copy()
        if prices:
            enriched["_prices"] = {
                "raw": prices,
                "min": min(prices),
                "max": max(prices),
                "avg": sum(prices) / len(prices),
                "currency": "USD",  # Default, could detect from symbols
            }
        return enriched

    def _enrich_geo(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Extract geographic information (placeholder for API integration)."""
        # This would integrate with a geocoding API in production
        # For now, extract location-like strings
        location_keywords = ["address", "location", "city", "state", "country", "zip", "postal"]
        geo_fields = {}

        for k, v in item.items():
            if any(kw in k.lower() for kw in location_keywords):
                geo_fields[k] = v

        enriched = item.copy()
        if geo_fields:
            enriched["_geo"] = geo_fields
        return enriched