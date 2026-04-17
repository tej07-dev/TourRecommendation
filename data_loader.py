"""
Complete Database Initialization and Data Loading Script

This script:
1. Initializes the PostgreSQL database with all tables
2. Generates synthetic training data
. Loads all data into the database with proper type conversions
4. Handles enum conversions and special PostgreSQL types
5. Provides progress tracking and error handling

Usage:
    python load_initial_data.py
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List
import logging
from pathlib import Path

# Import your modules
from database.connection import init_db, get_db_context, engine
from database_models.postgres_model import (
    User, Place, Interaction, SavedPlace, PlaceImage,
    GenderEnum, CrowdLevelEnum, CompanionTypeEnum, CategoryEnum, InteractionTypeEnum,
    Base
)
from geoalchemy2.elements import WKTElement
from sqlalchemy import text

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# STEP 1: GENERATE SYNTHETIC DATA
# ============================================================================

def generate_synthetic_data(output_dir: str = '.') -> Dict:
    """
    Generate all synthetic training data
    
    This imports and runs your data generation code
    """
    logger.info("="*80)
    logger.info("GENERATING SYNTHETIC TRAINING DATA")
    logger.info("="*80)
    
    # Import your data generation module
    # Assuming it's in a file called 'generate_training_data.py'
    try:
        from scripts.data_generator import generate_all_data
        data = generate_all_data(output_dir=output_dir)
        logger.info("✓ Synthetic data generation complete")
        return data
    except ImportError:
        logger.error("Could not import generate_training_data module")
        logger.info("Make sure generate_training_data.py is in the same directory")
        sys.exit(1)


# ============================================================================
# STEP 2: DATABASE INITIALIZATION
# ============================================================================

def initialize_database():
    """Initialize database with all tables and extensions"""
    logger.info("\n" + "="*80)
    logger.info("INITIALIZING DATABASE")
    logger.info("="*80)
    
    try:
        # Enable PostGIS extension
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            conn.commit()
            logger.info("✓ PostGIS extension enabled")
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("✓ All tables created")
        
        # Verify tables exist
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """))
            tables = [row[0] for row in result]
            logger.info(f"✓ Created {len(tables)} tables: {', '.join(tables)}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


# ============================================================================
# STEP : DATA LOADING FUNCTIONS
# ============================================================================

def load_users(users_df: pd.DataFrame, db) -> int:
    """Load users into database"""
    logger.info("\n" + "-"*80)
    logger.info("Loading Users...")
    logger.info("-"*80)
    
    loaded_count = 0
    
    for idx, row in users_df.iterrows():
        try:
            # Parse preferences (handle both string and list)
            preferences = row['preferences']
            if isinstance(preferences, str):
                # Remove brackets and quotes, split by comma
                preferences = preferences.strip('[]').replace("'", "").split(',')
                preferences = [p.strip() for p in preferences if p.strip()]
            
            user = User(
                email=row['email'],
                username=row['username'],
                password_hash=row['password_hash'],
                full_name=row['full_name'],
                age=int(row['age']),
                gender=GenderEnum(row['gender']),
                budget=float(row['budget']),
                preferred_crowd_level=CrowdLevelEnum(row['preferred_crowd_level']),
                preferences=preferences,  # List of strings
                companion_type=CompanionTypeEnum(row['companion_type']),
                created_at=pd.to_datetime(row['created_at']),
                updated_at=pd.to_datetime(row['updated_at']),
                is_active=bool(row['is_active']),
                last_login=pd.to_datetime(row['last_login'])
            )
            
            db.add(user)
            loaded_count += 1
            
            if loaded_count % 50 == 0:
                db.flush()
                logger.info(f"  Loaded {loaded_count}/{len(users_df)} users...")
        
        except Exception as e:
            logger.error(f"Error loading user {idx}: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            raise
    
    db.commit()
    logger.info(f"✓ Loaded {loaded_count} users")
    return loaded_count


def load_places(places_df: pd.DataFrame, db) -> int:
    """Load places into database"""
    logger.info("\n" + "-"*80)
    logger.info("Loading Places...")
    logger.info("-"*80)
    
    loaded_count = 0
    
    for idx, row in places_df.iterrows():
        try:
            # Parse tags (handle both string and list)
            tags = row['tags']
            if isinstance(tags, str):
                tags = tags.strip('[]').replace("'", "").split(',')
                tags = [t.strip() for t in tags if t.strip()]
            
            # Create WKT element for location
            lon = float(row['longitude'])
            lat = float(row['latitude'])
            
            place = Place(
                external_id=row['external_id'],
                name=row['name'],
                category=CategoryEnum(row['category']),
                subcategory=row.get('subcategory', row['category']),
                city=row['city'],
                state=row.get('state', 'State'),
                country=row['country'],
                latitude=lat,
                longitude=lon,
                location=WKTElement(f'POINT({lon} {lat})', srid=4326),
                description=row['description'],
                tags=tags,
                avg_cost=float(row['avg_cost']),
                avg_rating=float(row['avg_rating']),
                crowd_level=CrowdLevelEnum(row['crowd_level']),
                popularity_score=float(row.get('popularity_score', 0.5)),
                created_at=pd.to_datetime(row['created_at']),
                updated_at=pd.to_datetime(row['updated_at'])
            )
            
            db.add(place)
            loaded_count += 1
            
            if loaded_count % 100 == 0:
                db.flush()
                logger.info(f"  Loaded {loaded_count}/{len(places_df)} places...")
        
        except Exception as e:
            logger.error(f"Error loading place {idx}: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            raise
    
    db.commit()
    logger.info(f"✓ Loaded {loaded_count} places")
    return loaded_count


def load_interactions(interactions_df: pd.DataFrame, db) -> int:
    """Load interactions into database"""
    logger.info("\n" + "-"*80)
    logger.info("Loading Interactions...")
    logger.info("-"*80)
    
    loaded_count = 0
    
    # Batch insert for better performance
    batch_size = 1000
    interactions_batch = []
    
    for idx, row in interactions_df.iterrows():
        try:
            interaction = Interaction(
                user_id=int(row['user_id']),
                place_id=int(row['place_id']),
                interaction_type=InteractionTypeEnum(row['interaction_type']),
                timestamp=pd.to_datetime(row['timestamp']),
                 interaction_context={}  # Empty metadata for now
            )
            
            interactions_batch.append(interaction)
            loaded_count += 1
            
            # Batch insert
            if len(interactions_batch) >= batch_size:
                db.bulk_save_objects(interactions_batch)
                db.flush()
                logger.info(f"  Loaded {loaded_count}/{len(interactions_df)} interactions...")
                interactions_batch = []
        
        except Exception as e:
            logger.error(f"Error loading interaction {idx}: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            raise
    
    # Insert remaining batch
    if interactions_batch:
        db.bulk_save_objects(interactions_batch)
    
    db.commit()
    logger.info(f"✓ Loaded {loaded_count} interactions")
    return loaded_count


def load_saved_places(saved_places_df: pd.DataFrame, db) -> int:
    """Load saved places into database"""
    logger.info("\n" + "-"*80)
    logger.info("Loading Saved Places...")
    logger.info("-"*80)
    
    loaded_count = 0
    
    for idx, row in saved_places_df.iterrows():
        try:
            saved_place = SavedPlace(
                user_id=int(row['user_id']),
                place_id=int(row['place_id']),
                saved_at=pd.to_datetime(row['saved_at']),
                notes=row.get('notes', None)
            )
            
            db.add(saved_place)
            loaded_count += 1
            
            if loaded_count % 100 == 0:
                db.flush()
                logger.info(f"  Loaded {loaded_count}/{len(saved_places_df)} saved places...")
        
        except Exception as e:
            logger.error(f"Error loading saved place {idx}: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            raise
    
    db.commit()
    logger.info(f"✓ Loaded {loaded_count} saved places")
    return loaded_count


# ============================================================================
# STEP 4: VERIFICATION
# ============================================================================

def verify_data_loaded(db) -> Dict:
    """Verify all data was loaded correctly"""
    logger.info("\n" + "="*80)
    logger.info("VERIFYING DATA LOAD")
    logger.info("="*80)
    
    stats = {}
    
    try:
        # Count records
        stats['users'] = db.query(User).count()
        stats['places'] = db.query(Place).count()
        stats['interactions'] = db.query(Interaction).count()
        stats['saved_places'] = db.query(SavedPlace).count()
        
        logger.info(f"\nDatabase Statistics:")
        logger.info(f"  Users: {stats['users']}")
        logger.info(f"  Places: {stats['places']}")
        logger.info(f"  Interactions: {stats['interactions']}")
        logger.info(f"  Saved Places: {stats['saved_places']}")
        
        # Sample queries to verify data integrity
        logger.info(f"\nData Integrity Checks:")
        
        # Check if all users have valid enums
        invalid_users = db.query(User).filter(User.gender == None).count()
        logger.info(f"  ✓ Users with valid gender enum: {stats['users'] - invalid_users}/{stats['users']}")
        
        # Check if all places have valid locations
        places_with_location = db.query(Place).filter(Place.location != None).count()
        logger.info(f"  ✓ Places with valid location: {places_with_location}/{stats['places']}")
        
        # Check if all interactions link to valid users and places
        valid_interactions = db.execute(text("""
            SELECT COUNT(*) 
            FROM interactions i
            INNER JOIN users u ON i.user_id = u.user_id
            INNER JOIN places p ON i.place_id = p.place_id
        """)).scalar()
        logger.info(f"  ✓ Valid interactions (with existing users/places): {valid_interactions}/{stats['interactions']}")
        
        # Distribution checks
        logger.info(f"\nData Distribution:")
        
        # Interaction types
        interaction_types = db.execute(text("""
            SELECT interaction_type, COUNT(*) as count
            FROM interactions
            GROUP BY interaction_type
            ORDER BY count DESC
        """)).fetchall()
        
        logger.info(f"  Interaction Types:")
        for itype, count in interaction_types:
            logger.info(f"    - {itype}: {count}")
        
        # Category distribution
        category_dist = db.execute(text("""
            SELECT category, COUNT(*) as count
            FROM places
            GROUP BY category
            ORDER BY count DESC
        """)).fetchall()
        
        logger.info(f"  Place Categories:")
        for cat, count in category_dist[:5]:  # Top 5
            logger.info(f"    - {cat}: {count}")
        
        return stats
        
    except Exception as e:
        logger.error(f"Error during verification: {e}")
        raise


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution flow"""
    logger.info("\n" + "="*80)
    logger.info("DATABASE INITIALIZATION AND DATA LOADING")
    logger.info("="*80)
    logger.info(f"Start time: {datetime.now()}\n")
    
    try:
        # Step 1: Generate synthetic data
        logger.info("STEP 1: Generating synthetic training data...")
        data = generate_synthetic_data(output_dir='.')
        
        users_df = data['users']
        places_df = data['places']
        interactions_df = data['interactions']
        saved_places_df = data['saved_places']
        
        logger.info("✓ Data generation complete")
        
        # Step 2: Initialize database
        logger.info("\nSTEP 2: Initializing database...")
        initialize_database()
        logger.info("✓ Database initialization complete")
        
        # Step : Load data
        logger.info("\nSTEP : Loading data into database...")
        
        with get_db_context() as db:
            # Load in order (respecting foreign keys)
            load_users(users_df, db)
            load_places(places_df, db)
            load_interactions(interactions_df, db)
            load_saved_places(saved_places_df, db)
        
        logger.info("\n✓ All data loaded successfully")
        
        # Step 4: Verify
        logger.info("\nSTEP 4: Verifying data...")
        with get_db_context() as db:
            stats = verify_data_loaded(db)
        
        # Final summary
        logger.info("\n" + "="*80)
        logger.info("DATA LOADING COMPLETE")
        logger.info("="*80)
        logger.info(f"\nSummary:")
        logger.info(f"  ✓ {stats['users']} users loaded")
        logger.info(f"  ✓ {stats['places']} places loaded")
        logger.info(f"  ✓ {stats['interactions']} interactions loaded")
        logger.info(f"  ✓ {stats['saved_places']} saved places loaded")
        logger.info(f"\nEnd time: {datetime.now()}")
        logger.info("="*80)
        
        logger.info("\n✅ SUCCESS! Database is ready for training.")
        logger.info("\nNext steps:")
        logger.info("  1. Run training script: python tasks/ml_tasks.py")
        logger.info("  2. Test recommendations: python quick_test.py")
        
        return True
        
    except Exception as e:
        logger.error("\n" + "="*80)
        logger.error("❌ ERROR DURING DATA LOADING")
        logger.error("="*80)
        logger.exception(f"Error: {e}")
        logger.error("\nPlease check the error above and fix before retrying.")
        return False


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def clear_database():
    """Clear all data from database (use with caution!)"""
    logger.warning("⚠️  WARNING: This will delete ALL data from the database!")
    response = input("Are you sure you want to continue? (yes/no): ")
    
    if response.lower() != 'yes':
        logger.info("Operation cancelled.")
        return
    
    logger.info("Dropping all tables...")
    
    try:
        Base.metadata.drop_all(bind=engine)
        logger.info("✓ All tables dropped")
        
        # Recreate tables
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Tables recreated (empty)")
        
    except Exception as e:
        logger.error(f"Error clearing database: {e}")
        raise


def check_database_status():
    """Check current database status"""
    logger.info("Checking database status...")
    
    try:
        with get_db_context() as db:
            stats = {
                'users': db.query(User).count(),
                'places': db.query(Place).count(),
                'interactions': db.query(Interaction).count(),
                'saved_places': db.query(SavedPlace).count()
            }
            
            logger.info("\nCurrent Database Status:")
            for table, count in stats.items():
                logger.info(f"  {table}: {count} records")
            
            if sum(stats.values()) == 0:
                logger.info("\n✓ Database is empty and ready for initial load")
            else:
                logger.info("\n⚠️  Database contains data")
                logger.info("   Use --clear flag to clear before loading")
            
            return stats
            
    except Exception as e:
        logger.error(f"Error checking database: {e}")
        raise


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Load initial training data into database')
    parser.add_argument('--clear', action='store_true', help='Clear existing data before loading')
    parser.add_argument('--status', action='store_true', help='Check database status only')
    
    args = parser.parse_args()
    
    if args.status:
        check_database_status()
    elif args.clear:
        clear_database()
        main()
    else:
        # Check if database has data
        try:
            with get_db_context() as db:
                existing_count = db.query(User).count() + db.query(Place).count()
                
                if existing_count > 0:
                    logger.warning(f"\n⚠️  Database already contains {existing_count} records")
                    logger.warning("Use --clear flag to clear existing data first")
                    response = input("\nContinue anyway? (yes/no): ")
                    if response.lower() != 'yes':
                        logger.info("Operation cancelled")
                        sys.exit(0)
        except:
            pass
        
        # Run main loading
        success = main()
        sys.exit(0 if success else 1)