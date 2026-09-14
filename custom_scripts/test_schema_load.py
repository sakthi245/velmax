import json
import sys
import os

# Add schema file support
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Read schema from file
with open('custom_scripts/test_schema.json') as f:
    schema = json.load(f)

print(json.dumps(schema))