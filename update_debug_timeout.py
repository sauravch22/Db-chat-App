#!/usr/bin/env python3
"""Update debug script timeout"""

with open('/Users/sauravchakraborty/DbChat/debug_single_test.py', 'r') as f:
    content = f.read()

content = content.replace('timeout=90', 'timeout=180')

with open('/Users/sauravchakraborty/DbChat/debug_single_test.py', 'w') as f:
    f.write(content)

print("✓ Updated debug_single_test.py timeout to 180 seconds")
