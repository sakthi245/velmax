from scraper.models import ScrapeResult
from scraper.output import write_output
import json

def test_writes_jsonl_meta_and_csv(tmp_path):
    paths = write_output(ScrapeResult([{"url": "https://e.test", "title": "E"}], "scrapy"), "https://e.test", tmp_path)
    assert set(paths) == {"jsonl", "meta", "csv"}
    assert json.loads(paths["meta"].read_text())["engine_used"] == "scrapy"
