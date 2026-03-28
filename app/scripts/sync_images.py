import pandas as pd
import cloudinary
import cloudinary.api
from dotenv import load_dotenv
import os


load_dotenv()

# 1. SETUP: Get these from your Cloudinary "Dashboard" (Home) page
cloudinary.config(
  cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
  api_key = os.getenv("CLOUDINARY_API_KEY"),      # Replace with your actual API Key
  api_secret = os.getenv("CLOUDINARY_API_SECRET") # Replace with your actual API Secret
)

def sync_actual_urls(csv_path):
    df = pd.read_csv(csv_path)
    
    print("📡 Fetching real image paths from Cloudinary...")
    
    # We ask Cloudinary for a list of all images in your account
    # We set max_results to 100 to make sure we get all 50 recipes
    resources = cloudinary.api.resources(type="upload", max_results=100)['resources']
    
    # Create a mapping dictionary: { "48": "https://res.cloudinary.../48_hciir5.jpg" }
    url_map = {}
    for res in resources:
        public_id = res['public_id'] # e.g., "48_hciir5" or "aduane_recipes/48_hciir5"
        
        # Get the filename only (remove folder path if it exists)
        filename = public_id.split('/')[-1] 
        
        # Get the ID number (everything before the first underscore)
        # If your filename is "48_hciir5", this gets "48"
        id_prefix = filename.split('_')[0]
        
        if id_prefix.isdigit():
            url_map[id_prefix] = res['secure_url']

    # 2. UPDATE THE CSV
    count = 0
    for index, row in df.iterrows():
        recipe_id = str(int(row['recipe_id']))
        if recipe_id in url_map:
            df.at[index, 'image_url'] = url_map[recipe_id]
            count += 1
    
    # Save the updated CSV
    df.to_csv(csv_path, index=False)
    print(f"✅ Successfully mapped {count} images with their unique Cloudinary suffixes!")

# Run it!
sync_actual_urls("./data/ghana_recipes_v3.csv")