# app/services/data_loader.py
import pandas as pd
import logging
import hashlib
import re
from typing import List
from pathlib import Path
from langchain.schema import Document
from app.core.config import settings

logger = logging.getLogger(__name__)

class DataLoader:
    def __init__(self):
        self.df = None
        self.recipes_count = 0
        self.recipe_lookup = {}
        
    def load_data(self, file_path: str = None) -> pd.DataFrame:
        try:
            configured_path = Path(file_path) if file_path else settings.data_file_path
            file_path = configured_path.expanduser().resolve()
            logger.info(f"Loading data from: {file_path}")

            if not file_path.exists():
                raise FileNotFoundError(f"Recipe data file not found: {file_path}")
            
            self.df = pd.read_csv(file_path)
            self.recipes_count = len(self.df)
            logger.info(f"Successfully loaded {self.recipes_count} recipes")
            
            self._clean_data()
            self._deduplicate_recipes()
            self._assign_recipe_ids()
            return self.df
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            raise
    
    def _clean_data(self):
        self.df = self.df.fillna('')
        text_columns = ['Name', 'Type', 'Description', 'Ingredients', 'Directions', 'Notes', 'YT Link']
        for col in text_columns:
            if col in self.df.columns:
                self.df[col] = self.df[col].astype(str).apply(self._clean_text)
    
    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        
        replacements = {
            '\u2019': "'", '\u2018': "'", '\u201c': '"', '\u201d': '"',
            '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u00b0': ' degrees',
            '\u00bd': '1/2', '\u00bc': '1/4', '\u00be': '3/4'
        }
        
        for unicode_char, ascii_char in replacements.items():
            text = text.replace(unicode_char, ascii_char)
        
        text = text.encode('ascii', 'ignore').decode('ascii')
        lines = []
        for raw_line in text.splitlines():
            cleaned_line = ' '.join(raw_line.split()).strip()
            if cleaned_line:
                lines.append(cleaned_line)

        return '\n'.join(lines)
    
    def prepare_documents(self) -> List[Document]:
        if self.df is None:
            raise ValueError("Data not loaded. Call load_data() first.")
        
        documents = []
        for _, row in self.df.iterrows():
            recipe_text = f"""
Recipe Name: {row['Name']}
Type: {row['Type']}
Description: {row['Description']}
Calories: {row['Calories'] if row['Calories'] else 'Not specified'}
Ingredients: {row['Ingredients']}
Directions: {row['Directions']}
Notes: {row['Notes'] if row['Notes'] else 'No additional notes'}
"""
            metadata = {
                "recipe_id": row.get('recipe_id') or self._build_recipe_id(row.to_dict()),
                "name": row['Name'],
                "type": row['Type'],
                "calories": float(row['Calories']) if row['Calories'] and str(row['Calories']).replace('.', '').isdigit() else 0,
                "has_video": bool(row['YT Link']),
                "youtube_link": row['YT Link'] if row['YT Link'] else ""
            }
            documents.append(Document(page_content=recipe_text, metadata=metadata))
        
        return documents

    def _normalize_name(self, name: str) -> str:
        return ' '.join(str(name).lower().split())

    def _slugify_name(self, name: str) -> str:
        slug = re.sub(r'[^a-z0-9]+', '-', self._normalize_name(name)).strip('-')
        return slug or "recipe"

    def _build_recipe_id(self, row: dict) -> str:
        normalized_name = self._normalize_name(row.get('Name', ''))
        normalized_type = self._normalize_name(row.get('Type', ''))
        calories = str(row.get('Calories', '')).strip()
        fingerprint = f"{normalized_name}|{normalized_type}|{calories}"
        digest = hashlib.md5(fingerprint.encode("utf-8")).hexdigest()[:10]
        return f"{self._slugify_name(row.get('Name', ''))}-{digest}"

    def _deduplicate_recipes(self) -> None:
        if self.df is None or 'Name' not in self.df.columns:
            return

        before = len(self.df)
        normalized_names = self.df['Name'].astype(str).map(self._normalize_name)
        self.df = (
            self.df.assign(_normalized_name=normalized_names)
            .loc[lambda frame: frame['_normalized_name'].astype(bool)]
            .drop_duplicates(subset='_normalized_name', keep='last')
            .drop(columns=['_normalized_name'])
            .reset_index(drop=True)
        )

        removed = before - len(self.df)
        if removed > 0:
            logger.info("Removed %s duplicate recipe rows during data load", removed)

        self.recipes_count = len(self.df)

    def _assign_recipe_ids(self) -> None:
        if self.df is None:
            return

        self.recipe_lookup = {}
        recipe_ids = []
        for _, row in self.df.iterrows():
            row_dict = row.to_dict()
            recipe_id = self._build_recipe_id(row_dict)
            row_dict["recipe_id"] = recipe_id
            recipe_ids.append(recipe_id)

            name_key = self._normalize_name(row_dict.get('Name', ''))
            if name_key:
                self.recipe_lookup[name_key] = row_dict

        self.df['recipe_id'] = recipe_ids

    def get_recipe_record(self, name: str):
        if not name:
            return None
        return self.recipe_lookup.get(self._normalize_name(name))

    def build_recipe_text(self, row: dict) -> str:
        if not row:
            return ""

        return f"""
Recipe Name: {row.get('Name', '')}
Type: {row.get('Type', '')}
Description: {row.get('Description', '')}
Calories: {row.get('Calories', 'Not specified') if row.get('Calories', '') else 'Not specified'}
Ingredients: {row.get('Ingredients', '')}
Directions: {row.get('Directions', '')}
Notes: {row.get('Notes', 'No additional notes') if row.get('Notes', '') else 'No additional notes'}
"""
