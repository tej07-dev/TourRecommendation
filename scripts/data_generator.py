"""
Synthetic Training Data Generator for Place Recommendation System

This script generates realistic, diverse training data that:
1. Covers multiple user profiles and preferences
2. Creates geographically distributed places with realistic metrics
3. Generates diverse interaction patterns (not biased to one outcome)
4. Includes data variation to prevent data-only model failures
5. Maintains realistic distributions and relationships
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS - CONFIGURABLE PARAMETERS
# ============================================================================

# Geographic data for realistic Indian places
CITIES = {
    'Mumbai': {'lat': 19.0760, 'lon': 72.8777, 'places': 80},
    'Delhi': {'lat': 28.7041, 'lon': 77.1025, 'places': 75},
    'Bangalore': {'lat': 12.9716, 'lon': 77.5946, 'places': 70},
    'Kolkata': {'lat': 22.5726, 'lon': 88.3639, 'places': 65},
    'Chennai': {'lat': 13.0827, 'lon': 80.2707, 'places': 60},
    'Hyderabad': {'lat': 17.3850, 'lon': 78.4867, 'places': 65},
    'Jaipur': {'lat': 26.9124, 'lon': 75.7873, 'places': 55},
    'Goa': {'lat': 15.4909, 'lon': 73.8278, 'places': 50},
    'Kerala': {'lat': 10.8505, 'lon': 76.2711, 'places': 60},
    'Rajasthan': {'lat': 27.5522, 'lon': 74.6090, 'places': 50},
}

CATEGORIES = [
    'historical', 'nature', 'adventure', 'religious', 'beach',
    'museum', 'entertainment', 'shopping', 'food', 'nightlife',
    'cultural', 'wellness'
]

TAGS_POOL = {
    'historical': ['old', 'monuments', 'heritage', 'archaeology', 'architecture'],
    'nature': ['scenic', 'forest', 'trek', 'mountain', 'peaceful'],
    'adventure': ['thrilling', 'extreme', 'outdoor', 'sports', 'adrenaline'],
    'religious': ['temple', 'spiritual', 'sacred', 'pilgrimage', 'prayers'],
    'beach': ['sand', 'sea', 'water', 'swimming', 'tropical'],
    'museum': ['art', 'exhibition', 'artifacts', 'education', 'history'],
    'entertainment': ['fun', 'interactive', 'performance', 'show', 'crowds'],
    'shopping': ['retail', 'markets', 'brands', 'bargain', 'products'],
    'food': ['cuisine', 'dining', 'restaurant', 'taste', 'culture'],
    'nightlife': ['bar', 'club', 'live', 'late', 'drinks'],
    'cultural': ['tradition', 'arts', 'crafts', 'festivals', 'music'],
    'wellness': ['spa', 'yoga', 'meditation', 'health', 'retreat']
}

PLACE_NAMES = {
    'historical': [
        'Fort', 'Palace', 'Monument', 'Ruins', 'Historic Site',
        'Taj Mahal View', 'Ancient Temple', 'Old City Heritage'
    ],
    'nature': [
        'Nature Reserve', 'Botanical Garden', 'National Park', 'Wildlife Sanctuary',
        'Green Trail', 'Mountain Peak', 'Forest Walk'
    ],
    'adventure': [
        'Adventure Park', 'Zipline Course', 'Rock Climbing Site', 'Paragliding Point',
        'Trekking Trail', 'Adventure Camp'
    ],
    'religious': [
        'Temple', 'Mosque', 'Church', 'Gurudwara', 'Shrine',
        'Sacred Grounds', 'Pilgrimage Site', 'Holy Place'
    ],
    'beach': [
        'Beach Resort', 'Sandy Shore', 'Coastal View', 'Beach Club',
        'Water Sports Center', 'Beach Hut'
    ],
    'museum': [
        'Art Museum', 'History Museum', 'Science Museum', 'Cultural Museum',
        'Heritage Museum', 'War Museum'
    ],
    'entertainment': [
        'Theme Park', 'Entertainment Complex', 'Amusement Park', 'Fun Zone',
        'Comedy Club', 'Entertainment Hub'
    ],
    'shopping': [
        'Shopping Mall', 'Market Square', 'Boutique District', 'Commercial Hub',
        'Night Market', 'Bazaar'
    ],
    'food': [
        'Food Court', 'Restaurant Row', 'Culinary Street', 'Food Market',
        'Dining Hub', 'Gourmet District'
    ],
    'nightlife': [
        'Night Club', 'Bar & Lounge', 'Live Music Venue', 'Pub Street',
        'Night Market', 'Entertainment District'
    ],
    'cultural': [
        'Cultural Center', 'Art Gallery', 'Performance Hall', 'Craft Village',
        'Arts District', 'Cultural Hub'
    ],
    'wellness': [
        'Spa & Wellness', 'Yoga Center', 'Health Resort', 'Meditation Center',
        'Wellness Hub', 'Retreat'
    ]
}

# ============================================================================
# USER DATA GENERATION
# ============================================================================

def generate_users(num_users: int = 150) -> pd.DataFrame:
    """
    Generate diverse user profiles
    
    Diversity strategy:
    - Age: 18-65 with realistic distribution
    - Budget: Log-normal distribution (most budget-conscious, some high-spenders)
    - Preferences: Multi-label (each user has 2-4 preferences)
    - Profile variety to prevent one-user-type bias
    """
    np.random.seed(42)
    
    users = []
    for i in range(num_users):
        user_id = i + 1
        
        # Age distribution (roughly normal-ish)
        age = np.random.normal(35, 15)
        age = int(np.clip(age, 18, 65))
        
        # Budget distribution (log-normal - more budget-conscious than spenders)
        budget = np.random.lognormal(mean=4.5, sigma=0.6)  # 50-5000 range
        budget = np.clip(budget, 500, 10000)
        
        # Gender distribution
        gender = np.random.choice(['male', 'female', 'other', 'prefer_not_to_say'], 
                                 p=[0.45, 0.45, 0.05, 0.05])
        
        # Preferences: 2-4 random categories
        num_prefs = np.random.choice([2, 3, 4], p=[0.4, 0.4, 0.2])
        prefs = list(np.random.choice(CATEGORIES, size=num_prefs, replace=False))
        preferences = [str(p) for p in prefs]

        # Crowd preference distribution
        crowd_pref = np.random.choice(
            ['very_low', 'low', 'moderate', 'high', 'very_high'],
            p=[0.15, 0.25, 0.35, 0.2, 0.05]
        )
        
        # Companion type
        companion = np.random.choice(
            ['solo', 'couple', 'family', 'friends', 'group'],
            p=[0.2, 0.25, 0.25, 0.25, 0.05]
        )
        
        users.append({
            'user_id': user_id,
            'email': f'user_{user_id}@tourism.local',
            'username': f'traveler_{user_id}',
            'password_hash': 'hashed_password',
            'full_name': f'User {user_id}',
            'age': age,
            'gender': gender,
            'budget': round(budget, 2),
            'preferred_crowd_level': crowd_pref,
            'preferences': preferences,  # JSON array
            'companion_type': companion,
            'created_at': datetime.utcnow() - timedelta(days=np.random.randint(30, 365)),
            'updated_at': datetime.utcnow(),
            'is_active': True,
            'last_login': datetime.utcnow() - timedelta(hours=np.random.randint(1, 72))
        })
    
    return pd.DataFrame(users)


# ============================================================================
# PLACE DATA GENERATION
# ============================================================================

def generate_places(total_places: int = 650) -> pd.DataFrame:
    """
    Generate diverse places with realistic metrics
    
    Diversity strategy:
    - Geographic distribution across multiple cities
    - All categories represented
    - Varied ratings and costs (not all 5-star, not all expensive)
    - Realistic popularity distribution (power law)
    - Varied crowd levels
    """
    np.random.seed(42)
    
    places = []
    place_id = 1
    
    for city, city_info in CITIES.items():
        num_places_in_city = city_info['places']
        
        for _ in range(num_places_in_city):
            # Random category
            category = np.random.choice(CATEGORIES)
            
            # Name from category pool
            place_name = np.random.choice(PLACE_NAMES[category])
            
            # Add variety to name
            if np.random.random() > 0.5:
                place_name = f"{place_name} - {np.random.choice(['Downtown', 'Uptown', 'Central', 'Old', 'New', 'Premium'])}"
            
            # Geographic location (add noise around city center)
            lat = city_info['lat'] + np.random.normal(0, 0.05)
            lon = city_info['lon'] + np.random.normal(0, 0.05)
            
            # Rating distribution (realistic - not all 5 stars)
            # Beta distribution centered around 3.8
            rating = np.random.beta(8, 2)  # Most 4-5 stars, some 2-3
            rating = rating * 5
            rating = round(np.clip(rating, 1.0, 5.0), 2)
            
            # Number of ratings (power law - few have many, most have few)
            
            # Cost distribution (log-normal by category)
            category_costs = {
                'historical': (1000, 2000),
                'nature': (500, 1500),
                'adventure': (2000, 5000),
                'religious': (200, 500),
                'beach': (1000, 3000),
                'museum': (300, 800),
                'entertainment': (1000, 3000),
                'shopping': (100, 1000),  # Budget spent varies
                'food': (500, 2000),
                'nightlife': (1000, 3000),
                'cultural': (300, 1000),
                'wellness': (2000, 5000)
            }
            
            cost_range = category_costs.get(category, (500, 2000))
            avg_cost = np.random.uniform(cost_range[0], cost_range[1])
            avg_cost = round(avg_cost, 2)
            
            # Crowd level (realistic distribution)
            crowd_level = np.random.choice(
                ['very_low', 'low', 'moderate', 'high', 'very_high'],
                p=[0.15, 0.2, 0.3, 0.25, 0.1]
            )
            
            # Tags (category-specific)
            tags = list(np.random.choice(TAGS_POOL.get(category, TAGS_POOL['entertainment']),
                                        size=np.random.randint(2, 5), replace=False))
            
            # Description
            descriptions = [
                f"Beautiful {category} destination",
                f"Popular {category} spot in {city}",
                f"Must-visit {category} attraction",
                f"Hidden gem for {category} lovers",
                f"Best {category} experience in the area"
            ]
            description = np.random.choice(descriptions)
            
            # Popularity score (correlated with rating and ratings count, but with noise)
            popularity_base = (rating / 5.0) * 0.5 + (min(int(np.random.pareto(2) * 50 + 5), 200) / 200) * 0.5
            popularity_score = popularity_base + np.random.normal(0, 0.1)
            popularity_score = round(np.clip(popularity_score, 0, 1), 3)
            
            places.append({
                'place_id': place_id,
                'external_id': f'place_{place_id}',
                'name': place_name,
                'category': category,
                'subcategory': category,
                'city': city,
                'state': 'State',
                'country': 'India',
                'latitude': round(lat, 6),
                'longitude': round(lon, 6),
                'location': f'POINT({lon} {lat})',  # WKT format
                'description': description,
                'tags': tags,  # JSON array
                'avg_cost': avg_cost,
                'avg_rating': rating,
                'crowd_level': crowd_level,
                'created_at': datetime.utcnow() - timedelta(days=np.random.randint(1, 365)),
                'updated_at': datetime.utcnow()
            })
            
            place_id += 1
    
    return pd.DataFrame(places)


# ============================================================================
# INTERACTION DATA GENERATION
# ============================================================================

def generate_interactions(users_df: pd.DataFrame, places_df: pd.DataFrame,
                         interactions_per_user: int = 30) -> pd.DataFrame:
    """
    Generate diverse interaction patterns
    
    Diversity strategy:
    - Different interaction types with realistic weights (saves are rarer than clicks)
    - Vary interaction counts per user (some active, some inactive)
    - Mix positive and negative interactions (saves, skips)
    - Temporal distribution (recent and old interactions)
    - Geographic patterns but with variations
    - Category preferences but with exploration
    
    Returns:
        interactions_df: PostgreSQL-style interactions

    """
    np.random.seed(42)
    
    interactions = []
    
    for _, user in users_df.iterrows():
        user_id = user['user_id']
        user_prefs = user['preferences']
        user_budget = user['budget']
        
        # Vary interactions per user (20-40 interactions)
        num_interactions = np.random.randint(20, 40)
        
        for _ in range(num_interactions):
            # Generate interaction based on user preferences (with exploration)
            if np.random.random() < 0.75:  # 75% stick to preferences
                target_category = np.random.choice(user_prefs)
                candidate_places = places_df[places_df['category'] == target_category]
            else:  # 25% explore other categories
                candidate_places = places_df
            
            if len(candidate_places) == 0:
                continue
            
            # Filter by budget (realistic behavior)
            affordable_places = candidate_places[candidate_places['avg_cost'] <= user_budget * 1.5]
            if len(affordable_places) == 0:
                affordable_places = candidate_places.nlargest(int(len(candidate_places) * 0.3), 'avg_cost')
            
            place = affordable_places.sample(1).iloc[0]
            place_id = place['place_id']
            
            # Interaction type distribution (realistic)
            interaction_weights = {
                'click': 0.45,
                'preview_viewed': 0.25,
                'search': 0.15,
                'route_requested': 0.10,
                'save': 0.03,
                'skip': 0.02
            }
            interaction_type = np.random.choice(
                list(interaction_weights.keys()),
                p=list(interaction_weights.values())
            )
            
            # Temporal distribution
            days_ago = int(np.random.exponential(scale=30))  # Recency bias
            timestamp = datetime.utcnow() - timedelta(days=days_ago)
            
            # Rating correlation (users who save tend to visit high-rated places)
            if interaction_type == 'save':
                if place['avg_rating'] < 3.5 and np.random.random() > 0.3:
                    continue  # Skip low-rated places for saves (realistic)
            
            interactions.append({
                'interaction_id': len(interactions) + 1,
                'user_id': user_id,
                'place_id': place_id,
                'interaction_type': interaction_type,
                'timestamp': timestamp,
                'created_at': datetime.utcnow()
            })
    
    interactions_df = pd.DataFrame(interactions)
    
    return interactions_df

# ============================================================================
# TRAINING LABELS GENERATION
# ============================================================================

def generate_training_labels(interactions_df: pd.DataFrame,
                             users_df: pd.DataFrame,
                             places_df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate training labels for LambdaRank model
    
    Label strategy:
    - 5 (Perfect): User saved the place
    - 3 (Good): User viewed preview or requested route
    - 1 (Fair): User clicked
    - 0 (Bad): User skipped
    
    This ensures:
    - Realistic label distribution
    - Clear positive/negative signals
    - Relevant features for ranking
    """
    
    label_map = {
        'save': 5,
        'route_requested': 3,
        'preview_viewed': 3,
        'click': 1,
        'search': 1,
        'skip': 0
    }
    
    training_data = []
    
    for _, inter in interactions_df.iterrows():
        user_id = inter['user_id']
        place_id = inter['place_id']
        interaction_type = inter['interaction_type']
        
        user = users_df[users_df['user_id'] == user_id].iloc[0]
        place = places_df[places_df['place_id'] == place_id].iloc[0]
        
        # Create features for training
        features = {
            'user_id': user_id,
            'place_id': place_id,
            'label': label_map[interaction_type],
            'interaction_type': interaction_type,
            
            # User features
            'user_age': user['age'],
            'user_budget': user['budget'],
            'user_crowd_preference': user['preferred_crowd_level'],
            
            # Place features
            'place_category': place['category'],
            'place_rating': place['avg_rating'],
            'place_cost': place['avg_cost'],
            'place_crowd_level': place['crowd_level'],
            'place_city': place['city'],
            
            # Matching features
            'category_in_preferences': int(place['category'] in user['preferences']),
            'budget_match': int(place['avg_cost'] <= user['budget'] * 1.5),
            'crowd_match': int(place['crowd_level'] == user['preferred_crowd_level']),
        }
        
        training_data.append(features)
    
    return pd.DataFrame(training_data)


# ============================================================================
# SAVED PLACES GENERATION
# ============================================================================

# def generate_saved_places(users_df: pd.DataFrame, places_df: pd.DataFrame,
#                           interactions_df: pd.DataFrame) -> pd.DataFrame:
#     """Generate saved places (subset of saves from interactions)"""
    
#     saved_interactions = interactions_df[interactions_df['interaction_type'] == 'save'].copy()
    
#     saved_places = []
#     for _, inter in saved_interactions.iterrows():
#         saved_places.append({
#             'saved_place_id': len(saved_places) + 1,
#             'user_id': inter['user_id'],
#             'place_id': inter['place_id'],
#             'saved_at': inter['timestamp'],
#             'is_visited': np.random.random() > 0.7,  # 30% actually visited
#             'notes': 'Must visit!' if np.random.random() > 0.5 else None
#         })
    
#     return pd.DataFrame(saved_places)

# def generate_saved_places(users_df: pd.DataFrame, places_df: pd.DataFrame,
#                           interactions_df: pd.DataFrame) -> pd.DataFrame:
#     """Generate saved places (subset of saves from interactions)"""
    
#     saved_interactions = interactions_df[interactions_df['interaction_type'] == 'save'].copy()
    
#     saved_places = []
#     for _, inter in saved_interactions.iterrows():
#         saved_places.append({
#             'saved_place_id': len(saved_places) + 1,
#             'user_id': inter['user_id'],
#             'place_id': inter['place_id'],
#             'saved_at': inter['timestamp'],
#             'is_visited': np.random.random() > 0.7,  # 30% actually visited
#             'notes': 'Must visit!' if np.random.random() > 0.5 else None
#         })
    
#     return pd.DataFrame(saved_places)

def generate_saved_places(users_df, places_df, interactions_df):
    saved_places = (
        interactions_df
        [interactions_df['interaction_type'] == 'save']
        .sort_values('timestamp')
        .drop_duplicates(['user_id', 'place_id'], keep='last')
        .assign(
            saved_place_id=lambda df: range(1, len(df) + 1),
            is_visited=lambda df: np.random.random(len(df)) > 0.7,
            notes=lambda df: np.where(
                np.random.random(len(df)) > 0.5,
                'Must visit!',
                None
            ),
            saved_at=lambda df: df['timestamp']
        )
        [['saved_place_id', 'user_id', 'place_id', 'saved_at', 'is_visited', 'notes']]
    )

    return saved_places



# ============================================================================
# MAIN EXECUTION
# ============================================================================

def generate_all_data(output_dir: str = '.') -> Dict:
    """
    Generate complete dataset and save to CSV files
    
    Returns:
        Dictionary with all generated dataframes
    """
    logger.info("=" * 80)
    logger.info("STARTING SYNTHETIC DATA GENERATION")
    logger.info("=" * 80)
    
    # Generate core data
    logger.info("Generating users...")
    users_df = generate_users(num_users=150)
    logger.info(f"✓ Generated {len(users_df)} users")
    
    logger.info("Generating places...")
    places_df = generate_places(total_places=650)
    logger.info(f"✓ Generated {len(places_df)} places")
    
    logger.info("Generating interactions...")
    interactions_df = generate_interactions(users_df, places_df)
    logger.info(f"✓ Generated {len(interactions_df)} interactions")
    
    logger.info("Generating training labels...")
    training_labels_df = generate_training_labels(interactions_df, users_df, places_df)
    logger.info(f"✓ Generated {len(training_labels_df)} labeled samples")
    
    logger.info("Generating saved places...")
    saved_places_df = generate_saved_places(users_df, places_df, interactions_df)
    logger.info(f"✓ Generated {len(saved_places_df)} saved places")
    
    # Save to CSV
    logger.info("\nSaving data to CSV files...")
    output_files = {
        'users': f'{output_dir}/data_users.csv',
        'places': f'{output_dir}/data_places.csv',
        'interactions': f'{output_dir}/data_interactions.csv',
        'training_labels': f'{output_dir}/data_training_labels.csv',
        'saved_places': f'{output_dir}/data_saved_places.csv'
    }
    
    users_df.to_csv(output_files['users'], index=False)
    places_df.to_csv(output_files['places'], index=False)
    interactions_df.to_csv(output_files['interactions'], index=False)
    training_labels_df.to_csv(output_files['training_labels'], index=False)
    saved_places_df.to_csv(output_files['saved_places'], index=False)
    
    logger.info(f"✓ Saved all files to {output_dir}/")
    
    # Print statistics
    logger.info("\n" + "=" * 80)
    logger.info("DATA STATISTICS")
    logger.info("=" * 80)
    logger.info(f"Users: {len(users_df)}")
    logger.info(f"Places: {len(places_df)}")
    logger.info(f"Interactions: {len(interactions_df)}")
    logger.info(f"Training samples: {len(training_labels_df)}")
    logger.info(f"Saved places: {len(saved_places_df)}")
    
    logger.info("\nInteraction Type Distribution:")
    logger.info(interactions_df['interaction_type'].value_counts().to_string())
    
    logger.info("\nCategory Distribution (Places):")
    logger.info(places_df['category'].value_counts().to_string())
    
    logger.info("\nLabel Distribution (Training):")
    logger.info(training_labels_df['label'].value_counts().sort_index().to_string())
    
    logger.info("\nUser Age Distribution:")
    logger.info(f"Mean: {users_df['age'].mean():.1f}, Std: {users_df['age'].std():.1f}")
    
    logger.info("\nPlace Rating Distribution:")
    logger.info(f"Mean: {places_df['avg_rating'].mean():.2f}, Std: {places_df['avg_rating'].std():.2f}")
    
    logger.info("\n" + "=" * 80)
    logger.info("DATA GENERATION COMPLETE")
    logger.info("=" * 80)
    
    return {
        'users': users_df,
        'places': places_df,
        'interactions': interactions_df,
        'training_labels': training_labels_df,
        'saved_places': saved_places_df,
        'output_files': output_files
    }