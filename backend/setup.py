#!/usr/bin/env python3
"""
BigDream - Quick Setup Script
Automatically sets up the authentication system
"""

import os
import json
from pathlib import Path


def create_directory_structure():
    """Create all necessary directories"""
    directories = [
        "backend",
        "templates",
        "static/css",
        "static/js",
        "static/uploads/profiles",
        "data"
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"✅ Created directory: {directory}")


def initialize_database_files():
    """Initialize empty database JSON files"""
    data_dir = Path("data")
    
    database_files = {
        "users.json": {},
        "goals.json": [],
        "videos.json": [],
        "articles.json": [],
        "tokens_blacklist.json": [],
        "audit_log.json": [],
        "user_stats.json": {}
    }
    
    for filename, initial_data in database_files.items():
        filepath = data_dir / filename
        if not filepath.exists():
            with open(filepath, 'w') as f:
                json.dump(initial_data, f, indent=2)
            print(f"✅ Created database file: {filename}")
        else:
            print(f"⚠️  Database file already exists: {filename}")


def create_env_file():
    """Create .env file with default settings"""
    env_content = """# BigDream Environment Configuration
JWT_SECRET=bigdream-super-secret-key-change-in-production-IMPORTANT
JWT_EXPIRATION_HOURS=24
API_HOST=0.0.0.0
API_PORT=8000

# AI APIs
GROQ_API_KEY=your_groq_api_key_here
HUGGINGFACE_API_KEY=your_huggingface_token_here
"""
    
    env_file = Path(".env")
    if not env_file.exists():
        with open(env_file, 'w') as f:
            f.write(env_content)
        print("✅ Created .env file")
    else:
        print("⚠️  .env file already exists")


def create_first_admin():
    """Helper to create first admin user"""
    print("\n" + "="*60)
    print("CREATE FIRST ADMIN USER")
    print("="*60)
    
    create = input("Would you like to create an admin user now? (y/n): ")
    
    if create.lower() != 'y':
        print("⏩ Skipping admin creation")
        return
    
    try:
        from database_manager import DatabaseManager
        
        db = DatabaseManager(data_dir="data")
        
        name = input("Admin Name: ")
        email = input("Admin Email: ")
        password = input("Admin Password: ")
        
        user = db.create_user(
            name=name,
            email=email,
            password=password,
            role="admin"
        )
        
        print(f"\n✅ Admin user created successfully!")
        print(f"   Email: {user['email']}")
        print(f"   Role: {user['role']}")
        print(f"   User ID: {user['user_id']}")
        
    except Exception as e:
        print(f"\n❌ Error creating admin user: {e}")
        print("You can create an admin user later using the API or database manager")


def check_dependencies():
    """Check if required packages are installed"""
    print("\n" + "="*60)
    print("CHECKING DEPENDENCIES")
    print("="*60)
    
    required_packages = [
        'fastapi',
        'uvicorn',
        'bcrypt',
        'jwt',
        'python-multipart'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package if package != 'jwt' else 'PyJWT')
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - NOT INSTALLED")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n⚠️  Missing packages: {', '.join(missing_packages)}")
        print("\nInstall with:")
        print(f"pip install {' '.join(missing_packages)} --break-system-packages")
        return False
    
    print("\n✅ All dependencies installed!")
    return True


def main():
    """Main setup function"""
    print("\n" + "="*60)
    print("🚀 BigDream - SETUP SCRIPT")
    print("="*60 + "\n")
    
    # Step 1: Check dependencies
    if not check_dependencies():
        print("\n⚠️  Please install missing dependencies before continuing")
        return
    
    # Step 2: Create directory structure
    print("\n" + "="*60)
    print("CREATING DIRECTORY STRUCTURE")
    print("="*60)
    create_directory_structure()
    
    # Step 3: Initialize database files
    print("\n" + "="*60)
    print("INITIALIZING DATABASE FILES")
    print("="*60)
    initialize_database_files()
    
    # Step 4: Create .env file
    print("\n" + "="*60)
    print("CREATING ENVIRONMENT FILE")
    print("="*60)
    create_env_file()
    
    # Step 5: Create first admin (optional)
    create_first_admin()
    
    # Final instructions
    print("\n" + "="*60)
    print("✅ SETUP COMPLETE!")
    print("="*60)
    print("\nNext steps:")
    print("1. Copy all Python backend files to /backend/ directory")
    print("2. Copy all HTML files to /templates/ directory")
    print("3. Run: python backend/api_complete.py")
    print("4. Open: http://localhost:8000")
    print("\n🎯 BigDream is ready to launch!\n")


if __name__ == "__main__":
    main()
