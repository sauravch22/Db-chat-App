#!/usr/bin/env python3
"""Update timeout to 3 minutes"""

with open('/Users/sauravchakraborty/DbChat/test_comparison_prompts.py', 'r') as f:
    content = f.read()

# Update timeout
content = content.replace('TIMEOUT = 90  # 1 min 30 sec', 'TIMEOUT = 180  # 3 minutes for reasoning mode')

with open('/Users/sauravchakraborty/DbChat/test_comparison_prompts.py', 'w') as f:
    f.write(content)

print("✓ Updated timeout to 180 seconds (3 minutes)")
