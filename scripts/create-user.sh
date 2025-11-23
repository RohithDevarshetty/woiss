#!/bin/bash

###
# Create a user and API key
###

if [ -z "$1" ]; then
    echo "Usage: ./scripts/create-user.sh <email> [tier]"
    echo "Example: ./scripts/create-user.sh user@example.com free"
    exit 1
fi

EMAIL=$1
TIER=${2:-free}

echo "Creating user: $EMAIL (tier: $TIER)"

# Create user and API key
docker-compose exec -T api python -c "
import sys
import json
sys.path.insert(0, '/app')

from shared.database import db_manager, User, APIKey
from shared.utils.auth import generate_api_key

email = '$EMAIL'
tier = '$TIER'

with db_manager.session_scope() as db:
    # Check if user exists
    user = db.query(User).filter(User.email == email).first()

    if not user:
        # Create user
        user = User(email=email, tier=tier)
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f'✅ User created: {user.id}')
    else:
        print(f'⚠️  User already exists: {user.id}')

    # Generate API key
    api_key, key_hash = generate_api_key()

    new_key = APIKey(
        user_id=user.id,
        key_hash=key_hash,
        name='Default Key'
    )
    db.add(new_key)
    db.commit()

    print('')
    print('=' * 60)
    print('API Key (save this - it won\\'t be shown again):')
    print(api_key)
    print('=' * 60)
    print('')
    print('User ID:', str(user.id))
    print('Email:', email)
    print('Tier:', tier)
"

echo ""
echo "Use this API key in the web client or API requests."
