from scraper.metrics import registry, record_scrape, set_circuit_state, set_engine_health

def test_metrics_registry():
    assert registry is not None

def test_record_scrape():
    # Should not raise
    record_scrape("test_engine", True, 100)
    record_scrape("test_engine", False, 200)

def test_circuit_state():
    set_circuit_state("test", 0)  # closed
    set_circuit_state("test", 1)  # half_open
    set_circuit_state("test", 2)  # open

def test_engine_health():
    set_engine_health("test", True)
    set_engine_health("test", False)