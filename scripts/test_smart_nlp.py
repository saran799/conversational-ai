import sys
sys.path.insert(0, ".")
import re

test_phrases = [
    "ஆவடி கந்த பூந்தமல்லி போனோம்",
    "ஆவடி பூந்தமல்லி போனோம்",
    "போரூர் கிண்டி போகணும்",
    "ஆவடி லிருந்து பூந்தமல்லி",
    "avadi poonamalle",
    "porur guindy",
]

# Let's test a smarter extraction:
# If words contain known aliases or if two words precede 'போனோம்'/'போகணும்'
from backend.app.mobility.resolver import StopResolver
from backend.app.mobility.repository import SQLiteTransitRepository

repo = SQLiteTransitRepository("data/build/chennai.sqlite")
resolver = StopResolver(repo)

known_aliases = list(resolver.aliases.keys())
print("Known aliases count:", len(known_aliases))

def smart_extract(clean):
    # Check if 'போனோம்' / 'போகணும்' / 'poganum' present
    clean_norm = re.sub(r"[?,.]", "", clean).strip()
    words = clean_norm.split()
    
    # Check if any words match known stop aliases directly
    matched_spots = []
    i = 0
    while i < len(words):
        # try 2-word or 1-word aliases
        if i + 1 < len(words):
            two_w = f"{words[i]} {words[i+1]}".lower()
            if two_w in resolver.aliases:
                matched_spots.append((two_w, i, i+1))
                i += 2
                continue
        one_w = words[i].lower()
        # strip common suffixes like -இல், -க்கு, -லிருந்து, -கந்த?
        clean_w = re.sub(r"(?:யில்|யில|இல்|ில்|லிருந்து|இருந்து|க்கு|கு)$", "", one_w)
        if clean_w in resolver.aliases:
            matched_spots.append((clean_w, i, i))
        i += 1
        
    print(f"Phrase '{clean}' -> matched spots: {matched_spots}")

for p in test_phrases:
    smart_extract(p)
