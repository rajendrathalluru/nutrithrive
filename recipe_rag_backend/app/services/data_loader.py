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
        text_columns = [
            'Name', 'Type', 'Description', 'Ingredients', 'Directions', 'Notes', 'YT Link',
            'Recipe Link', 'Source Name (AICR or ACS)'
        ]
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
            row_dict = row.to_dict()
            recipe_text = self.build_recipe_text(row_dict)
            metadata = {
                "recipe_id": row.get('recipe_id') or self._build_recipe_id(row_dict),
                "name": row['Name'],
                "type": row['Type'],
                "calories": float(row['Calories']) if row['Calories'] and str(row['Calories']).replace('.', '').isdigit() else 0,
                "has_video": bool(row['YT Link']),
                "youtube_link": row['YT Link'] if row['YT Link'] else "",
                "recipe_link": row.get('Recipe Link', ''),
                "source_name": row.get('Source Name (AICR or ACS)', '')
            }
            documents.append(Document(page_content=recipe_text, metadata=metadata))
        
        return documents

    @staticmethod
    def split_recipe_documents(
        documents: List[Document], chunk_size: int, chunk_overlap: int
    ) -> List[Document]:
        """Keep each recipe as a single whole vector unless it exceeds chunk_size;
        if an unusually long recipe must be split, repeat its Recipe Name header on every chunk."""
        from langchain.text_splitter import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        result: List[Document] = []
        for doc in documents:
            if len(doc.page_content) <= chunk_size:
                result.append(doc)
                continue
            name = str(doc.metadata.get("name") or "").strip()
            header = f"Recipe Name: {name}\n" if name else ""
            sub_docs = splitter.split_documents([doc])
            for sub in sub_docs:
                if header and not sub.page_content.lstrip().startswith("Recipe Name:"):
                    sub = Document(page_content=header + sub.page_content, metadata=dict(sub.metadata))
                result.append(sub)
        return result

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

    def get_source_annotations(self, row: dict) -> dict:
        ingredients = str(row.get("Ingredients", ""))
        notes = str(row.get("Notes", "")).strip()
        markers = set(re.findall(r"(?<=\w)(\*+)", ingredients))
        explained = set(re.findall(r"^\s*(\*+)(?=\S|\s+\S)", notes, re.M))
        related = []
        reference_lines = [
            self._normalize_name(line) for line in ingredients.splitlines()
            if re.search(r"\bsee (?:related )?recipes?\b", line, re.I)
        ]
        if reference_lines:
            for name, record in self.recipe_lookup.items():
                if name == self._normalize_name(row.get("Name", "")):
                    continue
                if any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", line) for line in reference_lines):
                    link = str(record.get("Recipe Link", ""))
                    if re.match(r"^https?://", link, re.I):
                        related.append({
                            "recipe_id": record.get("recipe_id", ""),
                            "name": record.get("Name", ""),
                            "recipe_link": link,
                            "source_name": record.get("Source Name (AICR or ACS)", ""),
                        })
        return {
            "source_notes": notes,
            "unresolved_footnotes": sorted(markers - explained, key=len),
            "related_recipes": related,
        }

    def build_recipe_text(self, row: dict) -> str:
        if not row:
            return ""

        sections = [f"Recipe Name: {row.get('Name', '')}"]
        if str(row.get('Type', '')).strip():
            sections.append(f"Type: {row['Type']}")
        if str(row.get('Description', '')).strip():
            sections.append(f"Description: {row['Description']}")
        if str(row.get('Calories', '')).strip():
            sections.append(f"Calories: {row['Calories']}")
        if str(row.get('Ingredients', '')).strip():
            sections.append(f"Ingredients: {row['Ingredients']}")
        if str(row.get('Directions', '')).strip():
            sections.append(f"Directions: {row['Directions']}")
        if str(row.get('Notes', '')).strip():
            sections.append(f"Notes: {row['Notes']}")
        return "\n".join(sections)
