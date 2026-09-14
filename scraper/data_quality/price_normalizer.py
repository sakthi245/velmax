from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from .models import NormalizedPrice, Currency


@dataclass
class PriceConfig:
    target_currency: Currency = Currency.USD
    exchange_rates: Dict[str, float] = field(default_factory=lambda: {
        "USD": 1.0,
        "EUR": 0.92,
        "GBP": 0.79,
        "JPY": 149.5,
        "CAD": 1.35,
        "AUD": 1.52,
        "CHF": 0.88,
        "CNY": 7.24,
        "INR": 83.1,
        "BRL": 4.95,
    })
    update_rates_online: bool = False
    rate_cache_ttl_hours: int = 24
    handle_sale_prices: bool = True
    extract_from_text: bool = True
    price_patterns: List[str] = field(default_factory=lambda: [
        r"[\$\€\£\¥\₹]\s*[\d,]+\.?\d*",
        r"[\d,]+\.?\d*\s*[\$\€\£\¥\₹]",
        r"(?:price|cost|amount)[\s:]*[\$\€\£\¥\₹]?\s*[\d,]+\.?\d*",
        r"(?:sale|discount|offer)[\s:]*[\$\€\£\¥\₹]?\s*[\d,]+\.?\d*",
    ])
    currency_symbols: Dict[str, Currency] = field(default_factory=lambda: {
        "$": Currency.USD,
        "€": Currency.EUR,
        "£": Currency.GBP,
        "¥": Currency.JPY,
        "₹": Currency.INR,
        "₩": Currency.KRW,
        "₽": Currency.RUB,
        "₺": Currency.TRY,
        "R$": Currency.BRL,
        "CA$": Currency.CAD,
        "A$": Currency.AUD,
        "CHF": Currency.CHF,
        "CN¥": Currency.CNY,
    })
    currency_codes: Dict[str, Currency] = field(default_factory=lambda: {
        "usd": Currency.USD,
        "eur": Currency.EUR,
        "gbp": Currency.GBP,
        "jpy": Currency.JPY,
        "cad": Currency.CAD,
        "aud": Currency.AUD,
        "chf": Currency.CHF,
        "cny": Currency.CNY,
        "inr": Currency.INR,
        "brl": Currency.BRL,
        "krw": Currency.KRW,
        "rub": Currency.RUB,
        "try": Currency.TRY,
    })


class PriceNormalizer:
    def __init__(self, config: Optional[PriceConfig] = None):
        self.config = config or PriceConfig()
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.config.price_patterns]
    
    def normalize(self, price_input: Union[str, Decimal, float, int, None],
                  currency_hint: Optional[str] = None) -> NormalizedPrice:
        """Normalize a price value to standard format."""
        if price_input is None:
            return NormalizedPrice(original_value="", normalized_value=Decimal("0"))
        
        original_str = str(price_input)
        result = NormalizedPrice(original_value=original_str)
        
        # Extract currency
        currency = self._extract_currency(original_str, currency_hint)
        result.currency = currency
        result.original_currency = currency.value
        
        # Extract numeric value
        value = self._extract_value(original_str)
        if value is None:
            result.normalized_value = Decimal("0")
            return result
        
        result.normalized_value = value
        
        # Convert to target currency
        if currency != self.config.target_currency:
            rate = self._get_exchange_rate(currency)
            result.exchange_rate = rate
            result.normalized_value = (value * Decimal(str(rate))).quantize(Decimal("0.01"))
            result.currency = self.config.target_currency
        else:
            result.exchange_rate = 1.0
        
        # Detect sale
        if self.config.handle_sale_prices:
            result.is_sale = self._is_sale_price(original_str)
        
        return result
    
    def normalize_multiple(self, prices: List[Union[str, Decimal, float, int]],
                           currency_hint: Optional[str] = None) -> List[NormalizedPrice]:
        """Normalize multiple price values."""
        return [self.normalize(p, currency_hint) for p in prices]
    
    def extract_prices_from_text(self, text: str) -> List[NormalizedPrice]:
        """Extract all prices from text content."""
        prices = []
        for pattern in self._compiled_patterns:
            matches = pattern.findall(text)
            for match in matches:
                normalized = self.normalize(match)
                if normalized.normalized_value > 0:
                    prices.append(normalized)
        
        # Deduplicate by value
        seen = set()
        unique = []
        for p in prices:
            key = (p.normalized_value, p.currency)
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique
    
    def _extract_currency(self, text: str, hint: Optional[str] = None) -> Currency:
        # Check hint first
        if hint:
            hint_lower = hint.lower().strip()
            if hint_lower in self.config.currency_codes:
                return self.config.currency_codes[hint_lower]
            if hint in [c.value for c in Currency]:
                return Currency(hint)
        
        # Check for currency symbols
        for symbol, currency in self.config.currency_symbols.items():
            if symbol in text:
                return currency
        
        # Check for currency codes
        for code, currency in self.config.currency_codes.items():
            if re.search(rf"\b{code}\b", text, re.IGNORECASE):
                return currency
        
        # Default
        return self.config.target_currency
    
    def _extract_value(self, text: str) -> Optional[Decimal]:
        # Remove currency symbols and text
        cleaned = re.sub(r"[^\d.,\-]", " ", text)
        
        # Handle different decimal separators
        # If comma is used as decimal separator (European format)
        if "," in cleaned and "." in cleaned:
            # Determine which is decimal separator
            last_comma = cleaned.rfind(",")
            last_dot = cleaned.rfind(".")
            if last_comma > last_dot:
                # Comma is decimal separator
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                # Dot is decimal separator
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned and cleaned.count(",") == 1 and cleaned.rfind(",") > len(cleaned) - 4:
            # Single comma near end - likely decimal separator
            cleaned = cleaned.replace(",", ".")
        else:
            # Remove commas (thousand separators)
            cleaned = cleaned.replace(",", "")
        
        # Extract first valid number
        numbers = re.findall(r"-?\d+\.?\d*", cleaned)
        if numbers:
            try:
                return Decimal(numbers[0])
            except:
                pass
        return None
    
    def _is_sale_price(self, text: str) -> bool:
        sale_indicators = [
            "sale", "discount", "offer", "deal", "special", "clearance",
            "reduced", "markdown", "promo", "coupon", "save", "off"
        ]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in sale_indicators)
    
    def _get_exchange_rate(self, from_currency: Currency) -> float:
        rates = self.config.exchange_rates
        if from_currency.value in rates:
            return rates[from_currency.value]
        return 1.0
    
    def update_exchange_rates(self, rates: Dict[str, float]):
        """Update exchange rates from external source."""
        self.config.exchange_rates.update(rates)
    
    def convert(self, amount: Decimal, from_currency: Currency, to_currency: Currency) -> Decimal:
        """Convert amount between currencies."""
        if from_currency == to_currency:
            return amount
        
        from_rate = self._get_exchange_rate(from_currency)
        to_rate = self._get_exchange_rate(to_currency)
        
        # Convert to USD first, then to target
        usd_amount = amount / Decimal(str(from_rate))
        result = usd_amount * Decimal(str(to_rate))
        return result.quantize(Decimal("0.01"))
    
    def format_price(self, price: NormalizedPrice, locale: str = "en_US") -> str:
        """Format normalized price for display."""
        symbol_map = {
            Currency.USD: "$",
            Currency.EUR: "€",
            Currency.GBP: "£",
            Currency.JPY: "¥",
            Currency.CNY: "¥",
            Currency.INR: "₹",
        }
        symbol = symbol_map.get(price.currency, price.currency.value)
        
        if locale.startswith("en"):
            return f"{symbol}{price.normalized_value:,.2f}"
        elif locale.startswith("de") or locale.startswith("fr"):
            return f"{price.normalized_value:,.2f} {symbol}".replace(",", " ").replace(".", ",")
        else:
            return f"{symbol}{price.normalized_value:,.2f}"


def parse_price_string(text: str, config: Optional[PriceConfig] = None) -> Optional[NormalizedPrice]:
    """Convenience function to parse a single price string."""
    normalizer = PriceNormalizer(config)
    return normalizer.normalize(text)


def extract_prices(text: str, config: Optional[PriceConfig] = None) -> List[NormalizedPrice]:
    """Convenience function to extract all prices from text."""
    normalizer = PriceNormalizer(config)
    return normalizer.extract_prices_from_text(text)