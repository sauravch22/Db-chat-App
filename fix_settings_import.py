#!/usr/bin/env python3
"""Fix settings import in chat_service.py"""

with open('/Users/sauravchakraborty/DbChat/app/services/chat_service.py', 'r') as f:
    content = f.read()

# Fix the import
old_import = '''            # Use reasoning mode if enabled (Phase 3 enhancement)
            from app.config import settings
            use_reasoning = settings.USE_REASONING_MODE'''

new_import = '''            # Use reasoning mode if enabled (Phase 3 enhancement)
            from app.config import Settings
            settings = Settings()
            use_reasoning = settings.USE_REASONING_MODE'''

if old_import in content:
    content = content.replace(old_import, new_import)
    with open('/Users/sauravchakraborty/DbChat/app/services/chat_service.py', 'w') as f:
        f.write(content)
    print("✓ Fixed settings import in chat_service.py")
else:
    print("ERROR: Could not find import to fix")
